"""Tests de la résolution fournisseur/agence (`fournisseur.py`, L3-D8)."""

from __future__ import annotations

import uuid

from app.modules.normalize.fournisseur import (
    AgenceRef,
    FournisseurRef,
    MethodeFournisseur,
    ResolutionFournisseur,
    normaliser_siret,
    normaliser_tva,
    resoudre_agence,
    resoudre_fournisseur,
)

# --------------------------------------------------------------------------
# normaliser_siret / normaliser_tva
# --------------------------------------------------------------------------


def test_normaliser_siret_accepte_14_chiffres_avec_espaces() -> None:
    assert normaliser_siret("111 222 333 00011") == "11122233300011"


def test_normaliser_siret_accepte_9_chiffres_siren() -> None:
    assert normaliser_siret("111 222 333") == "111222333"


def test_normaliser_siret_longueur_invalide_renvoie_none() -> None:
    assert normaliser_siret("12345") is None


def test_normaliser_siret_none_renvoie_none() -> None:
    assert normaliser_siret(None) is None


def test_normaliser_tva_majuscules_sans_espaces_ni_points() -> None:
    assert normaliser_tva("fr. 12 345678901") == "FR12345678901"


def test_normaliser_tva_format_invalide_renvoie_none() -> None:
    assert normaliser_tva("1234FR") is None


# --------------------------------------------------------------------------
# resoudre_fournisseur
# --------------------------------------------------------------------------

_ID_PEINTURES = uuid.uuid4()
_ID_NUANCES = uuid.uuid4()


def _referentiel() -> tuple[FournisseurRef, ...]:
    return (
        FournisseurRef(
            id=_ID_PEINTURES,
            nom="Peintures Exemple",
            siret="11122233300011",
            tva="FR11122233344",
            aliases=(),
        ),
        FournisseurRef(
            id=_ID_NUANCES,
            nom="Nuances Exemple",
            siret="99988877700022",
            tva="FR99988877700",
            aliases=("Nuances Exemple Toulouse",),
        ),
    )


def test_resoudre_fournisseur_par_siret() -> None:
    resolution = resoudre_fournisseur(
        siret="111 222 333 00011", tva=None, nom=None, referentiel=_referentiel()
    )
    assert resolution == ResolutionFournisseur(_ID_PEINTURES, MethodeFournisseur.SIRET)


def test_resoudre_fournisseur_siren_commun_a_deux_agences_du_meme_fournisseur() -> None:
    """Deux agences (SIRET différent, même SIREN) d'un même fournisseur : le
    résultat -- le fournisseur, pas la ligne -- reste unique (L3-D8)."""
    referentiel = (
        FournisseurRef(
            id=_ID_PEINTURES,
            nom="Peintures Exemple",
            siret="11122233300011",
            tva=None,
            aliases=(),
        ),
        FournisseurRef(
            id=_ID_PEINTURES,
            nom="Peintures Exemple",
            siret="11122233300029",
            tva=None,
            aliases=(),
        ),
    )
    resolution = resoudre_fournisseur(
        siret="111222333", tva=None, nom=None, referentiel=referentiel
    )
    assert resolution == ResolutionFournisseur(_ID_PEINTURES, MethodeFournisseur.SIRET)


def test_resoudre_fournisseur_deux_references_au_meme_siren_passe_a_la_tva() -> None:
    """Deux fournisseurs distincts partagent le même SIREN : l'étape SIRET
    est ambiguë, on retombe sur la TVA."""
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    referentiel = (
        FournisseurRef(
            id=id_a,
            nom="Fournisseur A",
            siret="11122233300011",
            tva="FR10000000001",
            aliases=(),
        ),
        FournisseurRef(
            id=id_b,
            nom="Fournisseur B",
            siret="11122233300099",
            tva="FR20000000002",
            aliases=(),
        ),
    )
    resolution = resoudre_fournisseur(
        siret="111222333", tva="FR20000000002", nom=None, referentiel=referentiel
    )
    assert resolution == ResolutionFournisseur(id_b, MethodeFournisseur.TVA)


def test_resoudre_fournisseur_par_nom_via_alias() -> None:
    resolution = resoudre_fournisseur(
        siret=None, tva=None, nom="NUANCES EXEMPLE TOULOUSE", referentiel=_referentiel()
    )
    assert resolution == ResolutionFournisseur(_ID_NUANCES, MethodeFournisseur.NOM)


def test_resoudre_fournisseur_nom_insensible_aux_accents_et_a_la_casse() -> None:
    resolution = resoudre_fournisseur(
        siret=None, tva=None, nom="nuances éxemple", referentiel=_referentiel()
    )
    assert resolution == ResolutionFournisseur(_ID_NUANCES, MethodeFournisseur.NOM)


def test_resoudre_fournisseur_nom_ambigu_non_resolu() -> None:
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    referentiel = (
        FournisseurRef(
            id=id_a, nom="Peintures Exemple", siret=None, tva=None, aliases=()
        ),
        FournisseurRef(id=id_b, nom="Peintures Sud", siret=None, tva=None, aliases=()),
    )
    resolution = resoudre_fournisseur(
        siret=None, tva=None, nom="Peintures Exemple Sud", referentiel=referentiel
    )
    assert resolution == ResolutionFournisseur(None, None)


def test_resoudre_fournisseur_aucune_correspondance() -> None:
    resolution = resoudre_fournisseur(
        siret=None, tva=None, nom="Fournisseur Inconnu", referentiel=_referentiel()
    )
    assert resolution == ResolutionFournisseur(None, None)


# --------------------------------------------------------------------------
# resoudre_agence
# --------------------------------------------------------------------------


def test_resoudre_agence_resout_par_mots_inclus() -> None:
    id_toulouse = uuid.uuid4()
    agences = (
        AgenceRef(id=id_toulouse, nom="Toulouse"),
        AgenceRef(id=uuid.uuid4(), nom="Bordeaux"),
    )
    assert resoudre_agence("Agence de Toulouse Nord", agences) == id_toulouse


def test_resoudre_agence_aucune_correspondance_renvoie_none() -> None:
    agences = (AgenceRef(id=uuid.uuid4(), nom="Toulouse"),)
    assert resoudre_agence("Bordeaux", agences) is None
