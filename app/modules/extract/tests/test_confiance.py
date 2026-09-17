"""Tests de `confiance.py` (L3-T1, module PUR).

Données entièrement inventées, construites dans le test (positions calculées
via `str.index`, jamais comptées à la main) sauf la dernière section, qui
relit la réponse Mistral OCR inventée `donnees/bl_synthetique.mistral-ocr.json`
(constat 3, décision du contrôleur : aucune donnée client dedans).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.modules.extract.confiance import (
    Mot,
    confiance_min_pages,
    confiance_valeur,
    confiances_ligne,
    indexer_confiance,
)

_DONNEES = Path(__file__).parent / "donnees"


def _mot(
    texte: str, sous_chaine: str, confiance: float, depart: int = 0
) -> dict[str, Any]:
    """Entrée `word_confidence_scores` pour `sous_chaine` dans `texte`,
    positionnée en cherchant sa première occurrence à partir de `depart`
    (pour ne jamais compter les index à la main)."""
    index = texte.index(sous_chaine, depart)
    return {"text": sous_chaine, "confidence": confiance, "start_index": index}


def _index_page(texte: str, mots: list[dict[str, Any]]) -> Any:
    return indexer_confiance(
        {
            "pages": [
                {
                    "markdown": texte,
                    "confidence_scores": {"word_confidence_scores": mots},
                }
            ]
        }
    )


# --------------------------------------------------------------------------
# indexer_confiance
# --------------------------------------------------------------------------


def test_indexer_confiance_reponse_sans_pages_index_vide() -> None:
    index = indexer_confiance({})

    assert index.sources == ()
    assert index.disponible is False


def test_indexer_confiance_une_source_par_page_et_par_tableau_dans_l_ordre() -> None:
    reponse = {
        "pages": [
            {
                "markdown": "texte de page",
                "tables": [
                    {"content": "table un", "word_confidence_scores": []},
                    {"content": "table deux", "word_confidence_scores": []},
                ],
            }
        ]
    }

    index = indexer_confiance(reponse)

    assert [s.texte for s in index.sources] == [
        "texte de page",
        "table un",
        "table deux",
    ]


def test_indexer_confiance_ignore_les_entrees_mal_formees_sans_lever() -> None:
    reponse = {
        "pages": [
            {
                "markdown": "ABC",
                "confidence_scores": {
                    "word_confidence_scores": [
                        {"text": "ABC", "confidence": 0.9, "start_index": 0},
                        {"text": "hors texte", "confidence": 0.9, "start_index": 100},
                        {"text": 123, "confidence": 0.9, "start_index": 0},
                        {"text": "ABC", "confidence": "haute", "start_index": 0},
                        {"text": "ABC", "confidence": 0.9, "start_index": "0"},
                        {"text": "ABC", "confidence": True, "start_index": 0},
                        "pas un dict",
                    ]
                },
            }
        ]
    }

    index = indexer_confiance(reponse)

    assert len(index.sources) == 1
    assert index.sources[0].mots == (Mot(debut=0, fin=3, confiance=Decimal("0.9000")),)


def test_indexer_confiance_ignore_les_confiances_non_finies_sans_lever() -> None:
    """`json.loads` accepte `NaN`/`Infinity`/`-Infinity` par défaut : une
    réponse OCR corrompue ne doit jamais faire planter l'extraction
    (`Decimal("inf").quantize(...)` lève sinon `InvalidOperation`)."""
    reponse = {
        "pages": [
            {
                "markdown": "ABC DEF GHI JKL",
                "confidence_scores": {
                    "word_confidence_scores": [
                        {"text": "ABC", "confidence": float("nan"), "start_index": 0},
                        {"text": "DEF", "confidence": float("inf"), "start_index": 4},
                        {"text": "GHI", "confidence": float("-inf"), "start_index": 8},
                        {"text": "JKL", "confidence": 0.9, "start_index": 12},
                    ]
                },
            }
        ]
    }

    index = indexer_confiance(reponse)

    assert index.sources[0].mots == (
        Mot(debut=12, fin=15, confiance=Decimal("0.9000")),
    )


def test_indexer_confiance_reponse_sans_scores_index_indisponible() -> None:
    index = indexer_confiance({"pages": [{"markdown": "peu importe"}]})

    assert index.disponible is False


# --------------------------------------------------------------------------
# confiance_valeur
# --------------------------------------------------------------------------


def test_confiance_valeur_mot_avec_espace_initiale_prend_le_minimum() -> None:
    """« EXEMPLE SAS » recouvre les mots " EXEMPLE" et " SAS" (min 0,7),
    jamais le mot précédent " PEINTURES" (0,1) : constat 3, L3-D2."""
    texte = "PEINTURES EXEMPLE SAS"
    mots = [
        _mot(texte, "PEINTURES", 0.1),
        _mot(texte, " EXEMPLE", 0.7),
        _mot(texte, " SAS", 0.9),
    ]

    index = _index_page(texte, mots)

    assert confiance_valeur(index, "EXEMPLE SAS") == Decimal("0.7000")


def test_confiance_valeur_garde_la_meilleure_occurrence() -> None:
    texte = "ABC test ABC"
    mots = [
        _mot(texte, "ABC", 0.6, depart=0),
        _mot(texte, "ABC", 0.95, depart=4),
    ]

    index = _index_page(texte, mots)

    assert confiance_valeur(index, "ABC") == Decimal("0.9500")


def test_confiance_valeur_absente_du_texte_renvoie_zero() -> None:
    texte = "rien à voir ici"
    index = _index_page(texte, [_mot(texte, "rien", 0.9)])

    assert confiance_valeur(index, "ABC") == Decimal("0")


def test_confiance_valeur_none_ou_blanche_renvoie_none() -> None:
    texte = "rien à voir ici"
    index = _index_page(texte, [_mot(texte, "rien", 0.9)])

    assert confiance_valeur(index, None) is None
    assert confiance_valeur(index, "   ") is None


def test_confiance_valeur_reponse_sans_scores_renvoie_none() -> None:
    index = indexer_confiance({"pages": [{"markdown": "peu importe"}]})

    assert confiance_valeur(index, "peu") is None


def test_confiance_valeur_borne_un_isole_pas_dans_un_nombre_ou_alphanum() -> None:
    """« 4 » n'est trouvé ni dans « 24,50 » ni dans « 4X5 » ; « L209900000123 »
    est trouvé dans « N°L209900000123 » (bornes non alphanumériques)."""
    texte = "24,50 4X5 N°L209900000123"
    index = _index_page(texte, [_mot(texte, "L209900000123", 0.9)])

    assert confiance_valeur(index, "4") == Decimal("0")
    assert confiance_valeur(index, "L209900000123") == Decimal("0.9000")


def test_confiance_valeur_insensible_a_la_casse() -> None:
    texte = "Exemple valeur ABC"
    index = _index_page(texte, [_mot(texte, "ABC", 0.8)])

    assert confiance_valeur(index, "abc") == Decimal("0.8000")


def test_confiance_valeur_espaces_multiples_dans_le_texte() -> None:
    texte = "ABC     DEF"
    mots = [_mot(texte, "ABC", 0.7), _mot(texte, "DEF", 0.9)]

    index = _index_page(texte, mots)

    assert confiance_valeur(index, "ABC DEF") == Decimal("0.7000")


def test_confiance_valeur_cherche_aussi_l_autre_separateur_decimal() -> None:
    texte = "Montant 126,00 HT"
    index = _index_page(texte, [_mot(texte, "126,00", 0.85)])

    assert confiance_valeur(index, "126.00") == Decimal("0.8500")


# --------------------------------------------------------------------------
# confiances_ligne
# --------------------------------------------------------------------------


def test_confiances_ligne_isole_la_ligne_source_et_ignore_les_decoys_ailleurs() -> None:
    """Code et quantité de la ligne AB1234 -> confiances de cette ligne ;
    un « 4 » à forte confiance sur une autre ligne ne change rien ; un
    montant absent de la ligne retenue -> 0 (L3-D2)."""
    contenu = (
        "| Code | Qté | Montant |\n"
        "| --- | --- | --- |\n"
        "| AB1234 | 4 | 100,00 |\n"
        "| CD5678 | 2 | 50,00 |\n"
        "Remarque page 4 sur 4"
    )
    apres_ab = contenu.index("AB1234") + len("AB1234")
    apres_cd = contenu.index("CD5678") + len("CD5678")
    decoy1 = _mot(contenu, "4", 0.99, depart=contenu.index("Remarque"))
    decoy2 = _mot(contenu, "4", 0.99, depart=decoy1["start_index"] + 1)

    mots = [
        _mot(contenu, "AB1234", 0.90),
        _mot(contenu, "4", 0.85, depart=apres_ab),
        _mot(contenu, "CD5678", 0.92),
        _mot(contenu, "2", 0.93, depart=apres_cd),
        decoy1,
        decoy2,
    ]
    index = indexer_confiance(
        {
            "pages": [
                {
                    "markdown": "",
                    "tables": [{"content": contenu, "word_confidence_scores": mots}],
                }
            ]
        }
    )

    resultat = confiances_ligne(index, ["AB1234", "4", "999,99"])

    assert resultat == (Decimal("0.9000"), Decimal("0.8500"), Decimal("0"))


def test_confiances_ligne_valeur_none_renvoie_none() -> None:
    contenu = "| AB1234 | 4 |"
    index = indexer_confiance(
        {
            "pages": [
                {
                    "markdown": "",
                    "tables": [
                        {
                            "content": contenu,
                            "word_confidence_scores": [_mot(contenu, "AB1234", 0.9)],
                        }
                    ],
                }
            ]
        }
    )

    resultat = confiances_ligne(index, ["AB1234", None])

    assert resultat == (Decimal("0.9000"), None)


def test_confiances_ligne_aucune_ligne_ne_contient_aucune_valeur() -> None:
    contenu = "rien ici\nni là"
    index = indexer_confiance(
        {
            "pages": [
                {
                    "markdown": "",
                    "tables": [
                        {
                            "content": contenu,
                            "word_confidence_scores": [_mot(contenu, "rien", 0.9)],
                        }
                    ],
                }
            ]
        }
    )

    resultat = confiances_ligne(index, ["AB1234", "999,99"])

    assert resultat == (Decimal("0"), Decimal("0"))


def test_confiances_ligne_index_indisponible_renvoie_none_partout() -> None:
    index = indexer_confiance({"pages": [{"markdown": "AB1234 4"}]})

    resultat = confiances_ligne(index, ["AB1234", "4"])

    assert resultat == (None, None)


# --------------------------------------------------------------------------
# confiance_min_pages
# --------------------------------------------------------------------------


def test_confiance_min_pages_minimum_des_pages() -> None:
    reponse = {
        "pages": [
            {"confidence_scores": {"minimum_page_confidence_score": 0.91}},
            {"confidence_scores": {"minimum_page_confidence_score": 0.42}},
        ]
    }

    assert confiance_min_pages(reponse) == Decimal("0.4200")


def test_confiance_min_pages_sans_scores_renvoie_none() -> None:
    assert confiance_min_pages({"pages": [{"markdown": "rien"}]}) is None
    assert confiance_min_pages({}) is None


def test_confiance_min_pages_ignore_les_valeurs_non_finies_sans_lever() -> None:
    reponse = {
        "pages": [
            {"confidence_scores": {"minimum_page_confidence_score": float("nan")}},
            {"confidence_scores": {"minimum_page_confidence_score": float("inf")}},
            {"confidence_scores": {"minimum_page_confidence_score": float("-inf")}},
        ]
    }

    assert confiance_min_pages(reponse) is None


# --------------------------------------------------------------------------
# Sur la réponse Mistral OCR inventée (constat 3) : toutes les valeurs de
# l'annotation ont une confiance haute.
# --------------------------------------------------------------------------

_SEUIL_TEST = Decimal("0.5")

_CHAMPS_ENTETE = (
    "type_bon",
    "fournisseur",
    "agence_fournisseur",
    "siret",
    "tva_intracommunautaire",
    "numero",
    "date_doc",
    "chantier_brut",
    "numero_commande",
    "enleve_par",
    "total_ht",
    "total_tva",
    "total_ttc",
)


def _charger_bl_synthetique() -> tuple[dict[str, Any], dict[str, Any]]:
    reponse: dict[str, Any] = json.loads(
        (_DONNEES / "bl_synthetique.mistral-ocr.json").read_text(encoding="utf-8")
    )
    annotation: dict[str, Any] = json.loads(reponse["document_annotation"])
    return reponse, annotation


def test_bl_synthetique_toutes_les_valeurs_entete_ont_une_confiance_haute() -> None:
    reponse, annotation = _charger_bl_synthetique()
    index = indexer_confiance(reponse)

    for champ in _CHAMPS_ENTETE:
        valeur = annotation[champ]
        confiance = confiance_valeur(index, valeur)
        assert confiance is not None and confiance > _SEUIL_TEST, (champ, confiance)


def test_bl_synthetique_toutes_les_lignes_ont_une_confiance_haute() -> None:
    reponse, annotation = _charger_bl_synthetique()
    index = indexer_confiance(reponse)

    for ligne in annotation["lignes"]:
        valeurs = [
            ligne["code"],
            ligne["designation"],
            ligne["quantite"],
            ligne["unite"],
            ligne["pu_ht"],
            ligne["montant_ht"],
        ]
        confiances = confiances_ligne(index, valeurs)
        assert all(c is not None and c > _SEUIL_TEST for c in confiances), (
            ligne["code"],
            confiances,
        )
