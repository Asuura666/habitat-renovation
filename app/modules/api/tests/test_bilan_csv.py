"""Tests des routes `GET /api/bilan/....csv` (L5-T4) : autorisation, BOM,
`Content-Type`/`Content-Disposition`, et correspondance ligne pour ligne
avec la route JSON équivalente -- voir `app/modules/ingest/tests/test_export.py`
pour la sérialisation elle-même (en-têtes, séparateur, échappement, sans
base) et `test_bilan.py` pour les scénarios détaillés des quatre montants
(non refaits ici, seul le transport CSV est propre à ce fichier).

Même schéma que `test_bilan.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test`, IP dédiées (`10.84.1.x`) pour ne jamais partager le
quota `slowapi` du login avec un autre fichier de test.
"""

from __future__ import annotations

import csv
import io
import itertools
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest.models import (
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Ligne,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.84.1.{next(_IPS)}"


# --------------------------------------------------------------------------
# Aides d'application/requête (mêmes idiomes que `test_bilan.py`)
# --------------------------------------------------------------------------


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> object:
        return get_settings().model_copy(update={"docs_dir": docs_dir})

    app_test.dependency_overrides[get_settings] = _settings_test
    return app_test


async def _creer_utilisateur(
    db_session: AsyncSession, *, email: str, role: str
) -> None:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()


async def _login(app_test: FastAPI, *, email: str) -> str:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(
            "/api/auth/login", data={"username": email, "password": _MOT_DE_PASSE}
        )
    assert reponse.status_code == 204
    cookie = reponse.cookies.get(NOM_COOKIE)
    assert cookie is not None
    return cookie


async def _requete(
    app_test: FastAPI,
    chemin: str,
    *,
    cookie: str | None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.8.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(chemin, params=params)


# --------------------------------------------------------------------------
# Aides de construction (données inventées) -- copie réduite de celles de
# `test_bilan.py` (même raison : pas d'import d'un paquet `tests` frère).
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur CSV Bilan"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession,
    *,
    nom: str = "Chantier CSV Bilan",
    agence: str | None = None,
) -> Chantier:
    chantier = Chantier(nom_canonique=nom, agence=agence)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur | None,
    numero: str = "F0001",
    date_doc: date | None = date(2026, 7, 15),
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    numero_bl: str | None = "L0001",
    chantier_id: uuid.UUID | None = None,
    statut_rapprochement: str | None = "recu",
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        statut_rapprochement=statut_rapprochement,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture,
    montant_ht: Decimal = Decimal("100.00"),
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id,
        montant_ht=montant_ht,
        type_ligne="article",
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _scenario_simple(
    db_session: AsyncSession,
    *,
    date_doc: date | None = date(2026, 7, 15),
    montant_ht: Decimal = Decimal("100.00"),
    fournisseur: Fournisseur | None = None,
) -> tuple[Chantier, Fournisseur, BlocFacture]:
    """Un chantier, un fournisseur, une facture avec un bloc et une ligne
    (données inventées) -- appelé au plus une fois par test dans ce fichier,
    donc le numéro de facture par défaut (`_creer_facture`) ne collisionne
    jamais avec la contrainte d'unicité par fournisseur."""
    chantier = await _creer_chantier(db_session)
    if fournisseur is None:
        fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, date_doc=date_doc
    )
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc, montant_ht=montant_ht)
    return chantier, fournisseur, bloc


def _lignes_csv(reponse: httpx.Response) -> list[list[str]]:
    """Décode le corps de la réponse en retirant le BOM UTF-8
    (`utf-8-sig`, jamais `utf-8` seul -- un `decode("utf-8")` laisserait le
    caractère `\\ufeff` en tête du premier champ) puis reconstitue les
    lignes avec le même séparateur que le producteur."""
    contenu = reponse.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(contenu), delimiter=";"))


def _montant_virgule(valeur_json: str) -> str:
    """Un montant du JSON reformaté comme le CSV -- constat en cours de
    tâche : un montant nul (aucune ligne ne correspond à la branche `CASE`,
    ex. `rapproche` quand rien n'est reçu) revient de l'agrégat SQL sous la
    forme `"0"`, sans les deux décimales que porte un montant non nul comme
    `"100.00"` (`ingest.bilan`, agrégats `func.sum`, hors périmètre de cette
    tâche). Le CSV normalise toujours à deux décimales (`ROUND_HALF_UP`,
    même règle que `ingest.export._formater_montant`, dupliquée ici plutôt
    qu'importée pour que ce test vérifie un résultat, pas un détail interne
    du module testé) : une comparaison par simple remplacement du point par
    une virgule échouerait donc sur ces montants nuls."""
    arrondi = Decimal(valeur_json).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{arrondi:.2f}".replace(".", ",")
    return valeur_json.replace(".", ",")


# --------------------------------------------------------------------------
# Droits (401/403/200) sur les quatre routes CSV
# --------------------------------------------------------------------------


async def test_get_bilan_chantiers_csv_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "/api/bilan/chantiers.csv", cookie=None)

    assert reponse.status_code == 401


async def test_get_bilan_chantiers_csv_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.csv1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.csv1@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers.csv", cookie=cookie)

    assert reponse.status_code == 403


async def test_get_bilan_fournisseurs_du_chantier_csv_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs.csv",
        cookie=None,
    )

    assert reponse.status_code == 401


async def test_get_bilan_fournisseurs_du_chantier_csv_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.csv2@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.csv2@example.invalid")

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs.csv",
        cookie=cookie,
    )

    assert reponse.status_code == 403


async def test_get_bilan_bl_csv_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs/{uuid.uuid4()}/bl.csv",
        cookie=None,
    )

    assert reponse.status_code == 401


async def test_get_bilan_bl_csv_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.csv3@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.csv3@example.invalid")

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs/{uuid.uuid4()}/bl.csv",
        cookie=cookie,
    )

    assert reponse.status_code == 403


async def test_get_bilan_fournisseurs_global_csv_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "/api/bilan/fournisseurs.csv", cookie=None)

    assert reponse.status_code == 401


async def test_get_bilan_fournisseurs_global_csv_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.csv4@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.csv4@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/fournisseurs.csv", cookie=cookie)

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# BOM, Content-Type, Content-Disposition (admin)
# --------------------------------------------------------------------------


async def test_get_bilan_chantiers_csv_admin_bom_content_type_et_nom_fichier(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.csv1@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv1@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers.csv", cookie=cookie)

    assert reponse.status_code == 200
    assert reponse.content.startswith(b"\xef\xbb\xbf")
    assert reponse.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        reponse.headers["content-disposition"]
        == 'attachment; filename="bilan-chantiers.csv"'
    )


async def test_get_bilan_chantiers_csv_admin_nom_fichier_dit_la_periode(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session, date_doc=date(2026, 8, 3))
    await _creer_utilisateur(
        db_session, email="admin.csv2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv2@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/bilan/chantiers.csv",
        cookie=cookie,
        params={"mois": "2026-08-01"},
    )

    assert reponse.status_code == 200
    assert (
        reponse.headers["content-disposition"]
        == 'attachment; filename="bilan-chantiers-2026-08.csv"'
    )


async def test_get_bilan_fournisseurs_du_chantier_csv_nom_fichier(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier, _fournisseur, _bloc = await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.csv3@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv3@example.invalid")

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{chantier.id}/fournisseurs.csv",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    assert reponse.content.startswith(b"\xef\xbb\xbf")
    assert (
        reponse.headers["content-disposition"]
        == 'attachment; filename="bilan-fournisseurs.csv"'
    )


async def test_get_bilan_bl_csv_nom_fichier(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier, fournisseur, _bloc = await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.csv4@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv4@example.invalid")

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{chantier.id}/fournisseurs/{fournisseur.id}/bl.csv",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    assert reponse.content.startswith(b"\xef\xbb\xbf")
    assert (
        reponse.headers["content-disposition"] == 'attachment; filename="bilan-bl.csv"'
    )


async def test_get_bilan_fournisseurs_global_csv_nom_fichier(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.csv5@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv5@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/fournisseurs.csv", cookie=cookie)

    assert reponse.status_code == 200
    assert (
        reponse.headers["content-disposition"]
        == 'attachment; filename="bilan-fournisseurs.csv"'
    )


# --------------------------------------------------------------------------
# Contenu identique, ligne pour ligne, à la route JSON équivalente
# --------------------------------------------------------------------------


async def test_get_bilan_chantiers_csv_contenu_correspond_au_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session, montant_ht=Decimal("123.45"))
    await _creer_utilisateur(
        db_session, email="admin.csv6@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv6@example.invalid")

    reponse_json = await _requete(app_test, "/api/bilan/chantiers", cookie=cookie)
    reponse_csv = await _requete(app_test, "/api/bilan/chantiers.csv", cookie=cookie)

    assert reponse_json.status_code == 200
    assert reponse_csv.status_code == 200
    lignes_json = reponse_json.json()
    lignes_csv = _lignes_csv(reponse_csv)[1:]
    assert len(lignes_csv) == len(lignes_json)
    for ligne_json, ligne_csv in zip(lignes_json, lignes_csv, strict=True):
        montants = ligne_json["montants"]
        assert ligne_csv == [
            ligne_json["nom_canonique"] or "",
            ligne_json["agence"] or "",
            _montant_virgule(montants["facture_ht"]),
            _montant_virgule(montants["rapproche"]),
            _montant_virgule(montants["en_ecart"]),
            _montant_virgule(montants["non_justifie"]),
            str(montants["nb_anomalies_ouvertes"]),
        ]


async def test_get_bilan_chantiers_csv_ligne_non_resolue_cellule_vide(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Même scénario que
    `test_bilan.test_get_bilan_chantiers_ligne_chantier_non_resolu_serialisee`
    (JSON), côté CSV : la cellule est vide, jamais la chaîne "None"."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=None)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("42.00")
    )
    await _creer_utilisateur(
        db_session, email="admin.csv7@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv7@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers.csv", cookie=cookie)

    assert reponse.status_code == 200
    lignes = _lignes_csv(reponse)
    assert lignes[1][0] == ""
    assert lignes[1][1] == ""
    assert "None" not in reponse.content.decode("utf-8-sig")


async def test_get_bilan_chantiers_csv_filtre_mois_meme_service_que_le_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Preuve que la route CSV transmet `mois` au même service que la route
    JSON (décision du contrôleur : jamais une deuxième requête) -- deux
    factures du même chantier, deux mois, le filtre doit changer le
    montant vu côté CSV exactement comme côté JSON."""
    chantier = await _creer_chantier(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    facture_juillet = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-JUIL-CSV",
        date_doc=date(2026, 7, 15),
    )
    bloc_juillet = await _creer_bloc(
        db_session, facture=facture_juillet, chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session,
        document=facture_juillet,
        bloc=bloc_juillet,
        montant_ht=Decimal("100.00"),
    )
    facture_aout = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-AOUT-CSV",
        date_doc=date(2026, 8, 3),
    )
    bloc_aout = await _creer_bloc(
        db_session, facture=facture_aout, chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session, document=facture_aout, bloc=bloc_aout, montant_ht=Decimal("250.00")
    )
    await _creer_utilisateur(
        db_session, email="admin.csv8@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv8@example.invalid")

    reponse_juillet = await _requete(
        app_test,
        "/api/bilan/chantiers.csv",
        cookie=cookie,
        params={"mois": "2026-07-01"},
    )
    reponse_aout = await _requete(
        app_test,
        "/api/bilan/chantiers.csv",
        cookie=cookie,
        params={"mois": "2026-08-01"},
    )

    assert reponse_juillet.status_code == 200
    assert reponse_aout.status_code == 200
    lignes_juillet = _lignes_csv(reponse_juillet)
    lignes_aout = _lignes_csv(reponse_aout)
    ligne_chantier_juillet = next(
        ligne for ligne in lignes_juillet[1:] if ligne[0] == "Chantier CSV Bilan"
    )
    ligne_chantier_aout = next(
        ligne for ligne in lignes_aout[1:] if ligne[0] == "Chantier CSV Bilan"
    )
    assert ligne_chantier_juillet[2] == "100,00"
    assert ligne_chantier_aout[2] == "250,00"


async def test_get_bilan_fournisseurs_du_chantier_csv_contenu_correspond_au_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier, _fournisseur, _bloc = await _scenario_simple(
        db_session, montant_ht=Decimal("55.10")
    )
    await _creer_utilisateur(
        db_session, email="admin.csv9@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv9@example.invalid")

    reponse_json = await _requete(
        app_test, f"/api/bilan/chantiers/{chantier.id}/fournisseurs", cookie=cookie
    )
    reponse_csv = await _requete(
        app_test, f"/api/bilan/chantiers/{chantier.id}/fournisseurs.csv", cookie=cookie
    )

    assert reponse_json.status_code == 200
    assert reponse_csv.status_code == 200
    lignes_json = reponse_json.json()
    lignes_csv = _lignes_csv(reponse_csv)[1:]
    assert len(lignes_csv) == len(lignes_json)
    for ligne_json, ligne_csv in zip(lignes_json, lignes_csv, strict=True):
        montants = ligne_json["montants"]
        assert ligne_csv == [
            ligne_json["nom"] or "",
            _montant_virgule(montants["facture_ht"]),
            _montant_virgule(montants["rapproche"]),
            _montant_virgule(montants["en_ecart"]),
            _montant_virgule(montants["non_justifie"]),
            str(montants["nb_anomalies_ouvertes"]),
        ]


async def test_get_bilan_fournisseurs_global_csv_contenu_correspond_au_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _chantier, _fournisseur, _bloc = await _scenario_simple(
        db_session, montant_ht=Decimal("18.75")
    )
    await _creer_utilisateur(
        db_session, email="admin.csv10@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv10@example.invalid")

    reponse_json = await _requete(app_test, "/api/bilan/fournisseurs", cookie=cookie)
    reponse_csv = await _requete(app_test, "/api/bilan/fournisseurs.csv", cookie=cookie)

    assert reponse_json.status_code == 200
    assert reponse_csv.status_code == 200
    lignes_json = reponse_json.json()
    lignes_csv = _lignes_csv(reponse_csv)[1:]
    assert len(lignes_csv) == len(lignes_json)
    for ligne_json, ligne_csv in zip(lignes_json, lignes_csv, strict=True):
        montants = ligne_json["montants"]
        assert ligne_csv == [
            ligne_json["nom"] or "",
            _montant_virgule(montants["facture_ht"]),
            _montant_virgule(montants["rapproche"]),
            _montant_virgule(montants["en_ecart"]),
            _montant_virgule(montants["non_justifie"]),
            str(montants["nb_anomalies_ouvertes"]),
        ]


async def test_get_bilan_bl_csv_contenu_correspond_au_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier, fournisseur, _bloc = await _scenario_simple(
        db_session, montant_ht=Decimal("9.99")
    )
    await _creer_utilisateur(
        db_session, email="admin.csv11@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.csv11@example.invalid")

    chemin_json = f"/api/bilan/chantiers/{chantier.id}/fournisseurs/{fournisseur.id}/bl"
    reponse_json = await _requete(app_test, chemin_json, cookie=cookie)
    reponse_csv = await _requete(app_test, f"{chemin_json}.csv", cookie=cookie)

    assert reponse_json.status_code == 200
    assert reponse_csv.status_code == 200
    lignes_json = reponse_json.json()
    lignes_csv = _lignes_csv(reponse_csv)[1:]
    assert len(lignes_csv) == len(lignes_json)
    for ligne_json, ligne_csv in zip(lignes_json, lignes_csv, strict=True):
        montants = ligne_json["montants"]
        assert ligne_csv == [
            ligne_json["numero_bl"] or "",
            ligne_json["date_bl"] or "",
            ligne_json["statut_rapprochement"] or "",
            _montant_virgule(montants["facture_ht"]),
            _montant_virgule(montants["rapproche"]),
            _montant_virgule(montants["en_ecart"]),
            _montant_virgule(montants["non_justifie"]),
            str(montants["nb_anomalies_ouvertes"]),
        ]
