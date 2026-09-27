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
- `python -m app.cli rapport-ocr` (L3-T11, L3-D20 ; `--seuil` fix round 1,
  finding 2/ruling R13) : mesure le taux d'erreur OCR sur un dossier de
  photos de BL annotées à la main (fichiers `<nom>.attendu.json`, cache
  `<nom>.mistral-ocr.json`) et écrit le rapport Markdown demandé
  (`--sortie`). `--seuil` (défaut `SEUIL_CONFIANCE_DEFAUT`, entre 0 et 1,
  sinon `SystemExit(2)` via `argparse`) permet de recaler le seuil de
  confiance sans modifier de code (`docs/protocole-mesure-ocr.md` §6). Un
  `<nom>.attendu.json` invalide ou un échec OCR (cache invalide ou appel en
  échec) sont isolés par document (fix round 1, finding 1) : la commande
  continue sur les autres photos plutôt que d'échouer entièrement. Toute la
  logique (comparaison, agrégation, rendu) est déléguée à
  `app.modules.ingest.rapport_ocr` ; cette CLI ne fait que construire l'OCR
  réel de `--appeler-ocr` (mêmes options et délai que `ingest/router
  .py::get_ocr`, `OPTIONS_OCR_BL` d'`extract.bl`, `DELAI_OCR_BL`
  d'`ingest.router`) sur un client HTTP qu'elle ouvre et ferme elle-même —
  jamais sur un document client (R17, protocole détaillé dans
  `docs/protocole-mesure-ocr.md`).
- `python -m app.cli rapprocher [--facture <uuid> | --tout]` (L4-T11) :
  rejoue `ingest.rapprochement.rapprocher_facture` (déjà commité, idempotent
  L4-D3). `--facture` traite une seule facture (code 2, message sur stderr,
  si `FactureIntrouvable` — absente ou pas de type facture) ; `--tout`
  traite chaque facture `recu` de la plus ancienne à la plus récente
  (`ingest.rapprochement.factures_recues`), une transaction par facture via
  `rapprocher_facture_sans_echec` (déjà commité : journalise l'échec,
  absorbe l'exception, ne fait jamais échouer la boucle), compte les échecs
  et sort en code 1 s'il y en a eu au moins un, 0 sinon. Sortie : un repère
  par facture (`numero_interne`, jamais `Document.numero` du fournisseur)
  suivi de comptes et taux, jamais une valeur du document client (décision
  du contrôleur).
- `python -m app.cli controles-differes` (L4-T11) : évalue les quatre règles
  de suivi (R06, R14, R15, R16 — délais du CDC §5, L4-D14) via
  `ingest.suivi.controles_differes` et affiche le nombre d'anomalies de
  suivi ouvertes après synchronisation. Idempotente, sans argument (l'heure
  d'exécution est lue une fois, `datetime.now(UTC)`) ; à lancer
  quotidiennement par cron (`docs/exploitation-lot-4.md`) — pas de worker
  (CDC §7).
- `python -m app.cli drive-sync` (L5-T11) : synchronise par lot les originaux
  vers le dossier Google Drive configuré. Refuse de démarrer sans les deux
  variables Drive ; réessaie les échecs et signale après 24 h sur Telegram.
- `python -m app.cli rattacher-chantiers` (Task 8, spec §2.8) : reprise, au
  déploiement, des noms de chantier en attente de l'ancien flux (alias
  `chantier_id IS NULL`) et des bons non archivés encore sans chantier —
  rejoue `ingest.rattachement_chantier.reprendre_chantiers` (déjà commité,
  idempotente). Sans argument, à lancer une fois après la mise en
  production. Toujours code 0 (les deux fonctions rattachées absorbent déjà
  tous les cas, comme `controles-differes`).
- `python -m app.cli ranger-photos` (Task 9, spec §5) : (re)construit le
  rangement des photos de bon sous `<DOCS_DIR>/bl/<AAAA>/<MM>/...` — un lien
  physique par bon `bl`/`enlevement` non archivé, jamais une copie. Rejoue
  `ingest.rangement.ranger_tout` (idempotente) : pose les liens manquants,
  laisse inchangés ceux déjà corrects. Rattrape en particulier les bons dont
  le chantier a changé par propagation d'alias (jamais renommés à la volée,
  décision du contrôleur, Task 9) et ceux de la reprise
  (`rattacher-chantiers`). À lancer une fois au déploiement puis chaque nuit
  (cron, hors périmètre de cette tâche). Toujours code 0 (un échec individuel
  est absorbé et journalisé par `ingest.rangement.ranger_document`, jamais
  remonté ici).

N'importe comme couches applicatives que `app.core`, `app.modules.ingest` et
`app.modules.jobs` ; l'import de `messaging.telegram` reste différé au seul
signalement Drive. Les dépendances métier historiques sont `factures.py`,
`mistral.py` — depuis le découpage de l'ancien
`ingest/service.py`, vague finale du lot 2, point 1 ; `referentiels.py`
depuis L3-T5 ; `rapport_ocr.py`, `router.py` depuis L3-T11 ;
`rapprochement.py`, `suivi.py` depuis L4-T11, plus `FactureIllisible`
d'`extract` (nécessaire pour distinguer le code de sortie) et
`OPTIONS_OCR_BL`/`SEUIL_CONFIANCE_DEFAUT`/`TOLERANCE_TOTAL_DEFAUT`
d'`extract` (L3-T11, mêmes constantes que le reste du lot 3). La CLI ne fait
que construire ses dépendances (client HTTP, moteur DB) et les brancher vers
`ingest` ou `jobs` (décisions du contrôleur
T7/L2-T1b/L3-T5/L3-T11/L4-T11/L5-T11). L5-T11 ajoute le paquet `jobs`
et un import différé de `messaging.telegram` pour le seul signalement.
`rattachement_chantier.py` depuis Task 8 (avenant du 27/09/2026),
`rangement.py` depuis Task 9 (même avenant).

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
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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
from app.modules.ingest.rangement import ranger_tout
from app.modules.ingest.rapport_ocr import (
    ecrire_rapport,
    mesurer_dossier,
    rapport_markdown,
)
from app.modules.ingest.rapprochement import (
    FactureIntrouvable,
    ResultatRapprochement,
    factures_recues,
    rapprocher_facture,
    rapprocher_facture_sans_echec,
)
from app.modules.ingest.rattachement_chantier import reprendre_chantiers
from app.modules.ingest.referentiels import definir_fournisseur
from app.modules.ingest.router import DELAI_OCR_BL
from app.modules.ingest.suivi import controles_differes
from app.modules.jobs.drive import ClientGoogleDrive, JetonCompteServiceGoogle
from app.modules.jobs.drive_sync import synchroniser_documents

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


def _seuil_decimal(valeur: str) -> Decimal:
    """Type argparse de `--seuil` (fix round 1, finding 2 / ruling R13) :
    `Decimal` compris entre 0 et 1 inclus, sinon `argparse.ArgumentTypeError`
    — argparse affiche alors un message d'erreur clair et quitte avec le
    code 2, même mécanique que `--role` de `utilisateur-creer` (`choices`,
    `test_utilisateur_creer_role_invalide_rejete_par_argparse_systemexit_2`).
    `Decimal("nan")` est accepté par le constructeur (extension non standard,
    comme pour `json.loads`, cf. `extract/confiance.py`) mais n'est pas fini :
    le comparer lève `decimal.InvalidOperation` au lieu de retourner un
    booléen. `is_finite()` rejette donc `nan`/`inf`/`-inf` avant toute
    comparaison, avec le même message que hors bornes (vague finale, revue de
    branche)."""
    try:
        seuil = Decimal(valeur)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(
            f"seuil invalide (nombre attendu) : {valeur!r}"
        ) from None
    if not seuil.is_finite() or not (Decimal("0") <= seuil <= Decimal("1")):
        raise argparse.ArgumentTypeError(
            f"seuil doit être compris entre 0 et 1 (reçu {valeur!r})"
        )
    return seuil


async def _rapport_ocr(
    *, dossier: Path, sortie: Path, appeler_ocr: bool, seuil: Decimal
) -> int:
    """Implémentation de `rapport-ocr` (L3-T11, L3-D20 ; `--seuil` fix
    round 1, finding 2/ruling R13) : mesure le taux d'erreur OCR sur
    `dossier` (photos + `<nom>.attendu.json`) et écrit le rapport Markdown
    dans `sortie`. Toute la comparaison/agrégation est déléguée à
    `app.modules.ingest.rapport_ocr` (module pur/orchestré, sans FastAPI ni
    SQLAlchemy) : cette CLI ne fait que construire l'OCR réel et brancher
    les dépendances.

    Sans `--appeler-ocr`, seul le cache `<nom>.mistral-ocr.json` de chaque
    photo est utilisé (aucun appel réseau) : une photo sans cache part dans
    `documents_sans_ocr`. Avec `--appeler-ocr`, l'OCR de production est
    construit avec les mêmes options et le même délai que `ingest/router
    .py::get_ocr` (`OPTIONS_OCR_BL`, `DELAI_OCR_BL`), sur un client HTTP
    ouvert et fermé par cette commande, clé API lue dans la configuration —
    jamais sur un document client (décision du contrôleur,
    `docs/protocole-mesure-ocr.md`).

    `mesurer_dossier` isole désormais les fichiers invalides par document
    (fix round 1, finding 1) : un `<nom>.attendu.json` invalide ou un échec
    OCR (cache invalide ou appel en échec) n'interrompent plus la commande,
    ils sont comptés séparément (stdout) et listés (rapport Markdown).

    Codes de sortie : 2 si `dossier` n'existe pas, ou si aucune photo n'y a
    été trouvée du tout (ni mesurée, ni sans OCR, ni en attendu/OCR invalide
    — un dossier réellement vide, ou sans aucun `<nom>.attendu.json`) —
    message court sur stderr, rien n'est écrit dans `sortie` ; sinon 0,
    rapport écrit, seuls des comptes et des taux affichés sur stdout (jamais
    une valeur attendue ou lue)."""
    if not await asyncio.to_thread(dossier.is_dir):
        print(f"dossier introuvable : {dossier}", file=sys.stderr)
        return 2

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

    if (
        rapport.nb_documents == 0
        and not rapport.documents_sans_ocr
        and not rapport.attendus_invalides
        and not rapport.echecs_ocr
    ):
        print(
            f"aucun BL attendu (<nom>.attendu.json) trouvé dans {dossier}",
            file=sys.stderr,
        )
        return 2

    contenu_rapport = rapport_markdown(rapport, comparaisons)
    # Droits restreints (tâche T3, correction relecture) : jamais
    # `sortie.write_text`, voir `rapport_ocr.ecrire_rapport`.
    await asyncio.to_thread(ecrire_rapport, sortie, contenu_rapport)

    print(f"{rapport.nb_documents} documents mesurés ({rapport.nb_degrades} dégradés)")
    for champ, taux in rapport.taux_champs.items():
        print(f"  champ {champ} juste : {taux}")
    print(f"  documents 4 champs justes : {rapport.taux_documents_4_champs}")
    print(f"  lignes justes : {rapport.taux_lignes}")
    print(f"  erreurs silencieuses : {rapport.nb_erreurs_silencieuses}")
    if rapport.documents_sans_ocr:
        print(f"  documents sans réponse OCR : {len(rapport.documents_sans_ocr)}")
    if rapport.attendus_invalides:
        print(f"  attendus invalides : {len(rapport.attendus_invalides)}")
    if rapport.echecs_ocr:
        print(f"  échecs OCR : {len(rapport.echecs_ocr)}")
    print(f"rapport écrit : {sortie}")
    return 0


def _formater_resultat_rapprochement(resultat: ResultatRapprochement) -> str:
    """Sortie de `rapprocher` (décision du contrôleur : comptes et taux
    seulement, jamais une valeur de document client — ni numéro de facture,
    ni chantier, ni montant)."""
    return (
        f"{resultat.nb_blocs} blocs, {resultat.nb_blocs_recus} reçus, "
        f"{resultat.nb_blocs_pas_de_bon} pas de bon, "
        f"{resultat.nb_lignes_appariees} lignes appariées, "
        f"{resultat.nb_anomalies} anomalies ouvertes"
    )


async def _rapprocher_facture(*, facture_id: uuid.UUID) -> int:
    """Implémentation de `rapprocher --facture` (L4-T11). Toute la logique
    est déjà dans `ingest.rapprochement.rapprocher_facture` (idempotent,
    L4-D3) : cette CLI ne fait que construire ses dépendances (moteur DB) et
    les brancher, comme les autres commandes de ce fichier. Code de sortie 2
    si la facture est introuvable ou n'est pas une facture
    (`FactureIntrouvable`), message court sur stderr."""
    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            try:
                resultat = await rapprocher_facture(session, facture_id)
            except FactureIntrouvable as exc:
                print(f"facture introuvable : {exc}", file=sys.stderr)
                return 2
    finally:
        await engine.dispose()

    print(_formater_resultat_rapprochement(resultat))
    return 0


async def _rapprocher_tout() -> int:
    """Implémentation de `rapprocher --tout` (L4-T11, décision du
    contrôleur) : traite les factures `recu` de la plus ancienne à la plus
    récente (`ingest.rapprochement.factures_recues`), une transaction par
    facture via `rapprocher_facture_sans_echec` (déjà commité : journalise
    l'échec, absorbe l'exception, ne fait jamais échouer la boucle) — compte
    les échecs plutôt que de s'arrêter à la première facture en erreur.

    Une ligne par facture traitée (repère `numero_interne`, jamais
    `Document.numero` du fournisseur — décision du contrôleur : « comptes et
    taux seulement, jamais une valeur de document client »), puis une ligne
    de synthèse. Code de sortie 1 s'il y a eu au moins un échec, 0 sinon."""
    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            factures = await factures_recues(session)
            nb_echecs = 0
            nb_anomalies_total = 0
            for facture_id, numero_interne in factures:
                resultat = await rapprocher_facture_sans_echec(session, facture_id)
                if resultat is None:
                    nb_echecs += 1
                    print(
                        f"facture {numero_interne} : échec du rapprochement",
                        file=sys.stderr,
                    )
                else:
                    nb_anomalies_total += resultat.nb_anomalies
                    print(
                        f"facture {numero_interne} : "
                        f"{_formater_resultat_rapprochement(resultat)}"
                    )
    finally:
        await engine.dispose()

    print(
        f"{len(factures)} factures traitées, {nb_echecs} échecs, "
        f"{nb_anomalies_total} anomalies ouvertes au total"
    )
    return 1 if nb_echecs > 0 else 0


async def _controles_differes() -> int:
    """Implémentation de `controles-differes` (L4-T11) : évalue les règles
    de suivi (R06, R14, R15, R16, L4-D14) via `ingest.suivi
    .controles_differes` et affiche le nombre d'anomalies de suivi ouvertes
    après synchronisation. Toujours code 0 (aucune validation ne peut
    échouer ici, comme `fournisseur-definir`)."""
    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            nb_ouvertes = await controles_differes(
                session, maintenant=datetime.now(UTC)
            )
    finally:
        await engine.dispose()

    print(f"{nb_ouvertes} anomalies de suivi ouvertes")
    return 0


async def _drive_sync(*, limite: int) -> int:
    """Synchronise un lot borné ; refuse de démarrer sans secret Drive."""
    settings = get_settings()
    secret = settings.google_drive_service_account_json
    dossier_racine = settings.google_drive_folder_id
    if secret is None or not dossier_racine:
        print("configuration Google Drive absente", file=sys.stderr)
        return 2

    # Import différé : les autres commandes restent indépendantes du canal.
    from app.modules.messaging.telegram import TelegramClient

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as http:
        try:
            jetons = JetonCompteServiceGoogle(secret.get_secret_value(), http)
        except (TypeError, ValueError):
            print("configuration Google Drive invalide", file=sys.stderr)
            return 2
        drive = ClientGoogleDrive(
            http, jetons.obtenir, dossier_racine_id=dossier_racine
        )
        telegram = TelegramClient(settings.telegram_bot_token.get_secret_value(), http)

        async def _signaler(texte: str) -> None:
            await telegram.envoyer(settings.telegram_chat_supervision_id, texte)

        engine = creer_engine(settings.database_url)
        try:
            sessions = creer_sessionmaker(engine)
            async with sessions() as session:
                resultat = await synchroniser_documents(
                    session,
                    drive,
                    limite=limite,
                    signaler=_signaler,
                )
        finally:
            await engine.dispose()

    print(
        "Drive : "
        f"{resultat.traites} traité(s), "
        f"{resultat.reussis} réussi(s), "
        f"{resultat.echecs} échec(s), "
        f"{resultat.signales} signalé(s)"
    )
    return 1 if resultat.echecs else 0


async def _rattacher_chantiers() -> int:
    """Implémentation de `rattacher-chantiers` (Task 8, spec §2.8). Toute la
    logique (deux passes -- alias en attente puis bons sans chantier,
    ruling du contrôleur sur le nom d'un chantier créé à cette occasion) est
    déjà dans `ingest.rattachement_chantier.reprendre_chantiers` (idempotente,
    commite elle-même) : cette CLI ne fait que construire ses dépendances
    (moteur DB) et les brancher, comme les autres commandes de ce fichier.
    Toujours code 0 (aucune validation ne peut échouer ici, comme
    `controles-differes`)."""
    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            bilan = await reprendre_chantiers(session)
    finally:
        await engine.dispose()

    print(
        f"Noms rattachés : {bilan.alias_rattaches} · "
        f"chantiers créés : {bilan.chantiers_crees} · "
        f"noms ambigus : {bilan.alias_ambigus} · "
        f"bons rattachés : {bilan.bons_rattaches} · "
        f"bons en alerte : {bilan.bons_en_alerte}"
    )
    return 0


async def _ranger_photos() -> int:
    """Implémentation de `ranger-photos` (Task 9, spec §5). Toute la
    logique (chemin cible, lien physique, dossiers en 0750, idempotence) est
    déjà dans `ingest.rangement.ranger_tout` : cette CLI ne fait que
    construire ses dépendances (moteur DB, `DOCS_DIR`) et les brancher,
    comme les autres commandes de ce fichier. Toujours code 0 (un échec
    individuel de rangement est absorbé et journalisé par
    `ingest.rangement.ranger_document`, jamais remonté ici, comme
    `rattacher-chantiers`)."""
    settings = get_settings()
    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            nb_ranges = await ranger_tout(session, settings.docs_dir)
    finally:
        await engine.dispose()

    print(f"{nb_ranges} bon(s) rangé(s)")
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
        "--seuil",
        type=_seuil_decimal,
        default=SEUIL_CONFIANCE_DEFAUT,
        help=(
            "seuil de confiance OCR entre 0 et 1 (défaut : "
            f"{SEUIL_CONFIANCE_DEFAUT}) — voir docs/protocole-mesure-ocr.md §6 "
            "pour le calage"
        ),
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

    parser_rapprocher = sous_parsers.add_parser(
        "rapprocher",
        help="Rejoue le rapprochement d'une facture, ou de toutes les factures reçues",
    )
    groupe_rapprocher = parser_rapprocher.add_mutually_exclusive_group(required=True)
    groupe_rapprocher.add_argument(
        "--facture", type=uuid.UUID, help="identifiant de la facture à rapprocher"
    )
    groupe_rapprocher.add_argument(
        "--tout",
        action="store_true",
        help="toutes les factures reçues, de la plus ancienne à la plus récente",
    )

    sous_parsers.add_parser(
        "controles-differes",
        help=(
            "Évalue les règles de suivi (R14, R15, R16, et R06 seulement si "
            "CONTROLE_LIVRE_NON_FACTURE_ACTIF est vraie) et synchronise "
            "leurs anomalies"
        ),
    )

    parser_drive_sync = sous_parsers.add_parser(
        "drive-sync",
        help="Synchronise vers Google Drive les documents encore en attente",
    )
    parser_drive_sync.add_argument(
        "--limite",
        type=int,
        default=100,
        choices=range(1, 1001),
        metavar="1..1000",
        help="nombre maximal de documents à traiter (défaut : 100)",
    )

    sous_parsers.add_parser(
        "rattacher-chantiers",
        help=(
            "Reprise des noms de chantier en attente (ancien flux) et des "
            "bons non archivés encore sans chantier -- à lancer une fois au "
            "déploiement, idempotente"
        ),
    )

    sous_parsers.add_parser(
        "ranger-photos",
        help=(
            "(Re)construit le rangement des photos de bon sous "
            "<DOCS_DIR>/bl/<AAAA>/<MM>/... (lien physique, jamais une copie) "
            "-- idempotente, à lancer au déploiement puis chaque nuit"
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
                dossier=args.dossier,
                sortie=args.sortie,
                appeler_ocr=args.appeler_ocr,
                seuil=args.seuil,
            )
        )
    if args.commande == "rapprocher":
        if args.tout:
            return asyncio.run(_rapprocher_tout())
        return asyncio.run(_rapprocher_facture(facture_id=args.facture))
    if args.commande == "controles-differes":
        return asyncio.run(_controles_differes())
    if args.commande == "drive-sync":
        return asyncio.run(_drive_sync(limite=args.limite))
    if args.commande == "rattacher-chantiers":
        return asyncio.run(_rattacher_chantiers())
    if args.commande == "ranger-photos":
        return asyncio.run(_ranger_photos())
    raise AssertionError(f"commande inconnue : {args.commande}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
