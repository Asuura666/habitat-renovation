from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import commun
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


# ---------------------------------------------------------------------------
# Masquage des réglages d'un contrôle désactivé côté serveur : quand un
# contrôle est désactivé, ses réglages propres n'apparaissent plus du tout
# (au lieu de la mention affichée jusqu'ici par l'écran Réglages) --
# `app/modules/ingest/tests/conftest.py::_controle_prix_actif_par_defaut`
# réenclenche les deux drapeaux par défaut pour tout ce paquet, chaque test
# ci-dessous qui veut un drapeau désactivé l'écrase localement, même idiome
# que `test_controle_prix.py::_regler_controle_prix`.
# ---------------------------------------------------------------------------


def _regler_controles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prix_actif: bool,
    livre_non_facture_actif: bool,
) -> None:
    class _SettingsInventee:
        controle_prix_actif = prix_actif
        controle_livre_non_facture_actif = livre_non_facture_actif

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


async def test_lister_parametres_masque_les_seuils_de_prix_quand_desactives(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=True)

    cles = {p.cle for p in await lister_parametres(db_session)}

    assert cles == {
        "tolerance_total_ht",
        "delai_ligne_bl_non_facturee_j",
        "delai_alias_non_resolu_h",
        "delai_confirmation_bl_h",
        "delai_chantier_silencieux_j",
        "duree_ignorance_j",
    }


async def test_lister_parametres_masque_le_seuil_r06_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=False)

    cles = {p.cle for p in await lister_parametres(db_session)}

    assert "delai_ligne_bl_non_facturee_j" not in cles
    assert cles == {
        "tolerance_total_ht",
        "seuil_prix_pct",
        "seuil_prix_fort_pct",
        "occurrences_prix_min",
        "delai_alias_non_resolu_h",
        "delai_confirmation_bl_h",
        "delai_chantier_silencieux_j",
        "duree_ignorance_j",
    }


async def test_lister_parametres_toutes_les_cles_quand_les_deux_controles_actifs(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=True)

    assert len(await lister_parametres(db_session)) == 9


@pytest.mark.parametrize(
    "cle",
    ["seuil_prix_pct", "seuil_prix_fort_pct", "occurrences_prix_min"],
)
async def test_modifier_parametre_refuse_un_seuil_de_prix_masque_comme_inconnu(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    cle: str,
) -> None:
    _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=True)

    with pytest.raises(ValueError, match="Paramètre inconnu"):
        await modifier_parametre(db_session, cle, "9", auteur_id=None)


async def test_modifier_parametre_refuse_le_seuil_r06_masque_comme_inconnu(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=False)

    with pytest.raises(ValueError, match="Paramètre inconnu"):
        await modifier_parametre(
            db_session, "delai_ligne_bl_non_facturee_j", "60", auteur_id=None
        )


async def test_valeur_d_un_reglage_masque_est_conservee_et_reapparait_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rien n'est supprimé en base par le masquage : une valeur posée avant
    la désactivation reste inchangée pendant qu'elle est masquée, et
    réapparaît telle quelle dès la réactivation du contrôle."""
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=True)
    await modifier_parametre(db_session, "seuil_prix_pct", "12", auteur_id=None)

    _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=True)
    cles_masquees = {p.cle for p in await lister_parametres(db_session)}
    assert "seuil_prix_pct" not in cles_masquees
    with pytest.raises(ValueError, match="Paramètre inconnu"):
        await modifier_parametre(db_session, "seuil_prix_pct", "20", auteur_id=None)

    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=True)
    reactive = next(
        p for p in await lister_parametres(db_session) if p.cle == "seuil_prix_pct"
    )
    assert reactive.valeur == "12"


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
