"""R25 — grille ancienne (phase 3, prix des bons, spec §5.2).

Le prix de grille retrouvé pour cette ligne date de plus de
`age_grille_mois` mois (défaut 12, spec §3.4) avant `aujourdhui` (fourni
par `ingest`, spec §5.1) : gravité basse, justification chiffrée = produit,
date de grille, âge en mois et prix de grille -- un rappel qu'il serait bon
de rafraîchir la grille, pas une alerte sur le prix du bon lui-même.

Comme R19/R21/R23, exige `grille.comparable` (spec §5.2 : « une référence
non comparable n'alimente que R24 »). Sans `aujourdhui` (`None`, valeur par
défaut de `ParametresPrixBl` avant que `ingest` ne la fournisse), la règle
ne se déclenche jamais -- elle n'a alors aucune date de référence à
laquelle comparer (décision du contrôleur, plutôt que deviner ou lever)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl, ParametresPrixBl
from app.modules.rules.rules._prix_bl import TIRET, mois_ecoules


def R25(ligne: LignePrixBl, parametres: ParametresPrixBl) -> Anomalie | None:
    """`None` si la ligne n'a pas de produit de grille retrouvé, si la
    référence n'est pas comparable, si `aujourdhui` n'est pas fourni, ou si
    la grille n'a pas plus de `age_grille_mois` mois (comparaison
    stricte)."""
    grille = ligne.grille
    if grille is None or not grille.comparable:
        return None
    if parametres.aujourdhui is None:
        return None

    age_mois = mois_ecoules(grille.date, parametres.aujourdhui)
    if age_mois <= parametres.age_grille_mois:
        return None

    return Anomalie(
        regle="R25",
        gravite=Gravite.BASSE,
        detail={
            "produit": ligne.designation,
            "code": ligne.code or TIRET,
            "date_grille": grille.date.isoformat(),
            "age_mois": str(age_mois),
            "prix_grille": str(grille.prix),
        },
        document_id=ligne.document_id,
        ligne_id=ligne.ligne_id,
    )
