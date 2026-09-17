"""Tests de R14 — chantier non résolu (CDC §5, L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.modules.rules.modeles import AliasEnAttenteControle, Gravite, Parametres
from app.modules.rules.rules.R14 import R14


def _alias(**overrides: Any) -> AliasEnAttenteControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "libelle": "CHANTIER ALIAS INVENTE",
        "fournisseur": "FOURNISSEUR INVENTE",
        "cree_le": datetime(2026, 6, 1, 8, 0),
    }
    base.update(overrides)
    return AliasEnAttenteControle(**base)


def test_R14_alias_non_valide_apres_le_delai_produit_une_anomalie_moyenne() -> None:
    alias = _alias(cree_le=datetime(2026, 6, 1, 8, 0))
    aujourdhui = alias.cree_le + timedelta(hours=49)

    anomalie = R14(alias, aujourdhui, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R14"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.document_id is None
    assert anomalie.bloc_id is None
    assert anomalie.ligne_id is None
    assert anomalie.article_id is None
    assert anomalie.chantier_id is None
    assert anomalie.alias_id == alias.id
    assert anomalie.detail == {
        "libelle": "CHANTIER ALIAS INVENTE",
        "fournisseur": "FOURNISSEUR INVENTE",
        "heures": "49",
    }
    assert anomalie.detail  # jamais vide


def test_R14_deux_alias_distincts_portent_des_alias_id_distincts() -> None:
    """Ruling du contrôleur (fix round 1, trouvé par la revue) : sans
    `alias_id`, deux alias en attente distincts partageraient la même
    identité `("R14", None, None, None)` une fois persistés (L4-T11)."""
    alias_1 = _alias()
    alias_2 = _alias(id=uuid.uuid4(), libelle="AUTRE ALIAS")
    aujourdhui = alias_1.cree_le + timedelta(hours=49)

    anomalie_1 = R14(alias_1, aujourdhui, Parametres())
    anomalie_2 = R14(alias_2, aujourdhui, Parametres())

    assert anomalie_1 is not None
    assert anomalie_2 is not None
    assert anomalie_1.alias_id == alias_1.id
    assert anomalie_2.alias_id == alias_2.id
    assert anomalie_1.alias_id != anomalie_2.alias_id


def test_R14_exactement_au_delai_ne_produit_rien() -> None:
    alias = _alias()
    aujourdhui = alias.cree_le + timedelta(hours=48)

    assert R14(alias, aujourdhui, Parametres()) is None


def test_R14_avant_le_delai_ne_produit_rien() -> None:
    alias = _alias()
    aujourdhui = alias.cree_le + timedelta(hours=10)

    assert R14(alias, aujourdhui, Parametres()) is None


def test_R14_delai_personnalise() -> None:
    parametres = Parametres(delai_alias_non_resolu_h=6)
    alias = _alias()
    aujourdhui = alias.cree_le + timedelta(hours=7)

    assert R14(alias, aujourdhui, parametres) is not None
