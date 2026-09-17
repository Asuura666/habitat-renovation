"""`POST /api/factures` : dépôt d'une facture PDF Unikalo (L2-T4).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (jamais `extract`/`messaging` directement — garde
vérifiée par `tests/test_frontieres.py`). Réservé à l'admin (`admin_requis`,
`app/core/auth.py`) : le CDC (§4.2) réserve les factures à l'administrateur,
contrairement aux BL.

Déroulé (décisions du contrôleur, L2-T4) :
1. Lecture bornée du fichier envoyé (au plus 20 Mo + 1 octet), avant tout
   appel à `deposer_facture` -> 413 si dépassé.
2. `ingest.service.deposer_facture` fait tout le reste (signature PDF, OCR
   avec un délai de 90 s dédié aux factures via `get_ocr_facture`, analyse
   Unikalo, fournisseur, doublon, stockage atomique, insertions, journal),
   dans une seule transaction : ce routeur reste mince, aucune règle
   métier.
3. Traduction des erreurs typées de `deposer_facture` en codes HTTP : 422
   (fichier non PDF ou format non reconnu), 502 (échec de l'OCR), 409
   (doublon, avec l'identifiant de l'original — réponse construite à la
   main : `HTTPException(detail=...)` imbriquerait `original_id` sous
   `detail`, alors que le corps attendu les porte au même niveau).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.modules.ingest.router import get_ocr_facture
from app.modules.ingest.service import (
    Deposant,
    FactureEnDouble,
    FichierInvalide,
    FormatNonPrisEnCharge,
    LectureImpossible,
    deposer_facture,
)

router = APIRouter()

# Décision du contrôleur (L2-D11) : 20 Mo maximum. On lit au plus 20 Mo + 1
# octet pour détecter un dépassement sans jamais charger un fichier de
# taille illimitée en mémoire.
_TAILLE_MAX_OCTETS = 20 * 1024 * 1024


class FactureDeposeeReponse(BaseModel):
    id: uuid.UUID
    numero: str
    nb_blocs: int


def _deposant(utilisateur: Utilisateur) -> Deposant:
    return Deposant(
        id=utilisateur.id, nom_affichage=utilisateur.nom or utilisateur.email
    )


@router.post(
    "/factures",
    status_code=status.HTTP_201_CREATED,
    response_model=FactureDeposeeReponse,
)
async def deposer_facture_pdf(
    fichier: UploadFile,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    ocr: Annotated[
        Callable[[bytes, str], Awaitable[dict[str, Any]]], Depends(get_ocr_facture)
    ],
) -> FactureDeposeeReponse | JSONResponse:
    contenu = await fichier.read(_TAILLE_MAX_OCTETS + 1)
    if len(contenu) > _TAILLE_MAX_OCTETS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Fichier trop volumineux (20 Mo maximum).",
        )

    try:
        deposee = await deposer_facture(
            session, contenu, _deposant(utilisateur), settings.docs_dir, ocr
        )
    except FichierInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except LectureImpossible as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except FormatNonPrisEnCharge as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except FactureEnDouble as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Facture déjà déposée.",
                "original_id": str(exc.original_id),
            },
        )

    return FactureDeposeeReponse(
        id=deposee.id, numero=deposee.numero, nb_blocs=deposee.nb_blocs
    )
