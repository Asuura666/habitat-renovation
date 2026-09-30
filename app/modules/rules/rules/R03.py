"""R03 — quantité facturée supérieure à la quantité BL (CDC §5, L4-T3).

Une ligne facturée appariée à une ligne de BL (L4-D6) dont la quantité
convertie en unité de facturation (`qte_fact`, L4-D7) est strictement
supérieure côté facture est un écart de sur-facturation : gravité haute,
justification chiffrée = article, quantités des deux documents, unité et
écart (CDC §5 : « Article, qté BL, qté facture, unité, écart »).

`ecart_qte_fact` et `detail_ecart_qte` sont réutilisées par `R04` (même
garde, écart de signe opposé) — décision du contrôleur, même convention que
`R01`/`R02` (import du helper partagé depuis l'un des deux modules).

Une ligne dont la conversion est impossible d'un côté ou de l'autre
(`conversion_impossible`, L4-D7) ne produit ni R03 ni R04 (CDC §10 : « 0
anomalie R03/R04 due à une unité ») ; une ligne `eco`/`commentaire`, côté
facture ou côté BL, n'en produit jamais non plus (décision du contrôleur,
garde rendue symétrique par le Ruling R20, revue finale du lot 4 : le garde
d'origine ne vérifiait que le type de la ligne de facture, laissant passer
une ligne de facture "article" appariée par erreur, même code, à une ligne
de BL "eco"/"commentaire").

Ruling R16 (fix round 2 de L4-T7) : une quantité rendue inchangée faute
d'unité connue des deux côtés (`LigneControlee.unite_implicite`, cas 2 de
`convertir_en_unite_fact`) n'est comparable qu'à une autre quantité rendue
de la même façon -- une paire dont une seule ligne est en unité implicite
ne produit ni R03 ni R04, conservateur par construction (on perd la
comparaison plutôt que d'en produire une fausse entre deux unités
potentiellement différentes)."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from app.modules.rules.agregation import detail_groupe, lignes_a_comparer
from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    BlocControle,
    Gravite,
    LigneControlee,
    LigneRapprochee,
)

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def ecart_qte_fact(facture: LigneControlee, bl: LigneControlee) -> Decimal | None:
    """Écart `qte_facture - qte_bl` en unité de facturation. `None` si l'une
    des deux lignes (facture ou BL) n'est pas de type "article" (Ruling
    R20, revue finale du lot 4 : garde symétrique -- une ligne de facture
    "article" appariée par erreur, même code, à une ligne de BL "eco" ou
    "commentaire" ne doit jamais produire d'écart chiffré entre deux
    grandeurs qui n'ont rien à voir), si la conversion est impossible d'un
    côté ou de l'autre, si l'une des deux quantités converties est absente
    (L4-D7), ou si `unite_implicite` diffère entre les deux lignes (Ruling
    R16 : une quantité rendue inchangée faute d'unité connue des deux côtés
    n'est comparable qu'à une autre quantité rendue de la même façon)."""
    if facture.type_ligne != "article" or bl.type_ligne != "article":
        return None
    if facture.conversion_impossible or bl.conversion_impossible:
        return None
    if facture.qte_fact is None or bl.qte_fact is None:
        return None
    if facture.unite_implicite != bl.unite_implicite:
        return None
    return facture.qte_fact - bl.qte_fact


def detail_ecart_qte(
    facture: LigneControlee,
    bl: LigneControlee,
    articles: Mapping[UUID, ArticleControle],
    ecart: Decimal,
) -> dict[str, str]:
    """`detail` commun à R03/R04 : `article` = libellé de l'article
    (`ArticleControle.libelle`) ou désignation de la ligne, `code` = code de
    la ligne, `unite` = `article.unite_fact` — décision du contrôleur."""
    article = (
        articles.get(facture.article_id) if facture.article_id is not None else None
    )
    libelle = article.libelle if article is not None and article.libelle else None
    unite = article.unite_fact if article is not None and article.unite_fact else None
    return {
        "article": libelle or facture.designation or TIRET,
        "code": facture.code or TIRET,
        "qte_bl": str(bl.qte_fact),
        "qte_facture": str(facture.qte_fact),
        "unite": unite or TIRET,
        "ecart": str(ecart),
    }


def R03(
    bloc: BlocControle,
    rapprochee: LigneRapprochee,
    articles: Mapping[UUID, ArticleControle],
) -> Anomalie | None:
    """`None` si la ligne n'est pas appariée à une ligne de BL (ou est
    secondaire d'un groupe de même code, B-06 : la comparaison se fait sur
    les quantités totales, portée par la ligne de tête), ou si
    `ecart_qte_fact` ne renvoie pas un écart strictement positif (égalité
    exacte -> ni R03 ni R04 ; écart négatif -> matière de R04)."""
    comparees = lignes_a_comparer(rapprochee)
    if comparees is None:
        return None
    facture, bl = comparees
    ecart = ecart_qte_fact(facture, bl)
    if ecart is None or ecart <= 0:
        return None

    return Anomalie(
        regle="R03",
        gravite=Gravite.HAUTE,
        detail={
            **detail_ecart_qte(facture, bl, articles, ecart),
            **detail_groupe(rapprochee),
        },
        bloc_id=bloc.id,
        ligne_id=facture.id,
        article_id=facture.article_id,
    )
