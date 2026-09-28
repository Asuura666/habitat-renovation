"""R19 — plus cher que la grille (phase 3, prix des bons, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §5.2).

Le prix net lu sur un bon, déjà ramené à l'unité du bon, dépasse le prix en
vigueur de la grille du fournisseur (à la date du bon) de plus de
`seuil_hausse_pct` (défaut 0 %, spec §3.4 -- tout centime de plus
déclenche) : gravité haute, justification chiffrée = produit, prix du bon,
prix de grille (et sa date), écart en pourcentage, méthode et ressemblance
de la correspondance retrouvée.

Ne se déclenche jamais sur une référence non comparable (`grille.comparable`
faux, spec §5.2 : « une référence non comparable n'alimente que R24 ») ni
en l'absence de grille (matière de R22). Exclusive de R21 (une même ligne
ne peut être à la fois plus chère et moins chère que la même grille) mais
indépendante de R20 (comparaison à la dernière facture, pas à la grille) :
les deux peuvent se déclencher ensemble sur la même ligne."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl, ParametresPrixBl
from app.modules.rules.rules._prix_bl import TIRET, ecart_pct


def R19(ligne: LignePrixBl, parametres: ParametresPrixBl) -> Anomalie | None:
    """`None` si la ligne n'a pas de produit de grille retrouvé, si la
    référence n'est pas comparable (unités non convertibles), ou si le prix
    du bon ne dépasse pas le prix de grille de plus de `seuil_hausse_pct`
    (comparaison stricte, spec §5.2)."""
    grille = ligne.grille
    if grille is None or not grille.comparable:
        return None

    seuil = grille.prix * (1 + parametres.seuil_hausse_pct / 100)
    if ligne.prix_bon <= seuil:
        return None

    return Anomalie(
        regle="R19",
        gravite=Gravite.HAUTE,
        detail={
            "produit": ligne.designation,
            "code": ligne.code or TIRET,
            "prix_bon": str(ligne.prix_bon),
            "unite_bon": ligne.unite_bon or TIRET,
            "date_bon": ligne.date_bon.isoformat(),
            "prix_grille": str(grille.prix),
            "unite_grille": grille.unite or TIRET,
            "date_grille": grille.date.isoformat(),
            "ecart_pct": str(ecart_pct(ligne.prix_bon, grille.prix)),
            "methode": grille.methode,
            "ressemblance": str(grille.ressemblance),
            "designation_grille": grille.designation,
            "grille_posterieure_au_bon": (
                "oui" if grille.grille_posterieure_au_bon else "non"
            ),
        },
        document_id=ligne.document_id,
        ligne_id=ligne.ligne_id,
    )
