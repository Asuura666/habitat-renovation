"""R14 — chantier non résolu (CDC §5, L4-T5).

Un alias de chantier chez un fournisseur, créé lors d'une extraction et
toujours pas validé par l'admin plus de `delai_alias_non_resolu_h` heures
après sa création (défaut 48h, L4-D10) : gravité moyenne, justification
chiffrée = libellé brut lu et fournisseur (CDC §5 : « Libellé brut,
fournisseur »).

Règle de suivi (L4-D14), évaluée par `evaluer_suivi` — elle dépend du temps
écoulé depuis la création de l'alias, pas d'un document nouvellement
déposé. Comparaison strictement supérieure au délai, en heures entières :
exactement au délai -> rien (décision du contrôleur)."""

from __future__ import annotations

from datetime import datetime

from app.modules.rules.modeles import (
    AliasEnAttenteControle,
    Anomalie,
    Gravite,
    Parametres,
)


def R14(
    alias: AliasEnAttenteControle, aujourdhui: datetime, parametres: Parametres
) -> Anomalie | None:
    """`None` si `delai_alias_non_resolu_h` heures au plus se sont écoulées
    depuis la création de l'alias."""
    heures = (aujourdhui - alias.cree_le).total_seconds() / 3600
    if heures <= parametres.delai_alias_non_resolu_h:
        return None

    return Anomalie(
        regle="R14",
        gravite=Gravite.MOYENNE,
        detail={
            "libelle": alias.libelle,
            "fournisseur": alias.fournisseur,
            "heures": str(int(heures)),
        },
    )
