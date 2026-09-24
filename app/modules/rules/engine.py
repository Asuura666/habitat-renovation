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
   ne sont pas comparées) : les règles de **quantité** — R03 ou R04
   (exclusives, écart de quantité), puis R05 (ligne facturée absente du
   BL), puis R17 (conditionnement inhabituel) — L4-T3.
5. Puis, pour chaque ligne du bloc, **toujours** — quel que soit l'état du
   BL du bloc (absent, rapproché mais « à vérifier », ou rapproché mais
   incohérent, R11 déclenchée) : les règles de **prix** — R07 ou R08
   (exclusives, écart de prix) et R09 (remise absente) — L4-T4, Ruling R11
   du contrôleur (fix round 1) : un prix hors historique n'a rien à voir
   avec le bon de livraison, ces trois règles ne sont donc jamais gardées
   par Ruling R2 ni Ruling R3 — seules R03/R04/R05/R17 (étape 4) le sont.
   L'étape 4 (gardée) s'exécute intégralement avant l'étape 5
   (inconditionnelle) : pour une ligne qui déclenche à la fois une anomalie
   de quantité et une anomalie de prix, l'anomalie de quantité précède
   toujours l'anomalie de prix dans le tuple renvoyé.
6. Enfin, une fois par facture, après tous les blocs (L4-T5) : R13 (avoir
   sans origine) pour chaque couple `(ligne, chantier)` de
   `facture.lignes_negatives_sans_origine`, dans l'ordre de ce tuple — cette
   règle ne recalcule rien, `ingest` lui fournit déjà les lignes négatives
   sans ligne positive antérieure correspondante (décision du contrôleur).

L4-T1 posait la structure avec R10/R11 seules ; L4-T2 y a ajouté
R01/R02/R12 et restructuré `_evaluer_bloc` en conséquence (revue de L4-T1 :
la sortie précoce sur R11 aurait sauté R01/R02/R12, contraire à Ruling R2).
L4-T3 y ajoute les règles de ligne R03/R04/R05/R17, après les règles de
bloc, sous la double garde Ruling R2 (pas de R11) et Ruling R3 (BL reçu).
L4-T4 y ajoute R07/R08/R09 (prix et remise), d'abord câblées comme les
règles de quantité (mêmes gardes, sauf exception pour un bloc sans BL du
tout) puis, sur ruling du contrôleur (fix round 1, revue de L4-T4) : les
règles de prix ne comparent jamais rien au BL, elles sont donc sorties de
`_evaluer_ligne` et évaluées sans aucune garde, dans une passe séparée et
inconditionnelle sur `bloc.lignes`, après la passe (gardée) des règles de
quantité — `_evaluer_prix` n'est plus appelée que depuis `_evaluer_bloc`.
L4-T5 y ajoute R13 (étape 6 ci-dessus), additivement.

`evaluer_suivi` (R06, R14, R15, R16, contrôles différés au temps écoulé,
L4-D14) est un second point d'entrée, séparé de `evaluer_facture` : ces
règles ne dépendent pas d'une facture en cours de contrôle mais du temps
écoulé depuis un dépôt, une création d'alias ou un dernier dépôt de
chantier (décision du contrôleur). Elle enchaîne R06, R14, R15, R16 dans
l'ordre des champs de `ContexteSuivi`, déclenchée par la commande
`controles-differes` (L4-T11), pas à chaque dépôt.

`REGLES_FACTURE` et `REGLES_SUIVI` (adjonction du contrôleur, L4-T5) sont
la source de vérité des codes de règle que produit chacun des deux points
d'entrée : `ingest.anomalies.synchroniser_anomalies` les importe pour son
paramètre obligatoire `portee_regles` plutôt que de retyper la liste des
règles à chaque appel. `test_engine.py` vérifie qu'ils sont disjoints et
que leur union couvre exactement R01 à R17 — une règle ajoutée plus tard
sans mise à jour de l'un des deux ensembles fait donc échouer la suite.

`regles_actives` d'`evaluer_facture` (décision d'Ilane du 24/09/2026,
`docs/dette.md` : contrôles de prix désactivés tant que l'historique ne
couvre qu'un seul mois) : paramètre optionnel, `None` par défaut (=
comportement inchangé, toutes les règles de `REGLES_FACTURE` s'évaluent).
`rules` reste pur (n'importe rien de `app.core`) : c'est `ingest`, seul
orchestrateur, qui lit la configuration
(`ingest.commun.regles_desactivees`) et passe explicitement l'ensemble des
règles actives. Seules R07/R08/R09 (les règles de *prix*, `_evaluer_prix`)
observent ce paramètre pour l'instant : le retirer de `regles_actives` fait
sauter l'appel à la règle correspondante (elle n'est plus *évaluée*, pas
seulement filtrée en sortie) ; toute autre règle continue de s'évaluer
quel que soit son contenu."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    BlocControle,
    ContexteSuivi,
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
from app.modules.rules.rules.R06 import R06
from app.modules.rules.rules.R07 import R07
from app.modules.rules.rules.R08 import R08
from app.modules.rules.rules.R09 import R09
from app.modules.rules.rules.R10 import R10
from app.modules.rules.rules.R11 import R11
from app.modules.rules.rules.R12 import R12
from app.modules.rules.rules.R13 import R13
from app.modules.rules.rules.R14 import R14
from app.modules.rules.rules.R15 import R15
from app.modules.rules.rules.R16 import R16
from app.modules.rules.rules.R17 import R17

# Adjonction du contrôleur (L4-T5) : scopes des deux points d'entrée du
# moteur, source de vérité pour `ingest.anomalies.synchroniser_anomalies`
# (paramètre obligatoire `portee_regles`) — voir le test de couverture dans
# `test_engine.py`.
REGLES_FACTURE: frozenset[str] = frozenset(
    {
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
        "R07",
        "R08",
        "R09",
        "R10",
        "R11",
        "R12",
        "R13",
        "R17",
    }
)
REGLES_SUIVI: frozenset[str] = frozenset({"R06", "R14", "R15", "R16"})


def evaluer_facture(
    facture: FactureControlee,
    parametres: Parametres,
    regles_actives: frozenset[str] | None = None,
) -> tuple[Anomalie, ...]:
    """Point d'entrée du moteur pour une facture (niveau document).

    `regles_actives` : voir le docstring de module. `None` (défaut) évalue
    toutes les règles de `REGLES_FACTURE`, comme avant ce paramètre."""
    anomalie_r10 = R10(facture.document, parametres)
    if anomalie_r10 is not None:
        return (anomalie_r10,)

    actives = regles_actives if regles_actives is not None else REGLES_FACTURE

    anomalies: list[Anomalie] = []
    for bloc in facture.blocs:
        anomalies.extend(
            _evaluer_bloc(
                bloc,
                parametres,
                facture.document.numero,
                facture.articles,
                facture.historiques,
                actives,
            )
        )
    for ligne, chantier in facture.lignes_negatives_sans_origine:
        anomalie_r13 = R13(ligne, chantier)
        if anomalie_r13 is not None:
            anomalies.append(anomalie_r13)
    return tuple(anomalies)


def evaluer_suivi(
    contexte: ContexteSuivi, parametres: Parametres
) -> tuple[Anomalie, ...]:
    """Point d'entrée du moteur pour les règles de suivi (R06, R14, R15,
    R16 — contrôles différés au temps écoulé, L4-D14), distinct de
    `evaluer_facture` (décision du contrôleur). Enchaîne les règles dans
    l'ordre des champs de `ContexteSuivi` : lignes de BL non facturées
    (R06), alias en attente (R14), BL sans confirmation (R15), chantiers
    suivis (R16)."""
    anomalies: list[Anomalie] = []

    for bloc, ligne_bl in contexte.lignes_bl_non_facturees:
        anomalie_r06 = R06(bloc, ligne_bl, contexte.aujourdhui, parametres)
        if anomalie_r06 is not None:
            anomalies.append(anomalie_r06)

    for alias in contexte.alias_en_attente:
        anomalie_r14 = R14(alias, contexte.aujourdhui, parametres)
        if anomalie_r14 is not None:
            anomalies.append(anomalie_r14)

    for document in contexte.bl_sans_confirmation:
        anomalie_r15 = R15(document, contexte.aujourdhui, parametres)
        if anomalie_r15 is not None:
            anomalies.append(anomalie_r15)

    for chantier in contexte.chantiers:
        anomalie_r16 = R16(chantier, contexte.aujourdhui, parametres)
        if anomalie_r16 is not None:
            anomalies.append(anomalie_r16)

    return tuple(anomalies)


def _evaluer_bloc(
    bloc: BlocControle,
    parametres: Parametres,
    facture_numero: str | None,
    articles: Mapping[UUID, ArticleControle],
    historiques: Mapping[UUID, HistoriqueArticle],
    regles_actives: frozenset[str],
) -> tuple[Anomalie, ...]:
    """Règles de niveau bloc (L4-T2), dans l'ordre : R11 (si un BL est
    rapproché), puis R01, R02 et R12, **toujours** évaluées (Ruling R2).
    Puis les règles de *quantité* (R03/R04/R05/R17, L4-T3) sur chaque ligne,
    sous la double garde Ruling R2 (R11 pas déclenchée) et Ruling R3 (BL
    reçu). Puis, **sans aucune garde** — Ruling R11 du contrôleur (fix round
    1, L4-T4) : un prix hors historique n'a rien à voir avec le BL — les
    règles de *prix* (R07/R08/R09) sur chaque ligne du bloc, quel que soit
    l'état de son BL (absent, à vérifier, ou incohérent)."""
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
            anomalies.extend(_evaluer_quantite(bloc, rapprochee, articles))

    for rapprochee in bloc.lignes:
        anomalies.extend(
            _evaluer_prix(
                rapprochee.facture, articles, historiques, parametres, regles_actives
            )
        )

    return tuple(anomalies)


def _evaluer_quantite(
    bloc: BlocControle,
    rapprochee: LigneRapprochee,
    articles: Mapping[UUID, ArticleControle],
) -> tuple[Anomalie, ...]:
    """Règles de *quantité* de niveau ligne (L4-T3), dans l'ordre du CDC
    §5 : R03 ou R04 (exclusives — au plus l'une des deux peut se
    déclencher, selon le signe de l'écart), puis R05, puis R17. R03/R04
    (ligne appariée) et R05 (ligne non appariée) partagent une garde
    mutuellement exclusive sur `rapprochee.bl` : au plus une anomalie de
    quantité par ligne. N'inclut plus les règles de prix (R07/R08/R09,
    sorties vers `_evaluer_bloc` — Ruling R11 du contrôleur, fix round 1)."""
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
    regles_actives: frozenset[str],
) -> tuple[Anomalie, ...]:
    """R07 ou R08 (exclusives, écart de prix), puis R09 (remise absente) —
    L4-T4. Ne dépendent ni du BL rapproché ni de `conversion_impossible`
    (Ruling R7) : seuls l'article résolu et son historique chez le
    fournisseur comptent. `()` si la ligne n'a pas d'article résolu
    (`article_id` absent ou inconnu de `articles`) ou pas d'historique
    connu pour cet article (jamais mesuré — pas une erreur, simplement rien
    à comparer).

    Chaque règle n'est **appelée** que si son code figure dans
    `regles_actives` (décision d'Ilane du 24/09/2026, voir le docstring de
    module) : une règle retirée de `regles_actives` n'est pas évaluée,
    jamais seulement filtrée après coup."""
    if ligne.article_id is None:
        return ()
    article = articles.get(ligne.article_id)
    if article is None:
        return ()
    historique = historiques.get(ligne.article_id)
    if historique is None:
        return ()

    anomalies: list[Anomalie] = []
    anomalie_prix = None
    if "R07" in regles_actives:
        anomalie_prix = R07(ligne, article, historique, parametres)
    if anomalie_prix is None and "R08" in regles_actives:
        anomalie_prix = R08(ligne, article, historique, parametres)
    if anomalie_prix is not None:
        anomalies.append(anomalie_prix)

    if "R09" in regles_actives:
        anomalie_r09 = R09(ligne, article, historique, parametres)
        if anomalie_r09 is not None:
            anomalies.append(anomalie_r09)

    return tuple(anomalies)
