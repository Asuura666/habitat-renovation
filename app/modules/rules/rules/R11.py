"""R11 — incohérence arithmétique BL (CDC §5, L4-T1).

Même logique que R10 (L4-D8), appliquée au BL rapproché d'un bloc plutôt
qu'à la facture : gravité moyenne (le BL, pas la facture, est « à
vérifier » — CDC §5), `document_id` porte l'identifiant du BL. Ruling R2 :
si cette règle se déclenche pour un bloc, `evaluer_facture` saute les
règles de ligne de ce bloc (à partir de L4-T2) mais continue d'évaluer les
autres blocs."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, DocumentControle, Gravite, Parametres


def R11(bl: DocumentControle, parametres: Parametres) -> Anomalie | None:
    """`None` dans les mêmes cas que R10 (écart absent, sous tolérance, ou
    données incohérentes) — voir `R10.R10`."""
    if bl.ecart_somme is None:
        return None
    if bl.somme_lignes is None or bl.total_ht is None:
        return None
    if abs(bl.ecart_somme) <= parametres.tolerance_total_ht:
        return None

    return Anomalie(
        regle="R11",
        gravite=Gravite.MOYENNE,
        detail={
            "somme": str(bl.somme_lignes),
            "total": str(bl.total_ht),
            "ecart": str(bl.ecart_somme),
            "tolerance": str(parametres.tolerance_total_ht),
        },
        document_id=bl.id,
    )
