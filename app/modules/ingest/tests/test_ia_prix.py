"""Tests de `ingest/ia_prix.py` (T6, phase 4 IA) : explication des alertes
prix, prix trouvé sur internet, essai et avis d'une anomalie. Base de test
réelle (`bl_test`), aucun appel réseau (`httpx.MockTransport`, même
mécanique que `ingest/tests/test_opencode.py`/`test_ia_synthese.py`) ;
toutes les données (fournisseurs, anomalies, détails) sont entièrement
inventées.

Contexte (brief T6) : les règles de prix au bon (R19-R25, dont R22
« Produit absent de la grille ») ne sont pas encore fusionnées dans `dev`
(lot Prix construit en parallèle sur `origin/feature/phase-3-prix`) : les
anomalies R22 de ce fichier sont donc inventées, avec un `detail` de la
forme donnée par le brief (`produit`, `code`, `prix_bon`, `unite_bon`,
`date_bon`, `candidats`) -- forme confirmée mot pour mot contre le vrai code
de cette branche (fix round 2, relecture finale, lu via `git show
origin/feature/phase-3-prix:app/modules/rules/rules/R22.py`) : `code` et
`unite_bon` valent le tiret cadratin quand la ligne n'a ni référence ni
unité connue, et **aucune** clé `dernier_prix` n'y figure jamais (portée par
R20, pas R22 -- le test dédié plus bas, sur ce detail exact, couvre ce cas).
Pour la sélection par catégorie, un test dédié ajoute temporairement
`"R22": "prix"` à `ingest.anomalies.CATEGORIES_REGLE` via
`monkeypatch.setitem` (jamais une modification du dictionnaire lui-même)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.ingest import anomalies, commun, ia_prix, opencode
from app.modules.ingest.anomalies import AnomalieIntrouvable
from app.modules.ingest.ia_prix import (
    ECHECS_MAX,
    MAX_ANOMALIES_PRIX_INTERNET,
    REGLES_PRIX_INTERNET,
    TITRES_REGLES_PRIX,
    BilanIA,
    ProduitEssai,
    avis_ia_anomalie,
    chercher_prix_internet,
    cle_produit_internet,
    empreinte_detail,
    essayer_prix_internet,
    expliquer_alertes,
    prix_internet_des_anomalies,
)
from app.modules.ingest.models import (
    Anomalie,
    Document,
    ExplicationAlerte,
    Fournisseur,
    PrixInternet,
)
from app.modules.ingest.parametres import modifier_parametre
from app.modules.normalize.texte import normaliser_libelle

pytestmark = [pytest.mark.anyio, pytest.mark.db]


# --------------------------------------------------------------------------
# Réglages IA et contrôle des prix (même idiome que `test_opencode.py` /
# `test_controle_prix.py`, non réimportés d'un autre fichier de tests)
# --------------------------------------------------------------------------


class _SettingsIAFake:
    """Substitut minimal de `Settings` : seuls les attributs lus par
    `ingest.opencode` sont portés."""

    def __init__(
        self,
        *,
        ia_active: bool = True,
        opencode_url: str | None = "https://opencode-prix.test",
        opencode_mot_de_passe: str | None = "mdp-invente-prix",
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
    est éteinte) -- les tests dédiés au plafond l'écrasent localement."""
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())


def _regler_controle_prix(monkeypatch: pytest.MonkeyPatch, *, actif: bool) -> None:
    """Écrase, pour le test courant, la fixture autouse
    `_controle_prix_actif_par_defaut` (`conftest.py`) -- même idiome que
    `test_controle_prix.py`."""

    class _SettingsInventee:
        controle_prix_actif = actif
        controle_livre_non_facture_actif = True

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


async def _activer_controle_prix_bl(session: AsyncSession) -> None:
    """R19-R25 (dont R22) sont masquées par défaut (réglage `prix_controle_
    bl_actif`, en base, défaut 0) -- fix round 1, T10a : depuis que `ia_prix
    .py` masque ces règles via `ingest.commun.regles_masquees`, chaque test
    qui attend une anomalie R22 traitée (et non masquée) doit allumer
    l'interrupteur explicitement, comme `ingest.tests.test_prix_bl
    ._activer_controle` -- jamais une fixture autouse : ce fichier mélange
    des tests purs (sync, sans `db_session`) et des tests base de données,
    et une fixture autouse async casse la collecte des premiers (plugin
    anyio, absence de boucle événementielle pour un test synchrone)."""
    await modifier_parametre(session, "prix_controle_bl_actif", "1", auteur_id=None)


# --------------------------------------------------------------------------
# Données de test (entièrement inventées)
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    session: AsyncSession, *, nom: str = "Fournisseur Prix Invente"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    session.add(fournisseur)
    await session.flush()
    return fournisseur


async def _creer_facture(
    session: AsyncSession,
    *,
    fournisseur: Fournisseur | None,
    numero: str = "FA-PRIX-1",
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-prix-{uuid.uuid4()}.pdf",
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        numero=numero,
    )
    session.add(document)
    await session.flush()
    return document


async def _creer_anomalie(
    session: AsyncSession,
    *,
    regle: str,
    detail: dict[str, str],
    document: Document | None = None,
    statut: str = "ouverte",
    gravite: str = "moyenne",
    bloc_id: uuid.UUID | None = None,
    ligne_id: uuid.UUID | None = None,
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        detail=detail,
        statut=statut,
        document_id=document.id if document is not None else None,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
    )
    session.add(anomalie)
    await session.flush()
    return anomalie


def _detail_r07(**overrides: str) -> dict[str, str]:
    detail = {
        "article": "Sable 0/4",
        "code": "SAB04",
        "pu_facture": "12.50",
        "mediane": "10.00",
        "occurrences": "6",
        "ecart_pct": "25.00",
    }
    detail.update(overrides)
    return detail


def _explication_valide_pour(detail: dict[str, str]) -> str:
    """Explication qui ne recopie que des nombres déjà présents dans
    `detail` (garde des chiffres, `extract.reponses_ia.lire_explication`) --
    évite qu'un test « succès » échoue par accident sur ce contrôle, sans
    rapport avec ce que ce fichier vérifie."""
    return (
        f"Le prix facturé est de {detail['pu_facture']} alors que la médiane "
        f"habituelle est de {detail['mediane']}, soit un écart de "
        f"{detail['ecart_pct']} %."
    )


def _detail_r22(**overrides: str) -> dict[str, str]:
    """Detail R22 inventé, forme exacte du brief T6 (lot Prix, pas encore
    fusionné sur cette branche)."""
    detail = {
        "produit": "Plaque std 13",
        "code": "PL13",
        "prix_bon": "7.90",
        "unite_bon": "u",
        "date_bon": "2026-09-21",
        "candidats": "—",
    }
    detail.update(overrides)
    return detail


async def _creer_prix_internet(
    session: AsyncSession,
    *,
    cle: str,
    statut: str,
    consulte_le: datetime,
    fournisseur_id: uuid.UUID | None = None,
    designation: str = "Produit Cache Invente",
    code: str | None = None,
    raison: str | None = None,
) -> PrixInternet:
    ligne = PrixInternet(
        fournisseur_id=fournisseur_id,
        cle=cle,
        designation=designation,
        code=code,
        statut=statut,
        prix=Decimal("10.0000") if statut == "trouve" else None,
        devise="EUR" if statut == "trouve" else None,
        taxes="HT" if statut == "trouve" else None,
        unite="u" if statut == "trouve" else None,
        conditionnement=None,
        produit_trouve="Produit cache trouvé" if statut == "trouve" else None,
        source_url="https://exemple.invalid/produit-cache"
        if statut == "trouve"
        else None,
        confiance="moyenne" if statut == "trouve" else None,
        raison=None if statut == "trouve" else raison,
        modele=None,
        consulte_le=consulte_le,
    )
    session.add(ligne)
    await session.flush()
    return ligne


# --------------------------------------------------------------------------
# Faux transport OpenCode (même mécanique que `test_opencode.py`, non
# réimportée d'un autre fichier de tests)
# --------------------------------------------------------------------------

_SESSION_ID = "ses_test_1"


def _handler_json(
    reponses: dict[tuple[str, str], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        cle = (request.method, request.url.path)
        if cle not in reponses:
            raise AssertionError(f"requête inattendue : {request.method} {request.url}")
        return reponses[cle]

    return handler


def _aucune_requete(request: httpx.Request) -> httpx.Response:
    raise AssertionError(
        f"aucune requête ne doit être faite : {request.method} {request.url}"
    )


def _info_minimal(**overrides: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": "msg_test_1",
        "sessionID": _SESSION_ID,
        "role": "assistant",
        "time": {"created": 1, "completed": 2},
        "parentID": "msg_test_0",
        "modelID": "modele-prix-invente",
        "providerID": "fournisseur-prix-invente",
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


def _partie_webfetch(*, url: str, texte: str) -> dict[str, Any]:
    return {
        "id": "prt_1",
        "sessionID": _SESSION_ID,
        "messageID": "msg_test_1",
        "type": "tool",
        "callID": "call_prt_1",
        "tool": "webfetch",
        "state": {
            "status": "completed",
            "input": {"url": url},
            "output": texte,
            "title": "titre invente",
            "metadata": {},
            "time": {"start": 1, "end": 2},
        },
    }


def _refus_historique() -> httpx.Response:
    """Relecture des étapes de la recherche de prix (`GET /session/{id}/
    message`, voir `opencode._parties_de_toutes_les_etapes`) : forme de la
    réponse d'OpenCode 1.18.32 à la page qui contient la demande de départ
    (contenu inventé) -- seules restent les pages du dernier message."""
    return httpx.Response(
        400, json={"name": "BadRequest", "data": {"message": "refus inventé"}}
    )


def _historique(parts: list[dict[str, Any]]) -> httpx.Response:
    """Relecture des étapes : une étape précédente de l'IA, sans curseur
    (la relecture s'arrête là)."""
    return httpx.Response(
        200, json=[{"info": _info_minimal(id="msg_test_0b"), "parts": parts}]
    )


def _reponses_ok(structured: dict[str, Any]) -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(structured=structured)
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": _SESSION_ID}),
        (
            "POST",
            f"/session/{_SESSION_ID}/message",
        ): httpx.Response(200, json={"info": info, "parts": []}),
        ("GET", f"/session/{_SESSION_ID}/message"): _refus_historique(),
        ("DELETE", f"/session/{_SESSION_ID}"): httpx.Response(200, json=True),
    }


def _reponses_prix_trouve(
    *, prix: str, source_url: str, page_texte: str, taxes: str = "HT"
) -> dict[tuple[str, str], httpx.Response]:
    structured = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            {
                "produit_trouve": "Produit trouvé invente",
                "prix": float(prix),
                "devise": "EUR",
                "taxes": taxes,
                "unite": "u",
                "conditionnement": "boîte de 10",
                "source_url": source_url,
                "confiance": "elevee",
            }
        ],
    }
    info = _info_minimal(structured=structured)
    # Comme sur le vrai serveur : la page a été ouverte à une étape
    # précédente, le dernier message ne porte que la sortie structurée.
    parts = [_partie_webfetch(url=source_url, texte=page_texte)]
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": _SESSION_ID}),
        (
            "POST",
            f"/session/{_SESSION_ID}/message",
        ): httpx.Response(200, json={"info": info, "parts": []}),
        ("GET", f"/session/{_SESSION_ID}/message"): _historique(parts),
        ("DELETE", f"/session/{_SESSION_ID}"): httpx.Response(200, json=True),
    }


def _reponses_prix_non_verifiable(
    raison: str = "prix non communiqué",
) -> dict[tuple[str, str], httpx.Response]:
    structured = {
        "statut": "prix_non_verifiable",
        "produit_trouve": "",
        "prix": 0,
        "devise": "",
        "taxes": "inconnu",
        "unite": "",
        "conditionnement": "",
        "source_url": "",
        "confiance": "faible",
        "raison": raison,
    }
    return _reponses_ok(structured)


def _reponses_erreur(
    erreur_info: dict[str, Any],
) -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(error=erreur_info)
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": _SESSION_ID}),
        (
            "POST",
            f"/session/{_SESSION_ID}/message",
        ): httpx.Response(200, json={"info": info, "parts": []}),
        ("DELETE", f"/session/{_SESSION_ID}"): httpx.Response(200, json=True),
    }


# --------------------------------------------------------------------------
# empreinte_detail / cle_produit_internet (purs)
# --------------------------------------------------------------------------


def test_empreinte_detail_ignore_lordre_des_cles() -> None:
    assert empreinte_detail({"a": "1", "b": "2"}) == empreinte_detail(
        {"b": "2", "a": "1"}
    )


def test_empreinte_detail_differe_si_le_detail_differe() -> None:
    assert empreinte_detail({"a": "1"}) != empreinte_detail({"a": "2"})


def test_cle_produit_internet_avec_code_espaces_retires() -> None:
    fournisseur_id = uuid.uuid4()
    assert (
        cle_produit_internet(fournisseur_id, "Plaque std 13", "PL 13")
        == f"{fournisseur_id}|ref:PL13"
    )


def test_cle_produit_internet_code_tiret_utilise_designation() -> None:
    assert (
        cle_produit_internet(None, "Plaque Std 13", "—")
        == f"-|nom:{normaliser_libelle('Plaque Std 13')}"
    )


def test_cle_produit_internet_sans_code_utilise_designation_normalisee() -> None:
    fournisseur_id = uuid.uuid4()
    assert (
        cle_produit_internet(fournisseur_id, "Plaque std 13", None)
        == f"{fournisseur_id}|nom:{normaliser_libelle('Plaque std 13')}"
    )


def test_cle_produit_internet_fournisseurs_distincts_cles_distinctes() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    assert cle_produit_internet(a, "Même produit", "REF") != cle_produit_internet(
        b, "Même produit", "REF"
    )


# --------------------------------------------------------------------------
# expliquer_alertes -- sélection
# --------------------------------------------------------------------------


async def test_expliquer_alertes_selection_categorie_prix_seulement(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session, regle="R01", detail={"numero_bl": "BL-1"}, document=facture
    )
    anomalie_prix = await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    await db_session.commit()

    structured = {"explication": _explication_valide_pour(_detail_r07())}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA(ok=1)
    explications = (await db_session.execute(select(ExplicationAlerte))).scalars().all()
    assert len(explications) == 1
    assert explications[0].anomalie_id == anomalie_prix.id


async def test_expliquer_alertes_ignore_anomalies_non_ouvertes(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session,
        regle="R08",
        detail=_detail_r07(),
        document=facture,
        statut="traitee",
    )
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA()
    explications = (await db_session.execute(select(ExplicationAlerte))).scalars().all()
    assert explications == []


async def test_expliquer_alertes_ignore_regle_masquee(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R07 avec `CONTROLE_PRIX_ACTIF` faux (décision d'Ilane du 24/09/2026) :
    masquée de la sélection, aucune requête à l'IA."""
    _regler_controle_prix(monkeypatch, actif=False)
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA()


async def test_expliquer_alertes_lit_categories_regle_a_lexecution(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R22 n'existe pas encore dans `CATEGORIES_REGLE` sur cette branche :
    ajouté temporairement (`monkeypatch.setitem`, jamais une modification du
    dictionnaire lui-même), il doit être expliqué comme n'importe quelle
    règle de prix -- preuve que la sélection lit `CATEGORIES_REGLE` à
    l'exécution plutôt qu'une liste figée."""
    monkeypatch.setitem(anomalies.CATEGORIES_REGLE, "R22", "prix")
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22()
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    structured = {"explication": "Ce produit ne figure pas dans la grille."}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA(ok=1)


# --------------------------------------------------------------------------
# expliquer_alertes -- texte envoyé
# --------------------------------------------------------------------------


async def test_expliquer_alertes_texte_envoye_titre_fournisseur_detail(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Texte Invente")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    await _creer_anomalie(db_session, regle="R08", detail=detail, document=facture)
    await db_session.commit()

    requetes: list[httpx.Request] = []
    structured = {"explication": _explication_valide_pour(detail)}

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(_reponses_ok(structured))(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    bilan = await expliquer_alertes(db_session, http)
    assert bilan.ok == 1

    corps_message = json.loads(requetes[1].content)
    texte_envoye = corps_message["parts"][0]["text"]
    lignes = texte_envoye.splitlines()

    assert lignes[0] == f"Alerte : {TITRES_REGLES_PRIX['R08']}"
    assert lignes[1] == "Fournisseur : Fournisseur Texte Invente"
    assert lignes[2] == "Données :"
    for cle, valeur in detail.items():
        assert f"- {cle} : {valeur}" in lignes
    # Rien d'autre que le titre, le fournisseur, le détail et la consigne :
    # exactement 3 lignes d'en-tête + une ligne par entrée du detail + 1
    # ligne de consigne.
    assert len(lignes) == 3 + len(detail) + 1


async def test_expliquer_alertes_fournisseur_absent_tiret(
    db_session: AsyncSession,
) -> None:
    detail = _detail_r07()
    await _creer_anomalie(db_session, regle="R07", detail=detail, document=None)
    await db_session.commit()

    requetes: list[httpx.Request] = []
    structured = {"explication": _explication_valide_pour(detail)}

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(_reponses_ok(structured))(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await expliquer_alertes(db_session, http)

    texte_envoye = json.loads(requetes[1].content)["parts"][0]["text"]
    assert "Fournisseur : —" in texte_envoye


# --------------------------------------------------------------------------
# expliquer_alertes -- empreinte, échecs, plafond
# --------------------------------------------------------------------------


async def test_expliquer_alertes_succes_enregistre(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=detail, document=facture
    )
    await db_session.commit()

    explication_attendue = _explication_valide_pour(detail)
    structured = {"explication": explication_attendue}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA(ok=1)
    explication = (
        await db_session.execute(
            select(ExplicationAlerte).where(
                ExplicationAlerte.anomalie_id == anomalie.id
            )
        )
    ).scalar_one()
    assert explication.statut == "ok"
    assert explication.texte == explication_attendue
    assert explication.echecs == 0
    assert explication.empreinte_detail == empreinte_detail(detail)
    assert explication.modele == "fournisseur-prix-invente/modele-prix-invente"


async def test_expliquer_alertes_empreinte_changee_refaite(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=detail, document=facture
    )
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail="empreinte-perimee-inventee",
            statut="ok",
            texte="Ancienne explication, détail différent.",
            echecs=0,
            modele="ancien-modele-invente",
        )
    )
    await db_session.commit()

    nouvelle_explication = _explication_valide_pour(detail)
    structured = {"explication": nouvelle_explication}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA(ok=1)
    explication = (
        await db_session.execute(
            select(ExplicationAlerte).where(
                ExplicationAlerte.anomalie_id == anomalie.id
            )
        )
    ).scalar_one()
    assert explication.texte == nouvelle_explication
    assert explication.empreinte_detail == empreinte_detail(detail)
    assert explication.echecs == 0


async def test_expliquer_alertes_trois_echecs_plus_retentee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=detail, document=facture
    )
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail=empreinte_detail(detail),
            statut="echec",
            texte=None,
            echecs=ECHECS_MAX,
            modele=None,
        )
    )
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA()
    explication = (
        await db_session.execute(
            select(ExplicationAlerte).where(
                ExplicationAlerte.anomalie_id == anomalie.id
            )
        )
    ).scalar_one()
    assert explication.echecs == ECHECS_MAX


async def test_expliquer_alertes_nouveau_detail_compteur_remis(
    db_session: AsyncSession,
) -> None:
    """Trois échecs déjà comptés sur un *ancien* détail : le détail actuel a
    changé (empreinte différente), l'anomalie doit donc être retentée malgré
    `echecs == ECHECS_MAX`, et un nouvel échec remet le compteur à 1 (pas 4)
    sur la nouvelle empreinte."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=detail, document=facture
    )
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail="ancienne-empreinte-invalide",
            statut="echec",
            texte=None,
            echecs=ECHECS_MAX,
            modele=None,
        )
    )
    await db_session.commit()

    erreur_info = {"name": "ProviderAuthError", "data": {}}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_erreur(erreur_info)))
    )

    bilan = await expliquer_alertes(db_session, http)

    assert bilan.echecs == 1
    assert bilan.echecs_injoignable == 1
    explication = (
        await db_session.execute(
            select(ExplicationAlerte).where(
                ExplicationAlerte.anomalie_id == anomalie.id
            )
        )
    ).scalar_one()
    assert explication.echecs == 1
    assert explication.empreinte_detail == empreinte_detail(detail)


async def test_expliquer_alertes_plafond_arret_sans_requete(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    await db_session.commit()

    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_appels_max_jour=0)
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await expliquer_alertes(db_session, http)

    assert bilan == BilanIA(arret="plafond")
    explications = (await db_session.execute(select(ExplicationAlerte))).scalars().all()
    assert explications == []


async def test_expliquer_alertes_reponse_invalide_ligne_echec(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    await db_session.commit()

    # Chiffre inventé, absent du détail -> `ReponseIAInvalide` (garde des
    # chiffres, `extract.reponses_ia.lire_explication`).
    structured = {"explication": "Le prix a augmenté de 999.99 %."}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_ok(structured)))
    )

    bilan = await expliquer_alertes(db_session, http)

    assert bilan.ok == 0
    assert bilan.echecs == 1
    assert bilan.echecs_injoignable == 0
    explication = (
        await db_session.execute(
            select(ExplicationAlerte).where(
                ExplicationAlerte.anomalie_id == anomalie.id
            )
        )
    ).scalar_one()
    assert explication.statut == "echec"
    assert explication.texte is None
    assert explication.echecs == 1


# --------------------------------------------------------------------------
# chercher_prix_internet -- sélection
# --------------------------------------------------------------------------


async def test_chercher_prix_internet_R22_seulement(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    await _creer_anomalie(
        db_session, regle="R22", detail=_detail_r22(), document=facture
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    requetes: list[httpx.Request] = []
    reponses = _reponses_prix_trouve(
        prix="89.90",
        source_url="https://exemple.invalid/plaque-std-13",
        page_texte="Plaque std 13 -- Prix : 89,90 € TTC.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(reponses)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(ok=1)
    # Une seule recherche (une seule session créée), pour R22 -- R07 n'a
    # jamais atteint la sélection de `chercher_prix_internet`.
    assert [r.url.path for r in requetes if r.method == "POST"] == [
        "/session",
        f"/session/{_SESSION_ID}/message",
    ]


async def test_chercher_prix_internet_dernier_prix_present_pas_de_recherche(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session,
        regle="R22",
        detail=_detail_r22(dernier_prix="9.50"),
        document=facture,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA()
    lignes = (await db_session.execute(select(PrixInternet))).scalars().all()
    assert lignes == []


async def test_chercher_prix_internet_prix_du_bon_absent_du_texte_envoye(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(
        db_session, nom="Fournisseur Habituel Invente"
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session,
        regle="R22",
        detail=_detail_r22(prix_bon="7.90"),
        document=facture,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    requetes: list[httpx.Request] = []
    reponses = _reponses_prix_trouve(
        prix="89.90",
        source_url="https://exemple.invalid/plaque-std-13",
        page_texte="Prix : 89,90 €.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(reponses)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await chercher_prix_internet(db_session, http)

    texte_envoye = json.loads(requetes[1].content)["parts"][0]["text"]
    assert "7.90" not in texte_envoye
    assert "7,90" not in texte_envoye
    assert "Fournisseur habituel : Fournisseur Habituel Invente" in texte_envoye
    assert "Désignation : Plaque std 13" in texte_envoye
    assert "Code article chez le fournisseur habituel : PL13" in texte_envoye
    assert "Unité : u" in texte_envoye


async def test_chercher_prix_internet_detail_r22_reel_code_et_unite_tiret(
    db_session: AsyncSession,
) -> None:
    """Fix round 2 (relecture finale) : forme EXACTE du vrai `R22` de la
    branche du lot Prix (`git show
    origin/feature/phase-3-prix:app/modules/rules/rules/R22.py`) quand la
    ligne n'a ni référence (`code`) ni unité connue -- `ligne.code or TIRET`
    et `ligne.unite_bon or TIRET` y valent alors le tiret cadratin, jamais
    une chaîne vide ni la clé absente. Ce test prouve trois choses à la
    fois : le produit est quand même retenu pour la recherche (la
    désignation seule suffit, `code`/`unite_bon` ne sont pas obligatoires) ;
    les deux tirets sont bien traités comme absents par `_valeur_utile`
    (clé de cache retombant sur la désignation normalisée, jamais sur
    `ref:—`) ; et le texte envoyé à l'IA ne contient jamais `prix_bon`."""
    fournisseur = await _creer_fournisseur(
        db_session, nom="Fournisseur Habituel Invente"
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(code="—", unite_bon="—", prix_bon="7.90")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    requetes: list[httpx.Request] = []
    reponses = _reponses_prix_trouve(
        prix="89.90",
        source_url="https://exemple.invalid/plaque-std-13",
        page_texte="Plaque std 13 -- Prix : 89,90 € TTC.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(reponses)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    bilan = await chercher_prix_internet(db_session, http)

    # Le produit est retenu malgré `code` et `unite_bon` absents (tiret).
    assert bilan == BilanIA(ok=1)

    # « — » traité comme absent pour la clé de cache : avec `code=None`, la
    # clé retombe sur la désignation normalisée, jamais sur `ref:—`.
    ligne_prix = (await db_session.execute(select(PrixInternet))).scalar_one()
    assert ligne_prix.cle == cle_produit_internet(
        fournisseur.id, detail["produit"], None
    )

    texte_envoye = json.loads(requetes[1].content)["parts"][0]["text"]
    assert "7.90" not in texte_envoye
    assert "7,90" not in texte_envoye
    assert "Désignation : Plaque std 13" in texte_envoye
    assert "Code article chez le fournisseur habituel : —" in texte_envoye
    assert "Unité : —" in texte_envoye


async def test_chercher_prix_internet_cache_29_jours_rien(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Cache 29 Jours")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC) - timedelta(days=29),
        fournisseur_id=fournisseur.id,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA()


async def test_chercher_prix_internet_cache_31_jours_recherche(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Cache 31 Jours")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC) - timedelta(days=31),
        fournisseur_id=fournisseur.id,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    reponses = _reponses_prix_trouve(
        prix="45.00",
        source_url="https://exemple.invalid/produit-31-jours",
        page_texte="Prix : 45,00 €.",
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(ok=1)


async def test_chercher_prix_internet_trois_echecs_sept_jours_rien(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Echecs Repetes")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    maintenant = datetime.now(UTC)
    for jours in (1, 2, 3):
        await _creer_prix_internet(
            db_session,
            cle=cle,
            statut="echec",
            consulte_le=maintenant - timedelta(days=jours),
            fournisseur_id=fournisseur.id,
            raison="reseau",
        )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA()
    lignes = (await db_session.execute(select(PrixInternet))).scalars().all()
    assert len(lignes) == 3  # aucune ligne de plus


async def test_chercher_prix_internet_une_seule_recherche_meme_produit(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture_1 = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA-1")
    facture_2 = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA-2")
    detail = _detail_r22(produit="Produit Partage Invente")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture_1)
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture_2)
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    requetes: list[httpx.Request] = []
    reponses = _reponses_prix_trouve(
        prix="12.00",
        source_url="https://exemple.invalid/produit-partage",
        page_texte="Prix : 12,00 €.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(reponses)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(ok=1)
    # Une seule recherche, pas deux (une seule session créée).
    assert [r.url.path for r in requetes if r.method == "POST"] == [
        "/session",
        f"/session/{_SESSION_ID}/message",
    ]
    lignes = (await db_session.execute(select(PrixInternet))).scalars().all()
    assert len(lignes) == 1


# --------------------------------------------------------------------------
# chercher_prix_internet -- enregistrement
# --------------------------------------------------------------------------


async def test_chercher_prix_internet_trouve_enregistre_avec_taxes(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Trouve Taxes")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    reponses = _reponses_prix_trouve(
        prix="89.90",
        source_url="https://exemple.invalid/produit-trouve-taxes",
        page_texte="Prix : 89,90 € TTC.",
        taxes="TTC",
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(ok=1)
    ligne = (await db_session.execute(select(PrixInternet))).scalar_one()
    assert ligne.statut == "trouve"
    assert ligne.prix == Decimal("89.9000")
    assert ligne.devise == "EUR"
    assert ligne.taxes == "TTC"
    assert ligne.source_url == "https://exemple.invalid/produit-trouve-taxes"
    assert ligne.produit_trouve == "Produit trouvé invente"
    assert ligne.confiance == "elevee"
    assert ligne.modele == "fournisseur-prix-invente/modele-prix-invente"
    assert ligne.fournisseur_id == fournisseur.id


async def test_chercher_prix_internet_non_verifiable_enregistre(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Non Verifiable")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    reponses = _reponses_prix_non_verifiable("prix non communiqué par le revendeur")
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(non_verifiables=1)
    ligne = (await db_session.execute(select(PrixInternet))).scalar_one()
    assert ligne.statut == "non_verifiable"
    assert ligne.prix is None
    assert ligne.raison == "prix non communiqué par le revendeur"


async def test_chercher_prix_internet_erreur_ia_ligne_echec(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Erreur IA")
    await _creer_anomalie(db_session, regle="R22", detail=detail, document=facture)
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    erreur_info = {"name": "ProviderAuthError", "data": {}}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_erreur(erreur_info)))
    )

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(echecs=1, echecs_injoignable=1)
    ligne = (await db_session.execute(select(PrixInternet))).scalar_one()
    assert ligne.statut == "echec"
    assert ligne.raison == "ProviderAuthError"
    assert ligne.prix is None


async def test_chercher_prix_internet_plafond_arret(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_anomalie(
        db_session, regle="R22", detail=_detail_r22(), document=facture
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_appels_max_jour=0)
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(arret="plafond")


# --------------------------------------------------------------------------
# essayer_prix_internet -- essai (§7)
# --------------------------------------------------------------------------


async def test_essayer_prix_internet_succes_et_echec_sans_enregistrement(
    db_session: AsyncSession,
) -> None:
    produits = [
        ProduitEssai(
            fournisseur="Fournisseur Essai Invente",
            designation="Produit Essai Trouve",
            code="ESS1",
            unite="u",
        ),
        ProduitEssai(
            fournisseur="Fournisseur Essai Invente",
            designation="Produit Essai Echec",
            code="ESS2",
            unite="u",
        ),
    ]
    reponses_trouve = _reponses_prix_trouve(
        prix="20.00",
        source_url="https://exemple.invalid/produit-essai-trouve",
        page_texte="Prix : 20,00 €.",
    )
    erreur_info = {"name": "ProviderAuthError", "data": {}}
    reponses_echec = _reponses_erreur(erreur_info)

    def handler(request: httpx.Request) -> httpx.Response:
        cle = (request.method, request.url.path)
        chemin_message = f"/session/{_SESSION_ID}/message"
        if request.method == "POST" and request.url.path == chemin_message:
            corps = json.loads(request.content)
            texte = corps["parts"][0]["text"]
            reponses = (
                reponses_echec if "Produit Essai Echec" in texte else reponses_trouve
            )
            return reponses[cle]
        # POST /session et DELETE /session/{id} : identiques quel que soit
        # le produit (seule la réponse du message diffère).
        return reponses_trouve[cle]

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    lignes = await essayer_prix_internet(db_session, http, produits)

    assert len(lignes) == 2
    assert lignes[0].resultat is not None
    assert lignes[0].resultat.statut == "trouve"
    assert lignes[0].erreur is None
    assert lignes[0].duree_s >= 0
    assert lignes[1].resultat is None
    assert lignes[1].erreur == "ProviderAuthError"

    # Rien d'enregistré hors `appel_ia` (aucun cache, aucune trace en base).
    lignes_prix = (await db_session.execute(select(PrixInternet))).scalars().all()
    assert lignes_prix == []


# --------------------------------------------------------------------------
# avis_ia_anomalie
# --------------------------------------------------------------------------


async def test_avis_ia_anomalie_explication_perimee_masquee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=detail, document=facture
    )
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail="empreinte-perimee-inventee",
            statut="ok",
            texte="Explication périmée, détail différent.",
            echecs=0,
            modele=None,
        )
    )
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    assert avis.explication is None
    assert avis.prix_internet is None


async def test_avis_ia_anomalie_explication_a_jour_rendue(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r07()
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=detail, document=facture
    )
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail=empreinte_detail(detail),
            statut="ok",
            texte="Explication à jour.",
            echecs=0,
            modele=None,
        )
    )
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    assert avis.explication is not None
    assert avis.explication.texte == "Explication à jour."


async def test_avis_ia_anomalie_ligne_echec_jamais_montree(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Avis Echec")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="echec",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
        raison="reseau",
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    assert avis.prix_internet is None


async def test_avis_ia_anomalie_prix_trouve_rendu(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Avis Trouve")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    assert avis.prix_internet is not None
    assert avis.prix_internet.statut == "trouve"


async def test_avis_ia_anomalie_introuvable_404(db_session: AsyncSession) -> None:
    with pytest.raises(AnomalieIntrouvable):
        await avis_ia_anomalie(db_session, uuid.uuid4())


async def test_avis_ia_anomalie_masquee_introuvable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_prix(monkeypatch, actif=False)
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    anomalie = await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    await db_session.commit()

    with pytest.raises(AnomalieIntrouvable):
        await avis_ia_anomalie(db_session, anomalie.id)


# --------------------------------------------------------------------------
# Masquage du lot Prix (fix round 1, T10a) : les quatre sélections de ce
# module (`expliquer_alertes`, `chercher_prix_internet`, `avis_ia_anomalie`,
# `prix_internet_des_anomalies`) utilisaient `condition_regles_actives()`
# sans `exclues`, qui ne masque jamais R19-R25 -- seulement R07-R09/R06
# (`regles_desactivees`). Corrigé pour utiliser partout `ingest.commun
# .regles_masquees(session)`, qui tient aussi compte de l'interrupteur
# général `prix_controle_bl_actif` et des sept interrupteurs par alerte.
# --------------------------------------------------------------------------


async def test_masquage_interrupteur_general_eteint_rien_ne_se_passe(
    db_session: AsyncSession,
) -> None:
    """`prix_controle_bl_actif` à son défaut réel (éteint) : une alerte R22
    et une alerte R19 ouvertes ne sont ni expliquées, ni cherchées sur
    internet (aucune requête au faux transport), `avis_ia_anomalie` les
    traite comme introuvables et le service groupé les omet toutes les deux
    du dictionnaire."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    anomalie_r22 = await _creer_anomalie(
        db_session, regle="R22", detail=_detail_r22(), document=facture
    )
    anomalie_r19 = await _creer_anomalie(
        db_session, regle="R19", detail=_detail_r07(), document=facture
    )
    # Aucun réglage `prix_…` modifié : défaut réel de l'application (éteint).
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    assert await expliquer_alertes(db_session, http) == BilanIA()
    assert await chercher_prix_internet(db_session, http) == BilanIA()

    with pytest.raises(AnomalieIntrouvable):
        await avis_ia_anomalie(db_session, anomalie_r22.id)
    with pytest.raises(AnomalieIntrouvable):
        await avis_ia_anomalie(db_session, anomalie_r19.id)

    lot = await prix_internet_des_anomalies(
        db_session, [anomalie_r22.id, anomalie_r19.id]
    )
    assert lot.par_anomalie == {}

    explications = (await db_session.execute(select(ExplicationAlerte))).scalars().all()
    lignes_prix = (await db_session.execute(select(PrixInternet))).scalars().all()
    assert explications == []
    assert lignes_prix == []


async def test_masquage_alerte_absent_grille_eteinte_r22_omise(
    db_session: AsyncSession,
) -> None:
    """Interrupteur général allumé mais `prix_alerte_absent_grille` (alerte
    propre à R22) éteint : R22 reste masquée malgré le général -- ni
    cherchée sur internet, ni visible par `avis_ia_anomalie` ou le service
    groupé."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=_detail_r22(), document=facture
    )
    await modifier_parametre(db_session, "prix_controle_bl_actif", "1", auteur_id=None)
    await modifier_parametre(
        db_session, "prix_alerte_absent_grille", "0", auteur_id=None
    )
    await db_session.commit()

    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    assert await chercher_prix_internet(db_session, http) == BilanIA()

    with pytest.raises(AnomalieIntrouvable):
        await avis_ia_anomalie(db_session, anomalie.id)

    lot = await prix_internet_des_anomalies(db_session, [anomalie.id])
    assert lot.par_anomalie == {}


async def test_prix_internet_des_anomalies_deux_cles_plusieurs_lignes_chacune(
    db_session: AsyncSession,
) -> None:
    """Deux produits distincts, chacun avec plusieurs lignes `PrixInternet`
    (dont un `echec`) : la vue rendue pour chaque anomalie est la plus
    récente `trouve`/`non_verifiable` de SA clé -- jamais celle de l'autre
    produit, jamais une ligne `echec` même la plus récente (revue de fix
    round 1, T10a)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture_1 = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA-A")
    facture_2 = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA-B")
    detail_a = _detail_r22(produit="Produit Deux Cles A", code="CODE-A")
    detail_b = _detail_r22(produit="Produit Deux Cles B", code="CODE-B")
    anomalie_a = await _creer_anomalie(
        db_session, regle="R22", detail=detail_a, document=facture_1
    )
    anomalie_b = await _creer_anomalie(
        db_session, regle="R22", detail=detail_b, document=facture_2
    )
    cle_a = cle_produit_internet(fournisseur.id, detail_a["produit"], detail_a["code"])
    cle_b = cle_produit_internet(fournisseur.id, detail_b["produit"], detail_b["code"])
    maintenant = datetime.now(UTC)

    # Clé A : un `trouve` ancien, puis un `echec` plus récent -- ignoré.
    await _creer_prix_internet(
        db_session,
        cle=cle_a,
        statut="trouve",
        consulte_le=maintenant - timedelta(days=2),
        fournisseur_id=fournisseur.id,
    )
    await _creer_prix_internet(
        db_session,
        cle=cle_a,
        statut="echec",
        consulte_le=maintenant - timedelta(hours=1),
        fournisseur_id=fournisseur.id,
        raison="reseau",
    )

    # Clé B : deux résultats exploitables -- le plus récent (`trouve`)
    # l'emporte sur le plus ancien (`non_verifiable`).
    await _creer_prix_internet(
        db_session,
        cle=cle_b,
        statut="non_verifiable",
        consulte_le=maintenant - timedelta(days=5),
        fournisseur_id=fournisseur.id,
        raison="ancienne raison",
    )
    await _creer_prix_internet(
        db_session,
        cle=cle_b,
        statut="trouve",
        consulte_le=maintenant - timedelta(days=1),
        fournisseur_id=fournisseur.id,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    lot = await prix_internet_des_anomalies(db_session, [anomalie_a.id, anomalie_b.id])

    vue_a = lot.par_anomalie[anomalie_a.id]
    vue_b = lot.par_anomalie[anomalie_b.id]
    assert vue_a is not None
    assert vue_a.statut == "trouve"  # jamais l'échec, pourtant plus récent
    assert vue_b is not None
    assert vue_b.statut == "trouve"  # le plus récent des deux exploitables


def test_regles_prix_internet_contient_r22() -> None:
    assert frozenset({"R22"}) == REGLES_PRIX_INTERNET


# --------------------------------------------------------------------------
# prix_internet_des_anomalies (T10a) -- route groupée `GET
# /api/ia/prix-internet`, voir `api/tests/test_ia.py` pour le routeur.
# --------------------------------------------------------------------------


async def test_prix_internet_des_anomalies_trouve_et_en_attente(
    db_session: AsyncSession,
) -> None:
    """Une anomalie R22 dont le produit a déjà un résultat en cache -- la
    vue correspondante ; une autre, sans résultat encore -- présente dans le
    dictionnaire mais à `None` (« ou None si aucune encore », brief T10a).

    Deux documents distincts (même idiome que `test_chercher_prix_internet
    _une_seule_recherche_meme_produit`) : l'identité d'une anomalie inclut
    `document_id` (index unique `regle, document_id, bloc_id, ligne_id,
    chantier_id, alias_id`, `NULLS NOT DISTINCT`) -- deux R22 sans ligne du
    même document se confondraient en une seule anomalie."""
    fournisseur = await _creer_fournisseur(db_session)
    facture_1 = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA-1")
    facture_2 = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA-2")
    detail_trouve = _detail_r22(produit="Produit Lot Trouve")
    anomalie_trouve = await _creer_anomalie(
        db_session, regle="R22", detail=detail_trouve, document=facture_1
    )
    cle = cle_produit_internet(
        fournisseur.id, detail_trouve["produit"], detail_trouve["code"]
    )
    await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
    )
    # `code` différent (sinon même clé de cache que `detail_trouve` --
    # `cle_produit_internet` ignore la désignation dès qu'un code est
    # présent, cf. son docstring).
    anomalie_sans_cache = await _creer_anomalie(
        db_session,
        regle="R22",
        detail=_detail_r22(produit="Produit Lot Sans Cache", code="AUTRE-CODE"),
        document=facture_2,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    lot = await prix_internet_des_anomalies(
        db_session, [anomalie_trouve.id, anomalie_sans_cache.id]
    )

    assert lot.par_anomalie[anomalie_trouve.id] is not None
    vue = lot.par_anomalie[anomalie_trouve.id]
    assert vue is not None
    assert vue.statut == "trouve"
    assert anomalie_sans_cache.id in lot.par_anomalie
    assert lot.par_anomalie[anomalie_sans_cache.id] is None


async def test_prix_internet_des_anomalies_absentes_du_dictionnaire(
    db_session: AsyncSession,
) -> None:
    """Anomalie inconnue, fermée ou d'une autre règle que R22 : absente du
    dictionnaire, jamais une erreur ni une clé à `None` (« pas d'erreur : la
    page peut envoyer des identifiants de rangées sans R22 », brief T10a)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    anomalie_fermee = await _creer_anomalie(
        db_session,
        regle="R22",
        detail=_detail_r22(),
        document=facture,
        statut="traitee",
    )
    anomalie_autre_regle = await _creer_anomalie(
        db_session, regle="R07", detail=_detail_r07(), document=facture
    )
    inconnue = uuid.uuid4()
    await db_session.commit()

    lot = await prix_internet_des_anomalies(
        db_session, [anomalie_fermee.id, anomalie_autre_regle.id, inconnue]
    )

    assert lot.par_anomalie == {}


async def test_prix_internet_des_anomalies_doublons_ignores_hors_limite(
    db_session: AsyncSession,
) -> None:
    """Doublons ignorés (une seule clé au résultat) et jamais comptés dans
    la limite de `MAX_ANOMALIES_PRIX_INTERNET` : 300 fois le même
    identifiant reste un seul identifiant après déduplication."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=_detail_r22(), document=facture
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    lot = await prix_internet_des_anomalies(db_session, [anomalie.id] * 300)

    assert list(lot.par_anomalie.keys()) == [anomalie.id]


async def test_prix_internet_des_anomalies_plus_de_200_uniques_leve(
    db_session: AsyncSession,
) -> None:
    ids = [uuid.uuid4() for _ in range(MAX_ANOMALIES_PRIX_INTERNET + 1)]

    with pytest.raises(ValueError):
        await prix_internet_des_anomalies(db_session, ids)


async def test_prix_internet_des_anomalies_aucun_identifiant(
    db_session: AsyncSession,
) -> None:
    lot = await prix_internet_des_anomalies(db_session, [])

    assert lot.par_anomalie == {}


async def test_prix_internet_des_anomalies_sans_n_plus_1(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """Le nombre de requêtes SQL ne dépend pas du nombre d'anomalies
    demandées (brief T10a : « en lot ... jamais une requête par
    anomalie »), même idiome que `test_a_traiter
    .test_alias_en_attente_sans_n_plus_1`."""
    fournisseur = await _creer_fournisseur(db_session)

    async def _creer_n_anomalies_r22(n: int, *, prefixe: str) -> list[Anomalie]:
        # Un document distinct par anomalie (même idiome que
        # `test_chercher_prix_internet_une_seule_recherche_meme_produit`) :
        # l'identité d'une anomalie inclut `document_id` -- deux R22 sans
        # ligne du même document se confondraient en une seule anomalie.
        resultat = []
        for i in range(n):
            document = await _creer_facture(
                db_session, fournisseur=fournisseur, numero=f"{prefixe}-{i}"
            )
            resultat.append(
                await _creer_anomalie(
                    db_session,
                    regle="R22",
                    detail=_detail_r22(produit=f"Produit {prefixe} {i}"),
                    document=document,
                )
            )
        return resultat

    anomalies_deux = await _creer_n_anomalies_r22(2, prefixe="FA-N1-DEUX")
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    sync_engine: Engine = db_engine.sync_engine
    compteur_deux = {"n": 0}

    def _compter_deux(*args: object, **kwargs: object) -> None:
        compteur_deux["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _compter_deux)
    try:
        await prix_internet_des_anomalies(db_session, [a.id for a in anomalies_deux])
    finally:
        event.remove(sync_engine, "before_cursor_execute", _compter_deux)

    anomalies_cinq = await _creer_n_anomalies_r22(5, prefixe="FA-N1-CINQ")
    await db_session.commit()

    compteur_cinq = {"n": 0}

    def _compter_cinq(*args: object, **kwargs: object) -> None:
        compteur_cinq["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _compter_cinq)
    try:
        await prix_internet_des_anomalies(db_session, [a.id for a in anomalies_cinq])
    finally:
        event.remove(sync_engine, "before_cursor_execute", _compter_cinq)

    assert compteur_deux["n"] == compteur_cinq["n"]


async def test_prix_internet_des_anomalies_meme_calcul_qu_avis_ia_anomalie(
    db_session: AsyncSession,
) -> None:
    """Non-duplication (brief T10a) : les deux fonctions rendent la même
    vue pour la même anomalie, preuve qu'elles partagent le même calcul de
    clé et la même lecture du cache."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Lot Coherence")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)
    lot = await prix_internet_des_anomalies(db_session, [anomalie.id])

    assert avis.prix_internet is not None
    vue_lot = lot.par_anomalie[anomalie.id]
    assert vue_lot is not None
    assert avis.prix_internet == vue_lot


def test_texte_prix_code_du_fournisseur_jamais_exige_sur_la_page() -> None:
    """29/09/2026, essai sur dix vrais produits Unikalo : l'IA avait trouvé
    le bon produit et son prix dans quatre cas, puis les avait refusés parce
    que la page n'affichait pas le code article demandé -- un code interne
    au fournisseur habituel, qu'aucun autre site n'affiche. Le produit
    s'identifie par sa marque, son nom et son format ; le code n'est qu'un
    indice."""
    texte = ia_prix._texte_prix(
        fournisseur="Fournisseur Invente",
        designation="Mastic invente 300ML",
        code="XY123",
        unite=None,
    )

    assert "Code article chez le fournisseur habituel : XY123" in texte
    assert "Référence :" not in texte
    assert "marque, son nom et son format" in texte
    assert "n'est pas une raison de refuser" in texte
    assert "Vérifie la référence" not in texte


# --------------------------------------------------------------------------
# Plusieurs offres (tâche 3, spec prix internet à plusieurs sources)
# --------------------------------------------------------------------------


def _reponses_prix_deux_offres() -> dict[tuple[str, str], httpx.Response]:
    adresse_a = "https://site-a.exemple.invalid/produit"
    adresse_b = "https://site-b.exemple.invalid/produit"
    structured = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            {
                "produit_trouve": "Produit trouvé A",
                "prix": 13.91,
                "devise": "EUR",
                "taxes": "TTC",
                "unite": "u",
                "conditionnement": "boîte de 10",
                "source_url": adresse_a,
                "confiance": "elevee",
            },
            {
                "produit_trouve": "Produit trouvé B",
                "prix": 12.00,
                "devise": "EUR",
                "taxes": "HT",
                "unite": "u",
                "conditionnement": "boîte de 10",
                "source_url": adresse_b,
                "confiance": "moyenne",
            },
        ],
    }
    info = _info_minimal(structured=structured)
    parts = [
        _partie_webfetch(url=adresse_a, texte="Prix : 13,91 € TTC."),
        _partie_webfetch(url=adresse_b, texte="Prix : 12,00 € HT."),
    ]
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": _SESSION_ID}),
        (
            "POST",
            f"/session/{_SESSION_ID}/message",
        ): httpx.Response(200, json={"info": info, "parts": []}),
        ("GET", f"/session/{_SESSION_ID}/message"): _historique(parts),
        ("DELETE", f"/session/{_SESSION_ID}"): httpx.Response(200, json=True),
    }


async def test_chercher_prix_internet_deux_offres_enregistrees_et_vue(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Deux Offres")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler_json(_reponses_prix_deux_offres()))
    )

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(ok=1)
    ligne = (await db_session.execute(select(PrixInternet))).scalar_one()
    assert len(ligne.offres) == 2
    assert {o["prix"] for o in ligne.offres} == {"13.9100", "12.0000"}
    assert set(ligne.offres[0]) == {
        "prix",
        "devise",
        "taxes",
        "unite",
        "conditionnement",
        "produit_trouve",
        "source_url",
        "confiance",
    }
    # 13,91 TTC = 11,59 HT : colonnes = offre la moins chère en HT.
    assert ligne.prix == Decimal("13.9100")
    assert ligne.taxes == "TTC"

    avis = await avis_ia_anomalie(db_session, anomalie.id)
    vue = avis.prix_internet
    assert vue is not None
    assert vue.nb_sources == 2
    assert vue.prix_ht_min == Decimal("11.59")
    assert vue.prix_ht_max == Decimal("12.00")
    assert [o.prix_ht for o in vue.offres] == [Decimal("11.59"), Decimal("12.00")]


async def test_vue_ligne_trouve_sans_offres_reconstituee_depuis_les_colonnes(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Ancienne Ligne")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    ligne = await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
    )
    ligne.offres = []
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    vue = avis.prix_internet
    assert vue is not None
    assert vue.nb_sources == 1
    assert len(vue.offres) == 1
    assert vue.offres[0].prix == Decimal("10.0000")
    assert vue.offres[0].source_url == "https://exemple.invalid/produit-cache"
    assert vue.prix_ht_min == Decimal("10.00") == vue.prix_ht_max


async def test_vue_offres_toutes_taxes_inconnues_sans_prix_ht(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Taxes Inconnues")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    ligne = await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
    )
    ligne.taxes = None
    ligne.offres = [
        {
            "prix": prix,
            "devise": "EUR",
            "taxes": None,
            "unite": "u",
            "conditionnement": None,
            "produit_trouve": "Produit",
            "source_url": f"https://site-{prix}.exemple.invalid/p",
            "confiance": "moyenne",
        }
        for prix in ("10.0000", "9.0000")
    ]
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    vue = avis.prix_internet
    assert vue is not None
    assert vue.nb_sources == 2
    assert vue.prix_ht_min is None and vue.prix_ht_max is None
    assert [o.prix for o in vue.offres] == [Decimal("10.0000"), Decimal("9.0000")]


def test_texte_prix_demande_jusqu_a_cinq_offres_de_sites_differents() -> None:
    texte = ia_prix._texte_prix(
        fournisseur="Fournisseur Invente",
        designation="Mastic invente 300ML",
        code=None,
        unite=None,
    )

    assert "jusqu'à cinq offres" in texte
    assert "sites différents" in texte


async def test_vue_ignore_les_offres_mal_formees_en_base(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    detail = _detail_r22(produit="Produit Offres Corrompues")
    anomalie = await _creer_anomalie(
        db_session, regle="R22", detail=detail, document=facture
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    ligne = await _creer_prix_internet(
        db_session,
        cle=cle,
        statut="trouve",
        consulte_le=datetime.now(UTC),
        fournisseur_id=fournisseur.id,
    )
    valide = {
        "prix": "12.0000",
        "devise": "EUR",
        "taxes": "HT",
        "unite": "u",
        "conditionnement": None,
        "produit_trouve": "Produit",
        "source_url": "https://site-valide.exemple.invalid/p",
        "confiance": "moyenne",
    }
    ligne.offres = [
        {"devise": "EUR"},  # prix absent
        {**valide, "prix": ""},
        {**valide, "prix": "abc"},
        {**valide, "prix": "0"},
        {**valide, "prix": "-3"},
        "pas un dict",  # type: ignore[list-item]
        valide,
    ]
    await _activer_controle_prix_bl(db_session)
    await db_session.commit()

    avis = await avis_ia_anomalie(db_session, anomalie.id)

    vue = avis.prix_internet
    assert vue is not None
    assert vue.nb_sources == 1
    assert vue.offres[0].prix == Decimal("12.0000")

    # Plus aucune offre valide : retour aux colonnes de la ligne.
    ligne.offres = [{"devise": "EUR"}, 3]  # type: ignore[list-item]
    await db_session.commit()
    avis = await avis_ia_anomalie(db_session, anomalie.id)
    vue = avis.prix_internet
    assert vue is not None
    assert vue.nb_sources == 1
    assert vue.offres[0].prix == Decimal("10.0000")


def test_offre_vue_prix_aberrant_ecartee_sans_exception() -> None:
    """Relecture finale, point 1 : une offre stockée à prix hors borne
    (`0 < prix < 1 000 000`) est écartée, jamais une exception."""
    base = {"devise": "EUR", "taxes": "TTC", "source_url": "https://a.test/p"}

    assert ia_prix._offre_vue({**base, "prix": "1e100"}) is None
    assert ia_prix._offre_vue({**base, "prix": "1000000"}) is None
    assert ia_prix._offre_vue({**base, "prix": "Infinity"}) is None
    assert ia_prix._offre_vue({**base, "prix": "12.50"}) is not None


async def test_rechercher_prix_delai_300_secondes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    delais: list[float | None] = []

    async def faux_interroger(*args: Any, **kwargs: Any) -> Any:
        delais.append(kwargs.get("delai"))
        raise opencode.IAIndisponible("eteinte")

    monkeypatch.setattr(ia_prix, "interroger", faux_interroger)
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )

    with pytest.raises(opencode.IAIndisponible):
        await ia_prix.rechercher_prix(
            db_session, http, fournisseur=None, designation="P", code=None, unite=None
        )

    assert delais == [300]
