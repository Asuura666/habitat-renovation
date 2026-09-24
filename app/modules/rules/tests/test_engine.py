"""Tests de `evaluer_facture` (L4-T1 à L4-T5, fix round 1 sur L4-T4) :
ordre du CDC §5, Ruling R2, Ruling R3, Ruling R11 du contrôleur.

R10 (document), R11 (BL rapproché par bloc), R01/R02/R12 (niveau bloc,
toujours évaluées, depuis L4-T2), R03/R04/R05/R17 (règles de *quantité*, de
niveau ligne, sous la double garde Ruling R2 — pas de R11 sur le bloc — et
Ruling R3 — BL du bloc reçu, depuis L4-T3) sont enchaînées, puis R07/R08/R09
(règles de *prix* et remise) tournent en une passe séparée et
**inconditionnelle** sur `bloc.lignes` : Ruling R11 du contrôleur (fix
round 1, revue de L4-T4) — un prix hors historique ne dépend jamais du BL,
ces trois règles ne sont donc jamais gardées, contrairement à ce que
L4-T4 avait initialement câblé (Ruling R7, qui ne les exemptait que pour un
bloc sans BL du tout). Depuis L4-T5, `evaluer_facture` ajoute aussi R13
(une fois par facture, après les blocs, dans l'ordre de
`facture.lignes_negatives_sans_origine`) ; `evaluer_suivi` (R06, R14, R15,
R16, contrôles différés au temps écoulé) est testée séparément, ainsi que
les scopes `REGLES_FACTURE`/`REGLES_SUIVI` (adjonction du contrôleur,
L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.modules.rules.engine import (
    REGLES_FACTURE,
    REGLES_SUIVI,
    evaluer_facture,
    evaluer_suivi,
)
from app.modules.rules.modeles import (
    AliasEnAttenteControle,
    ArticleControle,
    BlocControle,
    ChantierSuiviControle,
    ContexteSuivi,
    DocumentControle,
    FactureControlee,
    HistoriqueArticle,
    LigneControlee,
    LigneRapprochee,
    Parametres,
)


def _document(*, coherent: bool = True, **overrides: Any) -> DocumentControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": "DOC0001",
        "date_doc": date(2026, 8, 1),
        "statut": "extraite",
        "somme_lignes": Decimal("100.00"),
        "total_ht": Decimal("100.00"),
        "ecart_somme": None,
        "depose_le": None,
        "deposant": None,
        "confirme_le": None,
    }
    if not coherent:
        base.update(
            somme_lignes=Decimal("110.00"),
            total_ht=Decimal("100.00"),
            ecart_somme=Decimal("10.00"),
        )
    base.update(overrides)
    return DocumentControle(**base)


def _bloc(**overrides: Any) -> BlocControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_bl": "BL0001",
        "date_bl": date(2026, 8, 1),
        "chantier_brut": "CHANTIER INVENTE",
        "chantier": "chantier invente",
        "commentaire": None,
        "montant_ht": Decimal("100.00"),
        "bl": None,
        "lignes": (),
        "lignes_bl_non_facturees": (),
        "autre_facture_numero": None,
        "autre_facture_id": None,
    }
    base.update(overrides)
    return BlocControle(**base)


def _ligne(**overrides: Any) -> LigneControlee:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ordre": 1,
        "code": "ART001",
        "designation": "ARTICLE INVENTE",
        "article_id": uuid.uuid4(),
        "qte_conditionnements": Decimal("2"),
        "qte_facturee": Decimal("20"),
        "qte_fact": Decimal("20"),
        "unite": "kg",
        "pu_ht": Decimal("1.50"),
        "remise_pct": None,
        "montant_ht": Decimal("30.00"),
        "type_ligne": "article",
        "conversion_impossible": False,
    }
    base.update(overrides)
    return LigneControlee(**base)


def _article(**overrides: Any) -> ArticleControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "code": "ART001",
        "libelle": "Article inventé",
        "unite_cdt": "seau",
        "unite_fact": "kg",
        "ratio": Decimal("10"),
        "valide": True,
    }
    base.update(overrides)
    return ArticleControle(**base)


def _historique(**overrides: Any) -> HistoriqueArticle:
    base: dict[str, Any] = {
        "article_id": uuid.uuid4(),
        "mediane_pu": None,
        "occurrences": 0,
        "remise_habituelle": None,
        "occurrences_remise": 0,
    }
    base.update(overrides)
    return HistoriqueArticle(**base)


def _facture(
    document: DocumentControle,
    blocs: tuple[BlocControle, ...] = (),
    articles: dict[uuid.UUID, ArticleControle] | None = None,
    historiques: dict[uuid.UUID, HistoriqueArticle] | None = None,
) -> FactureControlee:
    return FactureControlee(
        document=document,
        fournisseur="FOURNISSEUR INVENTE",
        blocs=blocs,
        articles=articles or {},
        historiques=historiques or {},
        lignes_negatives_sans_origine=(),
    )


def test_evaluer_facture_sans_aucune_incoherence_ne_produit_rien() -> None:
    document = _document(coherent=True)
    bloc = _bloc(bl=_document(coherent=True))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert anomalies == ()


def test_evaluer_facture_bloc_sans_bl_produit_r01_et_pas_r11() -> None:
    """Un bloc sans BL déposé (`bl=None`) ne fait pas planter R11 (elle
    n'est simplement pas évaluée, ce n'est pas son rôle) et produit R01
    (BL facturé non reçu, L4-T2) puisqu'aucune mention « pas de bon »
    n'est présente sur son commentaire."""
    document = _document(coherent=True)
    bloc = _bloc(bl=None)

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert len(anomalies) == 1
    assert anomalies[0].regle == "R01"
    assert anomalies[0].bloc_id == bloc.id


def test_evaluer_facture_bloc_recu_ne_produit_ni_r01_ni_r02() -> None:
    """Un bloc dont le BL a été rapproché (`bl` non `None`) ne produit ni
    R01 ni R02, même si son commentaire porte une mention « pas de bon » —
    le bon a bien été remis (décision du contrôleur)."""
    document = _document(coherent=True)
    bl = _document(coherent=True)
    bloc = _bloc(bl=bl, commentaire="RETRAIT FRED PAS DE BON")

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert anomalies == ()


def test_evaluer_facture_bloc_sans_bl_avec_mention_produit_r02_pas_r01() -> None:
    document = _document(coherent=True)
    bloc = _bloc(bl=None, commentaire="RETRAIT FRED PAS DE BON")

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert len(anomalies) == 1
    assert anomalies[0].regle == "R02"


def test_evaluer_facture_r12_evaluee_meme_si_r11_se_declenche() -> None:
    """Ruling R2 (restructuration L4-T2) : quand R11 se déclenche pour un
    bloc, ses règles de *ligne* (pas encore écrites) seraient sautées,
    mais pas ses règles de *bloc* — ici R12, indépendante de R11."""
    document = _document(coherent=True)
    bl_incoherent = _document(coherent=False)
    bloc = _bloc(
        bl=bl_incoherent,
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R11", "R12"]
    assert anomalies[0].document_id == bl_incoherent.id
    assert anomalies[1].bloc_id == bloc.id


def test_evaluer_facture_r01_et_r12_ordre_dans_le_meme_bloc() -> None:
    document = _document(coherent=True)
    bloc = _bloc(
        bl=None,
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R01", "R12"]


def test_evaluer_facture_r02_et_r12_ordre_dans_le_meme_bloc() -> None:
    document = _document(coherent=True)
    bloc = _bloc(
        bl=None,
        commentaire="RETRAIT FRED PAS DE BON",
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R02", "R12"]


def test_evaluer_facture_r10_est_la_seule_anomalie_renvoyee() -> None:
    """Ruling R2 : si R10 produit une anomalie, elle est la **seule**
    renvoyée — même si un bloc porte un BL par ailleurs incohérent."""
    document = _document(coherent=False)
    bloc = _bloc(bl=_document(coherent=False))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert len(anomalies) == 1
    assert anomalies[0].regle == "R10"
    assert anomalies[0].document_id == document.id


def test_evaluer_facture_r11_par_bloc_dans_lordre_des_blocs() -> None:
    """Facture cohérente, trois blocs dont le premier et le troisième
    portent un BL incohérent : les anomalies R11 sont renvoyées dans
    l'ordre des blocs, le second bloc (cohérent) n'en produit aucune."""
    document = _document(coherent=True)
    bl_incoherent_1 = _document(coherent=False)
    bl_coherent = _document(coherent=True)
    bl_incoherent_3 = _document(coherent=False)
    blocs = (
        _bloc(bl=bl_incoherent_1),
        _bloc(bl=bl_coherent),
        _bloc(bl=bl_incoherent_3),
    )

    anomalies = evaluer_facture(_facture(document, blocs), Parametres())

    assert len(anomalies) == 2
    assert [a.regle for a in anomalies] == ["R11", "R11"]
    assert anomalies[0].document_id == bl_incoherent_1.id
    assert anomalies[1].document_id == bl_incoherent_3.id
    assert all(a.detail for a in anomalies)  # detail jamais vide


# --------------------------------------------------------------------------
# Règles de ligne (L4-T3) : Ruling R2 (pas de R11), Ruling R3 (BL reçu)
# --------------------------------------------------------------------------


def test_evaluer_facture_ligne_evaluee_quand_bl_recu() -> None:
    """Bloc dont le BL est reçu et cohérent : la ligne en écart positif
    produit R03 (Ruling R3 : les quantités sont comparées)."""
    document = _document(coherent=True)
    ligne_bl = _ligne(qte_fact=Decimal("18"))
    ligne_facture = _ligne(article_id=ligne_bl.article_id, qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R03"]
    assert anomalies[0].ligne_id == ligne_facture.id


def test_evaluer_facture_ligne_ignoree_quand_bl_a_verifier() -> None:
    """Ruling R3 : un BL encore « à vérifier » est marqué reçu sur le bloc
    (`bl` non `None`), mais ses lignes ne sont pas comparées : aucune
    anomalie de ligne, même en présence d'un écart de quantité."""
    document = _document(coherent=True)
    ligne_bl = _ligne(qte_fact=Decimal("18"))
    ligne_facture = _ligne(article_id=ligne_bl.article_id, qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="a_verifier"), lignes=(rapprochee,))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert anomalies == ()


def test_evaluer_facture_ligne_ignoree_quand_r11_declenchee() -> None:
    """Ruling R2 : quand R11 se déclenche pour un bloc (BL incohérent), ses
    règles de ligne sont sautées même si le BL est par ailleurs `statut`
    "recu" et porte un écart de quantité."""
    document = _document(coherent=True)
    ligne_bl = _ligne(qte_fact=Decimal("18"))
    ligne_facture = _ligne(article_id=ligne_bl.article_id, qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bl_incoherent = _document(coherent=False, statut="recu")
    bloc = _bloc(bl=bl_incoherent, lignes=(rapprochee,))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R11"]


def test_evaluer_facture_lignes_ordre_bloc_puis_ligne() -> None:
    """Les anomalies de ligne (L4-T3) sont renvoyées après les anomalies de
    bloc (R01/R02/R12, L4-T2) — ici un doublon (R12) puis un écart positif
    de quantité (R03) dans le même bloc."""
    document = _document(coherent=True)
    ligne_bl = _ligne(qte_fact=Decimal("18"))
    ligne_facture = _ligne(article_id=ligne_bl.article_id, qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(
        bl=_document(coherent=True, statut="recu"),
        lignes=(rapprochee,),
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R12", "R03"]


def test_evaluer_facture_ligne_r17_evaluee_via_larticle_de_la_facture() -> None:
    """R17 est évaluée pour chaque ligne du bloc à partir de l'article
    trouvé dans `facture.articles` (par `article_id` de la ligne facturée),
    même quand la ligne est par ailleurs sans écart de quantité (R03/R04)."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=Decimal("10"), valide=True)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id,
        qte_fact=Decimal("20"),
        qte_conditionnements=Decimal("2.5"),
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))

    anomalies = evaluer_facture(
        _facture(document, (bloc,), articles={article_id: article}), Parametres()
    )

    assert [a.regle for a in anomalies] == ["R17"]
    assert anomalies[0].article_id == article_id


# --------------------------------------------------------------------------
# Règles de prix et remise (L4-T4) : Ruling R11 du contrôleur (fix round 1)
# — R07/R08/R09 ne sont jamais gardées par Ruling R2/R3, contrairement aux
# règles de quantité R03/R04/R05/R17. `_evaluer_bloc` les évalue donc en
# deux passes successives sur `bloc.lignes` : d'abord la passe de quantité
# (gardée), puis la passe de prix (inconditionnelle) — d'où l'ordre "R17
# avant R07" ci-dessous quand les deux se déclenchent sur la même ligne.
# --------------------------------------------------------------------------


def test_evaluer_facture_r17_puis_r07_deux_passes_distinctes() -> None:
    """Sur une même ligne appariée sans écart de quantité, la passe de
    quantité (gardée par Ruling R3, ici satisfaite) produit R17 en premier ;
    la passe de prix (inconditionnelle, toujours après) produit R07
    ensuite — les deux passes ne s'entrelacent jamais par ligne."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=Decimal("10"), valide=True)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id,
        qte_fact=Decimal("20"),
        qte_conditionnements=Decimal("2.5"),
        pu_ht=Decimal("110.00"),
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id, mediane_pu=Decimal("100.00"), occurrences=3
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R17", "R07"]
    assert anomalies[0].ligne_id == ligne_facture.id
    assert anomalies[1].ligne_id == ligne_facture.id
    assert anomalies[1].article_id == article_id


def test_evaluer_facture_r08_exclusif_de_r07() -> None:
    """Un écart de prix fort (> 15 %) produit R08, pas R07 (exclusivité,
    câblage identique au calcul R03/R04)."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=None)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id, qte_fact=Decimal("20"), pu_ht=Decimal("130.00")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id, mediane_pu=Decimal("100.00"), occurrences=3
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R08"]


def test_evaluer_facture_r17_puis_r07_et_r09_meme_ligne_dans_lordre() -> None:
    """Une ligne qui cumule R17 (quantité) et R07 + R09 (prix) : la passe
    de quantité produit R17, puis la passe de prix produit R07 (écart de
    prix) suivi de R09 (remise absente) — ordre interne à `_evaluer_prix`
    inchangé, seule la position de R17 par rapport aux deux autres a
    changé (fix round 1, Ruling R11 du contrôleur)."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=Decimal("10"), valide=True)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id,
        qte_fact=Decimal("20"),
        qte_conditionnements=Decimal("2.5"),
        pu_ht=Decimal("110.00"),
        remise_pct=None,
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id,
        mediane_pu=Decimal("100.00"),
        occurrences=3,
        remise_habituelle=Decimal("10.00"),
        occurrences_remise=3,
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R17", "R07", "R09"]


def test_evaluer_facture_prix_evaluee_meme_sur_bloc_sans_bl_rapproche() -> None:
    """Un prix hors historique reste une anomalie même sans BL rapproché du
    tout — la passe de prix tourne sur toutes les lignes "article" du bloc,
    indépendamment de R01/R02 (qui signalent l'absence de BL, pas le prix).
    Ce n'est plus un cas particulier (l'ancienne exception Ruling R7 du
    L4-T4) mais une instance de la règle générale : la passe de prix est
    désormais inconditionnelle, quel que soit l'état du BL du bloc (fix
    round 1, Ruling R11 du contrôleur) — voir aussi les deux tests suivants
    pour les cas « à vérifier » et R11 déclenchée."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id)
    ligne_facture = _ligne(article_id=article_id, pu_ht=Decimal("110.00"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)
    bloc = _bloc(bl=None, lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id, mediane_pu=Decimal("100.00"), occurrences=3
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R01", "R07"]
    assert anomalies[1].ligne_id == ligne_facture.id


def test_evaluer_facture_prix_evaluee_quand_bl_a_verifier() -> None:
    """Fix round 1, Ruling R11 du contrôleur : un BL rapproché mais encore
    « à vérifier » n'empêche plus la passe de prix (elle n'est plus une
    règle de quantité gardée par Ruling R3) — R07 se déclenche même si le
    BL n'est pas confirmé reçu. Renommé depuis
    `test_evaluer_facture_prix_ignoree_quand_bl_a_verifier` (L4-T4), qui
    asserte l'ancien comportement."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id, qte_fact=Decimal("20"), pu_ht=Decimal("110.00")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="a_verifier"), lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id, mediane_pu=Decimal("100.00"), occurrences=3
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R07"]


def test_evaluer_facture_prix_evaluee_et_quantite_ignoree_quand_bl_a_verifier() -> None:
    """Preuve conjointe, sur un bloc dont le BL est « à vérifier » et qui
    porte un véritable écart de quantité (18 sur le BL contre 20 facturés,
    qui déclencherait R03 si la garde Ruling R3 ne s'appliquait pas) : la
    passe de quantité reste bloquée (aucun R03) alors que la passe de prix
    tourne quand même (R07, R08 et R09 se déclenchent tous les trois sur
    cette même ligne, sans le moindre R03/R04/R05/R17)."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=None)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("18"))
    ligne_facture = _ligne(
        article_id=article_id,
        qte_fact=Decimal("20"),
        pu_ht=Decimal("130.00"),
        remise_pct=None,
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="a_verifier"), lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id,
        mediane_pu=Decimal("100.00"),
        occurrences=3,
        remise_habituelle=Decimal("10.00"),
        occurrences_remise=3,
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R08", "R09"]
    assert all(a.regle not in {"R03", "R04", "R05", "R17"} for a in anomalies)


def test_evaluer_facture_prix_evaluee_quand_r11_declenchee() -> None:
    """Fix round 1, Ruling R11 du contrôleur : un BL rapproché mais
    incohérent (R11 se déclenche) n'empêche plus la passe de prix — R07 se
    déclenche quand même, après R11 (règle de bloc). Renommé depuis
    `test_evaluer_facture_prix_ignoree_quand_r11_declenchee` (L4-T4), qui
    asserte l'ancien comportement."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id, qte_fact=Decimal("20"), pu_ht=Decimal("110.00")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bl_incoherent = _document(coherent=False, statut="recu")
    bloc = _bloc(bl=bl_incoherent, lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id, mediane_pu=Decimal("100.00"), occurrences=3
    )

    anomalies = evaluer_facture(
        _facture(
            document,
            (bloc,),
            articles={article_id: article},
            historiques={article_id: historique},
        ),
        Parametres(),
    )

    assert [a.regle for a in anomalies] == ["R11", "R07"]


def test_evaluer_facture_prix_sans_historique_connu_ne_produit_rien() -> None:
    """Un article résolu mais absent de `facture.historiques` (jamais
    mesuré) ne fait pas planter le moteur : simplement aucune anomalie de
    prix pour cette ligne."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=None)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id, qte_fact=Decimal("20"), pu_ht=Decimal("110.00")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))

    anomalies = evaluer_facture(
        _facture(document, (bloc,), articles={article_id: article}), Parametres()
    )

    assert anomalies == ()


# --------------------------------------------------------------------------
# `regles_actives` (décision d'Ilane du 24/09/2026, `docs/dette.md`) :
# R07/R08/R09 désactivables sans toucher aux autres règles.
# --------------------------------------------------------------------------


def _facture_prix_et_remise_hors_norme() -> FactureControlee:
    """Même scénario que `test_evaluer_facture_r17_puis_r07_et_r09_meme_ligne_
    dans_lordre` (sans le ratio qui produit R17, pour isoler R07/R09) : une
    ligne dont le prix s'écarte de la médiane (R07) et dont la remise
    habituelle est absente (R09)."""
    document = _document(coherent=True)
    article_id = uuid.uuid4()
    article = _article(id=article_id, ratio=None)
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=article_id,
        qte_fact=Decimal("20"),
        pu_ht=Decimal("110.00"),
        remise_pct=None,
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc(bl=_document(coherent=True, statut="recu"), lignes=(rapprochee,))
    historique = _historique(
        article_id=article_id,
        mediane_pu=Decimal("100.00"),
        occurrences=3,
        remise_habituelle=Decimal("10.00"),
        occurrences_remise=3,
    )
    return _facture(
        document,
        (bloc,),
        articles={article_id: article},
        historiques={article_id: historique},
    )


def test_evaluer_facture_regles_actives_none_evalue_r07_et_r09_comme_avant() -> None:
    """`regles_actives=None` (défaut) : comportement inchangé, toutes les
    règles de `REGLES_FACTURE` s'évaluent -- non-régression du paramètre
    ajouté par la décision d'Ilane du 24/09/2026."""
    anomalies = evaluer_facture(_facture_prix_et_remise_hors_norme(), Parametres())

    assert [a.regle for a in anomalies] == ["R07", "R09"]


def test_evaluer_facture_regles_actives_sans_r07_r08_r09_ne_les_evalue_pas() -> None:
    """Retirer R07/R08/R09 de `regles_actives` : aucune anomalie de prix ou
    de remise, même avec un écart et une remise habituelle hors norme --
    les règles ne sont pas seulement filtrées en sortie, elles ne sont plus
    appelées du tout (voir le docstring de module)."""
    regles_sans_prix = REGLES_FACTURE - {"R07", "R08", "R09"}

    anomalies = evaluer_facture(
        _facture_prix_et_remise_hors_norme(), Parametres(), regles_sans_prix
    )

    assert anomalies == ()


def test_evaluer_facture_regles_actives_avec_r07_r08_r09_les_evalue() -> None:
    """`regles_actives` incluant explicitement R07/R08/R09 : comportement
    identique à `None` -- réactivation du drapeau `CONTROLE_PRIX_ACTIF`."""
    anomalies = evaluer_facture(
        _facture_prix_et_remise_hors_norme(), Parametres(), REGLES_FACTURE
    )

    assert [a.regle for a in anomalies] == ["R07", "R09"]


def test_evaluer_facture_regles_actives_ne_touche_pas_les_autres_regles() -> None:
    """Retirer R07/R08/R09 de `regles_actives` n'affecte aucune autre règle
    (R01/R02/R12 de bloc ici) : le paramètre ne restreint que la passe de
    prix (`_evaluer_prix`)."""
    document = _document(coherent=True)
    bloc = _bloc(bl=None)  # aucun BL rapproché -> R01

    anomalies = evaluer_facture(
        _facture(document, (bloc,)),
        Parametres(),
        REGLES_FACTURE - {"R07", "R08", "R09"},
    )

    assert [a.regle for a in anomalies] == ["R01"]


def test_evaluer_facture_ajoute_r13_apres_les_blocs_dans_lordre() -> None:
    """R13 (L4-T5) : une fois par facture, après les blocs, dans l'ordre de
    `lignes_negatives_sans_origine` (décision du contrôleur)."""
    document = _document(coherent=True)
    bloc = _bloc(bl=_document(coherent=True))
    ligne1 = _ligne(designation="Ciment", montant_ht=Decimal("-10.00"))
    ligne2 = _ligne(designation="Sable", montant_ht=Decimal("-20.00"))

    facture = FactureControlee(
        document=document,
        fournisseur="FOURNISSEUR INVENTE",
        blocs=(bloc,),
        articles={},
        historiques={},
        lignes_negatives_sans_origine=((ligne1, "Chantier A"), (ligne2, None)),
    )

    anomalies = evaluer_facture(facture, Parametres())

    assert [a.regle for a in anomalies] == ["R13", "R13"]
    assert anomalies[0].ligne_id == ligne1.id
    assert anomalies[0].detail["chantier"] == "Chantier A"
    assert anomalies[1].ligne_id == ligne2.id
    assert anomalies[1].detail["chantier"] == "—"
    assert all(a.chantier_id is None and a.alias_id is None for a in anomalies)


def test_evaluer_facture_r10_incoherente_ignore_aussi_les_avoirs() -> None:
    """Ruling R2 : le retour anticipé de R10 (facture « à vérifier ») ne
    doit pas être contourné par l'ajout de R13 (régression, L4-T5)."""
    document = _document(coherent=False)
    ligne = _ligne(montant_ht=Decimal("-10.00"))
    facture = FactureControlee(
        document=document,
        fournisseur="FOURNISSEUR INVENTE",
        blocs=(),
        articles={},
        historiques={},
        lignes_negatives_sans_origine=((ligne, "Chantier A"),),
    )

    anomalies = evaluer_facture(facture, Parametres())

    assert [a.regle for a in anomalies] == ["R10"]


def test_evaluer_suivi_enchaine_r06_r14_r15_r16_dans_lordre() -> None:
    """`evaluer_suivi` (L4-T5) enchaîne les règles de suivi dans l'ordre des
    champs de `ContexteSuivi` : R06, R14, R15, R16."""
    aujourdhui = datetime(2026, 8, 1)

    bloc = _bloc(date_bl=date(2026, 6, 1))
    ligne_bl = _ligne(designation="Ciment")
    alias = AliasEnAttenteControle(
        id=uuid.uuid4(),
        libelle="ALIAS INVENTE",
        fournisseur="FOURNISSEUR INVENTE",
        cree_le=datetime(2026, 7, 1),
    )
    bl_non_confirme = _document(
        coherent=True,
        depose_le=datetime(2026, 7, 1),
        deposant="Agent Un",
        confirme_le=None,
    )
    chantier = ChantierSuiviControle(
        id=uuid.uuid4(),
        nom="Chantier Inventé",
        dernier_depot=datetime(2026, 7, 1),
        nb_bl_factures_depuis=3,
    )

    contexte = ContexteSuivi(
        aujourdhui=aujourdhui,
        lignes_bl_non_facturees=((bloc, ligne_bl),),
        alias_en_attente=(alias,),
        bl_sans_confirmation=(bl_non_confirme,),
        chantiers=(chantier,),
    )

    anomalies = evaluer_suivi(contexte, Parametres())

    assert [a.regle for a in anomalies] == ["R06", "R14", "R15", "R16"]
    anomalie_r06, anomalie_r14, anomalie_r15, anomalie_r16 = anomalies
    # Ruling du contrôleur (fix round 1) : seules R14/R16 portent une
    # portée de suivi (`alias_id`/`chantier_id`) ; les autres la laissent
    # à `None`, y compris R06 et R15 qui vivent aussi dans `evaluer_suivi`.
    assert anomalie_r06.chantier_id is None and anomalie_r06.alias_id is None
    assert anomalie_r14.chantier_id is None
    assert anomalie_r14.alias_id == alias.id
    assert anomalie_r15.chantier_id is None and anomalie_r15.alias_id is None
    assert anomalie_r16.alias_id is None
    assert anomalie_r16.chantier_id == chantier.id


def test_evaluer_suivi_sans_rien_a_signaler_ne_produit_rien() -> None:
    contexte = ContexteSuivi(
        aujourdhui=datetime(2026, 8, 1),
        lignes_bl_non_facturees=(),
        alias_en_attente=(),
        bl_sans_confirmation=(),
        chantiers=(),
    )

    assert evaluer_suivi(contexte, Parametres()) == ()


def test_evaluer_suivi_chantiers_et_alias_portent_des_identites_distinctes() -> None:
    """Ruling du contrôleur (fix round 1, R16 signalée par la tâche,
    étendue à R14 par la revue) : deux chantiers silencieux, ou deux alias
    en attente, distincts ne doivent jamais s'écraser une fois persistés
    (L4-T11) — vérifié ici au niveau du moteur, pas seulement de la règle
    isolée."""
    aujourdhui = datetime(2026, 8, 1)
    alias_1 = AliasEnAttenteControle(
        id=uuid.uuid4(),
        libelle="ALIAS UN",
        fournisseur="FOURNISSEUR INVENTE",
        cree_le=datetime(2026, 7, 1),
    )
    alias_2 = AliasEnAttenteControle(
        id=uuid.uuid4(),
        libelle="ALIAS DEUX",
        fournisseur="FOURNISSEUR INVENTE",
        cree_le=datetime(2026, 7, 1),
    )
    chantier_1 = ChantierSuiviControle(
        id=uuid.uuid4(),
        nom="Chantier Un",
        dernier_depot=datetime(2026, 7, 1),
        nb_bl_factures_depuis=1,
    )
    chantier_2 = ChantierSuiviControle(
        id=uuid.uuid4(),
        nom="Chantier Deux",
        dernier_depot=datetime(2026, 7, 1),
        nb_bl_factures_depuis=2,
    )

    contexte = ContexteSuivi(
        aujourdhui=aujourdhui,
        lignes_bl_non_facturees=(),
        alias_en_attente=(alias_1, alias_2),
        bl_sans_confirmation=(),
        chantiers=(chantier_1, chantier_2),
    )

    anomalies = evaluer_suivi(contexte, Parametres())

    assert [a.regle for a in anomalies] == ["R14", "R14", "R16", "R16"]
    anomalie_alias_1, anomalie_alias_2, anomalie_chantier_1, anomalie_chantier_2 = (
        anomalies
    )
    assert anomalie_alias_1.alias_id == alias_1.id
    assert anomalie_alias_2.alias_id == alias_2.id
    assert anomalie_alias_1.alias_id != anomalie_alias_2.alias_id
    assert anomalie_chantier_1.chantier_id == chantier_1.id
    assert anomalie_chantier_2.chantier_id == chantier_2.id
    assert anomalie_chantier_1.chantier_id != anomalie_chantier_2.chantier_id


def test_regles_facture_et_suivi_sont_disjointes_et_couvrent_r01_a_r17() -> None:
    """Adjonction du contrôleur (L4-T5) : `REGLES_FACTURE`/`REGLES_SUIVI`
    sont l'unique source de vérité des scopes que `ingest` utilisera pour
    `synchroniser_anomalies` — une règle ajoutée plus tard sans mise à jour
    de l'un des deux ensembles doit faire échouer ce test."""
    toutes_les_regles = {f"R{i:02d}" for i in range(1, 18)}

    assert REGLES_FACTURE.isdisjoint(REGLES_SUIVI)
    assert toutes_les_regles == REGLES_FACTURE | REGLES_SUIVI
