"""Tests de `decomposer_chantier`, `reconnaitre_chantier` et
`decider_chantier` (`chantier.py`, L3-D6, avenant du 27/09/2026)."""

from __future__ import annotations

import uuid

import pytest

from app.modules.normalize.chantier import (
    Correspondance,
    DecisionChantier,
    EtatCorrespondance,
    LibelleChantier,
    NomConnu,
    SourceNom,
    TypeDecision,
    correspondance_exacte,
    decider_chantier,
    decomposer_chantier,
    nom_pour_creation,
    reconnaitre_chantier,
)

A = uuid.UUID(int=1)
B = uuid.UUID(int=2)
C = uuid.UUID(int=3)


def test_decomposer_chantier_retire_prefixe_et_extrait_le_code() -> None:
    assert decomposer_chantier("Chantier : Maison Test (99-001)") == LibelleChantier(
        libelle="maison test", code="99-001"
    )


def test_decomposer_chantier_sans_prefixe_ni_code() -> None:
    assert decomposer_chantier("Maison Test") == LibelleChantier(
        libelle="maison test", code=None
    )


def test_decomposer_chantier_prefixe_sans_espace_avant_les_deux_points() -> None:
    assert decomposer_chantier("Chantier: Maison Test") == LibelleChantier(
        libelle="maison test", code=None
    )


def test_decomposer_chantier_prefixe_majuscules_sans_deux_points() -> None:
    assert decomposer_chantier("CHANTIER Maison Test") == LibelleChantier(
        libelle="maison test", code=None
    )


def test_decomposer_chantier_prefixe_est_un_mot_entier() -> None:
    """« Chantiers » (pluriel) n'est pas le mot « chantier » : le préfixe ne
    doit pas être retiré (fix round 1, finding 2)."""
    assert decomposer_chantier("Chantiers Réunis") == LibelleChantier(
        libelle="chantiers reunis", code=None
    )


def test_decomposer_chantier_parentheses_au_milieu_non_retirees() -> None:
    assert decomposer_chantier("Maison (Test) Dupont") == LibelleChantier(
        libelle="maison test dupont", code=None
    )


def test_decomposer_chantier_accents_et_casse() -> None:
    assert decomposer_chantier("Chantier : Résidence Été") == LibelleChantier(
        libelle="residence ete", code=None
    )


def test_decomposer_chantier_libelle_vide_renvoie_none() -> None:
    assert decomposer_chantier("(99-001)") is None


def test_decomposer_chantier_none_renvoie_none() -> None:
    assert decomposer_chantier(None) is None


def test_correspondance_exacte_reconnu_a_100() -> None:
    """Alias exact déjà rattaché chez ce fournisseur : reconnu à 100 sans
    comparaison de ressemblance (comportement actuel conservé, spec §2.2)."""
    assert correspondance_exacte(
        "Chantier : VILLA TEST (99887766)", A
    ) == Correspondance(
        EtatCorrespondance.RECONNU, libelle="villa test", chantier_id=A, score=100
    )


def test_correspondance_exacte_brut_vide_libelle_none() -> None:
    assert correspondance_exacte("(99887766)", A) == Correspondance(
        EtatCorrespondance.RECONNU, libelle=None, chantier_id=A, score=100
    )


def test_reconnaitre_vide() -> None:
    assert (
        reconnaitre_chantier("  ", [NomConnu(A, "Villa Test")], 90).etat
        is EtatCorrespondance.VIDE
    )
    assert (
        reconnaitre_chantier("(12345)", [NomConnu(A, "Villa Test")], 90).etat
        is EtatCorrespondance.VIDE
    )


def test_reconnaitre_au_seuil_exact() -> None:
    noms = [NomConnu(A, "Villa test")]
    assert (
        reconnaitre_chantier("Villa tes", noms, 94).etat is EtatCorrespondance.RECONNU
    )
    assert (
        reconnaitre_chantier("Villa tes", noms, 95).etat is EtatCorrespondance.INCONNU
    )


def test_reconnaitre_ignore_code_et_prefixe() -> None:
    c = reconnaitre_chantier(
        "Chantier : VILLA TEST (99887766)", [NomConnu(A, "Villa Test")], 90
    )
    assert (
        c.etat is EtatCorrespondance.RECONNU and c.chantier_id == A and c.score == 100
    )


def test_reconnaitre_meilleur_nom_du_chantier() -> None:
    noms = [NomConnu(A, "Villa Test"), NomConnu(A, "vt nord"), NomConnu(B, "Tilleuls")]
    c = reconnaitre_chantier("VT NORD", noms, 90)
    assert c.chantier_id == A


def test_reconnaitre_egalite_entre_deux_chantiers_est_ambigue() -> None:
    noms = [NomConnu(A, "Residence les Pins 1"), NomConnu(B, "Residence les Pins 2")]
    c = reconnaitre_chantier("Residence les Pins", noms, 90)
    assert c.etat is EtatCorrespondance.AMBIGU
    assert c.candidats == tuple(sorted((A, B), key=str))


def test_reconnaitre_meme_chantier_deux_noms_egaux_reste_reconnu() -> None:
    noms = [NomConnu(A, "Villa Test"), NomConnu(A, "VILLA TEST")]
    assert (
        reconnaitre_chantier("villa test", noms, 90).etat is EtatCorrespondance.RECONNU
    )


def test_nom_pour_creation_retire_code_et_prefixe() -> None:
    assert nom_pour_creation("  Chantier : VILLA TEST (99887766) ") == "VILLA TEST"
    assert nom_pour_creation("(99887766)") is None
    assert nom_pour_creation(None) is None


def reconnu(x: uuid.UUID) -> Correspondance:
    return Correspondance(
        EtatCorrespondance.RECONNU, libelle="x", chantier_id=x, score=95
    )


def ambigu(*xs: uuid.UUID) -> Correspondance:
    return Correspondance(
        EtatCorrespondance.AMBIGU, libelle="x", score=95, candidats=xs
    )


def inconnu() -> Correspondance:
    return Correspondance(EtatCorrespondance.INCONNU, libelle="x")


def vide() -> Correspondance:
    return Correspondance(EtatCorrespondance.VIDE)


def test_lu_reconnu_legende_vide_rattache_nom_lu() -> None:
    d = decider_chantier(reconnu(A), vide())
    assert d == DecisionChantier(
        TypeDecision.RATTACHER, chantier_id=A, source=SourceNom.NOM_LU, apprendre=True
    )


def test_legende_bavarde_ignoree_si_nom_lu_reconnu() -> None:
    assert decider_chantier(reconnu(A), inconnu()).chantier_id == A


def test_lu_et_legende_meme_chantier() -> None:
    assert decider_chantier(reconnu(A), reconnu(A)).type is TypeDecision.RATTACHER


def test_lu_reconnu_legende_ambigue_contenant_lu() -> None:
    assert decider_chantier(reconnu(A), ambigu(A, B)).chantier_id == A


def test_lu_reconnu_legende_autre_chantier_alerte() -> None:
    d = decider_chantier(reconnu(A), reconnu(B))
    assert d.type is TypeDecision.ALERTE and d.candidats == (A, B)


def test_lu_reconnu_legende_ambigue_sans_lu_alerte() -> None:
    assert decider_chantier(reconnu(A), ambigu(B, C)).candidats == (A, B, C)


def test_lu_ambigu_alerte_avec_legende_reconnue() -> None:
    assert decider_chantier(ambigu(A, B), reconnu(C)).candidats == (A, B, C)


def test_lu_ambigu_legende_parmi_candidats_sans_doublon() -> None:
    assert decider_chantier(ambigu(A, B), reconnu(B)).candidats == (A, B)


def test_lu_inconnu_legende_reconnue_rattache_legende_et_apprend() -> None:
    d = decider_chantier(inconnu(), reconnu(B))
    assert d == DecisionChantier(
        TypeDecision.RATTACHER, chantier_id=B, source=SourceNom.LEGENDE, apprendre=True
    )


def test_lu_inconnu_sans_legende_cree_depuis_nom_lu() -> None:
    assert decider_chantier(inconnu(), vide()) == DecisionChantier(
        TypeDecision.CREER, source=SourceNom.NOM_LU, apprendre=True
    )
    assert decider_chantier(inconnu(), inconnu()).type is TypeDecision.CREER


def test_lu_inconnu_legende_ambigue_alerte() -> None:
    assert decider_chantier(inconnu(), ambigu(A, B)).candidats == (A, B)


def test_lu_vide_legende_reconnue_rattache_sans_apprendre() -> None:
    assert decider_chantier(vide(), reconnu(B)) == DecisionChantier(
        TypeDecision.RATTACHER, chantier_id=B, source=SourceNom.LEGENDE, apprendre=False
    )


def test_lu_vide_legende_inconnue_cree_depuis_legende() -> None:
    assert decider_chantier(vide(), inconnu()) == DecisionChantier(
        TypeDecision.CREER, source=SourceNom.LEGENDE, apprendre=False
    )


def test_lu_vide_legende_ambigue_alerte() -> None:
    assert decider_chantier(vide(), ambigu(A, B)).type is TypeDecision.ALERTE


def test_rien_du_tout_aucun() -> None:
    assert decider_chantier(vide(), vide()).type is TypeDecision.AUCUN


# --- B-05 : jamais de rattachement automatique si seuls les nombres diffèrent ---


def test_reconnaitre_noms_ne_differant_que_par_un_nombre_a_confirmer() -> None:
    paires = [
        ("Lot 13", "Lot 12"),
        ("Résidence Les Pins 3", "Résidence Les Pins 2"),
        ("Bât A 4", "Bât A 3"),
        ("Résidence Les Tilleuls 13", "Résidence Les Tilleuls 12"),
    ]
    for lu, connu in paires:
        # seuil bas : quelle que soit la ressemblance, jamais RECONNU
        c = reconnaitre_chantier(lu, [NomConnu(A, connu)], 50)
        assert c.etat is EtatCorrespondance.AMBIGU, (lu, connu)
        assert c.chantier_id is None and c.candidats == (A,)
    c = reconnaitre_chantier(
        "Résidence Les Tilleuls 13", [NomConnu(A, "Résidence Les Tilleuls 12")], 90
    )
    assert c.etat is EtatCorrespondance.AMBIGU and c.candidats == (A,)


def test_reconnaitre_meme_nombre_toujours_rattache() -> None:
    for lu, connu in [
        ("VILLA TEST", "Villa Test"),
        ("lot 12", "Lot 12"),
        ("Bât. A - 3", "bat a 3"),
    ]:
        c = reconnaitre_chantier(lu, [NomConnu(A, connu)], 90)
        assert c.etat is EtatCorrespondance.RECONNU and c.chantier_id == A


def test_reconnaitre_le_bon_chantier_gagne_sur_le_voisin_numerote() -> None:
    noms = [
        NomConnu(A, "Résidence Les Tilleuls 12"),
        NomConnu(B, "Résidence Les Tilleuls 13"),
    ]
    c = reconnaitre_chantier("Résidence Les Tilleuls 13", noms, 90)
    assert c.etat is EtatCorrespondance.RECONNU and c.chantier_id == B


def test_reconnaitre_voisin_numerote_sous_le_seuil_reste_inconnu() -> None:
    c = reconnaitre_chantier("Lot 13", [NomConnu(A, "Lot 12")], 90)
    assert c.etat is EtatCorrespondance.INCONNU


def test_reconnaitre_nom_sans_nombre_inchange() -> None:
    c = reconnaitre_chantier("villa tes", [NomConnu(A, "Villa test")], 94)
    assert c.etat is EtatCorrespondance.RECONNU and c.chantier_id == A


# --- B-05 (tour 1) : légende voisine numérotée ---


def test_reconnaitre_voisin_numerote_est_signale() -> None:
    voisin = reconnaitre_chantier("Lot 13", [NomConnu(A, "Lot 12")], 50)
    assert voisin.etat is EtatCorrespondance.AMBIGU and voisin.voisin_numerote is True
    ex_aequo = reconnaitre_chantier(
        "Residence les Pins",
        [NomConnu(A, "Residence les Pins"), NomConnu(B, "residence les pins")],
        90,
    )
    assert ex_aequo.etat is EtatCorrespondance.AMBIGU
    assert ex_aequo.voisin_numerote is False


def test_lu_reconnu_legende_voisine_numerotee_alerte_sans_apprendre() -> None:
    lu = Correspondance(
        EtatCorrespondance.RECONNU, libelle="lot 12", chantier_id=A, score=100
    )
    legende = Correspondance(
        EtatCorrespondance.AMBIGU,
        libelle="lot 13",
        score=96,
        candidats=(A,),
        voisin_numerote=True,
    )
    d = decider_chantier(lu, legende)
    assert d.type is TypeDecision.ALERTE
    assert d.candidats == (A,) and d.apprendre is False


def test_lu_reconnu_legende_ex_aequo_contenant_lu_rattache_toujours() -> None:
    lu = Correspondance(
        EtatCorrespondance.RECONNU, libelle="x", chantier_id=A, score=100
    )
    legende = Correspondance(
        EtatCorrespondance.AMBIGU, libelle="x", score=100, candidats=(A, B)
    )
    assert decider_chantier(lu, legende).type is TypeDecision.RATTACHER


# --------------------------------------------------------------------------
# reference_utilisable (lot 2 du 31/10/2026, A4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    ["KAYRE", "LA CROIX", "CAMBUS", "SAINT GEORGES", "  Saint-Georges  "],
)
def test_reference_utilisable_pour_un_nom_de_chantier(reference: str) -> None:
    from app.modules.normalize.chantier import reference_utilisable

    assert reference_utilisable(reference, ["Loris Legras", "Fred Martin"]) is True


@pytest.mark.parametrize(
    "reference",
    [None, "", "   ", "AB", "1089390591", "12 A", "LORIS", "loris legras", "Frédéric"],
)
def test_reference_inutilisable(reference: str | None) -> None:
    from app.modules.normalize.chantier import reference_utilisable

    noms = ["Loris Legras", "Frédéric Dupont"]
    assert reference_utilisable(reference, noms) is False


def test_reference_dont_un_mot_n_est_pas_dans_un_compte_reste_utilisable() -> None:
    from app.modules.normalize.chantier import reference_utilisable

    assert reference_utilisable("LORIS CAMBUS", ["Loris Legras"]) is True


def test_reference_sans_aucun_compte() -> None:
    from app.modules.normalize.chantier import reference_utilisable

    assert reference_utilisable("KAYRE", []) is True
