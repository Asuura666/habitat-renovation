from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.ingest.models import Chantier, Document, Fournisseur
from app.modules.jobs.drive import ClientDriveMemoire
from app.modules.jobs.drive_sync import synchroniser_documents

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _document(
    session: AsyncSession,
    tmp_path: Path,
    *,
    fournisseur_nom: str = "Fournisseur Été / Sud",
    chantier_nom: str = "Chantier Démo",
    numero: str = "F-42 / test",
    fichier_nom: str = "document invente.pdf",
) -> Document:
    fournisseur = Fournisseur(nom=fournisseur_nom)
    chantier = Chantier(nom_canonique=chantier_nom)
    session.add_all([fournisseur, chantier])
    await session.flush()
    chemin = tmp_path / fichier_nom
    chemin.write_bytes(b"contenu invente")
    document = Document(
        type="facture",
        fournisseur_id=fournisseur.id,
        chantier_id=chantier.id,
        numero=numero,
        date_doc=date(2026, 8, 15),
        fichier_path=str(chemin),
        source="upload",
        statut="recu",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def test_destinations_visibles_restent_contractuelles_sans_collision_au_rejeu(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    premier = await _document(
        db_session,
        tmp_path,
        fournisseur_nom="Fournisseur A/B",
        chantier_nom="Chantier A/B",
        numero="F/42",
        fichier_nom="premier.pdf",
    )
    second = await _document(
        db_session,
        tmp_path,
        fournisseur_nom="Fournisseur A B",
        chantier_nom="Chantier A B",
        numero="F 42",
        fichier_nom="second.pdf",
    )
    client = ClientDriveMemoire()

    premier_passage = await synchroniser_documents(db_session, client, limite=10)

    for document in (premier, second):
        document.drive_url = None
        document.drive_sync_le = None
        document.drive_sync_tentative_le = None
    await db_session.commit()
    rejeu = await synchroniser_documents(db_session, client, limite=10)

    assert premier_passage.reussis == 2
    assert rejeu.reussis == 2
    assert len(client.fichiers) == 2
    chemins_visibles = [
        f"{dossier}/{nom}" for dossier, nom, _contenu in client.fichiers.values()
    ]
    assert chemins_visibles == [
        "Fournisseurs/Fournisseur-A-B/2026-08/facture_F-42_Chantier-A-B.pdf",
        "Fournisseurs/Fournisseur-A-B/2026-08/facture_F-42_Chantier-A-B.pdf",
    ]
    assert all(str(premier.fournisseur_id) not in chemin for chemin in chemins_visibles)
    assert all(str(second.fournisseur_id) not in chemin for chemin in chemins_visibles)
    assert all(str(premier.id) not in chemin for chemin in chemins_visibles)
    assert all(str(second.id) not in chemin for chemin in chemins_visibles)
    assert premier.drive_url != second.drive_url


async def test_synchroniser_documents_prend_un_verrou_advisory_transactionnel(
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    requetes: list[str] = []

    def memoriser_requete(
        connexion: object,
        curseur: object,
        requete: str,
        parametres: object,
        contexte: object,
        nombreux: bool,
    ) -> None:
        del connexion, curseur, parametres, contexte, nombreux
        requetes.append(requete)

    event.listen(db_engine.sync_engine, "before_cursor_execute", memoriser_requete)
    try:
        await synchroniser_documents(db_session, ClientDriveMemoire(), limite=1)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", memoriser_requete)

    assert any("pg_advisory_xact_lock" in requete for requete in requetes)


async def test_synchroniser_document_construit_chemin_et_nom_normalises(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    document = await _document(db_session, tmp_path)
    client = ClientDriveMemoire()

    resultat = await synchroniser_documents(db_session, client, limite=10)

    assert resultat.reussis == 1
    assert list(client.fichiers.values()) == [
        (
            "Fournisseurs/Fournisseur-Ete-Sud/2026-08",
            "facture_F-42-test_Chantier-Demo.pdf",
            b"contenu invente",
        )
    ]
    await db_session.refresh(document)
    assert document.drive_url is not None
    assert document.drive_sync_le is not None


async def test_synchroniser_document_est_idempotent(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await _document(db_session, tmp_path)
    client = ClientDriveMemoire()

    premier = await synchroniser_documents(db_session, client, limite=10)
    second = await synchroniser_documents(db_session, client, limite=10)

    assert premier.reussis == 1
    assert second.traites == 0
    assert len(client.fichiers) == 1


class _ClientInstable:
    def __init__(self) -> None:
        self.appels = 0

    async def televerser(
        self,
        chemin: Path,
        dossier: str,
        nom: str,
        *,
        identifiant: str,
        identifiants_dossier: tuple[str, ...],
    ) -> str:
        del chemin, dossier, nom
        self.appels += 1
        if self.appels == 1:
            raise RuntimeError("échec inventé")
        return "https://drive.example.test/fichier-invente"


async def test_echec_est_reessaye_et_efface_apres_succes(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    document = await _document(db_session, tmp_path)
    client = _ClientInstable()
    maintenant = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

    echec = await synchroniser_documents(
        db_session, client, limite=10, maintenant=maintenant
    )
    succes = await synchroniser_documents(
        db_session, client, limite=10, maintenant=maintenant + timedelta(minutes=1)
    )

    assert echec.echecs == 1
    assert succes.reussis == 1
    await db_session.refresh(document)
    assert document.drive_sync_echec_le is None
    assert document.drive_sync_erreur is None


class _ClientToujoursEnEchec:
    async def televerser(
        self,
        chemin: Path,
        dossier: str,
        nom: str,
        *,
        identifiant: str,
        identifiants_dossier: tuple[str, ...],
    ) -> str:
        del chemin, dossier, nom
        raise RuntimeError("échec inventé")


class _ClientEchecSurChemin:
    def __init__(self, chemin_en_echec: str) -> None:
        self._chemin_en_echec = Path(chemin_en_echec)

    async def televerser(
        self,
        chemin: Path,
        dossier: str,
        nom: str,
        *,
        identifiant: str,
        identifiants_dossier: tuple[str, ...],
    ) -> str:
        del dossier, nom
        if chemin == self._chemin_en_echec:
            raise RuntimeError("échec inventé")
        return "https://drive.example.test/fichier-invente"


async def test_un_echec_ancien_ne_prive_pas_un_nouveau_document_du_lot(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    ancien = await _document(db_session, tmp_path)
    client = _ClientEchecSurChemin(ancien.fichier_path)
    debut = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    await synchroniser_documents(db_session, client, limite=1, maintenant=debut)
    nouveau = await _document(
        db_session,
        tmp_path,
        fournisseur_nom="Nouveau fournisseur",
        chantier_nom="Nouveau chantier",
        numero="N-1",
        fichier_nom="nouveau.pdf",
    )

    resultat = await synchroniser_documents(
        db_session, client, limite=1, maintenant=debut + timedelta(minutes=1)
    )

    assert resultat.reussis == 1
    await db_session.refresh(ancien)
    await db_session.refresh(nouveau)
    assert ancien.drive_sync_le is None
    assert nouveau.drive_sync_le is not None
    assert ancien.drive_sync_echec_le == debut


async def test_limite_un_alterne_nouveau_et_reessai_sans_famine(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    ancien = await _document(db_session, tmp_path)
    client = _ClientEchecSurChemin(ancien.fichier_path)
    debut = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    await synchroniser_documents(db_session, client, limite=1, maintenant=debut)
    await _document(
        db_session,
        tmp_path,
        fournisseur_nom="Nouveau fournisseur 1",
        fichier_nom="nouveau-1.pdf",
    )
    await _document(
        db_session,
        tmp_path,
        fournisseur_nom="Nouveau fournisseur 2",
        fichier_nom="nouveau-2.pdf",
    )

    nouveau = await synchroniser_documents(
        db_session, client, limite=1, maintenant=debut + timedelta(minutes=1)
    )
    reessai = await synchroniser_documents(
        db_session, client, limite=1, maintenant=debut + timedelta(hours=1)
    )

    assert nouveau.reussis == 1
    assert reessai.echecs == 1


async def test_echec_vieux_de_24h_est_signale_une_seule_fois(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await _document(db_session, tmp_path)
    client = _ClientToujoursEnEchec()
    signaux: list[str] = []

    async def signaler(message: str) -> None:
        signaux.append(message)

    debut = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    await synchroniser_documents(
        db_session, client, limite=10, maintenant=debut, signaler=signaler
    )
    apres_25h = await synchroniser_documents(
        db_session,
        client,
        limite=10,
        maintenant=debut + timedelta(hours=25),
        signaler=signaler,
    )
    apres_50h = await synchroniser_documents(
        db_session,
        client,
        limite=10,
        maintenant=debut + timedelta(hours=50),
        signaler=signaler,
    )

    assert apres_25h.signales == 1
    assert apres_50h.signales == 0
    assert len(signaux) == 1
    assert "document interne" in signaux[0]


async def test_signalement_n_est_pas_retente_si_l_envoi_externe_echoue(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    document = await _document(db_session, tmp_path)
    client = _ClientToujoursEnEchec()
    appels = 0

    async def signaler(message: str) -> None:
        nonlocal appels
        del message
        appels += 1
        raise RuntimeError("échec Telegram inventé")

    debut = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    await synchroniser_documents(db_session, client, limite=10, maintenant=debut)
    await synchroniser_documents(
        db_session,
        client,
        limite=10,
        maintenant=debut + timedelta(hours=25),
        signaler=signaler,
    )
    await synchroniser_documents(
        db_session,
        client,
        limite=10,
        maintenant=debut + timedelta(hours=50),
        signaler=signaler,
    )

    assert appels == 1
    await db_session.refresh(document)
    assert document.drive_sync_signale_le == debut + timedelta(hours=25)
