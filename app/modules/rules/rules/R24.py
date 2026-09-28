"""R24 — unités différentes (phase 3, prix des bons, spec §5.2).

La grille ou la dernière facture retrouvée pour cette ligne porte une unité
qui n'a pas pu être ramenée à celle du bon (`comparable` faux --
`normalize.unites.unites_comparables`, spec §4.4 : ni les mêmes codes, ni un
ratio de conditionnement validé) : gravité moyenne, aucune comparaison de
prix n'est possible, l'humain juge sur les deux unités affichées telles
quelles.

Seule règle à se déclencher sur une référence non comparable (spec §5.2 :
« une référence non comparable n'alimente que R24 ») -- R19/R21/R23/R25
exigent toutes `comparable` vrai sur la grille, R20 sur la dernière
facture. La grille et la dernière facture sont testées indépendamment :
une seule des deux non comparable suffit à déclencher R24.

Le détail ne porte l'unité d'une référence (grille ou dernière facture)
que lorsque c'est elle qui est non comparable (tiret sinon) : une
référence présente mais comparable n'est jamais la cause de l'anomalie et
ne doit pas être désignée comme telle (constat qualité, tour 1)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl
from app.modules.rules.rules._prix_bl import TIRET


def R24(ligne: LignePrixBl) -> Anomalie | None:
    """`None` si ni la grille ni la dernière facture retrouvée ne portent
    une unité non comparable (grille ou dernier prix absents, ou tous deux
    comparables)."""
    grille = ligne.grille
    dernier_prix = ligne.dernier_prix
    grille_non_comparable = grille is not None and not grille.comparable
    dernier_prix_non_comparable = (
        dernier_prix is not None and not dernier_prix.comparable
    )
    if not grille_non_comparable and not dernier_prix_non_comparable:
        return None

    return Anomalie(
        regle="R24",
        gravite=Gravite.MOYENNE,
        detail={
            "produit": ligne.designation,
            "code": ligne.code or TIRET,
            "unite_bon": ligne.unite_bon or TIRET,
            "unite_grille": (
                (grille.unite or TIRET)
                if grille is not None and grille_non_comparable
                else TIRET
            ),
            "unite_dernier_prix": (
                (dernier_prix.unite or TIRET)
                if dernier_prix is not None and dernier_prix_non_comparable
                else TIRET
            ),
            "prix_bon": str(ligne.prix_bon),
        },
        document_id=ligne.document_id,
        ligne_id=ligne.ligne_id,
    )
