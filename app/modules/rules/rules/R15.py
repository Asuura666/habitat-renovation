"""R15 — BL sans confirmation (CDC §5, L4-T5).

Un BL déposé (`document.depose_le`) dont l'agent n'a jamais cliqué «
quantités vérifiées » (`document.confirme_le is None`), plus de
`delai_confirmation_bl_h` heures après son dépôt (défaut 24h, L4-D10) :
gravité basse, justification chiffrée = déposant et heure de dépôt (CDC §5
: « Déposant, heure de dépôt »).

Règle de suivi (L4-D14), évaluée par `evaluer_suivi` sur
`ContexteSuivi.bl_sans_confirmation` — déjà filtré par `ingest` aux BL non
confirmés (même principe que R13, décision du contrôleur) ; la garde
`confirme_le is not None` ci-dessous reste une vérification défensive du
champ lui-même, pas un recalcul du filtre. Comparaison strictement
supérieure au délai, en heures entières : exactement au délai -> rien."""

from __future__ import annotations

from datetime import datetime

from app.modules.rules.modeles import Anomalie, DocumentControle, Gravite, Parametres

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R15(
    document: DocumentControle, aujourdhui: datetime, parametres: Parametres
) -> Anomalie | None:
    """`None` si le BL est déjà confirmé, si sa date de dépôt est inconnue,
    ou si `delai_confirmation_bl_h` heures au plus se sont écoulées depuis
    le dépôt."""
    if document.confirme_le is not None:
        return None
    if document.depose_le is None:
        return None

    heures = (aujourdhui - document.depose_le).total_seconds() / 3600
    if heures <= parametres.delai_confirmation_bl_h:
        return None

    return Anomalie(
        regle="R15",
        gravite=Gravite.BASSE,
        detail={
            "deposant": document.deposant or TIRET,
            "depose_le": document.depose_le.isoformat(),
            "heures": str(int(heures)),
        },
        document_id=document.id,
    )
