"""Tests de `reponses_ia.py` (T2, module PUR, phase 4).

Toutes les réponses « IA » sont inventées en mémoire (aucune fixture, aucun
document client, aucun appel réseau) : ce module ne lit jamais un vrai
appel OpenCode, seulement la structure JSON déjà décodée qu'il produirait.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.extract.reponses_ia import (
    ActionLue,
    PageLue,
    PrixInternetLu,
    ReponseIAInvalide,
    SyntheseLue,
    lire_explication,
    lire_prix_internet,
    lire_synthese,
    nombres_du_texte,
)

# Construits via `chr()`, jamais recopiés tels quels dans une chaîne (`ruff`
# RUF001 signale à juste titre ces caractères ambigus au regard d'un
# lecteur humain) : espace insécable, fine insécable, signe moins Unicode.
_ESPACE_INSECABLE = chr(0x00A0)
_ESPACE_FINE_INSECABLE = chr(0x202F)
_MOINS_UNICODE = chr(0x2212)

# --------------------------------------------------------------------------
# lire_synthese
# --------------------------------------------------------------------------


def test_lire_synthese_nominale() -> None:
    structure = {
        "resume": "  Deux soucis de retard cette semaine.  ",
        "actions": [
            {"texte": "Relancer Unikalo pour le retard du c1", "commentaires": ["c1"]},
            {"texte": "Vérifier la palette abîmée", "commentaires": ["c3", "c4"]},
        ],
    }

    resultat = lire_synthese(structure, references_valides=["c1", "c2", "c3"])

    assert resultat == SyntheseLue(
        resume="Deux soucis de retard cette semaine.",
        actions=(
            ActionLue(
                texte="Relancer Unikalo pour le retard du c1", references=("c1",)
            ),
            ActionLue(texte="Vérifier la palette abîmée", references=("c3",)),
        ),
    )


def test_lire_synthese_structure_non_dict_invalide() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_synthese(["pas", "un", "dict"], references_valides=["c1"])


def test_lire_synthese_champ_manquant_invalide() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_synthese({"resume": "ok"}, references_valides=["c1"])


def test_lire_synthese_actions_type_invalide() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_synthese(
            {"resume": "ok", "actions": "pas une liste"}, references_valides=["c1"]
        )


def test_lire_synthese_resume_vide_invalide() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_synthese({"resume": "   ", "actions": []}, references_valides=["c1"])


def test_lire_synthese_resume_non_texte_invalide() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_synthese({"resume": 42, "actions": []}, references_valides=["c1"])


def test_lire_synthese_resume_tronque_sans_couper_un_mot() -> None:
    mot = "motif "
    resume_brut = mot * 300  # bien plus de 1200 caractères
    structure = {"resume": resume_brut, "actions": []}

    resultat = lire_synthese(structure, references_valides=[])

    assert len(resultat.resume) <= 1200
    assert resultat.resume.endswith("…")
    # Pas de coupure au milieu du mot répété : juste avant l'ellipse, on
    # retombe forcément sur un espace ou le début d'un « motif » complet.
    assert not resultat.resume[:-1].endswith("mo")


def test_lire_synthese_action_texte_tronque() -> None:
    texte_brut = "mot " * 100  # bien plus de 300 caractères
    structure = {
        "resume": "ok",
        "actions": [{"texte": texte_brut, "commentaires": ["c1"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1"])

    assert len(resultat.actions) == 1
    assert len(resultat.actions[0].texte) <= 300
    assert resultat.actions[0].texte.endswith("…")


def test_lire_synthese_reference_inconnue_retiree() -> None:
    structure = {
        "resume": "ok",
        "actions": [{"texte": "Une action", "commentaires": ["c1", "c99", "c2"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1", "c2"])

    assert resultat.actions == (ActionLue(texte="Une action", references=("c1", "c2")),)


def test_lire_synthese_action_sans_reference_valide_ecartee() -> None:
    structure = {
        "resume": "ok",
        "actions": [{"texte": "Une action fantôme", "commentaires": ["c99"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1"])

    assert resultat.actions == ()


def test_lire_synthese_action_sans_texte_ecartee() -> None:
    structure = {
        "resume": "ok",
        "actions": [{"texte": "   ", "commentaires": ["c1"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1"])

    assert resultat.actions == ()


def test_lire_synthese_action_mal_formee_ecartee() -> None:
    structure = {
        "resume": "ok",
        "actions": [
            "pas un dict",
            {"texte": "ok mais sans commentaires"},
            {"texte": 42, "commentaires": ["c1"]},
            {"texte": "bonne action", "commentaires": ["c1"]},
        ],
    }

    resultat = lire_synthese(structure, references_valides=["c1"])

    assert resultat.actions == (ActionLue(texte="bonne action", references=("c1",)),)


def test_lire_synthese_plus_de_dix_actions_garde_les_dix_premieres() -> None:
    actions = [{"texte": f"action {i}", "commentaires": [f"c{i}"]} for i in range(12)]
    structure = {"resume": "ok", "actions": actions}
    references_valides = [f"c{i}" for i in range(12)]

    resultat = lire_synthese(structure, references_valides=references_valides)

    assert len(resultat.actions) == 10
    assert [a.texte for a in resultat.actions] == [f"action {i}" for i in range(10)]


def test_lire_synthese_reference_dupliquee_non_repetee() -> None:
    structure = {
        "resume": "ok",
        "actions": [{"texte": "action", "commentaires": ["c1", "c1", "c2"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1", "c2"])

    assert resultat.actions[0].references == ("c1", "c2")


# --------------------------------------------------------------------------
# nombres_du_texte
# --------------------------------------------------------------------------


def test_nombres_du_texte_virgule_et_point_egaux() -> None:
    assert nombres_du_texte("5,30") == frozenset({Decimal("5.3")})
    assert nombres_du_texte("5.3") == nombres_du_texte("5,30")


def test_nombres_du_texte_milliers_espace_insecable() -> None:
    attendu = frozenset({Decimal("1234.56")})
    assert nombres_du_texte(f"1{_ESPACE_INSECABLE}234,56") == attendu
    assert nombres_du_texte(f"1{_ESPACE_FINE_INSECABLE}234,56") == attendu
    assert nombres_du_texte("1 234,56") == attendu


def test_nombres_du_texte_signe_ignore() -> None:
    assert nombres_du_texte("-9,3") == frozenset({Decimal("9.3")})
    assert nombres_du_texte(f"{_MOINS_UNICODE}9,3") == frozenset({Decimal("9.3")})


def test_nombres_du_texte_date_produit_trois_nombres() -> None:
    assert nombres_du_texte("01/09/2026") == frozenset(
        {Decimal("1"), Decimal("9"), Decimal("2026")}
    )


def test_nombres_du_texte_pourcentage() -> None:
    assert nombres_du_texte("un écart de 5,3 % constaté") == frozenset({Decimal("5.3")})


def test_nombres_du_texte_aucun_chiffre() -> None:
    assert nombres_du_texte("aucun montant ici") == frozenset()


def test_nombres_du_texte_plusieurs_nombres_distincts() -> None:
    assert nombres_du_texte("de 12,50 à 15 euros") == frozenset(
        {Decimal("12.5"), Decimal("15")}
    )


# --------------------------------------------------------------------------
# lire_explication (garde des chiffres)
# --------------------------------------------------------------------------


def test_lire_explication_nominale() -> None:
    detail = {"prix_bon": Decimal("12.50"), "prix_reference": Decimal("10.00")}
    structure = {"explication": "  Le prix de 12,50 dépasse la référence de 10.  "}

    resultat = lire_explication(structure, detail)

    assert resultat == "Le prix de 12,50 dépasse la référence de 10."


def test_lire_explication_chiffre_virgule_egal_chiffre_point() -> None:
    detail = {"ecart": 5.3}
    attendu = "Écart constaté de 5,30 sur cette ligne."
    structure = {"explication": attendu}

    assert lire_explication(structure, detail) == attendu


def test_lire_explication_milliers_insecable_accepte() -> None:
    detail = {"montant": "1234.56"}
    attendu = f"Montant facturé : 1{_ESPACE_INSECABLE}234,56 euros."
    structure = {"explication": attendu}

    assert lire_explication(structure, detail) == attendu


def test_lire_explication_chiffre_invente_refuse() -> None:
    detail = {"prix_bon": Decimal("12.50")}
    structure = {"explication": "Le prix de 99,99 dépasse la référence."}

    with pytest.raises(ReponseIAInvalide, match="chiffre absent des données"):
        lire_explication(structure, detail)


def test_lire_explication_date_recopiee_acceptee() -> None:
    detail = {"date": "2026-09-01"}
    structure = {"explication": "Constaté le 01/09/2026 sur le bon."}

    assert lire_explication(structure, detail) == "Constaté le 01/09/2026 sur le bon."


def test_lire_explication_texte_trop_long_refuse() -> None:
    detail: dict[str, object] = {}
    structure = {"explication": "a" * 401}

    with pytest.raises(ReponseIAInvalide):
        lire_explication(structure, detail)


def test_lire_explication_vide_refuse() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_explication({"explication": "   "}, {})


def test_lire_explication_champ_manquant_refuse() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_explication({}, {})


def test_lire_explication_structure_non_dict_refuse() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_explication("pas un dict", {})


def test_lire_explication_detail_imbrique_liste_et_dict() -> None:
    detail = {
        "lignes": [
            {"prix": Decimal("3.20")},
            {"prix": Decimal("4.10")},
        ]
    }
    structure = {"explication": "Comparé à 3,20 puis 4,10 sur les deux lignes."}

    assert (
        lire_explication(structure, detail)
        == "Comparé à 3,20 puis 4,10 sur les deux lignes."
    )


# --------------------------------------------------------------------------
# lire_prix_internet
# --------------------------------------------------------------------------


def test_lire_prix_internet_structure_non_dict_leve_exception() -> None:
    with pytest.raises(ReponseIAInvalide):
        lire_prix_internet("pas un dict", pages=[])


def test_lire_prix_internet_statut_prix_non_verifiable_garde_raison() -> None:
    structure = {"statut": "prix_non_verifiable", "raison": "  aucun résultat fiable  "}

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"
    assert resultat.prix is None
    assert resultat.raison == "aucun résultat fiable"


def test_lire_prix_internet_statut_prix_non_verifiable_sans_raison() -> None:
    structure = {"statut": "prix_non_verifiable"}

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.raison == "non vérifiable"


def test_lire_prix_internet_statut_prix_non_verifiable_garde_produit_et_source() -> (
    None
):
    structure = {
        "statut": "prix_non_verifiable",
        "produit_trouve": "Ciment 25kg",
        "source_url": "https://exemple.test/produit",
    }

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.produit_trouve == "Ciment 25kg"
    assert resultat.source_url == "https://exemple.test/produit"


def test_lire_prix_internet_statut_inconnu_non_verifiable() -> None:
    structure = {"statut": "autre_chose"}

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "réponse incomplète"


def _structure_trouve(**overrides: object) -> dict[str, object]:
    """Réponse `SCHEMA_PRIX_INTERNET` nominale, personnalisable par champ."""
    base: dict[str, object] = {
        "statut": "trouve",
        "produit_trouve": "Ciment CEM II 25kg",
        "prix": 12.34,
        "devise": "EUR",
        "taxes": "TTC",
        "unite": "sac",
        "conditionnement": "25kg",
        "source_url": "https://fournisseur.test/ciment",
        "confiance": "moyenne",
        "raison": "",
    }
    base.update(overrides)
    return base


def test_lire_prix_internet_garde2_prix_negatif_non_verifiable() -> None:
    structure = _structure_trouve(prix=-5)

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "réponse incomplète"


def test_lire_prix_internet_garde2_prix_bool_refuse() -> None:
    structure = _structure_trouve(prix=True)

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"


def test_lire_prix_internet_garde2_devise_invalide_non_verifiable() -> None:
    structure = _structure_trouve(devise="USD")

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "réponse incomplète"


def test_lire_prix_internet_garde2_source_non_https_non_verifiable() -> None:
    structure = _structure_trouve(source_url="http://fournisseur.test/ciment")

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"


def test_lire_prix_internet_garde2_confiance_invalide_non_verifiable() -> None:
    structure = _structure_trouve(confiance="totale")

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"


def test_lire_prix_internet_garde2_produit_vide_non_verifiable() -> None:
    structure = _structure_trouve(produit_trouve="   ")

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"


def test_lire_prix_internet_garde2_ok_positif() -> None:
    """Positif du garde 2 : la garde 3 échoue ensuite faute de page ouverte,
    mais la raison distincte (« source non ouverte ») prouve que la garde 2
    a bien été franchie."""
    structure = _structure_trouve()

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "source non ouverte"


def test_lire_prix_internet_garde3_page_absente_non_verifiable() -> None:
    structure = _structure_trouve(source_url="https://fournisseur.test/ciment")
    pages = [
        PageLue(outil="webfetch", adresse="https://autre.test/page", texte="12,34 €")
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "source non ouverte"


def test_lire_prix_internet_garde3_websearch_ne_compte_pas() -> None:
    structure = _structure_trouve(source_url="https://fournisseur.test/ciment")
    pages = [
        PageLue(
            outil="websearch",
            adresse="https://fournisseur.test/ciment",
            texte="12,34 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "source non ouverte"


def test_lire_prix_internet_garde3_barre_oblique_finale_ignoree() -> None:
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment/",
            texte="Prix : 12,34 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "trouve"


def test_lire_prix_internet_garde3_fragment_ignore() -> None:
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment#avis"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix : 12,34 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "trouve"


def test_lire_prix_internet_garde4_prix_absent_de_la_page() -> None:
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Aucun prix mentionné ici.",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


def test_lire_prix_internet_garde4_prix_colle_a_dautres_chiffres_refuse() -> None:
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Référence 112,34 en stock.",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


def test_lire_prix_internet_garde4_prix_entier_avec_symbole_euro() -> None:
    structure = _structure_trouve(prix=45, source_url="https://fournisseur.test/ciment")
    pages = [
        PageLue(
            outil="webfetch", adresse="https://fournisseur.test/ciment", texte="45 €"
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "trouve"
    assert resultat.prix == Decimal("45.0000")


def test_lire_prix_internet_garde4_prix_float_cherche_en_deux_decimales() -> None:
    structure = _structure_trouve(
        prix=12.3, source_url="https://fournisseur.test/ciment"
    )
    pages_virgule = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix : 12,30 €",
        )
    ]
    pages_point = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Price: 12.30 EUR",
        )
    ]

    assert lire_prix_internet(structure, pages=pages_virgule).statut == "trouve"
    assert lire_prix_internet(structure, pages=pages_point).statut == "trouve"


def test_lire_prix_internet_garde4_milliers_avec_point_accepte() -> None:
    structure = _structure_trouve(
        prix=1234.56, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix catalogue : 1.234,56 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "trouve"


def test_lire_prix_internet_tout_passe_trouve() -> None:
    structure = _structure_trouve(
        prix=12.34,
        unite="",
        conditionnement="25kg",
        source_url="https://fournisseur.test/ciment",
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Ciment 25kg à 12,34 € TTC.",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat == PrixInternetLu(
        statut="trouve",
        prix=Decimal("12.3400"),
        devise="EUR",
        taxes="TTC",
        unite=None,
        conditionnement="25kg",
        produit_trouve="Ciment CEM II 25kg",
        source_url="https://fournisseur.test/ciment",
        confiance="moyenne",
        raison=None,
    )


def test_lire_prix_internet_taxes_inconnu_devient_none() -> None:
    structure = _structure_trouve(
        prix=12.34,
        taxes="inconnu",
        source_url="https://fournisseur.test/ciment",
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="12,34 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.taxes is None


def test_lire_prix_internet_taxes_valeur_inattendue_devient_none() -> None:
    structure = _structure_trouve(
        prix=12.34,
        taxes="autre",
        source_url="https://fournisseur.test/ciment",
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="12,34 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.taxes is None
