"""Rangement des photos de bon sur le serveur (Task 9, avenant du
27/09/2026, spec §5) : chaque bon (`bl`/`enlevement`) non archivé a, en plus
de `docs_dir/<uuid4>.<ext>` (`Document.fichier_path`, jamais déplacé ni
renommé), un **lien physique** -- jamais une copie, jamais d'espace disque
supplémentaire -- sous
`<DOCS_DIR>/bl/<AAAA>/<MM>/<JJ>_<déposant>_<chantier>_n<numéro
interne>.<ext>`, `JJ` étant le jour du DÉPÔT (`Document.created_at`) à
l'heure de Paris.

Ce n'est PAS une sauvegarde : le lien pointe sur le même inode que
`fichier_path`, sur le même disque -- une panne disque, une suppression du
fichier d'origine ou un `chmod` emportent les deux à la fois. Seul un
objectif de rangement lisible pour un humain qui irait consulter le dossier
directement à la place de l'écran Documents (aucune sauvegarde hors site
n'est prévue avant le 1er octobre, `docs/dette.md`).

Posé après la lecture du bon (`ingest.depot_telegram.traiter_fichier`, une
fois l'OCR tenté -- le chantier lu peut alors déjà être résolu par
`rattachement_chantier.rattacher_chantier_document`, appelé depuis
`extraction_bl.enregistrer_extraction_bl`) et **renommé** (ancien lien
retiré, nouveau posé) à chaque changement de chantier commité par un
humain : voir les appelants côté `app.modules.api.documents`/`api
.referentiels`, après le commit de `rattachement_chantier
.choisir_chantier_document`/`fusion_chantier.fusionner_chantiers`
/`corrections.corriger_entete` (`docs_dir` lu via `get_settings().docs_dir`,
l'API pouvant importer `app.core`), et `corrections.relancer_extraction`,
qui reçoit déjà `docs_dir` en paramètre et appelle `ranger_document`
directement après son propre commit.

Ruling du contrôleur (27/09/2026, avenant, brief Task 9) : un bon dont le
chantier change par PROPAGATION d'un alias (apprentissage fait à l'occasion
d'un AUTRE bon, `rattachement_chantier._apprendre_alias` ->
`referentiels.candidats_alias`, ou validation manuelle d'un alias en attente,
`referentiels.valider_alias`) n'est **jamais** renommé à la volée -- retrouver
tous les documents qu'un alias qui vient d'être (ré)appris concerne
dupliquerait `candidats_alias` pour un gain marginal (aucun affichage ne
dépend du nom du fichier sur disque). Ces bons, comme ceux de la reprise
(`rattachement_chantier.reprendre_chantiers`, Task 8, déjà lancée avant
cette tâche), sont rattrapés par `ranger_tout`
(`python -m app.cli ranger-photos`) -- à lancer une fois au déploiement puis
chaque nuit (cron, hors périmètre de cette tâche).

Un échec de rangement (disque plein, droits, ...) est journalisé
(`logger.error`, jamais le contenu ni le chemin du document) et ne lève
jamais : `ranger_document` absorbe toute `OSError` et renvoie `None`. Ni
`traiter_fichier`, ni un routeur, ni la reprise ne doivent jamais échouer
pour un problème de lien physique -- le rangement n'est qu'un confort,
jamais une condition d'un dépôt ou d'une correction.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.core.segments import normaliser_segment
from app.modules.ingest.commun import _creer_dossier_documents
from app.modules.ingest.lecture import TYPES_BL
from app.modules.ingest.models import Chantier, Document, Utilisateur

logger = logging.getLogger("app.modules.ingest.rangement")


def _segment_optionnel(valeur: str | None) -> str | None:
    """`normaliser_segment(valeur).lower()`, ou `None` pour une valeur
    absente/vide -- `normaliser_segment` ne renvoie elle-même jamais de
    chaîne vide (repli `"sans-nom"`), donc c'est ici, avant l'appel, que se
    décide le repli propre à chaque segment (`"inconnu"`/`"sans-chantier"`,
    voir `chemin_range`)."""
    return normaliser_segment(valeur).lower() if valeur else None


def chemin_range(
    docs_dir: Path,
    *,
    depose_le: datetime,
    deposant: str | None,
    chantier: str | None,
    numero_interne: int,
    extension: str,
) -> Path:
    """Chemin cible du lien physique d'un bon -- voir le docstring de
    module. `depose_le` (généralement en UTC, tel que stocké en base) est
    converti en heure de Paris avant d'en tirer année/mois/jour (CDC : «
    jour du dépôt à l'heure de Paris », même fuseau que la ligne de
    supervision d'un dépôt, `ingest.depot_telegram._ligne_supervision`)."""
    heure_paris = depose_le.astimezone(FUSEAU_PARIS)
    deposant_segment = _segment_optionnel(deposant) or "inconnu"
    chantier_segment = _segment_optionnel(chantier) or "sans-chantier"
    extension_segment = normaliser_segment(extension).lower()
    nom = (
        f"{heure_paris:%d}_{deposant_segment}_{chantier_segment}_"
        f"n{numero_interne}.{extension_segment}"
    )
    return docs_dir / "bl" / f"{heure_paris:%Y}" / f"{heure_paris:%m}" / nom


def _assurer_dossiers(docs_dir: Path, dossier: Path) -> None:
    """Crée `dossier` (et les niveaux manquants entre `docs_dir` et lui),
    chacun en 0750 -- `Path.mkdir(parents=True)` n'applique le mode donné
    qu'au dernier niveau qu'il crée, les parents manquants intermédiaires
    étant créés avec le mode par défaut (comportement documenté de
    `pathlib`) : chaque niveau (`bl`, `bl/AAAA`, `bl/AAAA/MM`) est donc créé
    un par un via `_creer_dossier_documents`, jamais en un seul appel."""
    relatif = dossier.relative_to(docs_dir)
    courant = docs_dir
    for partie in relatif.parts:
        courant = courant / partie
        _creer_dossier_documents(courant)


def _poser_lien(docs_dir: Path, source: Path, cible: Path, numero_interne: int) -> None:
    """Partie synchrone (I/O disque bloquante), exécutée via
    `asyncio.to_thread` par `ranger_document`.

    Retire tout lien existant `bl/*/*/*_n<numero_interne>.*` différent de
    `cible` -- un bon ne porte jamais deux liens à la fois, un changement de
    chantier (ou de déposant/extension, en théorie immuables) renomme donc
    toujours en retirant l'ancien avant de poser le nouveau. Pose ensuite
    `cible` (dossiers créés en 0750 si besoin) sauf si elle existe déjà
    (idempotent : `ranger_tout` peut rejouer cette fonction sur un bon déjà
    rangé sans effet)."""
    motif = f"*_n{numero_interne}.*"
    for ancien in docs_dir.glob(f"bl/*/*/{motif}"):
        if ancien != cible:
            ancien.unlink(missing_ok=True)
    if cible.exists():
        return
    _assurer_dossiers(docs_dir, cible.parent)
    os.link(source, cible)


async def _nom_deposant(session: AsyncSession, deposant_id: uuid.UUID) -> str | None:
    ligne = (
        await session.execute(
            select(Utilisateur.nom, Utilisateur.email).where(
                Utilisateur.id == deposant_id
            )
        )
    ).first()
    if ligne is None:
        return None
    nom_ou_email: str | None = ligne.nom or ligne.email
    return nom_ou_email


async def ranger_document(
    session: AsyncSession, docs_dir: Path, document_id: uuid.UUID
) -> Path | None:
    """Pose (ou renomme) le lien physique d'un bon -- voir le docstring de
    module pour les points d'appel. `None` si le document est absent, n'est
    ni un `bl` ni un `enlevement`, ou est archivé (aucun rangement pour ces
    cas) ; `None` aussi en cas d'échec disque (`OSError`, journalisé,
    jamais levée). N'écrit rien en base : lecture seule côté document,
    déposant et chantier."""
    document = await session.get(Document, document_id)
    if (
        document is None
        or document.type not in TYPES_BL
        or document.statut == "archive"
    ):
        return None

    deposant_nom = (
        await _nom_deposant(session, document.deposant_id)
        if document.deposant_id is not None
        else None
    )

    chantier_nom: str | None = None
    if document.chantier_id is not None:
        chantier_nom = (
            await session.execute(
                select(Chantier.nom_canonique).where(
                    Chantier.id == document.chantier_id
                )
            )
        ).scalar_one_or_none()

    extension = Path(document.fichier_path).suffix.removeprefix(".")
    cible = chemin_range(
        docs_dir,
        depose_le=document.created_at,
        deposant=deposant_nom,
        chantier=chantier_nom,
        numero_interne=document.numero_interne,
        extension=extension,
    )

    try:
        await asyncio.to_thread(
            _poser_lien,
            docs_dir,
            Path(document.fichier_path),
            cible,
            document.numero_interne,
        )
    except OSError as exc:
        logger.error(
            "échec du rangement du bon n° %s : %s",
            document.numero_interne,
            type(exc).__name__,
        )
        return None
    return cible


async def ranger_tout(session: AsyncSession, docs_dir: Path) -> int:
    """(Re)construit tout le rangement -- `python -m app.cli ranger-photos`
    (spec §5) : rejoue `ranger_document` pour chaque bon non archivé,
    y compris ceux qu'un changement de chantier par propagation d'alias n'a
    jamais renommés à la volée (voir le docstring de module). Idempotente
    (`ranger_document`/`_poser_lien` le sont déjà). Renvoie le nombre de
    bons dont le lien a été posé ou confirmé -- un échec individuel est
    absorbé et journalisé par `ranger_document`, jamais compté ni remonté
    ici."""
    ids = (
        (
            await session.execute(
                select(Document.id).where(
                    Document.type.in_(TYPES_BL),
                    Document.statut != "archive",
                )
            )
        )
        .scalars()
        .all()
    )
    nb_ranges = 0
    for document_id in ids:
        if await ranger_document(session, docs_dir, document_id) is not None:
            nb_ranges += 1
    return nb_ranges
