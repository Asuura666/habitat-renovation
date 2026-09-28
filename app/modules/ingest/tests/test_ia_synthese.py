"""Tests de `ingest/ia_synthese.py` (T4, phase 4 IA) : semaine (heure de
Paris), texte envoyé à l'IA (pur), synthèse hebdomadaire, vue de l'accueil et
cochage des actions. Base de test réelle (`bl_test`), aucun appel réseau
(`httpx.MockTransport`, même mécanique que `ingest/tests/test_opencode.py`) ;
toutes les données (commentaires, fournisseurs, auteurs, chantiers) sont
entièrement inventées."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest import ia_synthese, opencode
from app.modules.ingest.ia_synthese import (
    ActionIntrouvable,
    BonLie,
    ResultatSynthese,
    _CommentaireEnvoye,
    _texte_synthese,
    derniere_semaine_complete,
    generer_synthese,
    marquer_action,
    semaine_de,
    vue_accueil,
)
from app.modules.ingest.models import (
    Chantier,
    Commentaire,
    Document,
    Fournisseur,
    Journal,
    SyntheseAction,
    SyntheseCommentaires,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

# Lundi inventé, réutilisé par toute la suite (21/09/2026 est un vrai lundi,
# mais la date elle-même est arbitraire).
_LUNDI = date(2026, 9, 21)


# --------------------------------------------------------------------------
# Réglages IA (même idiome que `test_opencode.py`)
# --------------------------------------------------------------------------


class _SettingsIAFake:
    """Substitut minimal de `Settings` (mêmes attributs que `_SettingsIAFake`
    de `test_opencode.py`, non réimporté d'un autre fichier de tests)."""

    def __init__(
        self,
        *,
        ia_active: bool = True,
        opencode_url: str | None = "https://opencode-synthese.test",
        opencode_mot_de_passe: str | None = "mdp-invente-synthese",
        ia_appels_max_jour: int = 40,
    ) -> None:
        self.ia_active = ia_active
        self.opencode_url = opencode_url
        self.opencode_mot_de_passe = (
            SecretStr(opencode_mot_de_passe)
            if opencode_mot_de_passe is not None
            else None
        )
        self.ia_appels_max_jour = ia_appels_max_jour


@pytest.fixture(autouse=True)
def _ia_active_par_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    """IA allumée par défaut pour ce fichier (le défaut réel de l'application
    est éteinte) -- les tests dédiés à l'extinction/au plafond l'écrasent
    localement avec le même idiome."""
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())


# --------------------------------------------------------------------------
# Données de test (entièrement inventées)
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    session: AsyncSession, *, nom: str = "Fournisseur Synthese Invente"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    session.add(fournisseur)
    await session.flush()
    return fournisseur


async def _creer_document(
    session: AsyncSession,
    *,
    fournisseur: Fournisseur | None,
    numero: str | None = "BL-SYNTHESE-1",
    chantier_id: uuid.UUID | None = None,
    chantier_brut: str | None = None,
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-synthese-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        numero=numero,
        chantier_id=chantier_id,
        chantier_brut=chantier_brut,
    )
    session.add(document)
    await session.flush()
    return document


async def _creer_commentaire(
    session: AsyncSession,
    document: Document,
    *,
    texte: str,
    created_at: datetime,
    ligne_libelle: str = "Ligne inventée",
    auteur_id: uuid.UUID | None = None,
) -> Commentaire:
    commentaire = Commentaire(
        document_id=document.id,
        ligne_id=None,
        ligne_libelle=ligne_libelle,
        auteur_id=auteur_id,
        texte=texte,
        created_at=created_at,
    )
    session.add(commentaire)
    await session.flush()
    return commentaire


def _paris(jour: date, heure_: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure_, minute), tzinfo=FUSEAU_PARIS)


# --------------------------------------------------------------------------
# Faux transport OpenCode (même mécanique que `test_opencode.py`, non
# réimportée d'un autre fichier de tests)
# --------------------------------------------------------------------------


def _handler_json(
    reponses: dict[tuple[str, str], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        cle = (request.method, request.url.path)
        if cle not in reponses:
            raise AssertionError(f"requête inattendue : {request.method} {request.url}")
        return reponses[cle]

    return handler


def _info_minimal(**overrides: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": "msg_synthese_1",
        "sessionID": "ses_synthese_1",
        "role": "assistant",
        "time": {"created": 1, "completed": 2},
        "parentID": "msg_synthese_0",
        "modelID": "modele-synthese-invente",
        "providerID": "fournisseur-synthese-invente",
        "mode": "habitat-synthese",
        "agent": "habitat-synthese",
        "path": {"cwd": "/", "root": "/"},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
    }
    info.update(overrides)
    return info


def _reponses_ok(structured: dict[str, Any]) -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(structured=structured)
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_synthese_1"}),
        ("POST", "/session/ses_synthese_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_synthese_1"): httpx.Response(200, json=True),
    }


def _reponses_erreur(
    erreur_info: dict[str, Any],
) -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(error=erreur_info)
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_synthese_1"}),
        ("POST", "/session/ses_synthese_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_synthese_1"): httpx.Response(200, json=True),
    }


def _aucune_requete(request: httpx.Request) -> httpx.Response:
    raise AssertionError(
        f"aucune requête ne doit être faite : {request.method} {request.url}"
    )


# --------------------------------------------------------------------------
# semaine_de / derniere_semaine_complete (purs)
# --------------------------------------------------------------------------


def test_semaine_de_lundi_et_dimanche() -> None:
    assert semaine_de(date(2026, 9, 24)) == (date(2026, 9, 21), date(2026, 9, 27))
    assert semaine_de(_LUNDI) == (date(2026, 9, 21), date(2026, 9, 27))
    assert semaine_de(date(2026, 9, 27)) == (date(2026, 9, 21), date(2026, 9, 27))


def test_derniere_semaine_complete_heure_de_paris() -> None:
    # Mardi 29/09/2026 10h UTC (12h à Paris, CEST) -> semaine précédente = 21/09.
    assert derniere_semaine_complete(datetime(2026, 9, 29, 10, 0, tzinfo=UTC)) == date(
        2026, 9, 21
    )
    # Dimanche 20/09/2026 23h30 UTC = lundi 21/09 01h30 à Paris (CEST) : déjà
    # dans la semaine du 21/09, donc la dernière semaine *complète* est celle
    # d'avant (14/09).
    assert derniere_semaine_complete(datetime(2026, 9, 20, 23, 30, tzinfo=UTC)) == date(
        2026, 9, 14
    )


# --------------------------------------------------------------------------
# _texte_synthese (pur)
# --------------------------------------------------------------------------


def test_texte_synthese_consigne_puis_lignes_dans_lordre() -> None:
    commentaires = (
        _CommentaireEnvoye(
            reference="c1",
            jour=date(2026, 9, 21),
            fournisseur="Fournisseur Un Invente",
            numero_bon="BL-1",
            ligne_libelle="Sable 0/4",
            texte="Livraison incomplète, il manque deux sacs.",
        ),
        _CommentaireEnvoye(
            reference="c2",
            jour=date(2026, 9, 23),
            fournisseur="fournisseur inconnu",
            numero_bon=None,
            ligne_libelle="Ligne 1",
            texte="Palette abîmée à la réception.",
        ),
    )

    texte = _texte_synthese(commentaires, nb_total=2)
    lignes = texte.splitlines()

    assert lignes[0] == ia_synthese._CONSIGNE_SYNTHESE
    assert lignes[1] == (
        "[c1] lundi 21/09 — Fournisseur Un Invente — bon BL-1 — "
        "ligne « Sable 0/4 » : Livraison incomplète, il manque deux sacs."
    )
    assert lignes[2] == (
        "[c2] mercredi 23/09 — fournisseur inconnu — bon inconnu — "
        "ligne « Ligne 1 » : Palette abîmée à la réception."
    )
    assert len(lignes) == 3  # pas de phrase de troncature ici


def test_texte_synthese_troncature_mentionnee_si_nb_total_superieur() -> None:
    commentaires = (
        _CommentaireEnvoye(
            reference="c1",
            jour=date(2026, 9, 21),
            fournisseur="F",
            numero_bon="1",
            ligne_libelle="L",
            texte="T",
        ),
    )

    texte = _texte_synthese(commentaires, nb_total=250)

    assert "250 commentaires cette semaine ; les 1 plus récents ci-dessous." in texte


# --------------------------------------------------------------------------
# generer_synthese
# --------------------------------------------------------------------------


async def test_generer_synthese_semaine_vide_aucune_requete(
    db_session: AsyncSession,
) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(
        statut="vide", semaine_debut=_LUNDI, nb_commentaires=0
    )

    synthese = (
        await db_session.execute(
            select(SyntheseCommentaires).where(
                SyntheseCommentaires.semaine_debut == _LUNDI
            )
        )
    ).scalar_one()
    assert synthese.statut == "vide"
    assert synthese.resume == "Aucun commentaire cette semaine."
    assert synthese.nb_commentaires == 0

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.action == "synthese_generee")
        )
    ).scalar_one()
    assert journal.utilisateur_id is None
    assert journal.apres == {
        "semaine_debut": _LUNDI.isoformat(),
        "semaine_fin": (_LUNDI + timedelta(days=6)).isoformat(),
        "statut": "vide",
        "nb_commentaires": 0,
        "nb_actions": 0,
    }


async def test_generer_synthese_ia_eteinte_rien_ecrit_meme_semaine_vide(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_active=False)
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(statut="ia_eteinte", semaine_debut=_LUNDI)
    syntheses = (await db_session.execute(select(SyntheseCommentaires))).scalars().all()
    assert syntheses == []


async def test_generer_synthese_nominale_actions_document_ids_et_journal(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Menuiserie Duval Invente")
    document = await _creer_document(
        db_session, fournisseur=fournisseur, numero="BL-4821"
    )
    commentaire_1 = await _creer_commentaire(
        db_session,
        document,
        texte="Retard de livraison de trois jours, client mécontent.",
        ligne_libelle="Portes intérieures",
        created_at=_paris(_LUNDI, 0, 30),
    )
    await _creer_commentaire(
        db_session,
        document,
        texte="Quantité livrée correcte, rien à signaler.",
        ligne_libelle="Charnières",
        created_at=_paris(_LUNDI + timedelta(days=1), 10),
    )
    await db_session.commit()

    structured = {
        "resume": "Une livraison en retard signalée, le reste conforme.",
        "actions": [
            {
                "texte": "Relancer le fournisseur sur le retard de livraison.",
                "commentaires": ["c1"],
            }
        ],
    }
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(
        statut="creee", semaine_debut=_LUNDI, nb_commentaires=2, nb_actions=1
    )

    synthese = (
        await db_session.execute(
            select(SyntheseCommentaires).where(
                SyntheseCommentaires.semaine_debut == _LUNDI
            )
        )
    ).scalar_one()
    assert synthese.statut == "ok"
    assert synthese.resume == structured["resume"]
    assert synthese.nb_commentaires == 2
    assert synthese.modele == "fournisseur-synthese-invente/modele-synthese-invente"

    actions = (
        (
            await db_session.execute(
                select(SyntheseAction).where(SyntheseAction.synthese_id == synthese.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(actions) == 1
    assert actions[0].ordre == 1
    assert actions[0].texte == "Relancer le fournisseur sur le retard de livraison."
    assert actions[0].commentaire_ids == [str(commentaire_1.id)]
    assert actions[0].document_ids == [str(document.id)]
    assert actions[0].faite_le is None
    assert actions[0].faite_par is None

    journal = (
        await db_session.execute(
            select(Journal)
            .where(Journal.action == "synthese_generee")
            .where(Journal.cible_id == str(synthese.id))
        )
    ).scalar_one()
    assert journal.utilisateur_id is None
    assert journal.apres == {
        "semaine_debut": _LUNDI.isoformat(),
        "semaine_fin": (_LUNDI + timedelta(days=6)).isoformat(),
        "statut": "ok",
        "nb_commentaires": 2,
        "nb_actions": 1,
    }


async def test_generer_synthese_texte_envoye_sans_auteur_ni_chantier_ni_client(
    db_session: AsyncSession,
) -> None:
    """Vérifié directement sur le corps reçu par le faux transport (brief
    T4) : ni le nom de l'auteur, ni le nom/l'identifiant du chantier, ni le
    client ne doivent jamais apparaître dans le texte envoyé à l'IA."""
    auteur = Utilisateur(
        email="auteur.distinctif@example.invalid",
        nom="Prenom Auteur Ultra Distinctif Invente",
        role="agent",
        is_active=True,
    )
    db_session.add(auteur)
    await db_session.flush()

    chantier = Chantier(
        nom_canonique="Chantier Super Distinctif Invente",
        client="Client Hyper Distinctif Invente",
        actif=True,
    )
    db_session.add(chantier)
    await db_session.flush()

    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Texte Invente")
    document = await _creer_document(
        db_session,
        fournisseur=fournisseur,
        numero="BL-TEXTE-1",
        chantier_id=chantier.id,
        chantier_brut="Nom De Chantier Tel Que Lu Sur Le Bon Invente",
    )
    await _creer_commentaire(
        db_session,
        document,
        texte="Livraison correcte, aucune anomalie constatée.",
        ligne_libelle="Ligne texte",
        created_at=_paris(_LUNDI, 9),
        auteur_id=auteur.id,
    )
    await db_session.commit()

    requetes: list[httpx.Request] = []
    structured = {"resume": "Résumé texte.", "actions": []}

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(_reponses_ok(structured))(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)
    assert resultat.statut == "creee"

    corps_message = json.loads(requetes[1].content)
    texte_envoye = corps_message["parts"][0]["text"]

    for valeur_interdite in (
        auteur.nom,
        auteur.email,
        chantier.nom_canonique,
        chantier.client,
        document.chantier_brut,
        str(auteur.id),
        str(chantier.id),
        str(document.id),
    ):
        assert valeur_interdite is not None
        assert valeur_interdite not in texte_envoye

    # Le fournisseur et le numéro du bon, eux, sont bien envoyés (§4.2).
    assert "Fournisseur Texte Invente" in texte_envoye
    assert "BL-TEXTE-1" in texte_envoye


async def test_generer_synthese_bornes_semaine_heure_de_paris(
    db_session: AsyncSession,
) -> None:
    """Un commentaire du dimanche 23h30 heure de Paris (dernier jour de la
    semaine) est compté ; un commentaire du lundi suivant 00h30 heure de
    Paris (première minute de la semaine d'après) ne l'est pas."""
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(db_session, fournisseur=fournisseur)
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire du dimanche soir, dans la semaine.",
        created_at=_paris(_LUNDI + timedelta(days=6), 23, 30),
    )
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire du lundi suivant, hors semaine.",
        created_at=_paris(_LUNDI + timedelta(days=7), 0, 30),
    )
    await db_session.commit()

    structured = {"resume": "Résumé bornes.", "actions": []}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat.statut == "creee"
    assert resultat.nb_commentaires == 1


async def test_generer_synthese_troncature_garde_les_plus_recents(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ia_synthese, "_COMMENTAIRES_MAX", 2)
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(db_session, fournisseur=fournisseur)
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire le plus ancien, doit être écarté.",
        created_at=_paris(_LUNDI, 8),
    )
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire du milieu.",
        created_at=_paris(_LUNDI, 9),
    )
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire le plus récent.",
        created_at=_paris(_LUNDI, 10),
    )
    await db_session.commit()

    requetes: list[httpx.Request] = []
    structured = {"resume": "Résumé troncature.", "actions": []}

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(_reponses_ok(structured))(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat.statut == "creee"
    assert resultat.nb_commentaires == 3  # compte réel, malgré la troncature

    texte_envoye = json.loads(requetes[1].content)["parts"][0]["text"]
    assert (
        "3 commentaires cette semaine ; les 2 plus récents ci-dessous." in texte_envoye
    )
    assert "Commentaire le plus ancien, doit être écarté." not in texte_envoye
    assert "Commentaire du milieu." in texte_envoye
    assert "Commentaire le plus récent." in texte_envoye


async def test_generer_synthese_deja_faite_aucune_requete(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        SyntheseCommentaires(
            semaine_debut=_LUNDI,
            semaine_fin=_LUNDI + timedelta(days=6),
            statut="vide",
            resume="Aucun commentaire cette semaine.",
            nb_commentaires=0,
            modele=None,
        )
    )
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(statut="deja_faite", semaine_debut=_LUNDI)


async def test_generer_synthese_semaine_debut_pas_lundi_value_error(
    db_session: AsyncSession,
) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    with pytest.raises(ValueError, match="lundi"):
        await generer_synthese(db_session, http, semaine_debut=date(2026, 9, 22))


async def test_generer_synthese_erreur_ia_rien_ecrit(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(db_session, fournisseur=fournisseur)
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire déclenchant un échec IA.",
        created_at=_paris(_LUNDI, 9),
    )
    await db_session.commit()

    erreur_info = {
        "name": "ProviderAuthError",
        "data": {
            "providerID": "fournisseur-invente",
            "message": "abonnement déconnecté (inventé)",
        },
    }
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_erreur(erreur_info)))
    )

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(
        statut="echec", semaine_debut=_LUNDI, erreur="ProviderAuthError"
    )
    syntheses = (await db_session.execute(select(SyntheseCommentaires))).scalars().all()
    assert syntheses == []


async def test_generer_synthese_reponse_invalide_rien_ecrit(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(db_session, fournisseur=fournisseur)
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire avec réponse invalide.",
        created_at=_paris(_LUNDI, 9),
    )
    await db_session.commit()

    structured = {"resume": "", "actions": []}  # résumé vide -> ReponseIAInvalide
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(
        statut="echec", semaine_debut=_LUNDI, erreur="reponse_invalide"
    )
    syntheses = (await db_session.execute(select(SyntheseCommentaires))).scalars().all()
    assert syntheses == []


async def test_generer_synthese_plafond_rien_ecrit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(db_session, fournisseur=fournisseur)
    await _creer_commentaire(
        db_session,
        document,
        texte="Commentaire avec plafond atteint.",
        created_at=_paris(_LUNDI, 9),
    )
    await db_session.commit()

    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_appels_max_jour=0)
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    resultat = await generer_synthese(db_session, http, semaine_debut=_LUNDI)

    assert resultat == ResultatSynthese(
        statut="echec", semaine_debut=_LUNDI, erreur="plafond"
    )
    syntheses = (await db_session.execute(select(SyntheseCommentaires))).scalars().all()
    assert syntheses == []


# --------------------------------------------------------------------------
# vue_accueil
# --------------------------------------------------------------------------


async def test_vue_accueil_derniere_encore_a_faire_bon_supprime(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document_1 = await _creer_document(
        db_session, fournisseur=fournisseur, numero="BL-VUE-1"
    )
    document_2 = await _creer_document(
        db_session, fournisseur=fournisseur, numero="BL-VUE-2"
    )
    commentaire_1 = await _creer_commentaire(
        db_session, document_1, texte="C1", created_at=_paris(_LUNDI, 9)
    )
    commentaire_2 = await _creer_commentaire(
        db_session, document_2, texte="C2", created_at=_paris(_LUNDI, 10)
    )

    admin = Utilisateur(
        email="admin.vue@example.invalid",
        nom="Admin Vue Invente",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    await db_session.flush()

    semaine_precedente = _LUNDI - timedelta(days=7)
    synthese_precedente = SyntheseCommentaires(
        semaine_debut=semaine_precedente,
        semaine_fin=semaine_precedente + timedelta(days=6),
        statut="ok",
        resume="Résumé précédent.",
        nb_commentaires=1,
        modele="modele-invente",
    )
    db_session.add(synthese_precedente)
    await db_session.flush()

    action_faite_precedente = SyntheseAction(
        synthese_id=synthese_precedente.id,
        ordre=1,
        texte="Action déjà faite (semaine précédente).",
        commentaire_ids=[str(commentaire_1.id)],
        document_ids=[str(document_1.id)],
        faite_le=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        faite_par=admin.id,
    )
    action_encore_a_faire_bon_supprime = SyntheseAction(
        synthese_id=synthese_precedente.id,
        ordre=2,
        texte="Action encore à faire, bon supprimé.",
        commentaire_ids=[str(commentaire_2.id)],
        document_ids=[str(uuid.uuid4())],  # bon inexistant -- « supprimé »
        faite_le=None,
        faite_par=None,
    )
    db_session.add_all([action_faite_precedente, action_encore_a_faire_bon_supprime])

    synthese_derniere = SyntheseCommentaires(
        semaine_debut=_LUNDI,
        semaine_fin=_LUNDI + timedelta(days=6),
        statut="ok",
        resume="Résumé dernière.",
        nb_commentaires=2,
        modele="modele-invente",
    )
    db_session.add(synthese_derniere)
    await db_session.flush()

    action_derniere_non_faite = SyntheseAction(
        synthese_id=synthese_derniere.id,
        ordre=1,
        texte="Action de la dernière synthèse, non faite.",
        commentaire_ids=[str(commentaire_1.id), str(commentaire_2.id)],
        document_ids=[str(document_1.id), str(document_2.id)],
        faite_le=None,
        faite_par=None,
    )
    db_session.add(action_derniere_non_faite)
    await db_session.commit()

    accueil = await vue_accueil(db_session)

    assert accueil.ia_active is True
    assert accueil.derniere is not None
    assert accueil.derniere.id == synthese_derniere.id
    assert accueil.derniere.semaine_debut == _LUNDI
    assert len(accueil.derniere.actions) == 1
    assert accueil.derniere.actions[0].id == action_derniere_non_faite.id
    assert accueil.derniere.actions[0].bons == (
        BonLie(document_id=document_1.id, numero="BL-VUE-1"),
        BonLie(document_id=document_2.id, numero="BL-VUE-2"),
    )

    # Une seule action « encore à faire » : celle, non faite, de la synthèse
    # *précédente* -- l'action non faite de `derniere` n'y figure pas (déjà
    # rendue dans `derniere.actions`), et l'action déjà faite non plus.
    assert len(accueil.encore_a_faire) == 1
    action_vue = accueil.encore_a_faire[0]
    assert action_vue.id == action_encore_a_faire_bon_supprime.id
    assert action_vue.texte == "Action encore à faire, bon supprimé."
    assert action_vue.semaine_debut == semaine_precedente
    assert action_vue.faite_le is None
    assert action_vue.faite_par is None
    assert action_vue.bons == ()  # le document référencé n'existe pas


async def test_vue_accueil_sans_synthese(db_session: AsyncSession) -> None:
    accueil = await vue_accueil(db_session)

    assert accueil.derniere is None
    assert accueil.encore_a_faire == ()


# --------------------------------------------------------------------------
# marquer_action
# --------------------------------------------------------------------------


async def test_marquer_action_coche_decoche_idempotence_journal(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(
        db_session, fournisseur=fournisseur, numero="BL-MARQUER-1"
    )
    commentaire = await _creer_commentaire(
        db_session, document, texte="Commentaire marquer.", created_at=_paris(_LUNDI, 9)
    )
    synthese = SyntheseCommentaires(
        semaine_debut=_LUNDI,
        semaine_fin=_LUNDI + timedelta(days=6),
        statut="ok",
        resume="Résumé marquer.",
        nb_commentaires=1,
        modele=None,
    )
    db_session.add(synthese)
    await db_session.flush()
    action = SyntheseAction(
        synthese_id=synthese.id,
        ordre=1,
        texte="Action à cocher.",
        commentaire_ids=[str(commentaire.id)],
        document_ids=[str(document.id)],
    )
    db_session.add(action)

    admin = Utilisateur(
        email="admin.marquer@example.invalid",
        nom="Admin Marquer Invente",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    await db_session.commit()

    action_cochee = await marquer_action(
        db_session, action.id, faite=True, utilisateur_id=admin.id
    )
    assert action_cochee.faite_le is not None
    assert action_cochee.faite_par == "Admin Marquer Invente"
    assert action_cochee.bons == (
        BonLie(document_id=document.id, numero="BL-MARQUER-1"),
    )

    journal_faite = (
        await db_session.execute(
            select(Journal).where(Journal.action == "synthese_action_faite")
        )
    ).scalar_one()
    assert journal_faite.utilisateur_id == admin.id
    assert journal_faite.cible_table == "synthese_action"
    assert journal_faite.cible_id == str(action.id)
    assert journal_faite.apres == {
        "texte": "Action à cocher.",
        "semaine_debut": _LUNDI.isoformat(),
    }

    # Idempotence : recocher une action déjà faite -> rien de nouveau.
    await marquer_action(db_session, action.id, faite=True, utilisateur_id=admin.id)
    journaux_faite = (
        (
            await db_session.execute(
                select(Journal).where(Journal.action == "synthese_action_faite")
            )
        )
        .scalars()
        .all()
    )
    assert len(journaux_faite) == 1

    action_decochee = await marquer_action(
        db_session, action.id, faite=False, utilisateur_id=admin.id
    )
    assert action_decochee.faite_le is None
    assert action_decochee.faite_par is None

    journal_a_faire = (
        await db_session.execute(
            select(Journal).where(Journal.action == "synthese_action_a_faire")
        )
    ).scalar_one()
    assert journal_a_faire.utilisateur_id == admin.id

    # Idempotence sur « à faire » aussi.
    await marquer_action(db_session, action.id, faite=False, utilisateur_id=admin.id)
    journaux_a_faire = (
        (
            await db_session.execute(
                select(Journal).where(Journal.action == "synthese_action_a_faire")
            )
        )
        .scalars()
        .all()
    )
    assert len(journaux_a_faire) == 1


async def test_marquer_action_inconnue(db_session: AsyncSession) -> None:
    with pytest.raises(ActionIntrouvable):
        await marquer_action(
            db_session, uuid.uuid4(), faite=True, utilisateur_id=uuid.uuid4()
        )
