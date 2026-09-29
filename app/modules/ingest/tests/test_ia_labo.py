"""Tests de `ingest/ia_labo.py` (tâche LABO, Laboratoire IA) : essais de
bout en bout (trace complète, contrôles, résultat), rien d'enregistré hors
`appel_ia`, IA éteinte, plafond atteint, erreur du fournisseur (trace
`erreur` avec `brut`), borne des 20 essais, extrait tronqué, aucun secret
dans la trace. Base de test réelle (`bl_test`), aucun appel réseau
(`httpx.MockTransport`, même mécanique que `test_opencode.py`) ; toutes les
données (fournisseurs, anomalies, commentaires) sont entièrement inventées.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from fastapi import BackgroundTasks
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest import ia_labo, opencode
from app.modules.ingest.anomalies import AnomalieIntrouvable
from app.modules.ingest.ia_labo import (
    derniers_essais,
    journal_appels,
    lancer_essai_explication,
    lancer_essai_prix,
    lancer_essai_synthese,
    lire_essai,
)
from app.modules.ingest.models import (
    Anomalie,
    AppelIA,
    Commentaire,
    Document,
    ExplicationAlerte,
    Fournisseur,
    Journal,
    PrixInternet,
    SyntheseAction,
    SyntheseCommentaires,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

MDP_INVENTE = "mdp-opencode-invente-pour-le-labo"
URL_INVENTEE = "https://opencode-labo.test"


class _SettingsIAFake:
    def __init__(
        self,
        *,
        ia_active: bool = True,
        opencode_url: str | None = URL_INVENTEE,
        opencode_mot_de_passe: str | None = MDP_INVENTE,
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
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())


@pytest.fixture(autouse=True)
def _vider_essais() -> None:
    """Le registre en mémoire de `ia_labo` est un module-level (voulu, brief
    LABO) : vidé avant chaque test pour ne jamais dépendre de l'ordre
    d'exécution de la suite."""
    ia_labo._essais.clear()


# --------------------------------------------------------------------------
# Faux transport OpenCode (même mécanique que `test_opencode.py`)
# --------------------------------------------------------------------------


def _info_minimal(**overrides: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": "msg_labo_1",
        "sessionID": "ses_labo_1",
        "role": "assistant",
        "time": {"created": 1, "completed": 2},
        "parentID": "msg_labo_0",
        "modelID": "modele-labo-invente",
        "providerID": "fournisseur-labo-invente",
        "mode": "habitat-prix",
        "agent": "habitat-prix",
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


def _partie_outil(
    *, id_partie: str, outil: str, entree: dict[str, Any], output: str
) -> dict[str, Any]:
    return {
        "id": id_partie,
        "sessionID": "ses_labo_1",
        "messageID": "msg_labo_1",
        "type": "tool",
        "callID": f"call_{id_partie}",
        "tool": outil,
        "state": {"status": "completed", "input": entree, "output": output},
    }


def _handler_json(
    reponses: dict[tuple[str, str], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        cle = (request.method, request.url.path)
        if cle not in reponses:
            raise AssertionError(f"requête inattendue : {request.method} {request.url}")
        return reponses[cle]

    return handler


def _reponses_session(
    structured: Any, parts: list[dict[str, Any]] | None = None
) -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(structured=structured)
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_labo_1"}),
        ("POST", "/session/ses_labo_1/message"): httpx.Response(
            200, json={"info": info, "parts": parts or []}
        ),
        ("DELETE", "/session/ses_labo_1"): httpx.Response(200, json=True),
    }


async def _compter(session: AsyncSession, modele: type) -> int:
    return (
        await session.execute(select(func.count()).select_from(modele))
    ).scalar_one()


async def _executer(background_tasks: BackgroundTasks) -> None:
    """Exécute la tâche de fond tout de suite (même principe qu'un vrai
    appel HTTP, où Starlette exécute les tâches de fond juste après avoir
    envoyé la réponse) -- déterministe, sans polling ni délai dans les
    tests."""
    await background_tasks()


# --------------------------------------------------------------------------
# Essai : prix internet -- bout en bout
# --------------------------------------------------------------------------


async def test_essai_prix_bout_en_bout_trouve(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    reponses = _reponses_session(
        {
            "statut": "trouve",
            "produit_trouve": "Ciment CEM II 25kg",
            "prix": 12.34,
            "devise": "EUR",
            "taxes": "TTC",
            "unite": "sac",
            "conditionnement": "25kg",
            "source_url": "https://fournisseur.test/ciment",
            "confiance": "moyenne",
            "raison": "",
        },
        parts=[
            _partie_outil(
                id_partie="prt_1",
                outil="webfetch",
                entree={"url": "https://fournisseur.test/ciment"},
                output="Ciment 25kg à 12,34 € TTC.",
            )
        ],
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur="Point P",
        designation="Ciment CEM II 25kg",
        code="CIM25",
        unite="sac",
    )
    trace_en_cours = lire_essai(essai_id)
    assert trace_en_cours is not None
    assert trace_en_cours.statut == "en_cours"
    assert trace_en_cours.type == "prix"
    assert "Ciment CEM II 25kg" in trace_en_cours.texte_envoye
    assert "Point P" in trace_en_cours.texte_envoye
    # Jamais le prix du bon dans le texte envoyé (§6.2 : recherche non
    # orientée) -- pas de `prix_bon` transmis à `lancer_essai_prix` de toute
    # façon, mais on vérifie qu'aucun montant n'apparaît par accident.

    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "fini"
    assert trace.erreur is None
    assert trace.modele == "fournisseur-labo-invente/modele-labo-invente"
    assert trace.fin is not None
    assert trace.duree_ms is not None and trace.duree_ms >= 0
    assert len(trace.outils) == 1
    assert trace.outils[0].outil == "webfetch"
    assert trace.outils[0].adresse == "https://fournisseur.test/ciment"
    assert trace.reponse_brute["info"]["structured"]["statut"] == "trouve"
    assert len(trace.controles) == 4
    assert all(controle.ok for controle in trace.controles)
    assert trace.resultat == {
        "statut": "trouve",
        "prix": "12.3400",
        "devise": "EUR",
        "taxes": "TTC",
        "unite": "sac",
        "conditionnement": "25kg",
        "produit_trouve": "Ciment CEM II 25kg",
        "source_url": "https://fournisseur.test/ciment",
        "confiance": "moyenne",
        "raison": None,
    }
    assert trace.appels_restants == 39  # plafond par défaut (40) - 1 appel


async def test_essai_prix_rien_enregistre_hors_appel_ia(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    reponses = _reponses_session(
        {"statut": "prix_non_verifiable", "raison": "aucun résultat"}
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    avant = {
        modele: await _compter(db_session, modele)
        for modele in (
            PrixInternet,
            ExplicationAlerte,
            SyntheseCommentaires,
            SyntheseAction,
            Journal,
            Anomalie,
        )
    }

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit inventé",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)
    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "fini"
    assert trace.resultat is not None and trace.resultat["statut"] == "non_verifiable"

    apres = {
        modele: await _compter(db_session, modele)
        for modele in (
            PrixInternet,
            ExplicationAlerte,
            SyntheseCommentaires,
            SyntheseAction,
            Journal,
            Anomalie,
        )
    }
    assert avant == apres  # aucune table métier touchée par l'essai


async def test_essai_prix_extrait_tronque(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    texte_long = "x" * 5000
    reponses = _reponses_session(
        {
            "statut": "trouve",
            "produit_trouve": "Produit",
            "prix": 1,
            "devise": "EUR",
            "taxes": "HT",
            "unite": "u",
            "conditionnement": "",
            "source_url": "https://fournisseur.test/produit",
            "confiance": "faible",
            "raison": "",
        },
        parts=[
            _partie_outil(
                id_partie="prt_1",
                outil="webfetch",
                entree={"url": "https://fournisseur.test/produit"},
                output=texte_long + " 1,00 €",
            )
        ],
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert len(trace.outils[0].extrait) == 3000


async def test_essai_ia_eteinte_trace_erreur(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_active=False)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête ne doit être faite, IA éteinte")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "eteinte"
    assert "éteinte" in trace.erreur["message_court"]
    assert trace.erreur["brut"] is None

    lignes = (
        await db_session.execute(select(func.count()).select_from(AppelIA))
    ).scalar_one()
    assert lignes == 0


async def test_essai_plafond_atteint_trace_erreur(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_appels_max_jour=1)
    )
    aujourdhui = datetime.now(FUSEAU_PARIS).replace(
        hour=1, minute=0, second=0, microsecond=0
    )
    db_session.add(
        AppelIA(usage="synthese", statut="ok", duree_ms=1, created_at=aujourdhui)
    )
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête ne doit être faite, plafond atteint")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "plafond"
    assert trace.appels_restants == 0


async def test_essai_erreur_fournisseur_trace_avec_brut(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    erreur_info = {
        "name": "ProviderAuthError",
        "data": {
            "providerID": "fournisseur-labo-invente",
            "message": "jeton expiré inventé",
        },
    }
    info = _info_minimal(error=erreur_info)
    reponses = {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_labo_1"}),
        ("POST", "/session/ses_labo_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_labo_1"): httpx.Response(200, json=True),
    }
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "ProviderAuthError"
    assert trace.erreur["brut"] == erreur_info
    assert MDP_INVENTE not in trace.erreur["message_court"]


# --------------------------------------------------------------------------
# Essai : explication d'une alerte prix
# --------------------------------------------------------------------------


async def _creer_anomalie_prix(
    session: AsyncSession, *, regle: str = "R07", detail: dict[str, str] | None = None
) -> Anomalie:
    fournisseur = Fournisseur(nom="Fournisseur Labo Invente")
    session.add(fournisseur)
    await session.flush()
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-labo-invente-{uuid.uuid4()}.pdf",
        fournisseur_id=fournisseur.id,
        numero=f"FA-LABO-{uuid.uuid4().hex[:8]}",
    )
    session.add(document)
    await session.flush()
    detail_effectif = detail or {
        "article": "Sable 0/4",
        "code": "SAB04",
        "pu_facture": "12.50",
        "mediane": "10.00",
        "occurrences": "6",
        "ecart_pct": "25.00",
    }
    anomalie = Anomalie(
        regle=regle,
        gravite="moyenne",
        detail=detail_effectif,
        statut="ouverte",
        document_id=document.id,
    )
    session.add(anomalie)
    await session.commit()
    return anomalie


async def test_essai_explication_bout_en_bout(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    anomalie = await _creer_anomalie_prix(db_session)
    reponses = _reponses_session(
        {"explication": "Prix 12.50, médiane 10.00, écart 25.00 %."}
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_explication(
        sessions_test, http, background_tasks, anomalie.id
    )
    trace_en_cours = lire_essai(essai_id)
    assert trace_en_cours is not None
    assert trace_en_cours.type == "explication"
    assert "Fournisseur Labo Invente" in trace_en_cours.texte_envoye
    assert (
        "Sable 0/4" in trace_en_cours.texte_envoye
        or "Prix un peu plus cher" in trace_en_cours.texte_envoye
    )

    await _executer(background_tasks)
    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "fini"
    assert trace.resultat == {"texte": "Prix 12.50, médiane 10.00, écart 25.00 %."}
    # Un contrôle par nombre écrit dans l'explication.
    assert len(trace.controles) >= 3
    assert all(controle.ok for controle in trace.controles)


async def test_essai_explication_anomalie_inconnue_404(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    background_tasks = BackgroundTasks()

    with pytest.raises(AnomalieIntrouvable):
        await lancer_essai_explication(
            sessions_test, http, background_tasks, uuid.uuid4()
        )


async def test_essai_explication_anomalie_hors_categorie_prix_404(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    anomalie = await _creer_anomalie_prix(
        db_session, regle="R01", detail={"info": "valeur"}
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    background_tasks = BackgroundTasks()

    with pytest.raises(AnomalieIntrouvable):
        await lancer_essai_explication(
            sessions_test, http, background_tasks, anomalie.id
        )


async def test_essai_explication_chiffre_invente_trace_erreur(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    anomalie = await _creer_anomalie_prix(db_session)
    reponses = _reponses_session(
        {"explication": "Le prix facturé de 99,99 est trop élevé."}
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_explication(
        sessions_test, http, background_tasks, anomalie.id
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "reponse_invalide"
    assert trace.resultat is None
    # Le contrôle sur le nombre inventé est bien signalé en échec.
    assert any(not controle.ok for controle in trace.controles)


# --------------------------------------------------------------------------
# Essai : synthèse hebdomadaire
# --------------------------------------------------------------------------

_LUNDI = date(2026, 9, 21)


async def _creer_commentaire(
    session: AsyncSession, document: Document, *, texte: str, created_at: datetime
) -> Commentaire:
    commentaire = Commentaire(
        document_id=document.id,
        ligne_id=None,
        ligne_libelle="Ligne inventée",
        auteur_id=None,
        texte=texte,
        created_at=created_at,
    )
    session.add(commentaire)
    await session.flush()
    return commentaire


async def test_essai_synthese_bout_en_bout(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    fournisseur = Fournisseur(nom="Fournisseur Synthese Labo")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-labo-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
        numero="BL-LABO-1",
    )
    db_session.add(document)
    await db_session.flush()
    await _creer_commentaire(
        db_session,
        document,
        texte="Retard de livraison constaté.",
        created_at=datetime.combine(_LUNDI, time(10, 0), tzinfo=FUSEAU_PARIS),
    )
    await db_session.commit()

    reponses = _reponses_session(
        {
            "resume": "Un retard signalé cette semaine.",
            "actions": [{"texte": "Relancer le fournisseur.", "commentaires": ["c1"]}],
        }
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_synthese(
        sessions_test, http, background_tasks, _LUNDI
    )
    trace_en_cours = lire_essai(essai_id)
    assert trace_en_cours is not None
    assert trace_en_cours.type == "synthese"
    assert "Retard de livraison constaté." in trace_en_cours.texte_envoye
    assert "Fournisseur Synthese Labo" in trace_en_cours.texte_envoye

    await _executer(background_tasks)
    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "fini"
    assert trace.resultat == {
        "resume": "Un retard signalé cette semaine.",
        "actions": [{"texte": "Relancer le fournisseur.", "commentaires": ["c1"]}],
    }

    # Rien n'est enregistré (aucune SyntheseCommentaires/SyntheseAction).
    assert await _compter(db_session, SyntheseCommentaires) == 0
    assert await _compter(db_session, SyntheseAction) == 0


async def test_essai_synthese_semaine_vide_appelle_quand_meme_lia(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    """Contrairement à la production (`generer_synthese`, raccourci « vide »
    sans appel à l'IA), l'essai appelle toujours l'IA -- le but est de voir
    ce qu'elle ferait, y compris sur une semaine sans commentaire."""
    reponses = _reponses_session(
        {"resume": "Aucun commentaire cette semaine.", "actions": []}
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_synthese(
        sessions_test, http, background_tasks, _LUNDI
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "fini"


async def test_essai_synthese_semaine_pas_lundi_422(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    background_tasks = BackgroundTasks()

    with pytest.raises(ValueError, match="lundi"):
        await lancer_essai_synthese(
            sessions_test, http, background_tasks, date(2026, 9, 22)
        )


# --------------------------------------------------------------------------
# Registre en mémoire : borne des 20 essais, lire_essai, derniers_essais
# --------------------------------------------------------------------------


async def test_borne_20_essais_les_plus_anciens_chasses(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    reponses = _reponses_session({"statut": "prix_non_verifiable", "raison": "essai"})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    essai_ids: list[uuid.UUID] = []
    for indice in range(25):
        background_tasks = BackgroundTasks()
        essai_id = await lancer_essai_prix(
            sessions_test,
            http,
            background_tasks,
            fournisseur=None,
            designation=f"Produit {indice}",
            code=None,
            unite=None,
        )
        await _executer(background_tasks)
        essai_ids.append(essai_id)

    assert len(ia_labo._essais) == 20
    # Les 5 premiers essais ont été chassés.
    for essai_id in essai_ids[:5]:
        assert lire_essai(essai_id) is None
    # Les 20 derniers sont toujours là.
    for essai_id in essai_ids[5:]:
        assert lire_essai(essai_id) is not None


async def test_lire_essai_inconnu_none(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    assert lire_essai(uuid.uuid4()) is None


async def test_derniers_essais_plus_recents_dabord(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    reponses = _reponses_session({"statut": "prix_non_verifiable", "raison": "essai"})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    essai_ids: list[uuid.UUID] = []
    for indice in range(3):
        background_tasks = BackgroundTasks()
        essai_id = await lancer_essai_prix(
            sessions_test,
            http,
            background_tasks,
            fournisseur=None,
            designation=f"Produit {indice}",
            code=None,
            unite=None,
        )
        await _executer(background_tasks)
        essai_ids.append(essai_id)

    derniers = derniers_essais()
    assert [trace.id for trace in derniers] == list(reversed(essai_ids))


# --------------------------------------------------------------------------
# journal_appels
# --------------------------------------------------------------------------


async def test_journal_appels_lignes_recentes_dabord(db_session: AsyncSession) -> None:
    maintenant = datetime.now(UTC)
    db_session.add(
        AppelIA(
            usage="synthese",
            statut="ok",
            duree_ms=10,
            created_at=maintenant - timedelta(minutes=2),
        )
    )
    db_session.add(
        AppelIA(
            usage="prix",
            statut="erreur",
            erreur="delai",
            duree_ms=5000,
            created_at=maintenant - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    lignes = await journal_appels(db_session, limite=50)

    assert len(lignes) == 2
    assert lignes[0].usage == "prix"
    assert lignes[0].statut == "erreur"
    assert lignes[0].erreur == "delai"
    assert lignes[1].usage == "synthese"


async def test_journal_appels_respecte_la_limite(db_session: AsyncSession) -> None:
    maintenant = datetime.now(UTC)
    for indice in range(5):
        db_session.add(
            AppelIA(
                usage="synthese",
                statut="ok",
                duree_ms=1,
                created_at=maintenant - timedelta(minutes=indice),
            )
        )
    await db_session.commit()

    lignes = await journal_appels(db_session, limite=2)

    assert len(lignes) == 2


# --------------------------------------------------------------------------
# Aucun secret dans la trace
# --------------------------------------------------------------------------


async def test_essai_prix_aucun_secret_dans_la_trace(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    reponses = _reponses_session({"statut": "prix_non_verifiable", "raison": "essai"})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert MDP_INVENTE not in trace.texte_envoye
    assert MDP_INVENTE not in str(trace.reponse_brute)
    assert MDP_INVENTE not in str(trace.resultat)


# --------------------------------------------------------------------------
# Fix round 1 (revue LABO) : un essai se termine toujours, même sur une
# exception imprévue (bug dans controles_..., panne du calcul des appels
# restants) -- jamais bloqué en `en_cours` pour toujours.
# --------------------------------------------------------------------------


async def test_essai_prix_bug_imprevu_dans_controles_termine_la_trace(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une exception qu'aucun `except` ciblé de `_executer_essai_prix` ne
    prévoit (ici un bug inventé dans `controles_prix_internet`) doit
    terminer la trace en `erreur` -- jamais la laisser bloquée en
    `en_cours` pour toujours (l'écran l'interroge toutes les 2 s tant
    qu'elle y reste)."""

    def _controles_qui_bug(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("bug inventé, message qui ne doit apparaître nulle part")

    monkeypatch.setattr(ia_labo, "controles_prix_internet", _controles_qui_bug)

    reponses = _reponses_session(
        {
            "statut": "trouve",
            "produit_trouve": "Ciment",
            "prix": 12.34,
            "devise": "EUR",
            "taxes": "TTC",
            "unite": "sac",
            "conditionnement": "25kg",
            "source_url": "https://fournisseur.test/ciment",
            "confiance": "moyenne",
            "raison": "",
        }
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Ciment",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut != "en_cours"
    assert trace.statut == "erreur"
    assert trace.fin is not None
    assert trace.duree_ms is not None
    assert trace.erreur is not None
    assert trace.erreur["code"] == "RuntimeError"
    assert trace.erreur["message_court"] == "Erreur imprévue pendant l'essai."
    assert trace.erreur["brut"] is None
    # Jamais le message de l'exception (pourrait porter une donnée) --
    # seul le nom de la classe est gardé.
    assert "bug inventé" not in str(trace.erreur)
    assert "bug inventé" not in str(trace.__dict__)


async def test_essai_explication_bug_imprevu_termine_la_trace(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Même garantie qu'`_executer_essai_prix`, vérifiée aussi pour
    `_executer_essai_explication` (bug inventé dans `controles_explication`)."""
    anomalie = await _creer_anomalie_prix(db_session)

    def _controles_qui_bug(*args: Any, **kwargs: Any) -> Any:
        raise KeyError("clé inventée absente")

    monkeypatch.setattr(ia_labo, "controles_explication", _controles_qui_bug)

    reponses = _reponses_session({"explication": "Prix 12.50, médiane 10.00."})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_explication(
        sessions_test, http, background_tasks, anomalie.id
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "KeyError"
    assert trace.erreur["message_court"] == "Erreur imprévue pendant l'essai."


async def test_essai_synthese_bug_imprevu_termine_la_trace(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Même garantie, vérifiée aussi pour `_executer_essai_synthese` (bug
    inventé dans `controles_synthese`)."""

    def _controles_qui_bug(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("valeur inventée invalide")

    monkeypatch.setattr(ia_labo, "controles_synthese", _controles_qui_bug)

    reponses = _reponses_session({"resume": "Rien à signaler.", "actions": []})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_synthese(
        sessions_test, http, background_tasks, _LUNDI
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "ValueError"
    assert trace.erreur["message_court"] == "Erreur imprévue pendant l'essai."


async def test_essai_prix_appels_restants_echoue_mais_essai_termine(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une panne du calcul des appels restants (ex. base indisponible juste
    après un essai par ailleurs réussi) ne doit jamais empêcher l'essai de
    se terminer avec son résultat déjà calculé -- seul `appels_restants`
    reste `None`, jamais l'ensemble de la trace remplacé par une erreur
    générique."""

    async def _appels_restants_qui_bug(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("panne de base inventée")

    monkeypatch.setattr(ia_labo, "_appels_restants", _appels_restants_qui_bug)

    reponses = _reponses_session(
        {
            "statut": "trouve",
            "produit_trouve": "Ciment",
            "prix": 12.34,
            "devise": "EUR",
            "taxes": "TTC",
            "unite": "sac",
            "conditionnement": "25kg",
            "source_url": "https://fournisseur.test/ciment",
            "confiance": "moyenne",
            "raison": "",
        },
        parts=[
            _partie_outil(
                id_partie="prt_1",
                outil="webfetch",
                entree={"url": "https://fournisseur.test/ciment"},
                output="Ciment 25kg à 12,34 € TTC.",
            )
        ],
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Ciment",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "fini"
    assert trace.erreur is None
    assert trace.resultat is not None
    assert trace.resultat["statut"] == "trouve"
    assert trace.appels_restants is None


async def test_essai_plafond_appels_restants_echoue_mais_essai_termine(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Même garantie que ci-dessus, sur le chemin `_terminer_en_echec_avant_
    appel` (IA éteinte/plafond, avant même une tentative de requête)."""

    async def _appels_restants_qui_bug(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("panne de base inventée")

    monkeypatch.setattr(ia_labo, "_appels_restants", _appels_restants_qui_bug)
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_active=False)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête ne doit être faite, IA éteinte")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )
    await _executer(background_tasks)

    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "erreur"
    assert trace.erreur is not None
    assert trace.erreur["code"] == "eteinte"
    assert trace.appels_restants is None


async def test_essai_prix_annulation_nest_pas_avalee(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    """`asyncio.CancelledError` (hérite de `BaseException`, pas d'`Exception`
    depuis Python 3.8) ne doit jamais être avalée par le filet de sécurité
    du fix round 1 -- elle doit continuer à se propager telle quelle hors
    de `_executer_essai_prix`."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    background_tasks = BackgroundTasks()

    essai_id = await lancer_essai_prix(
        sessions_test,
        http,
        background_tasks,
        fournisseur=None,
        designation="Produit",
        code=None,
        unite=None,
    )

    with pytest.raises(asyncio.CancelledError):
        await _executer(background_tasks)

    # La trace reste `en_cours` (l'annulation a interrompu la tâche avant
    # qu'elle ne puisse se terminer elle-même) -- comportement attendu d'une
    # vraie annulation, à la différence d'un bug imprévu.
    trace = lire_essai(essai_id)
    assert trace is not None
    assert trace.statut == "en_cours"
