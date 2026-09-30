"""B-06 : lignes de même code sur plusieurs lignes d'un bloc ou d'un BL.

Chaîne pure (sans base ni réseau) : `apparier_lignes` ->
`construire_lignes_rapprochees` -> `evaluer_facture`. Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.ingest.regroupement_lignes import construire_lignes_rapprochees
from app.modules.normalize.appariement import (
    Appariement,
    LigneAApparier,
    apparier_lignes,
)
from app.modules.rules.engine import evaluer_facture
from app.modules.rules.modeles import (
    Anomalie,
    BlocControle,
    DocumentControle,
    FactureControlee,
    LigneControlee,
    Parametres,
)


def _ligne(code: str | None, qte: str, ordre: int = 1, **kw: Any) -> LigneControlee:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ordre": ordre,
        "code": code,
        "designation": f"DESIGNATION {code}",
        "article_id": None,
        "qte_conditionnements": Decimal(qte),
        "qte_facturee": Decimal(qte),
        "qte_fact": Decimal(qte),
        "unite": "kg",
        "pu_ht": Decimal("1.50"),
        "remise_pct": None,
        "montant_ht": Decimal("15.00"),
        "type_ligne": "article",
        "conversion_impossible": False,
    }
    base.update(kw)
    return LigneControlee(**base)


def _document(statut: str = "extraite") -> DocumentControle:
    return DocumentControle(
        id=uuid.uuid4(),
        numero_interne=1,
        numero="DOC1",
        date_doc=date(2026, 8, 1),
        statut=statut,
        somme_lignes=Decimal("100"),
        total_ht=Decimal("100"),
        ecart_somme=None,
        depose_le=None,
        deposant=None,
        confirme_le=None,
    )


def _vue(lignes: list[LigneControlee]) -> list[LigneAApparier]:
    return [LigneAApparier(x.id, x.code, x.designation) for x in lignes]


def _anomalies(
    facture: list[LigneControlee], bl: list[LigneControlee]
) -> tuple[Anomalie, ...]:
    def vue(lignes: list[LigneControlee]) -> list[LigneAApparier]:
        return [LigneAApparier(x.id, x.code, x.designation) for x in lignes]

    construction = construire_lignes_rapprochees(
        facture, bl, apparier_lignes(vue(facture), vue(bl))
    )
    bloc = BlocControle(
        id=uuid.uuid4(),
        numero_bl="BL1",
        date_bl=date(2026, 8, 1),
        chantier_brut="C",
        chantier="c",
        commentaire=None,
        montant_ht=Decimal("100"),
        bl=_document("recu"),
        lignes=construction.lignes,
        lignes_bl_non_facturees=tuple(
            x for x in bl if x.id not in construction.cles_bl_couvertes
        ),
        autre_facture_numero=None,
        autre_facture_id=None,
    )
    controlee = FactureControlee(
        document=_document(),
        fournisseur="F",
        blocs=(bloc,),
        articles={},
        historiques={},
        lignes_negatives_sans_origine=(),
    )
    return evaluer_facture(controlee, Parametres())


def test_une_ligne_facture_deux_lignes_bl_qui_s_equilibrent() -> None:
    assert _anomalies([_ligne("X", "20")], [_ligne("X", "10"), _ligne("X", "10")]) == ()


def test_deux_lignes_facture_une_ligne_bl_qui_s_equilibrent() -> None:
    assert _anomalies([_ligne("X", "10"), _ligne("X", "10")], [_ligne("X", "20")]) == ()


def test_deux_contre_deux_qui_s_equilibrent_au_total() -> None:
    assert (
        _anomalies(
            [_ligne("X", "10"), _ligne("X", "20")],
            [_ligne("X", "20"), _ligne("X", "10")],
        )
        == ()
    )


def test_vrai_ecart_au_total_une_seule_anomalie_r03_avec_detail() -> None:
    anomalies = _anomalies([_ligne("X", "10"), _ligne("X", "10")], [_ligne("X", "15")])
    assert [a.regle for a in anomalies] == ["R03"]
    detail = anomalies[0].detail
    assert detail["qte_facture"] == "20"
    assert detail["qte_bl"] == "15"
    assert detail["ecart"] == "5"
    assert detail["lignes_facture"] == "10 + 10"
    assert detail["lignes_bl"] == "15"


def test_vrai_ecart_au_total_une_seule_anomalie_r04_avec_detail() -> None:
    anomalies = _anomalies([_ligne("X", "10")], [_ligne("X", "10"), _ligne("X", "5")])
    assert [a.regle for a in anomalies] == ["R04"]
    detail = anomalies[0].detail
    assert detail["qte_facture"] == "10"
    assert detail["qte_bl"] == "15"
    assert detail["ecart"] == "-5"
    assert detail["lignes_facture"] == "10"
    assert detail["lignes_bl"] == "10 + 5"


def test_aucun_faux_conforme_une_ligne_de_facture_d_un_autre_code_reste_r05() -> None:
    anomalies = _anomalies(
        [_ligne("X", "10"), _ligne("X", "10"), _ligne("Y", "3")],
        [_ligne("X", "20")],
    )
    assert [a.regle for a in anomalies] == ["R05"]
    assert anomalies[0].detail["code"] == "Y"


def test_ligne_isolee_garde_le_detail_habituel() -> None:
    anomalies = _anomalies([_ligne("X", "12")], [_ligne("X", "10")])
    assert [a.regle for a in anomalies] == ["R03"]
    assert "lignes_facture" not in anomalies[0].detail


def test_groupe_non_agregeable_reste_ligne_a_ligne() -> None:
    """Conversion impossible sur une ligne du groupe : pas d'agrégation, donc
    pas de faux « conforme » ; la ligne de facture en trop reste non appariée."""
    anomalies = _anomalies(
        [_ligne("X", "10"), _ligne("X", "10")],
        [_ligne("X", "20", qte_fact=None, conversion_impossible=True)],
    )
    assert [a.regle for a in anomalies] == ["R05"]


def test_liens_persistes_toutes_les_lignes_de_bl_du_groupe_sont_reliees() -> None:
    facture = [_ligne("X", "20")]
    bl = [_ligne("X", "10"), _ligne("X", "10")]
    construction = construire_lignes_rapprochees(
        facture, bl, apparier_lignes(_vue(facture), _vue(bl))
    )
    assert len(construction.liens) == 2
    assert {lien.ligne_facture_id for lien in construction.liens} == {facture[0].id}
    assert {lien.ligne_bl_id for lien in construction.liens} == {b.id for b in bl}
    assert construction.liens[0].ecart_qte == Decimal("0")
    assert construction.cles_bl_couvertes == {bl[0].id, bl[1].id}


def test_groupe_d_articles_differents_n_est_pas_agrege() -> None:
    """Constat 8 : deux lignes de même code rattachées à deux articles
    différents (donc converties dans deux unités de facturation possibles)
    ne sont jamais additionnées : retour à la comparaison ligne à ligne."""
    anomalies = _anomalies(
        [
            _ligne("X", "10", article_id=uuid.uuid4()),
            _ligne("X", "10", article_id=uuid.uuid4()),
        ],
        [_ligne("X", "20")],
    )
    assert sorted(a.regle for a in anomalies) == ["R04", "R05"]


def test_appariement_de_groupe_incoherent_ne_leve_pas() -> None:
    """Constat 7 : un groupe de facture qui ne contient pas la ligne (donnée
    incohérente, jamais produite par `apparier_lignes`) laisse la ligne sans
    bon au lieu de lever `ValueError`."""
    facture = [_ligne("X", "10"), _ligne("X", "10", type_ligne="eco")]
    bl = [_ligne("X", "10")]
    autre = uuid.uuid4()
    appariements = tuple(
        Appariement(
            cle_facture=ligne.id,
            cle_bl=bl[0].id,
            methode="code",
            groupe_facture=(autre,),
            groupe_bl=(bl[0].id,),
        )
        for ligne in facture
    )
    construction = construire_lignes_rapprochees(facture, bl, appariements)
    assert [ligne.bl for ligne in construction.lignes] == [None, None]
