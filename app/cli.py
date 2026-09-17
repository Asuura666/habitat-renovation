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

N'importe que `app.core` (config, db, auth) et `app.modules.ingest`
(`factures.py`, `mistral.py` — depuis le découpage de l'ancien
`ingest/service.py`, vague finale du lot 2, point 1), plus `FactureIllisible`
d'`extract` (nécessaire pour distinguer le code de sortie) : `ingest` reste
le seul orchestrateur, la CLI ne fait que construire ses dépendances
(client HTTP, moteur DB) et les brancher (décisions du contrôleur T7/L2-T1b).

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

import httpx

from app.core.config import get_settings
from app.core.db import creer_engine, creer_sessionmaker
from app.modules.extract.facture import FactureIllisible
from app.modules.ingest.factures import (
    blocs_avec_reception,
    formater_blocs,
    lire_facture,
)
from app.modules.ingest.mistral import ErreurOCR, ocr_document

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
    raise AssertionError(f"commande inconnue : {args.commande}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
