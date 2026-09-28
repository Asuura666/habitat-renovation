"""Table unique des catégories de problèmes (revue finale de la refonte du
front, constat SERVEUR-3) : `ingest.anomalies.CATEGORIES_REGLE` fonde à la
fois l'état d'un chantier (`ingest.tableau_de_bord`), le montant « en écart »
du bilan (`ingest.bilan.REGLES_QUANTITE_OU_PRIX`) et les filtres de l'écran
« À régler » (champ `categorie` de l'API). Tests purs, sans base."""

from __future__ import annotations

from typing import get_args

from app.modules.ingest.anomalies import (
    CATEGORIES_REGLE,
    Categorie,
    categorie_regle,
    regles_de_categorie,
)
from app.modules.ingest.bilan import REGLES_BL_MANQUANT, REGLES_QUANTITE_OU_PRIX
from app.modules.rules.engine import (
    REGLES_CHANTIER,
    REGLES_FACTURE,
    REGLES_PRIX_BL,
    REGLES_SUIVI,
)


def test_prix_et_quantites_valent_exactement_l_ancien_perimetre_en_ecart() -> None:
    """`en_ecart` (L5-T1, définition monétaire en attente de validation par
    Ilane) ne change pas *en pratique* : R03 à R09 restent les seules
    règles de cette famille qui portent un `bloc_id` (la requête du bilan
    ne retient que celui-ci, `ingest/bilan.py`). R19 à R25 (phase 3, prix
    des bons) rejoignent techniquement la catégorie « prix » (spec §6.5) et
    élargissent donc `REGLES_QUANTITE_OU_PRIX`, mais ne posent jamais
    `bloc_id` : elles ne peuvent jamais alimenter `en_ecart`."""
    attendu_facture = {"R03", "R04", "R05", "R06", "R07", "R08", "R09"}
    attendu = attendu_facture | REGLES_PRIX_BL
    assert set(REGLES_QUANTITE_OU_PRIX) == attendu
    assert regles_de_categorie("prix") | regles_de_categorie("quantites") == attendu


def test_bon_manquant_vaut_r01_et_r02() -> None:
    assert set(REGLES_BL_MANQUANT) == {"R01", "R02"}


def test_toute_regle_du_moteur_a_une_categorie_connue() -> None:
    """`REGLES_CHANTIER` (avenant du 27/09/2026, R18) et `REGLES_PRIX_BL`
    (phase 3, R19-R25) rejoignent l'union bien qu'`evaluer_chantier` et
    `evaluer_prix_bl` ne soient pas encore appelées par `ingest` : chacune a
    déjà sa catégorie (`CATEGORIES_REGLE`, voir ci-dessus)."""
    categories_connues = set(get_args(Categorie))
    regles_moteur = (
        set(REGLES_FACTURE)
        | set(REGLES_SUIVI)
        | set(REGLES_CHANTIER)
        | set(REGLES_PRIX_BL)
    )
    assert set(CATEGORIES_REGLE) <= regles_moteur
    for regle in regles_moteur:
        assert categorie_regle(regle) in categories_connues, regle


def test_regle_inconnue_tombe_dans_autre() -> None:
    assert categorie_regle("R99") == "autre"
    for regle in ("R10", "R11", "R12", "R13", "R15", "R16", "R17"):
        assert categorie_regle(regle) == "autre", regle
    assert categorie_regle("R14") == "rattacher"
    assert categorie_regle("R18") == "rattacher"


def test_r19_a_r25_valent_prix() -> None:
    for regle in ("R19", "R20", "R21", "R22", "R23", "R24", "R25"):
        assert categorie_regle(regle) == "prix", regle
