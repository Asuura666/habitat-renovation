"""Recalcul des bons déjà reçus avec les règles de lecture du lot 2 du
31/10/2026 (commande `recalculer-bons`), sans rappeler l'OCR.

Les règles de confirmation (fournisseur reconnu par SIREN ou TVA, chantier
reconnu ou donné par la légende, chantier lu dans la référence de commande,
voir `ajustement_motifs`) ne s'appliquent qu'aux lectures faites après leur
mise en service. Ce service les applique aux bons existants en rejouant leur
lecture gardée (`document.ocr_brut`) par le même chemin que
`ingest.resolution_fournisseurs` (`rejouer_bon`, donc
`corrections.rejouer_extraction_depuis_reponse` : mêmes écritures, même
rapprochement, mêmes anomalies resynchronisées, journal `extraction_relancee`
« Sans nouvel OCR »).

- Bons concernés : `bl` ou `enlevement` non archivés, `a_verifier`, `ocr_brut`
  présent.
- Jamais un bon corrigé ou validé à la main (mêmes exclusions de journal que
  `resoudre-fournisseurs`) : ils sont comptés parmi les ignorés.
- Le statut suit les motifs restants (un bon sans motif passe à `recu`).
- Simulation : n'écrit rien et ne simule pas les règles (elles dépendent de
  l'écriture du rattachement) ; elle ne dénombre que les bons qui seraient
  relus et ceux qui seraient ignorés.

Aucune valeur client dans les journaux applicatifs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import Document, Journal
from app.modules.ingest.resolution_fournisseurs import (
    a_des_pages,
    candidats_bons,
    corriges_a_la_main,
    rejouer_bon,
)


@dataclass(frozen=True)
class BilanRecalcul:
    examines: int
    passes_a_recu: int
    motifs_leves: dict[str, int]  # par code de motif
    chantiers_par_reference: int
    ignores: int  # corrigés ou validés à la main
    echecs: int


def _codes(motifs: Any) -> Counter[str]:
    if not isinstance(motifs, list):
        return Counter()
    return Counter(
        str(m.get("code")) for m in motifs if isinstance(m, dict) and "code" in m
    )


async def _chantier_par_reference(session: AsyncSession, document_id: Any) -> bool:
    apres = (
        await session.execute(
            select(Journal.apres)
            .where(
                Journal.cible_table == "document",
                Journal.cible_id == str(document_id),
                Journal.action == "extraction_bl",
            )
            .order_by(Journal.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return isinstance(apres, dict) and apres.get("methode_chantier") == (
        "référence de commande"
    )


async def recalculer_bons(
    session: AsyncSession, docs_dir: Path, *, simulation: bool = False
) -> BilanRecalcul:
    candidats = await candidats_bons(session, sans_fournisseur=False)
    a_la_main = await corriges_a_la_main(session, [i for i, _ in candidats])
    a_relire = [(i, n) for i, n in candidats if str(i) not in a_la_main]
    ignores = len(candidats) - len(a_relire)

    examines = passes = par_reference = echecs = 0
    leves: Counter[str] = Counter()

    for document_id, _numero in a_relire:
        document = await session.get(Document, document_id)
        if document is None or document.ocr_brut is None:
            continue
        reponse = document.ocr_brut
        if not a_des_pages(reponse):
            continue
        examines += 1
        if simulation:
            continue

        avant = _codes(document.motifs)
        if not await rejouer_bon(session, document, reponse, docs_dir):
            echecs += 1
            examines -= 1
            continue
        await session.refresh(document)
        leves.update(avant - _codes(document.motifs))
        if document.statut == "recu":
            passes += 1
        if await _chantier_par_reference(session, document_id):
            par_reference += 1

    return BilanRecalcul(
        examines=examines,
        passes_a_recu=passes,
        motifs_leves=dict(leves),
        chantiers_par_reference=par_reference,
        ignores=ignores,
        echecs=echecs,
    )
