"""R23 — produit reconnu seulement par son nom (phase 3, prix des bons,
spec §5.2).

Le produit de la grille retrouvé pour cette ligne l'a été par
ressemblance de désignation (`grille.methode == "nom"`, jamais par
référence -- `normalize.prix.trouver_produit`), et la référence reste
comparable (spec §5.2 : « une référence non comparable n'alimente que
R24 ») : gravité basse, justification chiffrée = produit lu, désignation et
ressemblance de la correspondance retrouvée, prix du bon et de la grille --
un simple rappel que la correspondance n'est pas certaine, à l'humain de la
confirmer (ou de contester)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl
from app.modules.rules.rules._prix_bl import TIRET


def R23(ligne: LignePrixBl) -> Anomalie | None:
    """`None` si aucun produit de grille n'a été retrouvé, si la référence
    n'est pas comparable, ou si la correspondance a été faite par
    référence (`methode != "nom"`)."""
    grille = ligne.grille
    if grille is None or not grille.comparable:
        return None
    if grille.methode != "nom":
        return None

    return Anomalie(
        regle="R23",
        gravite=Gravite.BASSE,
        detail={
            "produit": ligne.designation,
            "code": ligne.code or TIRET,
            "designation_grille": grille.designation,
            "ressemblance": str(grille.ressemblance),
            "prix_bon": str(ligne.prix_bon),
            "prix_grille": str(grille.prix),
        },
        document_id=ligne.document_id,
        ligne_id=ligne.ligne_id,
    )
