"""R21 — moins cher que la grille (phase 3, prix des bons, spec §5.2).

Symétrique de R19 : le prix net lu sur un bon est inférieur au prix en
vigueur de la grille du fournisseur de plus de `seuil_baisse_pct` (défaut
5 %, spec §3.4) : gravité **basse** (contrairement à R19, une baisse n'est
pas urgente -- décision d'Ilane, D4), même détail que R19. Exclusive de R19
(au plus l'une des deux se déclenche pour une même ligne, selon le signe de
l'écart)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LignePrixBl, ParametresPrixBl
from app.modules.rules.rules._prix_bl import TIRET, ecart_pct


def R21(ligne: LignePrixBl, parametres: ParametresPrixBl) -> Anomalie | None:
    """`None` si la ligne n'a pas de produit de grille retrouvé, si la
    référence n'est pas comparable, ou si le prix du bon n'est pas inférieur
    au prix de grille de plus de `seuil_baisse_pct` (comparaison stricte)."""
    grille = ligne.grille
    if grille is None or not grille.comparable:
        return None

    seuil = grille.prix * (1 - parametres.seuil_baisse_pct / 100)
    if ligne.prix_bon >= seuil:
        return None

    return Anomalie(
        regle="R21",
        gravite=Gravite.BASSE,
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
