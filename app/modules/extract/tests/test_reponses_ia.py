"""Tests de `reponses_ia.py` (T2, module PUR, phase 4).

Toutes les réponses « IA » sont inventées en mémoire (aucune fixture, aucun
document client, aucun appel réseau) : ce module ne lit jamais un vrai
appel OpenCode, seulement la structure JSON déjà décodée qu'il produirait.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.modules.extract.reponses_ia import (
    ActionLue,
    Controle,
    OffreLue,
    PageLue,
    PrixInternetLu,
    ReponseIAInvalide,
    SyntheseLue,
    controles_explication,
    controles_prix_internet,
    controles_synthese,
    lire_explication,
    lire_prix_internet,
    lire_synthese,
    nombres_du_texte,
    prix_ht,
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


@pytest.mark.parametrize("citee", ["[c1]", "C1", " c1 ", "[ c1 ]", "[C1]"])
def test_lire_synthese_reference_ecrite_autrement_reconnue(citee: str) -> None:
    """29/09/2026, essai réel : toutes les actions d'une synthèse avaient été
    écartées alors que les commentaires existaient -- la consigne envoyée
    demandait « les références [cN] » (avec crochets), celle de l'agent
    « c1, c2 ». Une référence citée avec crochets, espaces ou majuscule est
    la même référence."""
    structure = {
        "resume": "ok",
        "actions": [{"texte": "Une action", "commentaires": [citee]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1"])

    assert resultat.actions == (ActionLue(texte="Une action", references=("c1",)),)


def test_lire_synthese_reference_normalisee_non_repetee() -> None:
    structure = {
        "resume": "ok",
        "actions": [{"texte": "action", "commentaires": ["c1", "[c1]", "C2"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1", "c2"])

    assert resultat.actions[0].references == ("c1", "c2")


def test_lire_synthese_reference_normalisee_toujours_verifiee() -> None:
    structure = {
        "resume": "ok",
        "actions": [{"texte": "Action fantôme", "commentaires": ["[c99]", "c", "[]"]}],
    }

    resultat = lire_synthese(structure, references_valides=["c1"])

    assert resultat.actions == ()


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


def test_lire_explication_nombre_espace_groupe_accepte_par_parties() -> None:
    """Fix round 1, revue T2 : `nombres_du_texte("5 300")` fusionne en
    `{5300}` (spécifié, testé à part), mais « 5 » et « 300 » sont ici deux
    valeurs réellement distinctes du détail -- acceptée via la lecture
    partie par partie."""
    detail = {"nb_alertes": 5, "nb_bons": 300}
    structure = {"explication": "5 300 bons contrôlés ce mois-ci."}

    assert lire_explication(structure, detail) == "5 300 bons contrôlés ce mois-ci."


def test_lire_explication_nombre_espace_groupe_accepte_par_valeur_fusionnee() -> None:
    detail = {"total": 5300}
    structure = {"explication": "5 300 bons contrôlés ce mois-ci."}

    assert lire_explication(structure, detail) == "5 300 bons contrôlés ce mois-ci."


def test_lire_explication_nombre_espace_groupe_refuse_si_partie_absente() -> None:
    detail = {"nb_alertes": 5}
    structure = {"explication": "5 300 bons contrôlés ce mois-ci."}

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
        "offres": [
            {
                "produit_trouve": "Ciment 25kg",
                "source_url": "https://exemple.test/produit",
            }
        ],
    }

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.produit_trouve == "Ciment 25kg"
    assert resultat.source_url == "https://exemple.test/produit"


def test_lire_prix_internet_statut_inconnu_non_verifiable() -> None:
    structure = {"statut": "autre_chose"}

    resultat = lire_prix_internet(structure, pages=[])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "réponse incomplète"


def _offre(**champs: Any) -> dict[str, Any]:
    """Une offre nominale (forme du 29/09/2026), personnalisable par champ."""
    base: dict[str, Any] = {
        "produit_trouve": "Ciment CEM II 25kg",
        "prix": 12.34,
        "devise": "EUR",
        "taxes": "TTC",
        "unite": "sac",
        "conditionnement": "25kg",
        "source_url": "https://fournisseur.test/ciment",
        "confiance": "moyenne",
    }
    base.update(champs)
    return base


def _structure_trouve(**offre: Any) -> dict[str, Any]:
    """Une réponse `trouve` à une seule offre (forme du 29/09/2026)."""
    return {"statut": "trouve", "raison": "", "offres": [_offre(**offre)]}


def _page(adresse: str, texte: str) -> PageLue:
    return PageLue(outil="webfetch", adresse=adresse, texte=texte)


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


def test_lire_prix_internet_garde4_nombre_colle_a_un_mot_refuse() -> None:
    """Fix round 1, revue T2 : `(?:€|EUR)` sans borne de mot faisait
    matcher « Eur » au début de « Euromaster » (`re.IGNORECASE`)."""
    structure = _structure_trouve(prix=45, source_url="https://fournisseur.test/ciment")
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Voir aussi le pneu modele 45 Euromaster en promotion",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


def test_lire_prix_internet_garde4_nombre_suivi_dune_lettre_refuse() -> None:
    """Fix round 1, revue T2 : seul `(?!\\d)` après le nombre laissait
    passer un suffixe alphabétique collé (« 12,34eme »)."""
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Reference produit 12,34eme lot",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


def test_lire_prix_internet_garde4_nombre_precede_dune_lettre_refuse() -> None:
    """Fix round 1, revue T2 : seul `(?<!\\d)` avant le nombre laissait
    passer un préfixe alphabétique collé (« AB12,34 »)."""
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Ref AB12,34 en stock",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


def test_lire_prix_internet_garde4_milliers_ne_valide_pas_la_sous_partie() -> None:
    """Fix round 1, revue T2 : `1 212,34 €` ne doit pas valider un prix de
    212,34 -- seul le nombre complet 1212,34 y figure réellement."""
    structure = _structure_trouve(
        prix=212.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix catalogue : 1 212,34 €",
        )
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


def test_lire_prix_internet_garde4_milliers_valide_le_nombre_complet() -> None:
    structure = _structure_trouve(
        prix=1212.34, source_url="https://fournisseur.test/ciment"
    )
    pages_espace = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix catalogue : 1 212,34 €",
        )
    ]
    pages_point = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix catalogue : 1.212,34 €",
        )
    ]

    assert lire_prix_internet(structure, pages=pages_espace).statut == "trouve"
    assert lire_prix_internet(structure, pages=pages_point).statut == "trouve"


@pytest.mark.parametrize(
    "texte", ["45 EUR", "45€", "45 €"], ids=["mot-eur", "colle", "espace"]
)
def test_lire_prix_internet_garde4_prix_entier_formes_devise_acceptees(
    texte: str,
) -> None:
    structure = _structure_trouve(prix=45, source_url="https://fournisseur.test/ciment")
    pages = [
        PageLue(
            outil="webfetch", adresse="https://fournisseur.test/ciment", texte=texte
        )
    ]

    assert lire_prix_internet(structure, pages=pages).statut == "trouve"


def test_lire_prix_internet_garde4_texte_apres_espace_nempeche_pas_la_validation() -> (
    None
):
    """Choix documenté (fix round 1, revue T2) : la garde ne vérifie que le
    caractère immédiatement collé au nombre. Un espace suffit à le
    démarquer, même si un mot suit ensuite (« €TTC ») -- seul un caractère
    directement collé (chiffre ou lettre) invalide le nombre."""
    structure = _structure_trouve(
        prix=12.34, source_url="https://fournisseur.test/ciment"
    )
    pages = [
        PageLue(
            outil="webfetch",
            adresse="https://fournisseur.test/ciment",
            texte="Prix : 12,34 €TTC",
        )
    ]

    assert lire_prix_internet(structure, pages=pages).statut == "trouve"


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


@pytest.mark.parametrize(
    ("prix", "texte"),
    [
        pytest.param(7.47, "Soit 7€47 TTC/La pièce", id="euro-colle"),
        pytest.param(2.49, "2 €49 TTC/Le M2", id="espace-avant-euro"),
        pytest.param(2.49, f"2{chr(0x00A0)}€49 TTC/Le M2", id="insecable-avant-euro"),
        pytest.param(1234.5, "Palette : 1 234€50 HT", id="milliers"),
        pytest.param(45, "Sac : 45€00", id="centimes-nuls"),
    ],
)
def test_lire_prix_internet_garde4_euro_entre_euros_et_centimes_accepte(
    prix: float, texte: str
) -> None:
    """29/09/2026, essai réel sur une page Brico Dépôt (« 2 €49 TTC/Le M2
    Soit 7€47 TTC/La pièce ») : l'écriture avec « € » entre les euros et les
    centimes, courante chez les enseignes, n'était pas reconnue -- le prix
    était rejeté alors qu'il figurait bien sur la page ouverte."""
    structure = _structure_trouve(prix=prix, source_url="https://fournisseur.test/ba13")
    pages = [
        PageLue(outil="webfetch", adresse="https://fournisseur.test/ba13", texte=texte)
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "trouve"


@pytest.mark.parametrize(
    "texte",
    [
        pytest.param("Soit 17€47 TTC", id="chiffre-avant"),
        pytest.param("Soit 7€470 TTC", id="chiffre-apres"),
        pytest.param("Soit 7€47cm", id="lettre-apres"),
        pytest.param("Lot de 7 € 47 pièces", id="espace-apres-euro"),
    ],
)
def test_lire_prix_internet_garde4_euro_entre_euros_et_centimes_borne(
    texte: str,
) -> None:
    """Mêmes bornes que l'écriture « 7,47 » : jamais collé à d'autres
    chiffres ni à des lettres ; un espace après « € » n'est pas accepté
    (« 7 € 47 pièces » n'est pas un prix de 7,47 €)."""
    structure = _structure_trouve(prix=7.47, source_url="https://fournisseur.test/ba13")
    pages = [
        PageLue(outil="webfetch", adresse="https://fournisseur.test/ba13", texte=texte)
    ]

    resultat = lire_prix_internet(structure, pages=pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "prix absent de la page"


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
        offres=(
            OffreLue(
                prix=Decimal("12.3400"),
                devise="EUR",
                taxes="TTC",
                prix_ht=Decimal("10.28"),
                unite=None,
                conditionnement="25kg",
                produit_trouve="Ciment CEM II 25kg",
                source_url="https://fournisseur.test/ciment",
                confiance="moyenne",
            ),
        ),
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


def test_prix_ht_ttc_divise_par_1_20_au_centime() -> None:
    assert prix_ht(Decimal("13.91"), "TTC") == Decimal("11.59")
    assert prix_ht(Decimal("12.34"), "HT") == Decimal("12.34")
    assert prix_ht(Decimal("12.34"), None) is None
    assert prix_ht(Decimal("12.34"), "inconnu") is None


def test_lire_prix_internet_plusieurs_offres_triees_la_moins_chere_en_tete() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=13.91, taxes="TTC", source_url="https://a.test/p"),
            _offre(prix=12.00, taxes="HT", source_url="https://b.test/p"),
            _offre(prix=9.99, taxes="inconnu", source_url="https://c.test/p"),
        ],
    }
    pages = [
        _page("https://a.test/p", "Prix : 13,91 € TTC"),
        _page("https://b.test/p", "12,00 € HT"),
        _page("https://c.test/p", "9,99 €"),
    ]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.statut == "trouve"
    assert [o.source_url for o in resultat.offres] == [
        "https://a.test/p",  # 11,59 HT
        "https://b.test/p",  # 12,00 HT
        "https://c.test/p",  # inconnu : à la fin
    ]
    assert resultat.prix == Decimal("13.9100")
    assert resultat.taxes == "TTC"
    assert resultat.source_url == "https://a.test/p"
    assert [o.prix_ht for o in resultat.offres] == [
        Decimal("11.59"),
        Decimal("12.00"),
        None,
    ]


def test_lire_prix_internet_offre_en_echec_ecartee_les_autres_gardees() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://a.test/p"),  # page jamais ouverte
            _offre(prix=11.00, source_url="https://b.test/p"),  # prix absent
            _offre(prix=12.00, source_url="https://c.test/p"),  # gardée
        ],
    }
    pages = [_page("https://b.test/p", "rien"), _page("https://c.test/p", "12,00 €")]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.statut == "trouve"
    assert [o.source_url for o in resultat.offres] == ["https://c.test/p"]


def test_lire_prix_internet_aucune_offre_gardee_raison_de_la_premiere() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://a.test/p"),
            _offre(prix=11.00, source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://b.test/p", "rien")]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "source non ouverte"
    assert resultat.offres == ()


def test_lire_prix_internet_liste_vide_aucune_offre() -> None:
    resultat = lire_prix_internet({"statut": "trouve", "raison": "", "offres": []}, [])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "aucune offre"


def test_lire_prix_internet_ancien_format_a_plat_aucune_offre() -> None:
    """Point de vigilance 1 : un OpenCode pas encore mis à jour répond à
    l'ancienne forme (champs à plat, sans `offres`)."""
    structure = {
        "statut": "trouve",
        "produit_trouve": "Produit",
        "prix": 12.0,
        "devise": "EUR",
        "taxes": "HT",
        "source_url": "https://a.test/p",
        "confiance": "elevee",
        "raison": "",
    }

    resultat = lire_prix_internet(structure, [_page("https://a.test/p", "12,00 €")])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "aucune offre"


def test_lire_prix_internet_meme_page_une_seule_offre() -> None:
    """Point de vigilance 2 : barre oblique finale et fragment ignorés."""
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=12.00, source_url="https://a.test/p"),
            _offre(prix=12.00, source_url="https://A.test/p/#avis"),
        ],
    }

    resultat = lire_prix_internet(structure, [_page("https://a.test/p", "12,00 €")])

    assert len(resultat.offres) == 1


def test_lire_prix_internet_cinq_offres_au_plus() -> None:
    offres = [
        _offre(prix=10.00 + i, source_url=f"https://s{i}.test/p") for i in range(7)
    ]
    pages = [_page(f"https://s{i}.test/p", f"{10 + i},00 €") for i in range(7)]

    resultat = lire_prix_internet(
        {"statut": "trouve", "raison": "", "offres": offres}, pages
    )

    assert [o.source_url for o in resultat.offres] == [
        f"https://s{i}.test/p" for i in range(5)
    ]


def test_lire_prix_internet_toutes_inconnues_premiere_offre_en_tete() -> None:
    """Point de vigilance 3."""
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=15.00, taxes="inconnu", source_url="https://a.test/p"),
            _offre(prix=9.00, taxes="inconnu", source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://a.test/p", "15,00 €"), _page("https://b.test/p", "9,00 €")]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.source_url == "https://a.test/p"
    assert all(o.prix_ht is None for o in resultat.offres)


def test_controles_prix_internet_une_ligne_par_offre() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://www.a.test/p"),
            _offre(prix=11.00, source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://www.a.test/p", "10,00 €")]

    controles = controles_prix_internet(structure, pages)

    assert [(c.nom, c.ok) for c in controles] == [
        ("L'IA annonce un prix, pas « non vérifiable »", True),
        ("Offre 1 — a.test", True),
        ("Offre 2 — b.test", False),
    ]
    assert (
        controles[2].detail
        == "écartée : aucune page ouverte à l'adresse https://b.test/p"
    )


def test_controles_prix_internet_coherents_avec_lire() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://a.test/p"),
            _offre(prix=11.00, source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://a.test/p", "10,00 €"), _page("https://b.test/p", "11,00 €")]

    gardees = sum(1 for c in controles_prix_internet(structure, pages)[1:] if c.ok)

    assert gardees == len(lire_prix_internet(structure, pages).offres)


# --------------------------------------------------------------------------
# Controle (dataclass) -- immuable, comme `PageLue`/`ActionLue`.
# --------------------------------------------------------------------------


def test_controle_immuable() -> None:
    controle = Controle(nom="Un contrôle", ok=True, detail="tout va bien")

    assert controle.nom == "Un contrôle"
    assert controle.ok is True
    assert controle.detail == "tout va bien"
    with pytest.raises(AttributeError):
        controle.ok = False  # type: ignore[misc]


# --------------------------------------------------------------------------
# controles_prix_internet (Laboratoire IA) -- le statut, puis une ligne par
# offre, cohérents avec `lire_prix_internet` sur la même entrée.
# --------------------------------------------------------------------------

_NOM_STATUT = "L'IA annonce un prix, pas « non vérifiable »"


def test_controles_prix_internet_structure_non_dict() -> None:
    controles = controles_prix_internet("pas un dict", pages=[])

    assert [(c.nom, c.ok) for c in controles] == [(_NOM_STATUT, False)]


def test_controles_prix_internet_statut_non_verifiable_seul_controle() -> None:
    structure = {"statut": "prix_non_verifiable", "raison": "aucun résultat"}

    controles = controles_prix_internet(structure, pages=[])

    assert [(c.nom, c.ok) for c in controles] == [(_NOM_STATUT, False)]


def test_controles_prix_internet_statut_inconnu() -> None:
    controles = controles_prix_internet({"statut": "autre"}, pages=[])

    assert [(c.nom, c.ok) for c in controles] == [(_NOM_STATUT, False)]


def test_controles_prix_internet_statut_positif_si_trouve() -> None:
    controles = controles_prix_internet(_structure_trouve(), pages=[])

    assert controles[0].ok is True


def test_controles_prix_internet_liste_vide() -> None:
    controles = controles_prix_internet(
        {"statut": "trouve", "raison": "", "offres": []}, pages=[]
    )

    assert [(c.nom, c.ok, c.detail) for c in controles] == [
        (_NOM_STATUT, True, "l'IA répond « trouvé »"),
        ("Au moins une offre", False, "aucune offre dans la réponse"),
    ]


def test_controles_prix_internet_offre_champ_invalide() -> None:
    controles = controles_prix_internet(_structure_trouve(devise="USD"), pages=[])

    assert controles[1].nom == "Offre 1 — fournisseur.test"
    assert controles[1].ok is False
    assert controles[1].detail == (
        "écartée : champ manquant ou invalide (prix, devise, source ou confiance)"
    )


def test_controles_prix_internet_offre_page_absente() -> None:
    controles = controles_prix_internet(_structure_trouve(), pages=[])

    assert controles[1].ok is False
    assert controles[1].detail == (
        "écartée : aucune page ouverte à l'adresse https://fournisseur.test/ciment"
    )


def test_controles_prix_internet_offre_prix_absent() -> None:
    pages = [_page("https://fournisseur.test/ciment", "Aucun prix mentionné ici.")]

    controles = controles_prix_internet(_structure_trouve(), pages=pages)

    assert controles[1].ok is False
    assert controles[1].detail == "écartée : prix absent du texte de la page lue"


def test_controles_prix_internet_offre_gardee() -> None:
    pages = [_page("https://fournisseur.test/ciment", "Ciment 25kg à 12,34 € TTC.")]

    controles = controles_prix_internet(_structure_trouve(), pages=pages)

    assert [c.ok for c in controles] == [True, True]
    assert controles[1].detail == (
        "gardée : page https://fournisseur.test/ciment lue, prix retrouvé"
    )


def test_controles_prix_internet_au_dela_de_cinq_et_doublon() -> None:
    offres = [
        _offre(prix=10.0 + i, source_url=f"https://s{i}.test/p") for i in range(6)
    ]
    offres.append(_offre(prix=10.0, source_url="https://s0.test/p/"))
    pages = [_page(f"https://s{i}.test/p", f"{10 + i},00 €") for i in range(6)]

    controles = controles_prix_internet(
        {"statut": "trouve", "raison": "", "offres": offres}, pages=pages
    )

    assert controles[6].detail == "écartée : au-delà des 5 offres gardées"
    assert controles[7].detail == "écartée : au-delà des 5 offres gardées"

    doublon = controles_prix_internet(
        {"statut": "trouve", "raison": "", "offres": [offres[0], offres[6]]},
        pages=pages,
    )
    assert doublon[2].detail == "écartée : même page qu'une offre déjà gardée"


# --------------------------------------------------------------------------
# controles_explication (Laboratoire IA)
# --------------------------------------------------------------------------


def test_controles_explication_structure_non_dict() -> None:
    controles = controles_explication("pas un dict", {})

    assert len(controles) == 1
    assert controles[0].ok is False


def test_controles_explication_champ_manquant() -> None:
    controles = controles_explication({}, {})

    assert len(controles) == 1
    assert controles[0].ok is False


def test_controles_explication_vide() -> None:
    controles = controles_explication({"explication": "   "}, {})

    assert [c.ok for c in controles] == [True, False]


def test_controles_explication_trop_longue() -> None:
    controles = controles_explication({"explication": "a" * 401}, {})

    assert [c.ok for c in controles] == [True, False]


def test_controles_explication_nombre_valide_et_invente() -> None:
    detail = {"prix_bon": Decimal("12.50")}
    structure = {"explication": "Le prix de 12,50 dépasse la référence de 99."}

    controles = controles_explication(structure, detail)

    # Forme, longueur, puis un contrôle par nombre écrit (12,50 puis 99).
    assert [c.ok for c in controles] == [True, True, True, False]
    assert controles[2].detail == "12,50 figure dans les données"
    assert controles[3].detail == "99 absent des données"


def test_controles_explication_sans_nombre() -> None:
    controles = controles_explication({"explication": "Rien à signaler ici."}, {})

    assert [c.ok for c in controles] == [True, True]


def test_controles_explication_coherente_avec_lire_explication() -> None:
    """Le nombre de contrôles « nombre » réussis correspond exactement au
    fait que `lire_explication` accepte (ou non) la réponse."""
    detail = {"prix_bon": Decimal("12.50")}
    for structure, accepte in (
        ({"explication": "Le prix de 12,50 est confirmé."}, True),
        ({"explication": "Le prix de 99 est confirmé."}, False),
    ):
        controles = controles_explication(structure, detail)
        try:
            lire_explication(structure, detail)
            ok_reel = True
        except ReponseIAInvalide:
            ok_reel = False
        assert ok_reel == accepte
        assert all(c.ok for c in controles) == accepte


# --------------------------------------------------------------------------
# controles_synthese (Laboratoire IA)
# --------------------------------------------------------------------------


def test_controles_synthese_structure_non_dict() -> None:
    controles = controles_synthese("pas un dict", references_valides=[])

    assert len(controles) == 1
    assert controles[0].ok is False


def test_controles_synthese_champ_manquant() -> None:
    controles = controles_synthese({"resume": "ok"}, references_valides=[])

    assert len(controles) == 1
    assert controles[0].ok is False


def test_controles_synthese_resume_vide() -> None:
    controles = controles_synthese(
        {"resume": "   ", "actions": []}, references_valides=[]
    )

    assert [c.ok for c in controles] == [True, False]


def test_controles_synthese_action_gardee_ecartee_et_pourquoi() -> None:
    structure = {
        "resume": "Deux soucis cette semaine.",
        "actions": [
            {"texte": "Relancer Unikalo", "commentaires": ["c1", "c99"]},
            {"texte": "   ", "commentaires": ["c1"]},
            {"texte": "Action fantôme", "commentaires": ["c99"]},
        ],
    }

    controles = controles_synthese(structure, references_valides=["c1", "c2"])

    # forme, résumé, puis une ligne par action.
    assert len(controles) == 5
    assert controles[0].ok is True
    assert controles[1].ok is True
    assert controles[2].ok is True  # gardée, référence inconnue retirée
    assert "inconnue" in controles[2].detail
    assert controles[3].ok is False  # sans texte
    assert "sans texte" in controles[3].detail
    assert controles[4].ok is False  # aucune référence valide
    assert "aucune référence valide" in controles[4].detail


def test_controles_synthese_au_dela_de_dix_actions() -> None:
    actions = [{"texte": f"action {i}", "commentaires": [f"c{i}"]} for i in range(12)]
    structure = {"resume": "ok", "actions": actions}
    references_valides = [f"c{i}" for i in range(12)]

    controles = controles_synthese(structure, references_valides=references_valides)

    # forme, résumé, dix actions gardées, deux au-delà écartées.
    assert len(controles) == 2 + 12
    assert all(c.ok for c in controles[2:12])
    assert controles[12].ok is False
    assert controles[13].ok is False
    assert "au-delà" in controles[12].detail


def test_controles_synthese_coherente_avec_lire_synthese() -> None:
    structure = {
        "resume": "Résumé.",
        "actions": [
            {"texte": "Action valide", "commentaires": ["c1"]},
            {"texte": "Action fantôme", "commentaires": ["c99"]},
        ],
    }
    references_valides = ["c1", "c2"]

    resultat = lire_synthese(structure, references_valides=references_valides)
    controles = controles_synthese(structure, references_valides=references_valides)

    nb_actions_gardees_controles = sum(1 for controle in controles[2:] if controle.ok)
    assert nb_actions_gardees_controles == len(resultat.actions)


def test_controles_synthese_reference_entre_crochets_gardee() -> None:
    structure = {
        "resume": "Résumé.",
        "actions": [{"texte": "Action", "commentaires": ["[c1]", "C2"]}],
    }

    controles = controles_synthese(structure, references_valides=["c1", "c2"])

    assert controles[2].ok is True
    assert controles[2].detail == "gardée, toutes les références citées sont valides"


def test_controles_synthese_action_ecartee_montre_les_references_citees() -> None:
    """Sans les références citées, une action écartée ne se comprend pas
    (29/09/2026 : six actions écartées, impossible de dire pourquoi)."""
    structure = {
        "resume": "Résumé.",
        "actions": [
            {"texte": "Action fantôme", "commentaires": ["c99", "commentaire 3"]},
            {"texte": "Action sans source", "commentaires": []},
        ],
    }

    controles = controles_synthese(structure, references_valides=["c1"])

    assert controles[2].ok is False
    assert controles[2].detail == (
        "aucune référence valide (citées : c99, commentaire 3), écartée"
    )
    assert controles[3].ok is False
    assert controles[3].detail == "aucune référence valide (aucune citée), écartée"
