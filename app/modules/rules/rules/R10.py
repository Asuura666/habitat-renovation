"""R10 — incohérence arithmétique facture (CDC §5, L4-T1).

Reprend le motif `somme_incoherente` déjà produit par l'extraction (lot 3,
`extract.verification`) et persisté dans `document.motifs` : R10 ne
recalcule jamais la somme des lignes, elle applique seulement le seuil
configurable par l'admin (`Parametres.tolerance_total_ht`, L4-D10) à
l'écart déjà calculé par `ingest` (`DocumentControle.ecart_somme`, L4-D8).
Gravité haute (CDC §5) : le document reste « à vérifier » tant que
l'écart dépasse la tolérance (Ruling R2 : `evaluer_facture` s'arrête après
cette règle si elle se déclenche)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, DocumentControle, Gravite, Parametres


def R10(document: DocumentControle, parametres: Parametres) -> Anomalie | None:
    """`None` si `ecart_somme` est absent (somme cohérente ou non
    calculable, L4-D8), si l'écart ne dépasse pas la tolérance, ou si
    `somme_lignes`/`total_ht` manquent malgré un `ecart_somme` renseigné
    (état incohérent qui ne doit jamais faire lever d'exception : une
    donnée manquante donne toujours `None`)."""
    if document.ecart_somme is None:
        return None
    if document.somme_lignes is None or document.total_ht is None:
        return None
    if abs(document.ecart_somme) <= parametres.tolerance_total_ht:
        return None

    return Anomalie(
        regle="R10",
        gravite=Gravite.HAUTE,
        detail={
            "somme": str(document.somme_lignes),
            "total": str(document.total_ht),
            "ecart": str(document.ecart_somme),
            "tolerance": str(parametres.tolerance_total_ht),
        },
        document_id=document.id,
    )
