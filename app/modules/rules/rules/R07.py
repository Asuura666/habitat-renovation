"""R07 — prix hors historique (CDC §5, L4-T4).

Le prix unitaire HT (`pu_ht`) d'une ligne facturée de type "article"
s'écarte de la médiane des 6 derniers mois pour cet article chez ce
fournisseur (`HistoriqueArticle.mediane_pu`, L4-D9, construite par
`ingest`) de plus de `seuil_prix_pct` (CDC §5 : 5 % par défaut) mais pas
plus de `seuil_prix_fort_pct` (15 % par défaut, matière de R08, borne haute
incluse ici) : gravité moyenne, justification chiffrée = article, PU
facturé, médiane, nombre d'occurrences et écart en pourcentage (CDC §5).

Aucune anomalie si l'historique est trop pauvre (`mediane_pu` absente,
occurrences insuffisantes, ou médiane non strictement positive) —
décisions du contrôleur : pas de bruit au démarrage faute d'historique
suffisant. `mediane_utilisable` et `ecart_prix_pct` sont partagées avec R08
(même calcul, seuil différent), à l'image de `mention_pas_de_bon` partagée
entre R01 et R02.

Ne dépend ni du BL rapproché ni de `conversion_impossible` (Ruling R7) :
seul le prix unitaire compte, jamais une quantité — le câblage dans
`engine.py` applique donc cette règle même à une ligne dont l'unité n'a pas
pu être convertie, ou dont le bloc n'a pas de BL rapproché."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    Gravite,
    HistoriqueArticle,
    LigneControlee,
    Parametres,
)

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)
_QUANTUM_ECART = Decimal("0.01")


def mediane_utilisable(
    historique: HistoriqueArticle, parametres: Parametres
) -> Decimal | None:
    """Médiane de l'historique si assez riche pour fonder une comparaison
    de prix (partagée avec R08) : `None` si absente, si `occurrences` est
    en dessous de `occurrences_prix_min`, ou si la médiane n'est pas
    strictement positive (division impossible — ne devrait jamais arriver
    en pratique, mais une règle ne lève jamais)."""
    if historique.mediane_pu is None:
        return None
    if historique.occurrences < parametres.occurrences_prix_min:
        return None
    if historique.mediane_pu <= 0:
        return None
    return historique.mediane_pu


def ecart_prix_pct(pu_ht: Decimal, mediane: Decimal) -> Decimal:
    """Écart relatif entre `pu_ht` et `mediane`, en pourcentage, en valeur
    absolue et sans arrondi (partagé avec R08) : « le prix est inférieur à
    la médiane de plus de 5 % » compte aussi (CDC §5, l'écart est absolu —
    décision du contrôleur)."""
    return abs(pu_ht - mediane) / mediane * 100


def R07(
    ligne: LigneControlee,
    article: ArticleControle,
    historique: HistoriqueArticle,
    parametres: Parametres,
) -> Anomalie | None:
    """`None` si la ligne n'est pas de type "article", si son `pu_ht` est
    absent, si l'historique est trop pauvre, si l'écart ne dépasse pas
    `seuil_prix_pct`, ou s'il dépasse `seuil_prix_fort_pct` (matière de
    R08, exclusivité avec R07 : borne haute incluse ici, `<=`)."""
    if ligne.type_ligne != "article":
        return None
    if ligne.pu_ht is None:
        return None
    mediane = mediane_utilisable(historique, parametres)
    if mediane is None:
        return None

    ecart = ecart_prix_pct(ligne.pu_ht, mediane)
    if ecart <= parametres.seuil_prix_pct:
        return None
    if ecart > parametres.seuil_prix_fort_pct:
        return None

    return Anomalie(
        regle="R07",
        gravite=Gravite.MOYENNE,
        detail={
            "article": article.libelle or ligne.designation or TIRET,
            "code": ligne.code or TIRET,
            "pu_facture": str(ligne.pu_ht),
            "mediane": str(mediane),
            "occurrences": str(historique.occurrences),
            "ecart_pct": str(ecart.quantize(_QUANTUM_ECART, rounding=ROUND_HALF_UP)),
        },
        ligne_id=ligne.id,
        article_id=article.id,
    )
