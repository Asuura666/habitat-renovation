"""R16 — chantier silencieux (CDC §5, L4-T5).

Un chantier actif sans nouveau dépôt de BL depuis plus de
`delai_chantier_silencieux_j` jours (défaut 7, L4-D10), alors que des
factures ont, depuis ce dernier dépôt, référencé des BL de ce chantier
(`nb_bl_factures_depuis > 0`) : gravité basse, justification chiffrée =
chantier, date du dernier dépôt, nombre de BL facturés depuis et jours
écoulés (CDC §5 : « Chantier, dernier dépôt, BL facturés depuis »).

La condition `nb_bl_factures_depuis > 0` est explicite dans le CDC (« alors
que des factures y référencent des BL ») : un chantier simplement inactif,
sans aucune facture qui continue de s'y référer, n'est pas une anomalie
(décision du contrôleur). Règle de suivi (L4-D14), évaluée par
`evaluer_suivi`. Comparaison strictement supérieure au délai, en jours
entiers : exactement au délai -> rien.

`chantier_id` (ruling du contrôleur, fix round 1) porte la portée de
l'anomalie : sans lui, deux chantiers silencieux distincts partageraient la
même identité `("R16", None, None, None)` une fois persistés (L4-T11)."""

from __future__ import annotations

from datetime import datetime

from app.modules.rules.modeles import (
    Anomalie,
    ChantierSuiviControle,
    Gravite,
    Parametres,
)


def R16(
    chantier: ChantierSuiviControle, aujourdhui: datetime, parametres: Parametres
) -> Anomalie | None:
    """`None` si aucun dépôt n'est jamais survenu pour ce chantier, si
    `delai_chantier_silencieux_j` jours au plus se sont écoulés depuis le
    dernier, ou si aucune facture n'a référencé de BL de ce chantier depuis
    (CDC §5)."""
    if chantier.dernier_depot is None:
        return None

    jours = (aujourdhui.date() - chantier.dernier_depot.date()).days
    if jours <= parametres.delai_chantier_silencieux_j:
        return None
    if chantier.nb_bl_factures_depuis <= 0:
        return None

    return Anomalie(
        regle="R16",
        gravite=Gravite.BASSE,
        detail={
            "chantier": chantier.nom,
            "dernier_depot": chantier.dernier_depot.isoformat(),
            "bl_factures_depuis": str(chantier.nb_bl_factures_depuis),
            "jours": str(jours),
        },
        chantier_id=chantier.id,
    )
