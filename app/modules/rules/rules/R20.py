"""R20 — plus cher que la dernière fois (phase 3, prix des bons, spec
§5.2).

Le prix net lu sur un bon dépasse le prix de la dernière facture retrouvée
pour ce produit chez ce fournisseur (spec §6.3), de plus de
`seuil_hausse_pct` : gravité haute, justification chiffrée = produit, prix
du bon, dernier prix facturé (date, numéro de facture), écart en
pourcentage, méthode et ressemblance de la correspondance retrouvée.

Indépendante de R19/R21 (elle compare à la dernière facture, jamais à la
grille) : les deux peuvent se déclencher ensemble (spec §5.2)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl, ParametresPrixBl
from app.modules.rules.rules._prix_bl import TIRET, ecart_pct


def R20(ligne: LignePrixBl, parametres: ParametresPrixBl) -> Anomalie | None:
    """`None` si aucune facture antérieure n'a été retrouvée pour ce
    produit, si elle n'est pas comparable (unités non convertibles), ou si
    le prix du bon ne dépasse pas ce dernier prix de plus de
    `seuil_hausse_pct` (comparaison stricte)."""
    dernier_prix = ligne.dernier_prix
    if dernier_prix is None or not dernier_prix.comparable:
        return None

    seuil = dernier_prix.prix * (1 + parametres.seuil_hausse_pct / 100)
    if ligne.prix_bon <= seuil:
        return None

    return Anomalie(
        regle="R20",
        gravite=Gravite.HAUTE,
        detail={
            "produit": ligne.designation,
            "code": ligne.code or TIRET,
            "prix_bon": str(ligne.prix_bon),
            "unite_bon": ligne.unite_bon or TIRET,
            "date_bon": ligne.date_bon.isoformat(),
            "dernier_prix": str(dernier_prix.prix),
            "unite_dernier_prix": dernier_prix.unite or TIRET,
            "date_dernier_prix": dernier_prix.date.isoformat(),
            "numero_facture": dernier_prix.numero_facture or TIRET,
            "ecart_pct": str(ecart_pct(ligne.prix_bon, dernier_prix.prix)),
            "methode": dernier_prix.methode,
            "ressemblance": str(dernier_prix.ressemblance),
        },
        document_id=ligne.document_id,
        ligne_id=ligne.ligne_id,
    )
