"""R22 — produit absent de la grille (phase 3, prix des bons, spec §5.2).

Aucun produit de la grille du fournisseur n'a été retrouvé pour cette ligne
(`ligne.grille is None`, ni par référence ni par nom au-dessus du seuil de
ressemblance -- `normalize.prix.trouver_produit`) : gravité basse,
justification chiffrée = produit, prix du bon et, s'il y en a, les
désignations à égalité rendues par `trouver_produit` faute de départage
(`candidats`, spec §4.3).

Exclut toutes les autres règles de grille (R19, R21, R23, R25 : elles
exigent toutes `ligne.grille is not None`) -- seule R24 (unités
différentes) et R20 (dernière facture, indépendante de la grille) peuvent
encore se déclencher sur la même ligne.

`dernier_prix`/`date_dernier_prix` : dernier prix facturé du produit s'il
existe (« — » sinon) -- la recherche d'un prix sur internet (phase 4,
`ingest/ia_prix.py`) n'est lancée que pour un produit jamais facturé."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl
from app.modules.rules.rules._prix_bl import TIRET, candidats_ou_tiret


def R22(ligne: LignePrixBl) -> Anomalie | None:
    """`None` si un produit de la grille a été retrouvé pour cette ligne."""
    if ligne.grille is not None:
        return None

    dernier_prix = ligne.dernier_prix
    return Anomalie(
        regle="R22",
        gravite=Gravite.BASSE,
        detail={
            "produit": ligne.designation,
            "code": ligne.code or TIRET,
            "prix_bon": str(ligne.prix_bon),
            "unite_bon": ligne.unite_bon or TIRET,
            "date_bon": ligne.date_bon.isoformat(),
            "candidats": candidats_ou_tiret(ligne.candidats),
            "dernier_prix": str(dernier_prix.prix) if dernier_prix else TIRET,
            "date_dernier_prix": (
                dernier_prix.date.isoformat() if dernier_prix else TIRET
            ),
        },
        document_id=ligne.document_id,
        ligne_id=ligne.ligne_id,
    )
