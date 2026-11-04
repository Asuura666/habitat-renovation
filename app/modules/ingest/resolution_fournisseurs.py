"""Rattachement des bons déjà reçus aux fournisseurs créés après coup, sans
rappeler l'OCR (décision d'Ilane du 31/10/2026).

Après la création des fournisseurs manquants (Point.P, Cedeo, Rexel, …), les
bons reçus avant leur création n'ont pas de `fournisseur_id`. Ce service rejoue
leur lecture à partir de `document.ocr_brut` (la réponse OCR déjà gardée) :
aucun appel à Mistral, aucun fichier relu. Il n'a d'ailleurs aucune
dépendance OCR.

- Bons concernés : type `bl` ou `enlevement`, non archivés, `fournisseur_id`
  vide, `ocr_brut` présent.
- Les bons **corrigés ou validés à la main** (une entrée de journal
  `document_corrige`, `lignes_corrigees` ou `document_valide` pour ce
  document) sont ignorés : la relecture écraserait le travail de l'équipe.
- La relecture passe par le chemin unique de `relancer_extraction`
  (`corrections.rejouer_extraction_depuis_reponse`), jamais une copie : mêmes
  écritures, même rapprochement, même journal `extraction_relancee` (précisé
  « Sans nouvel OCR », auteur vide).
- Le statut suit les motifs restants : un bon dont le seul motif était
  « fournisseur inconnu » passe à `recu` (et sort de « À régler ») ; un bon qui
  garde un autre motif reste `a_verifier`. Seuls les bons `a_verifier` sont
  relus ; un autre statut est compté parmi les ignorés.
- Simulation : n'écrit rien ; pour chaque bon, appelle seulement
  `normalize.fournisseur.resoudre_fournisseur` sur les champs lus.

Aucune valeur client dans les journaux applicatifs : seulement le numéro
interne du bon et le type de l'exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.bl import analyser_bl
from app.modules.ingest.commun import logger
from app.modules.ingest.corrections import rejouer_extraction_depuis_reponse
from app.modules.ingest.models import Document, Journal
from app.modules.ingest.referentiels import charger_fournisseurs
from app.modules.normalize.fournisseur import resoudre_fournisseur

# Corrections faites à la main par l'équipe : le bon n'est plus relu.
_ACTIONS_MAIN = ("document_corrige", "lignes_corrigees", "document_valide")


@dataclass(frozen=True)
class LigneSimulation:
    """Un bon examiné en simulation : son numéro interne et le nom du
    fournisseur qui serait trouvé (`None` : toujours inconnu)."""

    numero_interne: int
    fournisseur: str | None


@dataclass(frozen=True)
class BilanResolution:
    relus: int
    rattaches: int
    inconnus: int
    ignores: int  # corrigés ou validés à la main
    echecs: int
    lignes: tuple[LigneSimulation, ...]  # rempli en simulation seulement


async def candidats_bons(
    session: AsyncSession, *, sans_fournisseur: bool
) -> list[tuple[Any, int]]:
    """Bons et enlèvements non archivés dont la lecture est gardée ;
    `sans_fournisseur` : seulement ceux sans fournisseur (résolution), sinon
    seulement ceux à vérifier (recalcul, `ingest.recalcul_bons`)."""
    condition = (
        Document.fournisseur_id.is_(None)
        if sans_fournisseur
        else Document.statut == "a_verifier"
    )
    lignes = await session.execute(
        select(Document.id, Document.numero_interne)
        .where(
            Document.type.in_(("bl", "enlevement")),
            Document.statut != "archive",
            condition,
            Document.ocr_brut.is_not(None),
        )
        .order_by(Document.numero_interne)
    )
    return [(ligne.id, ligne.numero_interne) for ligne in lignes]


async def corriges_a_la_main(session: AsyncSession, ids: list[Any]) -> set[str]:
    if not ids:
        return set()
    lignes = await session.execute(
        select(Journal.cible_id)
        .where(
            Journal.cible_table == "document",
            Journal.action.in_(_ACTIONS_MAIN),
            Journal.cible_id.in_([str(i) for i in ids]),
        )
        .distinct()
    )
    return {cible for (cible,) in lignes if cible is not None}


def a_des_pages(reponse: Any) -> bool:
    return isinstance(reponse, dict) and isinstance(reponse.get("pages"), list)


async def rejouer_bon(
    session: AsyncSession, document: Document, reponse: dict[str, Any], docs_dir: Path
) -> bool:
    """Rejoue la lecture gardée d'un bon par le chemin unique de
    `relancer_extraction` (sans nouvel OCR). Partagé avec
    `ingest.recalcul_bons`. Vrai si la relecture a abouti ; sinon la
    transaction est annulée, l'échec journalisé (numéro interne et type de
    l'exception seulement) et le résultat est faux."""
    numero_interne = document.numero_interne
    try:
        await rejouer_extraction_depuis_reponse(
            session,
            document,
            reponse,
            docs_dir,
            auteur_id=None,
            sans_nouvel_ocr=True,
        )
    except Exception as exc:
        await session.rollback()
        logger.error(
            "résolution des fournisseurs : bon n° %s non relu : %s",
            numero_interne,
            type(exc).__name__,
        )
        return False
    return True


async def resoudre_fournisseurs_des_bons(
    session: AsyncSession, docs_dir: Path, *, simulation: bool = False
) -> BilanResolution:
    candidats = await candidats_bons(session, sans_fournisseur=True)
    a_la_main = await corriges_a_la_main(session, [i for i, _ in candidats])
    a_relire = [(i, n) for i, n in candidats if str(i) not in a_la_main]
    ignores = len(candidats) - len(a_relire)

    relus = rattaches = inconnus = echecs = 0
    lignes: list[LigneSimulation] = []
    referentiel = await charger_fournisseurs(session) if simulation else []

    for document_id, numero_interne in a_relire:
        document = await session.get(Document, document_id)
        if document is None or document.ocr_brut is None:
            continue  # disparu entre-temps
        reponse = document.ocr_brut
        if document.statut != "a_verifier":
            ignores += 1  # même condition que `relancer_extraction`
            continue
        relus += 1

        if simulation:
            nom = _fournisseur_trouve(reponse, referentiel)
            lignes.append(LigneSimulation(numero_interne, nom))
            if nom is None:
                inconnus += 1
            else:
                rattaches += 1
            continue

        if not a_des_pages(reponse):
            inconnus += 1
            continue
        if not await rejouer_bon(session, document, reponse, docs_dir):
            echecs += 1
            relus -= 1
            continue
        fournisseur_id = (
            await session.execute(
                select(Document.fournisseur_id).where(Document.id == document_id)
            )
        ).scalar_one()
        if fournisseur_id is None:
            inconnus += 1
        else:
            rattaches += 1

    return BilanResolution(
        relus=relus,
        rattaches=rattaches,
        inconnus=inconnus,
        ignores=ignores,
        echecs=echecs,
        lignes=tuple(lignes),
    )


def _fournisseur_trouve(reponse: Any, referentiel: list[Any]) -> str | None:
    """Nom du fournisseur du référentiel que la résolution trouverait pour la
    lecture gardée (`None` : toujours inconnu ou lecture inexploitable)."""
    if not a_des_pages(reponse):
        return None
    try:
        extrait = analyser_bl(reponse)
    except Exception:
        return None
    resolution = resoudre_fournisseur(
        siret=extrait.siret.brut,
        tva=extrait.tva_intracommunautaire.brut,
        nom=extrait.fournisseur.brut,
        referentiel=referentiel,
    )
    if resolution.fournisseur_id is None:
        return None
    return next((f.nom for f in referentiel if f.id == resolution.fournisseur_id), None)
