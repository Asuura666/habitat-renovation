"""Moteur qui enchaîne les règles dans l'ordre du CDC §5 (L4-D2).

Ordre complet du catalogue (CDC §5, « Ordre d'exécution ») :

1. R10 sur le document de la facture (cohérence arithmétique). Si elle
   produit une anomalie, le document reste « à vérifier » et **aucune**
   autre règle ne tourne pour cette facture : R10 est alors la seule
   anomalie renvoyée (Ruling R2).
2. Sinon, pour chaque bloc de la facture, dans l'ordre : R11 sur le BL
   rapproché à ce bloc, s'il y en a un.
3. Puis, pour ce même bloc, toujours — que R11 se soit déclenchée ou non,
   qu'il ait ou non un BL rapproché : R01 (BL facturé non reçu), R02 (BL
   facturé « pas de bon »), R12 (doublon de facturation) — L4-T2. Ruling R2
   ne saute jamais les règles de *bloc* : seules les règles de *ligne*
   (étape 4) le sont, quand R11 se déclenche pour ce bloc.
4. Puis, pour chaque ligne du bloc, dans l'ordre de `bloc.lignes` — mais
   seulement si R11 ne s'est *pas* déclenchée pour ce bloc (Ruling R2) et si
   le BL du bloc est reçu, `bloc.bl.statut == "recu"` (Ruling R3 : un bloc
   dont le BL est encore « à vérifier » est marqué reçu, mais ses quantités
   ne sont pas comparées) : R03 ou R04 (exclusives, écart de quantité), puis
   R05 (ligne facturée absente du BL), puis R07 ou R08 (exclusives, écart de
   prix) et R09 (remise absente) — L4-T4 — puis R17 (conditionnement
   inhabituel) — L4-T3. R13 reste à écrire (L4-T5) ; aucun code ne
   l'anticipe (YAGNI).
5. Ruling R7 (L4-T4) : R07/R08/R09 ne dépendent ni du BL rapproché ni de
   `conversion_impossible` — un prix hors historique est une anomalie même
   sans bon de livraison. Pour un bloc **sans** BL rapproché (`bloc.bl is
   None`), elles tournent donc quand même, sur toutes les lignes "article"
   du bloc — seule exception aux gardes de l'étape 4 (un bloc dont le BL
   est rapproché mais encore « à vérifier », ou dont le BL rapproché est
   incohérent (R11), reste soumis aux mêmes gardes que R03-R05/R17, faute
   d'indication contraire).

L4-T1 posait la structure avec R10/R11 seules ; L4-T2 y a ajouté
R01/R02/R12 et restructuré `_evaluer_bloc` en conséquence (revue de L4-T1 :
la sortie précoce sur R11 aurait sauté R01/R02/R12, contraire à Ruling R2).
L4-T3 y ajoute les règles de ligne R03/R04/R05/R17, après les règles de
bloc, sous la double garde Ruling R2 (pas de R11) et Ruling R3 (BL reçu).
L4-T4 y ajoute R07/R08/R09 (prix et remise), entre R05 et R17, avec
l'exception Ruling R7 décrite ci-dessus.

`evaluer_suivi` (R06, R14, R15, R16, contrôles différés au temps écoulé,
L4-D14) n'est pas de ce module (L4-T5/T11).
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    BlocControle,
    FactureControlee,
    HistoriqueArticle,
    LigneControlee,
    LigneRapprochee,
    Parametres,
)
from app.modules.rules.rules.R01 import R01
from app.modules.rules.rules.R02 import R02
from app.modules.rules.rules.R03 import R03
from app.modules.rules.rules.R04 import R04
from app.modules.rules.rules.R05 import R05
from app.modules.rules.rules.R07 import R07
from app.modules.rules.rules.R08 import R08
from app.modules.rules.rules.R09 import R09
from app.modules.rules.rules.R10 import R10
from app.modules.rules.rules.R11 import R11
from app.modules.rules.rules.R12 import R12
from app.modules.rules.rules.R17 import R17


def evaluer_facture(
    facture: FactureControlee, parametres: Parametres
) -> tuple[Anomalie, ...]:
    """Point d'entrée du moteur pour une facture (niveau document)."""
    anomalie_r10 = R10(facture.document, parametres)
    if anomalie_r10 is not None:
        return (anomalie_r10,)

    anomalies: list[Anomalie] = []
    for bloc in facture.blocs:
        anomalies.extend(
            _evaluer_bloc(
                bloc,
                parametres,
                facture.document.numero,
                facture.articles,
                facture.historiques,
            )
        )
    return tuple(anomalies)


def _evaluer_bloc(
    bloc: BlocControle,
    parametres: Parametres,
    facture_numero: str | None,
    articles: Mapping[UUID, ArticleControle],
    historiques: Mapping[UUID, HistoriqueArticle],
) -> tuple[Anomalie, ...]:
    """Règles de niveau bloc (L4-T2) : R11 (si un BL est rapproché), puis
    R01, R02 et R12, **toujours** évaluées (Ruling R2). Puis, sous la double
    garde Ruling R2 (R11 pas déclenchée) et Ruling R3 (BL reçu), les règles
    de ligne (L4-T3/L4-T4). Ruling R7 (L4-T4) : un bloc sans BL rapproché du
    tout échappe à cette double garde pour les seules règles de prix
    (R07/R08/R09), évaluées alors sur toutes les lignes "article" du
    bloc — `elif bloc.bl is None`, exclusif du premier cas."""
    anomalies: list[Anomalie] = []

    anomalie_r11 = None
    if bloc.bl is not None:
        anomalie_r11 = R11(bloc.bl, parametres)
        if anomalie_r11 is not None:
            anomalies.append(anomalie_r11)

    for anomalie in (R01(bloc), R02(bloc), R12(bloc, facture_numero)):
        if anomalie is not None:
            anomalies.append(anomalie)

    bl_recu = bloc.bl is not None and bloc.bl.statut == "recu"
    if anomalie_r11 is None and bl_recu:
        for rapprochee in bloc.lignes:
            anomalies.extend(
                _evaluer_ligne(bloc, rapprochee, articles, historiques, parametres)
            )
    elif bloc.bl is None:
        for rapprochee in bloc.lignes:
            anomalies.extend(
                _evaluer_prix(rapprochee.facture, articles, historiques, parametres)
            )

    return tuple(anomalies)


def _evaluer_ligne(
    bloc: BlocControle,
    rapprochee: LigneRapprochee,
    articles: Mapping[UUID, ArticleControle],
    historiques: Mapping[UUID, HistoriqueArticle],
    parametres: Parametres,
) -> tuple[Anomalie, ...]:
    """Règles de niveau ligne, dans l'ordre du CDC §5 : R03 ou R04
    (exclusives — au plus l'une des deux peut se déclencher, selon le signe
    de l'écart), puis R05, puis R07/R08/R09 (prix et remise, L4-T4), puis
    R17. R03/R04 (ligne appariée) et R05 (ligne non appariée) partagent une
    garde mutuellement exclusive sur `rapprochee.bl` : au plus une anomalie
    de quantité par ligne."""
    anomalies: list[Anomalie] = []

    anomalie_quantite = R03(bloc, rapprochee, articles) or R04(
        bloc, rapprochee, articles
    )
    if anomalie_quantite is not None:
        anomalies.append(anomalie_quantite)

    anomalie_r05 = R05(bloc, rapprochee)
    if anomalie_r05 is not None:
        anomalies.append(anomalie_r05)

    facture = rapprochee.facture
    anomalies.extend(_evaluer_prix(facture, articles, historiques, parametres))

    article = (
        articles.get(facture.article_id) if facture.article_id is not None else None
    )
    if article is not None:
        anomalie_r17 = R17(facture, article)
        if anomalie_r17 is not None:
            anomalies.append(anomalie_r17)

    return tuple(anomalies)


def _evaluer_prix(
    ligne: LigneControlee,
    articles: Mapping[UUID, ArticleControle],
    historiques: Mapping[UUID, HistoriqueArticle],
    parametres: Parametres,
) -> tuple[Anomalie, ...]:
    """R07 ou R08 (exclusives, écart de prix), puis R09 (remise absente) —
    L4-T4. Ne dépendent ni du BL rapproché ni de `conversion_impossible`
    (Ruling R7) : seuls l'article résolu et son historique chez le
    fournisseur comptent. `()` si la ligne n'a pas d'article résolu
    (`article_id` absent ou inconnu de `articles`) ou pas d'historique
    connu pour cet article (jamais mesuré — pas une erreur, simplement rien
    à comparer)."""
    if ligne.article_id is None:
        return ()
    article = articles.get(ligne.article_id)
    if article is None:
        return ()
    historique = historiques.get(ligne.article_id)
    if historique is None:
        return ()

    anomalies: list[Anomalie] = []
    anomalie_prix = R07(ligne, article, historique, parametres) or R08(
        ligne, article, historique, parametres
    )
    if anomalie_prix is not None:
        anomalies.append(anomalie_prix)

    anomalie_r09 = R09(ligne, article, historique, parametres)
    if anomalie_r09 is not None:
        anomalies.append(anomalie_r09)

    return tuple(anomalies)
