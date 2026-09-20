from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.jobs.drive import (
    ClientDriveMemoire,
    ClientGoogleDrive,
    JetonCompteServiceGoogle,
    normaliser_segment,
)

pytestmark = pytest.mark.anyio


def test_normaliser_segment_retire_accents_espaces_et_caracteres_interdits() -> None:
    assert normaliser_segment("  Dépôt / Nord : été 2026  ") == "Depot-Nord-ete-2026"


async def test_client_drive_memoire_est_idempotent(tmp_path: Path) -> None:
    chemin = tmp_path / "document.pdf"
    chemin.write_bytes(b"contenu invente")
    client = ClientDriveMemoire()

    premiere = await client.televerser(
        chemin,
        "Fournisseurs/Exemple/2026-08",
        "facture-42.pdf",
    )
    seconde = await client.televerser(
        chemin,
        "Fournisseurs/Exemple/2026-08",
        "facture-42.pdf",
    )

    assert premiere == seconde
    assert len(client.fichiers) == 1


async def test_client_google_cree_les_dossiers_et_televerse_sans_reseau(
    tmp_path: Path,
) -> None:
    chemin = tmp_path / "document.pdf"
    chemin.write_bytes(b"contenu invente")
    crees: dict[tuple[str, str], str] = {}
    fichier_id: str | None = None

    def repondre(requete: httpx.Request) -> httpx.Response:
        nonlocal fichier_id
        assert requete.headers["Authorization"] == "Bearer jeton-invente"
        if requete.method == "GET":
            assert requete.url.params["includeItemsFromAllDrives"] == "true"
            q = requete.url.params["q"]
            if "mimeType = 'application/vnd.google-apps.folder'" in q:
                trouve = next(
                    (
                        identifiant
                        for (parent, nom), identifiant in crees.items()
                        if f"'{parent}' in parents" in q and f"name = '{nom}'" in q
                    ),
                    None,
                )
                fichiers = [] if trouve is None else [{"id": trouve}]
                return httpx.Response(200, json={"files": fichiers})
            fichiers = (
                []
                if fichier_id is None
                else [
                    {
                        "id": fichier_id,
                        "webViewLink": "https://drive.example.test/fichier",
                    }
                ]
            )
            return httpx.Response(200, json={"files": fichiers})
        if requete.url.path == "/drive/v3/files":
            assert requete.url.params["supportsAllDrives"] == "true"
            corps = requete.content.decode()
            parent = corps.split('"parents":["', 1)[1].split('"', 1)[0]
            nom = corps.split('"name":"', 1)[1].split('"', 1)[0]
            identifiant = f"dossier-{len(crees) + 1}"
            crees[(parent, nom)] = identifiant
            return httpx.Response(200, json={"id": identifiant})
        fichier_id = "fichier-1"
        assert requete.url.params["supportsAllDrives"] == "true"
        content_type = requete.headers["Content-Type"]
        assert content_type.startswith("multipart/related; boundary=")
        boundary = content_type.split("boundary=", 1)[1]
        assert (
            requete.content
            == (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f'{{"name":"facture-42.pdf","parents":["{list(crees.values())[-1]}"]}}'
                "\r\n"
                f"--{boundary}\r\n"
                "Content-Type: application/pdf\r\n\r\n"
            ).encode()
            + b"contenu invente"
            + f"\r\n--{boundary}--\r\n".encode()
        )
        return httpx.Response(
            200,
            json={
                "id": fichier_id,
                "webViewLink": "https://drive.example.test/fichier",
            },
        )

    async def jeton() -> str:
        return "jeton-invente"

    async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as http:
        client = ClientGoogleDrive(http, jeton, dossier_racine_id="racine")
        premiere = await client.televerser(
            chemin, "Fournisseurs/Exemple/2026-08", "facture-42.pdf"
        )
        seconde = await client.televerser(
            chemin, "Fournisseurs/Exemple/2026-08", "facture-42.pdf"
        )

    assert premiere == "https://drive.example.test/fichier"
    assert seconde == premiere
    assert len(crees) == 3


async def test_jeton_compte_service_est_signe_et_mis_en_cache() -> None:
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cle_pem = cle.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    secret = json.dumps(
        {
            "client_email": "drive-invente@example.test",
            "private_key": cle_pem,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    appels = 0

    def repondre(requete: httpx.Request) -> httpx.Response:
        nonlocal appels
        appels += 1
        formulaire = parse_qs(requete.content.decode())
        assertion = formulaire["assertion"][0]
        charge_b64 = assertion.split(".")[1]
        charge_b64 += "=" * (-len(charge_b64) % 4)
        charge = json.loads(base64.urlsafe_b64decode(charge_b64))
        assert charge["aud"] == "https://oauth2.googleapis.com/token"
        assert charge["scope"] == "https://www.googleapis.com/auth/drive"
        return httpx.Response(
            200, json={"access_token": "jeton-invente", "expires_in": 3600}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as http:
        jetons = JetonCompteServiceGoogle(secret, http)
        premier = await jetons.obtenir()
        second = await jetons.obtenir()

    assert premier == "jeton-invente"
    assert second == premier
    assert appels == 1


async def test_compte_service_avec_algorithme_invalide_est_refuse_proprement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuser_cle(contenu: bytes, password: bytes | None) -> object:
        del contenu, password
        raise UnsupportedAlgorithm("algorithme inventé")

    monkeypatch.setattr(serialization, "load_pem_private_key", refuser_cle)
    secret = json.dumps(
        {
            "client_email": "drive-invente@example.test",
            "private_key": "cle-inventee",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="Clé de compte de service"):
            JetonCompteServiceGoogle(secret, http)


async def test_client_google_utilise_upload_resumable_au_dela_de_5_mio(
    tmp_path: Path,
) -> None:
    chemin = tmp_path / "document-volumineux.pdf"
    chemin.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    recherches = 0
    initialisations = 0
    envois = 0

    def repondre(requete: httpx.Request) -> httpx.Response:
        nonlocal recherches, initialisations, envois
        if requete.method == "GET":
            recherches += 1
            if recherches <= 3:
                return httpx.Response(200, json={"files": [{"id": f"d-{recherches}"}]})
            return httpx.Response(200, json={"files": []})
        if requete.method == "POST":
            initialisations += 1
            assert requete.url.params["uploadType"] == "resumable"
            assert requete.headers["X-Upload-Content-Length"] == str(
                5 * 1024 * 1024 + 1
            )
            return httpx.Response(
                200,
                headers={
                    "Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=invente"
                },
            )
        envois += 1
        assert requete.method == "PUT"
        assert len(requete.content) == 5 * 1024 * 1024 + 1
        return httpx.Response(
            200,
            json={"id": "fichier-1", "webViewLink": "https://drive.example.test/gros"},
        )

    async def jeton() -> str:
        return "jeton-invente"

    async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as http:
        client = ClientGoogleDrive(http, jeton, dossier_racine_id="racine")
        url = await client.televerser(
            chemin, "Fournisseurs/Exemple/2026-08", "gros-document.pdf"
        )

    assert url == "https://drive.example.test/gros"
    assert initialisations == 1
    assert envois == 1
