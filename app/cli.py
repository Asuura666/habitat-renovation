"""CLI de recette et d'exploitation.

- `python -m app.cli bl-non-recus <facture.pdf>` (T7) : lit une facture PDF
  via l'OCR Mistral et affiche, pour chaque bloc « Concerne le B.L. », si une
  photo de bon a déjà été reçue — le livrable visible du lot 1. Lecture
  seule (décision D14 du brief) : elle parse la facture et interroge la
  base, mais n'enregistre rien.
- `python -m app.cli utilisateur-creer` / `utilisateur-desactiver` (L2-T1b) :
  gestion des comptes par l'administrateur (Q3 du brief lot 2, aucun des 5
  écrans ne la porte). Mot de passe saisi deux fois via `getpass` (jamais en
  argument ni affiché) ; l'écriture (hachage, unicité, journal) est déléguée
  à `creer_utilisateur`/`desactiver_utilisateur` (`app.core.auth`) — cette
  CLI ne fait que construire ses dépendances (moteur DB) et les brancher,
  jamais de logique métier ici.
- `python -m app.cli fournisseur-definir` (L3-T5) : alimente le référentiel
  fournisseur (Q7/L3-D8, jamais créé automatiquement par l'extraction) —
  crée ou met à jour un fournisseur (SIRET/TVA remplacés s'ils sont fournis,
  alias et agences ajoutés sans doublon). Même organisation que
  `utilisateur-creer` : l'écriture est déléguée à `definir_fournisseur`
  (`app.modules.ingest.referentiels`), cette CLI ne fait que construire ses
  dépendances et les brancher.
- `python -m app.cli rapport-ocr` (L3-T11, L3-D20) : mesure le taux d'erreur
  OCR sur un dossier de photos de BL annotées à la main (fichiers
  `<nom>.attendu.json`, cache `<nom>.mistral-ocr.json`) et écrit le rapport
  Markdown demandé (`--sortie`). Toute la logique (comparaison, agrégation,
  rendu) est déléguée à `app.modules.ingest.rapport_ocr` ; cette CLI ne fait
  que construire l'OCR réel de `--appeler-ocr` (mêmes options et délai que
  `ingest/router.py::get_ocr`, `OPTIONS_OCR_BL` d'`extract.bl`,
  `DELAI_OCR_BL` d'`ingest.router`) sur un client HTTP qu'elle ouvre et
  ferme elle-même — jamais sur un document client (R17, protocole détaillé
  dans `docs/protocole-mesure-ocr.md`).

N'importe que `app.core` (config, db, auth) et `app.modules.ingest`
(`factures.py`, `mistral.py` — depuis le découpage de l'ancien
`ingest/service.py`, vague finale du lot 2, point 1 ; `referentiels.py`
depuis L3-T5 ; `rapport_ocr.py`, `router.py` depuis L3-T11), plus
`FactureIllisible` d'`extract` (nécessaire pour distinguer le code de
sortie) et `OPTIONS_OCR_BL`/`SEUIL_CONFIANCE_DEFAUT`/
`TOLERANCE_TOTAL_DEFAUT` d'`extract` (L3-T11, mêmes constantes que le reste
du lot 3) : `ingest` reste le seul orchestrateur, la CLI ne fait que
construire ses dépendances (client HTTP, moteur DB) et les brancher
(décisions du contrôleur T7/L2-T1b/L3-T5/L3-T11).

Import différé de `app.core.auth` (dans le corps de `_utilisateur_creer`/
`_utilisateur_desactiver`, pas en tête de fichier) : ce module appelle
`get_settings()` à l'import (comme `app.main`, voir son docstring), ce qui
casserait la garantie « sans configuration » de `bl-non-recus` — un import
en tête de fichier ferait échouer tout `python -m app.cli ...` (y compris
`bl-non-recus`) avant même l'analyse des arguments dès qu'une variable
d'environnement manque, un comportement démasqué et fixé pendant cette
tâche (`test_bl_non_recus_fichier_inexistant_code_2_sans_configuration`
tournait au rouge tant que l'import restait en tête de fichier).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.db import creer_engine, creer_sessionmaker
from app.modules.extract.bl import OPTIONS_OCR_BL
from app.modules.extract.facture import FactureIllisible
from app.modules.extract.verification import (
    SEUIL_CONFIANCE_DEFAUT,
    TOLERANCE_TOTAL_DEFAUT,
)
from app.modules.ingest.factures import (
    blocs_avec_reception,
    formater_blocs,
    lire_facture,
)
from app.modules.ingest.mistral import ErreurOCR, ocr_document
from app.modules.ingest.rapport_ocr import mesurer_dossier, rapport_markdown
from app.modules.ingest.referentiels import definir_fournisseur
from app.modules.ingest.router import DELAI_OCR_BL

_SIGNATURE_PDF = b"%PDF-"


def _est_pdf(contenu: bytes) -> bool:
    return contenu[:5] == _SIGNATURE_PDF


class _LectureEchouee(Exception):
    """Fichier absent, illisible ou non-PDF (message déjà prêt pour stderr)."""


def _lire_fichier(chemin_pdf: Path) -> bytes:
    """Lecture bloquante du PDF (I/O disque), exécutée hors de la boucle
    asyncio via `asyncio.to_thread` (même principe que `_ecrire_atomique`
    dans `ingest/commun.py`). Lève `_LectureEchouee` (message déjà prêt,
    sans contenu de fichier) si le fichier est absent, illisible ou n'a pas
    la signature d'un PDF."""
    if not chemin_pdf.is_file():
        raise _LectureEchouee(f"fichier introuvable : {chemin_pdf}")
    try:
        contenu = chemin_pdf.read_bytes()
    except OSError:
        raise _LectureEchouee(f"lecture du fichier impossible : {chemin_pdf}") from None
    if not _est_pdf(contenu):
        raise _LectureEchouee(f"fichier non PDF : {chemin_pdf}")
    return contenu


async def _bl_non_recus(chemin_pdf: Path) -> int:
    """Implémentation de `bl-non-recus`.

    Codes de sortie (décisions du contrôleur T7, révision après T5
    requalifiée) :
    - fichier absent, illisible ou non-PDF -> 2, message sur stderr, aucun
      appel réseau ni lecture de configuration ;
    - configuration manquante -> échec fail-fast (`get_settings()`,
      exception non interceptée) ;
    - `ErreurOCR` ou `FactureIllisible` -> 2, message court sur stderr,
      jamais le contenu du document ni la clé API ;
    - sinon -> tableau des blocs sur stdout, 0.
    """
    try:
        contenu = await asyncio.to_thread(_lire_fichier, chemin_pdf)
    except _LectureEchouee as exc:
        print(str(exc), file=sys.stderr)
        return 2

    settings = get_settings()

    async with httpx.AsyncClient() as http:
        ocr = partial(ocr_document, http, settings.mistral_api_key.get_secret_value())
        try:
            facture = await lire_facture(contenu, ocr)
        except (ErreurOCR, FactureIllisible) as exc:
            print(
                f"lecture de la facture impossible ({type(exc).__name__})",
                file=sys.stderr,
            )
            return 2

    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            blocs = await blocs_avec_reception(session, facture)
    finally:
        await engine.dispose()

    print(formater_blocs(blocs))
    return 0


async def _utilisateur_creer(
    *,
    email: str,
    nom: str,
    role: str,
    agence: str,
    telegram_user_id: int | None,
) -> int:
    """Implémentation de `utilisateur-creer` (décisions du contrôleur
    L2-T1b). Le rôle est déjà validé par `argparse` (`choices`) avant
    d'arriver ici. Codes de sortie : 0 succès ; 2 mots de passe différents,
    mot de passe trop court, e-mail ou identifiant Telegram déjà pris —
    message court sur stderr, jamais le mot de passe."""
    mot_de_passe = getpass.getpass("Mot de passe : ")
    confirmation = getpass.getpass("Confirmation du mot de passe : ")
    if mot_de_passe != confirmation:
        print("les deux mots de passe ne correspondent pas", file=sys.stderr)
        return 2

    # Import différé (voir docstring de module).
    from app.core.auth import (
        EmailDejaUtilise,
        MotDePasseTropCourt,
        RoleInvalide,
        TelegramUserIdDejaAttribue,
        creer_utilisateur,
    )

    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            try:
                utilisateur = await creer_utilisateur(
                    session,
                    email=email,
                    nom=nom,
                    role=role,
                    agence=agence,
                    mot_de_passe=mot_de_passe,
                    telegram_user_id=telegram_user_id,
                )
            except (
                RoleInvalide,
                MotDePasseTropCourt,
                EmailDejaUtilise,
                TelegramUserIdDejaAttribue,
            ) as exc:
                print(str(exc), file=sys.stderr)
                return 2
    finally:
        await engine.dispose()

    print(f"utilisateur créé : {utilisateur.email} ({utilisateur.role})")
    return 0


async def _utilisateur_desactiver(*, email: str) -> int:
    """Implémentation de `utilisateur-desactiver`. Code de sortie 2 si
    aucun compte ne correspond à `email`."""
    # Import différé (voir docstring de module).
    from app.core.auth import UtilisateurIntrouvable, desactiver_utilisateur

    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            try:
                await desactiver_utilisateur(session, email)
            except UtilisateurIntrouvable as exc:
                print(str(exc), file=sys.stderr)
                return 2
    finally:
        await engine.dispose()

    print(f"utilisateur désactivé : {email}")
    return 0


async def _fournisseur_definir(
    *,
    nom: str,
    siret: str | None,
    tva: str | None,
    alias: list[str],
    agence: list[str],
) -> int:
    """Implémentation de `fournisseur-definir` (décisions du contrôleur
    L3-T5). Toute la logique (upsert par nom insensible à la casse,
    dédoublonnage des alias/agences) est dans `definir_fournisseur`
    (`app.modules.ingest.referentiels`) : cette CLI ne fait que construire
    ses dépendances (moteur DB) et les brancher, comme `_utilisateur_creer`.
    Toujours code 0 (aucune validation ne peut échouer ici : `--nom` est le
    seul argument requis, `argparse` refuse déjà son absence)."""
    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            resultat = await definir_fournisseur(
                session, nom=nom, siret=siret, tva=tva, alias=alias, agence=agence
            )
            await session.commit()
    finally:
        await engine.dispose()

    libelle = "Fournisseur créé" if resultat.cree else "Fournisseur mis à jour"
    print(
        f"{libelle} ({resultat.nombre_alias} alias, {resultat.nombre_agences} agences)"
    )
    return 0


async def _rapport_ocr(*, dossier: Path, sortie: Path, appeler_ocr: bool) -> int:
    """Implémentation de `rapport-ocr` (L3-T11, L3-D20) : mesure le taux
    d'erreur OCR sur `dossier` (photos + `<nom>.attendu.json`) et écrit le
    rapport Markdown dans `sortie`. Toute la comparaison/agrégation est
    déléguée à `app.modules.ingest.rapport_ocr` (module pur/orchestré, sans
    FastAPI ni SQLAlchemy) : cette CLI ne fait que construire l'OCR réel et
    brancher les dépendances.

    Sans `--appeler-ocr`, seul le cache `<nom>.mistral-ocr.json` de chaque
    photo est utilisé (aucun appel réseau) : une photo sans cache part dans
    `documents_sans_ocr`. Avec `--appeler-ocr`, l'OCR de production est
    construit avec les mêmes options et le même délai que `ingest/router
    .py::get_ocr` (`OPTIONS_OCR_BL`, `DELAI_OCR_BL`), sur un client HTTP
    ouvert et fermé par cette commande, clé API lue dans la configuration —
    jamais sur un document client (décision du contrôleur,
    `docs/protocole-mesure-ocr.md`).

    Codes de sortie : 2 si `dossier` n'existe pas ou ne contient aucun BL
    attendu (aucun `<nom>.attendu.json` apparié à une photo) — message court
    sur stderr, rien n'est écrit dans `sortie` ; sinon 0, rapport écrit,
    seuls des comptes et des taux affichés sur stdout (jamais une valeur
    attendue ou lue)."""
    if not await asyncio.to_thread(dossier.is_dir):
        print(f"dossier introuvable : {dossier}", file=sys.stderr)
        return 2

    seuil = SEUIL_CONFIANCE_DEFAUT
    tolerance = TOLERANCE_TOTAL_DEFAUT

    if appeler_ocr:
        settings = get_settings()
        cle_api = settings.mistral_api_key.get_secret_value()
        async with httpx.AsyncClient() as http:

            async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
                return await ocr_document(
                    http,
                    cle_api,
                    contenu,
                    mime,
                    delai=DELAI_OCR_BL,
                    options=OPTIONS_OCR_BL,
                )

            rapport, comparaisons = await mesurer_dossier(
                dossier, ocr=_ocr, seuil=seuil, tolerance=tolerance
            )
    else:
        rapport, comparaisons = await mesurer_dossier(
            dossier, ocr=None, seuil=seuil, tolerance=tolerance
        )

    if rapport.nb_documents == 0 and not rapport.documents_sans_ocr:
        print(
            f"aucun BL attendu (<nom>.attendu.json) trouvé dans {dossier}",
            file=sys.stderr,
        )
        return 2

    contenu_rapport = rapport_markdown(rapport, comparaisons)
    await asyncio.to_thread(sortie.write_text, contenu_rapport, encoding="utf-8")

    print(f"{rapport.nb_documents} documents mesurés ({rapport.nb_degrades} dégradés)")
    for champ, taux in rapport.taux_champs.items():
        print(f"  champ {champ} juste : {taux}")
    print(f"  documents 4 champs justes : {rapport.taux_documents_4_champs}")
    print(f"  lignes justes : {rapport.taux_lignes}")
    print(f"  erreurs silencieuses : {rapport.nb_erreurs_silencieuses}")
    if rapport.documents_sans_ocr:
        print(f"  documents sans réponse OCR : {len(rapport.documents_sans_ocr)}")
    print(f"rapport écrit : {sortie}")
    return 0


def _construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli")
    sous_parsers = parser.add_subparsers(dest="commande", required=True)

    parser_bl_non_recus = sous_parsers.add_parser(
        "bl-non-recus",
        help="Liste les blocs BL d'une facture avec l'indicateur « photo reçue »",
    )
    parser_bl_non_recus.add_argument(
        "facture", type=Path, help="chemin du PDF de la facture"
    )

    parser_utilisateur_creer = sous_parsers.add_parser(
        "utilisateur-creer",
        help="Crée un compte utilisateur (mot de passe saisi de façon interactive)",
    )
    parser_utilisateur_creer.add_argument("--email", required=True)
    parser_utilisateur_creer.add_argument("--nom", required=True)
    parser_utilisateur_creer.add_argument(
        "--role", required=True, choices=["admin", "agent"]
    )
    parser_utilisateur_creer.add_argument("--agence", required=True)
    parser_utilisateur_creer.add_argument(
        "--telegram-id",
        dest="telegram_id",
        type=int,
        default=None,
        help="identifiant Telegram numérique (optionnel)",
    )

    parser_utilisateur_desactiver = sous_parsers.add_parser(
        "utilisateur-desactiver", help="Désactive un compte utilisateur"
    )
    parser_utilisateur_desactiver.add_argument("--email", required=True)

    parser_fournisseur_definir = sous_parsers.add_parser(
        "fournisseur-definir",
        help="Crée ou met à jour un fournisseur du référentiel",
    )
    parser_fournisseur_definir.add_argument("--nom", required=True)
    parser_fournisseur_definir.add_argument("--siret", default=None)
    parser_fournisseur_definir.add_argument("--tva", default=None)
    parser_fournisseur_definir.add_argument(
        "--alias",
        action="append",
        default=None,
        help="alias supplémentaire (répétable)",
    )
    parser_fournisseur_definir.add_argument(
        "--agence",
        action="append",
        default=None,
        help="agence à rattacher (répétable)",
    )

    parser_rapport_ocr = sous_parsers.add_parser(
        "rapport-ocr",
        help="Mesure le taux d'erreur OCR sur un dossier de photos de BL annotées",
    )
    parser_rapport_ocr.add_argument(
        "dossier", type=Path, help="dossier contenant les photos et leurs .attendu.json"
    )
    parser_rapport_ocr.add_argument(
        "--sortie", required=True, type=Path, help="chemin du rapport Markdown à écrire"
    )
    parser_rapport_ocr.add_argument(
        "--appeler-ocr",
        dest="appeler_ocr",
        action="store_true",
        help=(
            "appelle réellement l'API Mistral OCR pour les photos sans cache "
            "(jamais sur un document client)"
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _construire_parser().parse_args(argv)
    if args.commande == "bl-non-recus":
        return asyncio.run(_bl_non_recus(args.facture))
    if args.commande == "utilisateur-creer":
        return asyncio.run(
            _utilisateur_creer(
                email=args.email,
                nom=args.nom,
                role=args.role,
                agence=args.agence,
                telegram_user_id=args.telegram_id,
            )
        )
    if args.commande == "utilisateur-desactiver":
        return asyncio.run(_utilisateur_desactiver(email=args.email))
    if args.commande == "fournisseur-definir":
        return asyncio.run(
            _fournisseur_definir(
                nom=args.nom,
                siret=args.siret,
                tva=args.tva,
                alias=args.alias or [],
                agence=args.agence or [],
            )
        )
    if args.commande == "rapport-ocr":
        return asyncio.run(
            _rapport_ocr(
                dossier=args.dossier, sortie=args.sortie, appeler_ocr=args.appeler_ocr
            )
        )
    raise AssertionError(f"commande inconnue : {args.commande}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
