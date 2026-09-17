"""Tests de `apparier_lignes` (`appariement.py`, L4-D6, L4-T6).

Deux passes (code puis désignation), une ligne de BL consommée une seule
fois, ordre de sortie = ordre des lignes de facture reçues. Données
inventées."""

from __future__ import annotations

import uuid

from app.modules.normalize.appariement import (
    Appariement,
    LigneAApparier,
    apparier_lignes,
)


def _uuids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def test_apparier_par_code_normalise() -> None:
    fact_cle, bl_cle = _uuids(2)
    ligne_facture = LigneAApparier(cle=fact_cle, code="AB-1234", designation="Colle")
    ligne_bl = LigneAApparier(cle=bl_cle, code="ab 1234", designation="Colle exemple")

    resultat = apparier_lignes([ligne_facture], [ligne_bl])

    assert resultat == (
        Appariement(cle_facture=fact_cle, cle_bl=bl_cle, methode="code"),
    )


def test_apparier_par_libelle_quand_code_absent_ou_different() -> None:
    fact_cle, bl_cle = _uuids(2)
    ligne_facture = LigneAApparier(cle=fact_cle, code=None, designation="Seau de colle")
    ligne_bl = LigneAApparier(cle=bl_cle, code="ZZ9999", designation="Seau de Colle")

    resultat = apparier_lignes([ligne_facture], [ligne_bl])

    assert resultat == (
        Appariement(cle_facture=fact_cle, cle_bl=bl_cle, methode="libelle"),
    )


def test_apparier_doublons_de_code_chacun_apparie_une_fois() -> None:
    """Deux lignes de facture et deux lignes de BL portant le même code :
    chaque ligne de BL n'est consommée qu'une seule fois, dans l'ordre."""
    fact_1, fact_2, bl_1, bl_2 = _uuids(4)
    lignes_facture = [
        LigneAApparier(cle=fact_1, code="AB1234", designation="Colle A"),
        LigneAApparier(cle=fact_2, code="AB1234", designation="Colle B"),
    ]
    lignes_bl = [
        LigneAApparier(cle=bl_1, code="AB1234", designation="Colle A"),
        LigneAApparier(cle=bl_2, code="AB1234", designation="Colle B"),
    ]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (
        Appariement(cle_facture=fact_1, cle_bl=bl_1, methode="code"),
        Appariement(cle_facture=fact_2, cle_bl=bl_2, methode="code"),
    )


def test_apparier_passe_libelle_ne_vole_pas_une_ligne_bl_deja_appariee_par_code() -> (
    None
):
    """Fix round 1 : une ligne de BL déjà consommée par la passe code ne
    doit jamais être reprise par la passe désignation, même si sa
    désignation correspond à une autre ligne de facture restée sans
    correspondance."""
    fact_1, fact_2, bl_1 = _uuids(3)
    lignes_facture = [
        LigneAApparier(cle=fact_1, code="AB1234", designation="Colle"),
        LigneAApparier(cle=fact_2, code=None, designation="Colle"),
    ]
    lignes_bl = [LigneAApparier(cle=bl_1, code="AB1234", designation="Colle")]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (
        Appariement(cle_facture=fact_1, cle_bl=bl_1, methode="code"),
        Appariement(cle_facture=fact_2, cle_bl=None, methode=None),
    )


def test_apparier_ligne_facture_en_trop_sans_correspondance() -> None:
    fact_1, fact_2, bl_1 = _uuids(3)
    lignes_facture = [
        LigneAApparier(cle=fact_1, code="AB1234", designation="Colle"),
        LigneAApparier(cle=fact_2, code="ZZ0000", designation="Article introuvable"),
    ]
    lignes_bl = [LigneAApparier(cle=bl_1, code="AB1234", designation="Colle")]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (
        Appariement(cle_facture=fact_1, cle_bl=bl_1, methode="code"),
        Appariement(cle_facture=fact_2, cle_bl=None, methode=None),
    )


def test_apparier_ligne_bl_en_trop_est_ignoree() -> None:
    """Une ligne de BL sans facture correspondante ne produit rien : la
    sortie ne compte qu'une entrée par ligne de facture (L4-T7 s'occupera
    des lignes de BL non facturées, R14)."""
    fact_1, bl_1, bl_2 = _uuids(3)
    lignes_facture = [LigneAApparier(cle=fact_1, code="AB1234", designation="Colle")]
    lignes_bl = [
        LigneAApparier(cle=bl_1, code="AB1234", designation="Colle"),
        LigneAApparier(cle=bl_2, code="ZZ0000", designation="Autre article"),
    ]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (Appariement(cle_facture=fact_1, cle_bl=bl_1, methode="code"),)


def test_apparier_ordre_de_sortie_suit_lordre_des_lignes_de_facture() -> None:
    fact_1, fact_2, bl_1, bl_2 = _uuids(4)
    lignes_facture = [
        LigneAApparier(cle=fact_2, code="ZZ9999", designation="Deuxième"),
        LigneAApparier(cle=fact_1, code="AB1234", designation="Première"),
    ]
    lignes_bl = [
        LigneAApparier(cle=bl_1, code="AB1234", designation="Première"),
        LigneAApparier(cle=bl_2, code="ZZ9999", designation="Deuxième"),
    ]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (
        Appariement(cle_facture=fact_2, cle_bl=bl_2, methode="code"),
        Appariement(cle_facture=fact_1, cle_bl=bl_1, methode="code"),
    )


def test_apparier_code_absent_des_deux_cotes_tente_le_libelle() -> None:
    fact_1, bl_1 = _uuids(2)
    lignes_facture = [
        LigneAApparier(cle=fact_1, code=None, designation="Plaque de plâtre")
    ]
    lignes_bl = [LigneAApparier(cle=bl_1, code=None, designation="plaque de platre")]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (
        Appariement(cle_facture=fact_1, cle_bl=bl_1, methode="libelle"),
    )


def test_apparier_cle_vide_napparie_personne() -> None:
    """Un code ou une désignation qui se normalise en chaîne vide (ex.
    ponctuation seule) ne peut apparier personne, même une autre ligne dont
    la clé est également vide."""
    fact_1, bl_1 = _uuids(2)
    lignes_facture = [LigneAApparier(cle=fact_1, code="---", designation="...")]
    lignes_bl = [LigneAApparier(cle=bl_1, code="///", designation="!!!")]

    resultat = apparier_lignes(lignes_facture, lignes_bl)

    assert resultat == (Appariement(cle_facture=fact_1, cle_bl=None, methode=None),)


def test_apparier_aucune_ligne_de_bl_renvoie_tout_sans_correspondance() -> None:
    fact_1 = uuid.uuid4()
    lignes_facture = [LigneAApparier(cle=fact_1, code="AB1234", designation="Colle")]

    resultat = apparier_lignes(lignes_facture, [])

    assert resultat == (Appariement(cle_facture=fact_1, cle_bl=None, methode=None),)


def test_apparier_aucune_ligne_de_facture_renvoie_tuple_vide() -> None:
    bl_1 = uuid.uuid4()
    lignes_bl = [LigneAApparier(cle=bl_1, code="AB1234", designation="Colle")]

    resultat = apparier_lignes([], lignes_bl)

    assert resultat == ()
