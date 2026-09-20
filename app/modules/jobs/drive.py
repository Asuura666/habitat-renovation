"""Contrat minimal du stockage Drive et implémentations (L5-D8)."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import secrets
import time
import unicodedata
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_CARACTERES_INTERDITS = re.compile(r"[^A-Za-z0-9._-]+")
_SEPARATEURS = re.compile(r"[-_.]{2,}")


def _base64url(contenu: bytes) -> str:
    return base64.urlsafe_b64encode(contenu).rstrip(b"=").decode("ascii")


class JetonCompteServiceGoogle:
    """Fournit un jeton OAuth signé RS256, sans exposer le secret JSON."""

    _PORTEE = "https://www.googleapis.com/auth/drive"
    _URL_JETON = "https://oauth2.googleapis.com/token"

    def __init__(self, secret_json: str, http: httpx.AsyncClient) -> None:
        try:
            secret = json.loads(secret_json)
            email = secret["client_email"]
            cle_pem = secret["private_key"]
            url_jeton = secret["token_uri"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError("Compte de service Google Drive invalide") from exc
        if not all(isinstance(valeur, str) and valeur for valeur in (email, cle_pem)):
            raise ValueError("Compte de service Google Drive invalide")
        if url_jeton != self._URL_JETON:
            raise ValueError("URL de jeton Google Drive non autorisée")
        try:
            cle = serialization.load_pem_private_key(cle_pem.encode(), password=None)
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise ValueError("Clé de compte de service Google Drive invalide") from exc
        if not isinstance(cle, rsa.RSAPrivateKey):
            raise ValueError("Clé de compte de service Google Drive invalide")
        self._email = email
        self._cle = cle
        self._http = http
        self._jeton: str | None = None
        self._expire_le = 0
        self._verrou = asyncio.Lock()

    async def obtenir(self) -> str:
        async with self._verrou:
            maintenant = int(time.time())
            if self._jeton is not None and maintenant < self._expire_le - 60:
                return self._jeton

            entete = _base64url(b'{"alg":"RS256","typ":"JWT"}')
            charge = _base64url(
                json.dumps(
                    {
                        "iss": self._email,
                        "scope": self._PORTEE,
                        "aud": self._URL_JETON,
                        "iat": maintenant,
                        "exp": maintenant + 3600,
                    },
                    separators=(",", ":"),
                ).encode()
            )
            a_signer = f"{entete}.{charge}".encode("ascii")
            signature = await asyncio.to_thread(
                self._cle.sign, a_signer, padding.PKCS1v15(), hashes.SHA256()
            )
            assertion = f"{entete}.{charge}.{_base64url(signature)}"
            reponse = await self._http.post(
                self._URL_JETON,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            reponse.raise_for_status()
            resultat = reponse.json()
            jeton = resultat.get("access_token")
            expiration = resultat.get("expires_in")
            if not isinstance(jeton, str) or not isinstance(expiration, int):
                raise ValueError("Réponse OAuth Google Drive invalide")
            self._jeton = jeton
            self._expire_le = maintenant + expiration
            return jeton


_LONGUEUR_MAX = 100


def normaliser_segment(valeur: str) -> str:
    """Produit un segment stable, ASCII, sans espace ni caractère réservé."""

    sans_accents = (
        unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode("ascii")
    )
    nettoye = _CARACTERES_INTERDITS.sub("-", sans_accents.strip())
    nettoye = _SEPARATEURS.sub("-", nettoye).strip("-._")
    return nettoye[:_LONGUEUR_MAX] or "sans-nom"


class ClientDrive(Protocol):
    async def televerser(
        self,
        chemin: Path,
        dossier: str,
        nom: str,
        *,
        identifiant: str,
        identifiants_dossier: tuple[str, ...],
    ) -> str:
        """Téléverse un fichier et renvoie son URL partageable."""


class ClientDriveMemoire:
    """Double déterministe et idempotent, sans réseau, pour les tests."""

    def __init__(self) -> None:
        self.fichiers: dict[str, tuple[str, str, bytes]] = {}

    async def televerser(
        self,
        chemin: Path,
        dossier: str,
        nom: str,
        *,
        identifiant: str,
        identifiants_dossier: tuple[str, ...],
    ) -> str:
        del identifiants_dossier
        if identifiant not in self.fichiers:
            self.fichiers[identifiant] = (
                dossier,
                nom,
                await asyncio.to_thread(chemin.read_bytes),
            )
        return f"memoire://fichier/{quote(identifiant, safe='')}"


class ClientGoogleDrive:
    """Client REST Google Drive minimal : dossiers et téléversement multipart."""

    _API = "https://www.googleapis.com/drive/v3/files"
    _UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
    _DOSSIER_MIME = "application/vnd.google-apps.folder"
    _TAILLE_MULTIPART_MAX = 5 * 1024 * 1024
    _CLE_IDENTITE = "habitat_reno_id"

    def __init__(
        self,
        http: httpx.AsyncClient,
        obtenir_jeton: Callable[[], Awaitable[str]],
        *,
        dossier_racine_id: str,
    ) -> None:
        self._http = http
        self._obtenir_jeton = obtenir_jeton
        self._racine = dossier_racine_id

    async def _entetes(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._obtenir_jeton()}"}

    @staticmethod
    def _echapper(valeur: str) -> str:
        return valeur.replace("\\", "\\\\").replace("'", "\\'")

    async def _chercher(
        self, parent_id: str, *, identifiant: str, dossier: bool
    ) -> dict[str, Any] | None:
        morceaux = [
            f"'{self._echapper(parent_id)}' in parents",
            "appProperties has "
            f"{{ key='{self._CLE_IDENTITE}' and "
            f"value='{self._echapper(identifiant)}' }}",
            "trashed = false",
        ]
        if dossier:
            morceaux.append(f"mimeType = '{self._DOSSIER_MIME}'")
        reponse = await self._http.get(
            self._API,
            headers=await self._entetes(),
            params={
                "q": " and ".join(morceaux),
                "fields": "files(id,webViewLink)",
                "pageSize": "1",
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
            },
        )
        reponse.raise_for_status()
        fichiers = reponse.json().get("files", [])
        return fichiers[0] if fichiers else None

    async def _creer_dossier(
        self, parent_id: str, nom: str, *, identifiant: str
    ) -> str:
        reponse = await self._http.post(
            self._API,
            headers={**await self._entetes(), "Content-Type": "application/json"},
            content=json.dumps(
                {
                    "name": nom,
                    "mimeType": self._DOSSIER_MIME,
                    "parents": [parent_id],
                    "appProperties": {self._CLE_IDENTITE: identifiant},
                },
                separators=(",", ":"),
            ),
            params={"fields": "id", "supportsAllDrives": "true"},
        )
        reponse.raise_for_status()
        return str(reponse.json()["id"])

    async def _assurer_dossier(
        self, parent_id: str, nom: str, *, identifiant: str
    ) -> str:
        existant = await self._chercher(
            parent_id, identifiant=identifiant, dossier=True
        )
        if existant is not None:
            return str(existant["id"])
        return await self._creer_dossier(parent_id, nom, identifiant=identifiant)

    @staticmethod
    def _url_resultat(resultat: dict[str, Any]) -> str:
        return str(
            resultat.get("webViewLink")
            or f"https://drive.google.com/file/d/{resultat['id']}/view"
        )

    async def _televerser_resumable(
        self,
        contenu: bytes,
        metadonnees: str,
        type_mime: str,
    ) -> str:
        initialisation = await self._http.post(
            self._UPLOAD,
            headers={
                **await self._entetes(),
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": type_mime,
                "X-Upload-Content-Length": str(len(contenu)),
            },
            params={
                "uploadType": "resumable",
                "fields": "id,webViewLink",
                "supportsAllDrives": "true",
            },
            content=metadonnees,
        )
        initialisation.raise_for_status()
        url_session = initialisation.headers.get("Location")
        if url_session is None:
            raise ValueError("Réponse Drive sans URL de téléversement")
        url_analysee = urlparse(url_session)
        if (
            url_analysee.scheme != "https"
            or url_analysee.hostname != "www.googleapis.com"
            or url_analysee.path != "/upload/drive/v3/files"
        ):
            raise ValueError("URL de téléversement Drive non autorisée")
        reponse = await self._http.put(
            url_session,
            headers={
                "Content-Type": type_mime,
                "Content-Length": str(len(contenu)),
            },
            content=contenu,
        )
        reponse.raise_for_status()
        return self._url_resultat(reponse.json())

    async def televerser(
        self,
        chemin: Path,
        dossier: str,
        nom: str,
        *,
        identifiant: str,
        identifiants_dossier: tuple[str, ...],
    ) -> str:
        parent_id = self._racine
        segments = dossier.split("/")
        if len(segments) != len(identifiants_dossier):
            raise ValueError("Identités de dossiers Drive incohérentes")
        for segment, identifiant_dossier in zip(
            segments, identifiants_dossier, strict=True
        ):
            parent_id = await self._assurer_dossier(
                parent_id, segment, identifiant=identifiant_dossier
            )

        existant = await self._chercher(
            parent_id, identifiant=identifiant, dossier=False
        )
        if existant is not None:
            return str(
                existant.get("webViewLink")
                or f"https://drive.google.com/file/d/{existant['id']}/view"
            )

        contenu = await asyncio.to_thread(chemin.read_bytes)
        type_mime = mimetypes.guess_type(nom)[0] or "application/octet-stream"
        metadonnees = json.dumps(
            {
                "name": nom,
                "parents": [parent_id],
                "appProperties": {self._CLE_IDENTITE: identifiant},
            },
            separators=(",", ":"),
        )
        if len(contenu) > self._TAILLE_MULTIPART_MAX:
            return await self._televerser_resumable(contenu, metadonnees, type_mime)
        boundary = f"habitat-reno-{secrets.token_hex(16)}"
        corps = (
            (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadonnees}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {type_mime}\r\n\r\n"
            ).encode()
            + contenu
            + f"\r\n--{boundary}--\r\n".encode()
        )
        reponse = await self._http.post(
            self._UPLOAD,
            headers={
                **await self._entetes(),
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            params={
                "uploadType": "multipart",
                "fields": "id,webViewLink",
                "supportsAllDrives": "true",
            },
            content=corps,
        )
        reponse.raise_for_status()
        return self._url_resultat(reponse.json())
