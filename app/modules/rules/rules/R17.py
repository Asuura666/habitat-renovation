"""R17 — conditionnement inhabituel (CDC §5, L4-T3).

Une ligne facturée de type "article" dont la quantité de conditionnements
(`qte_conditionnements`, = `ligne.qte_livree`, L3-D24) n'a pas de partie
décimale nulle — ex. 2,5 seaux — alors que le ratio de l'article est connu
et validé (`article.ratio`, `article.valide`) est un conditionnement
inhabituel : gravité moyenne, justification chiffrée = article, quantité et
conditionnement (CDC §5 : « Article, qté, conditionnement »).

Ne dépend pas de `conversion_impossible` (L4-D7) : R17 ne compare aucune
quantité entre deux documents, elle regarde la quantité de conditionnements
d'une seule ligne — décision du contrôleur."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, ArticleControle, Gravite, LigneControlee

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R17(ligne: LigneControlee, article: ArticleControle) -> Anomalie | None:
    """`None` si la ligne n'est pas de type "article", si sa quantité de
    conditionnements est absente ou entière, ou si le ratio de l'article
    est absent, nul, ou l'article non validé."""
    if ligne.type_ligne != "article":
        return None
    if ligne.qte_conditionnements is None:
        return None
    if ligne.qte_conditionnements % 1 == 0:
        return None
    if article.ratio is None or article.ratio == 0 or not article.valide:
        return None

    return Anomalie(
        regle="R17",
        gravite=Gravite.MOYENNE,
        detail={
            "article": article.libelle or ligne.designation or TIRET,
            "code": ligne.code or TIRET,
            "qte": str(ligne.qte_conditionnements),
            "conditionnement": article.unite_cdt or TIRET,
            "ratio": str(article.ratio),
        },
        ligne_id=ligne.id,
        article_id=article.id,
    )
