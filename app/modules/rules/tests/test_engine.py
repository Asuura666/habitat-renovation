"""Tests de `evaluer_facture` (L4-T1 à L4-T4) : ordre du CDC §5, Ruling R2,
Ruling R3, Ruling R7.

R10 (document), R11 (BL rapproché par bloc), R01/R02/R12 (niveau bloc,
toujours évaluées, depuis L4-T2), R03/R04/R05/R17 (niveau ligne, sous la
double garde Ruling R2 — pas de R11 sur le bloc — et Ruling R3 — BL du bloc
reçu, depuis L4-T3) et, depuis L4-T4, R07/R08/R09 (prix et remises,
insérées entre R05 et R17, Ruling R7 : mêmes gardes que R03-R05/R17 **sauf**
qu'elles tournent aussi sur les lignes d'un bloc sans BL rapproché, faute
de quantité à comparer) sont enchaînées. R13 (niveau ligne) et R14-R16
(suivi) n'existent pas encore (L4-T5/T11). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.engine import evaluer_facture
from app.modules.rules.modeles import (
    ArticleControle,
    BlocControle,
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
# Règles de prix et remise (L4-T4) : Ruling R7
# --------------------------------------------------------------------------


def test_evaluer_facture_r07_evaluee_entre_r05_et_r17() -> None:
    """R07 (écart de prix moyen) s'insère entre R05 et R17 dans le
    traitement d'une ligne appariée sans écart de quantité, sur un bloc
    dont le BL est reçu (Ruling R3)."""
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

    assert [a.regle for a in anomalies] == ["R07", "R17"]
    assert anomalies[0].ligne_id == ligne_facture.id
    assert anomalies[0].article_id == article_id


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


def test_evaluer_facture_r07_r09_et_r17_meme_ligne_dans_lordre() -> None:
    """R05 (absente ici, ligne appariée), R07/R08 (prix), puis R09
    (remise), puis R17 (conditionnement) : ordre complet du CDC §5 pour une
    ligne qui cumule les trois anomalies indépendantes."""
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

    assert [a.regle for a in anomalies] == ["R07", "R09", "R17"]


def test_evaluer_facture_prix_evaluee_meme_sur_bloc_sans_bl_rapproche() -> None:
    """Ruling R7 : un prix hors historique reste une anomalie même sans BL
    rapproché — la règle tourne alors sur toutes les lignes "article" du
    bloc, indépendamment de R01/R02 (qui signalent l'absence de BL, pas le
    prix)."""
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


def test_evaluer_facture_prix_ignoree_quand_bl_a_verifier() -> None:
    """Un BL rapproché mais encore « à vérifier » n'est pas « sans BL
    rapproché » (Ruling R7 ne s'applique pas ici) : mêmes gardes que
    R03-R05/R17 (Ruling R3), donc aucune anomalie de prix tant que le BL
    n'est pas confirmé reçu."""
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

    assert anomalies == ()


def test_evaluer_facture_prix_ignoree_quand_r11_declenchee() -> None:
    """Ruling R2 : un BL rapproché mais incohérent (R11) saute aussi les
    règles de prix, comme les autres règles de ligne — il porte bien un BL
    (`bl is not None`), l'exception Ruling R7 ne s'applique donc pas."""
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

    assert [a.regle for a in anomalies] == ["R11"]


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
