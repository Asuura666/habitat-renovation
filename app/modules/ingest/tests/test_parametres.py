from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import Journal, Utilisateur
from app.modules.ingest.parametres import lister_parametres, modifier_parametre
from app.modules.ingest.rapprochement import _charger_parametres

pytestmark = pytest.mark.anyio


async def test_lister_parametres_retourne_les_neuf_cles_et_leurs_bornes(
    db_session: AsyncSession,
) -> None:
    parametres = await lister_parametres(db_session)

    assert len(parametres) == 9
    tolerance = next(p for p in parametres if p.cle == "tolerance_total_ht")
    assert tolerance.valeur == "0.05"
    assert tolerance.libelle == "Tolérance sur le total HT"
    assert tolerance.unite == "€"
    assert tolerance.minimum == "0"
    assert tolerance.maximum == "1000"


async def test_modifier_parametre_refuse_une_cle_inconnue(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="Paramètre inconnu"):
        await modifier_parametre(
            db_session,
            "cle_inconnue",
            "12",
            auteur_id=None,
        )


@pytest.mark.parametrize("valeur", ["-0.01", "1000.01", "NaN"])
async def test_modifier_parametre_refuse_une_valeur_hors_bornes(
    db_session: AsyncSession,
    valeur: str,
) -> None:
    with pytest.raises(ValueError):
        await modifier_parametre(
            db_session,
            "tolerance_total_ht",
            valeur,
            auteur_id=None,
        )


async def test_modifier_parametre_refuse_un_decimal_pour_un_entier(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="entier"):
        await modifier_parametre(
            db_session,
            "occurrences_prix_min",
            "2.5",
            auteur_id=None,
        )


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [("seuil_prix_pct", "20"), ("seuil_prix_fort_pct", "4")],
)
async def test_modifier_parametre_preserve_ordre_des_seuils_de_prix(
    db_session: AsyncSession,
    cle: str,
    valeur: str,
) -> None:
    with pytest.raises(ValueError, match="inférieur ou égal"):
        await modifier_parametre(db_session, cle, valeur, auteur_id=None)


async def test_modifier_parametre_refuse_une_precision_demestrielle(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="six décimales"):
        await modifier_parametre(
            db_session,
            "tolerance_total_ht",
            "1e-10000",
            auteur_id=None,
        )


async def test_modifier_parametre_journalise_avant_et_apres(
    db_session: AsyncSession,
) -> None:
    auteur = Utilisateur(email="admin.reglages@example.test", role="admin")
    db_session.add(auteur)
    await db_session.flush()

    resultat = await modifier_parametre(
        db_session,
        "seuil_prix_pct",
        "7.50",
        auteur_id=auteur.id,
    )

    assert resultat.valeur == "7.5"
    entree = (
        await db_session.execute(
            select(Journal).where(Journal.action == "parametre_modifie")
        )
    ).scalar_one()
    assert entree.utilisateur_id == auteur.id
    assert entree.cible_table == "parametre"
    assert entree.cible_id == "seuil_prix_pct"
    assert entree.avant == {"valeur": "5"}
    assert entree.apres == {"valeur": "7.5"}


async def test_valeur_modifiee_est_relue_par_le_rapprochement(
    db_session: AsyncSession,
) -> None:
    await modifier_parametre(
        db_session,
        "seuil_prix_pct",
        "8.25",
        auteur_id=None,
    )

    parametres = await _charger_parametres(db_session)

    assert str(parametres.seuil_prix_pct) == "8.25"


def test_libelles_des_reglages_en_francais_courant() -> None:
    """Revue finale de la refonte du front (constat COUVERTURE-9) : les
    libellés et unités affichés par l'écran Réglages ne portent ni
    « occurrence » (jargon, déjà refusé dans les phrases des problèmes) ni
    « anomalie » (« problème » partout ailleurs dans l'application)."""
    from app.modules.ingest.parametres import DEFINITIONS_PARAMETRES

    for definition in DEFINITIONS_PARAMETRES:
        for texte in (definition.libelle, definition.unite):
            assert "occurrence" not in texte.lower(), definition.cle
            assert "anomalie" not in texte.lower(), definition.cle
