"""`GET /api/documents` et `GET /api/documents/{id}/fichier` (L2-T5) :
lecture des BL et enlèvements. `GET /api/documents/{id}`, `PATCH
/api/documents/{id}`, `PUT /api/documents/{id}/lignes`, `POST
/api/documents/{id}/validation`, `POST /api/documents/{id}/archivage` et
`POST /api/documents/{id}/extraction` (L3-T8a) : détail, correction,
validation, archivage et relance — voir `ingest/corrections.py` pour toute
la logique métier.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (jamais `extract`/`messaging` directement — garde
vérifiée par `tests/test_frontieres.py`). `GET /api/documents` et `GET
/api/documents/{id}` sont ouverts aux deux rôles (`utilisateur_courant`) :
le CDC réserve les factures à l'admin, pas les BL — `ingest.lecture
.lister_documents`/`fichier_document`/`ingest.corrections.detail_document`
décident seuls de ce que chaque rôle voit (aucune règle ici, décision du
contrôleur). Toutes les écritures (`PATCH`, `PUT`, les trois `POST`) sont
réservées à l'admin (`admin_requis`) : un agent reçoit 403 avant tout accès
au service.

`limite` (`1..500`, défaut 100) est une borne de requête HTTP, pas une règle
métier : elle est validée ici par FastAPI (`Query(ge=..., le=...)`), comme la
taille maximale du fichier dans `factures.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis, utilisateur_courant
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.modules.api.schemas import (
    ArchivageRequete,
    CorrectionEnteteRequete,
    DocumentDetailReponse,
    DocumentReponse,
    LignesRequete,
)
from app.modules.ingest.corrections import (
    CorrectionEntete,
    DocumentNonModifiable,
    FournisseurIntrouvable,
    LigneInconnue,
    LigneSaisie,
    NumeroDejaUtilise,
    ValidationRefusee,
    archiver_document,
    corriger_entete,
    corriger_lignes,
    detail_document,
    relancer_extraction,
    valider_document,
)
from app.modules.ingest.factures import LectureImpossible
from app.modules.ingest.lecture import (
    LIMITE_DOCUMENTS_DEFAUT,
    LIMITE_DOCUMENTS_MAX,
    LIMITE_DOCUMENTS_MIN,
    DocumentIntrouvable,
    fichier_document,
    lister_documents,
)
from app.modules.ingest.router import get_ocr

router = APIRouter()


@router.get("/documents", response_model=list[DocumentReponse])
async def lister_documents_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
    depuis: Annotated[datetime | None, Query()] = None,
    limite: Annotated[
        int, Query(ge=LIMITE_DOCUMENTS_MIN, le=LIMITE_DOCUMENTS_MAX)
    ] = LIMITE_DOCUMENTS_DEFAUT,
) -> list[DocumentReponse]:
    resumes = await lister_documents(
        session,
        utilisateur_id=utilisateur.id,
        role=utilisateur.role,
        depuis=depuis,
        limite=limite,
    )
    return [DocumentReponse.model_validate(resume) for resume in resumes]


@router.get("/documents/{document_id}/fichier")
async def telecharger_document(
    document_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    try:
        fichier = await fichier_document(
            session,
            document_id,
            settings.docs_dir,
            utilisateur_id=utilisateur.id,
            role=utilisateur.role,
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    return FileResponse(fichier.chemin, media_type=fichier.type_mime)


# --------------------------------------------------------------------------
# Détail, correction, validation, archivage, relance (L3-T8a)
# --------------------------------------------------------------------------


@router.get("/documents/{document_id}", response_model=DocumentDetailReponse)
async def obtenir_document(
    document_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetailReponse:
    try:
        detail = await detail_document(
            session, document_id, utilisateur_id=utilisateur.id, role=utilisateur.role
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    return DocumentDetailReponse.model_validate(detail)


@router.patch("/documents/{document_id}", response_model=DocumentDetailReponse)
async def corriger_entete_endpoint(
    document_id: uuid.UUID,
    requete: CorrectionEnteteRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetailReponse | JSONResponse:
    valeurs = {champ: getattr(requete, champ) for champ in requete.model_fields_set}
    try:
        detail = await corriger_entete(
            session,
            document_id,
            CorrectionEntete(valeurs=valeurs),
            auteur_id=utilisateur.id,
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    except DocumentNonModifiable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document non modifiable"
        ) from exc
    except FournisseurIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="fournisseur introuvable",
        ) from exc
    except NumeroDejaUtilise as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "numéro déjà utilisé.",
                "original_id": str(exc.original_id),
            },
        )
    return DocumentDetailReponse.model_validate(detail)


@router.put("/documents/{document_id}/lignes", response_model=DocumentDetailReponse)
async def corriger_lignes_endpoint(
    document_id: uuid.UUID,
    requete: LignesRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetailReponse:
    lignes = [
        LigneSaisie(
            id=ligne.id,
            code_brut=ligne.code_brut,
            article_brut=ligne.article_brut,
            qte_livree=ligne.qte_livree,
            qte_totale=ligne.qte_totale,
            unite_brut=ligne.unite_brut,
            pu_ht=ligne.pu_ht,
            montant_ht=ligne.montant_ht,
        )
        for ligne in requete.lignes
    ]
    try:
        detail = await corriger_lignes(
            session, document_id, lignes, auteur_id=utilisateur.id
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    except DocumentNonModifiable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document non modifiable"
        ) from exc
    except LigneInconnue as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="ligne inconnue"
        ) from exc
    return DocumentDetailReponse.model_validate(detail)


@router.post(
    "/documents/{document_id}/validation", response_model=DocumentDetailReponse
)
async def valider_document_endpoint(
    document_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetailReponse | JSONResponse:
    try:
        detail = await valider_document(session, document_id, auteur_id=utilisateur.id)
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    except DocumentNonModifiable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="document non « à vérifier »",
        ) from exc
    except ValidationRefusee as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "validation refusée, des anomalies subsistent.",
                "motifs": [
                    {"code": motif.code, "champ": motif.champ, "detail": motif.detail}
                    for motif in exc.motifs
                ],
            },
        )
    return DocumentDetailReponse.model_validate(detail)


@router.post("/documents/{document_id}/archivage", response_model=DocumentDetailReponse)
async def archiver_document_endpoint(
    document_id: uuid.UUID,
    requete: ArchivageRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetailReponse:
    try:
        detail = await archiver_document(
            session,
            document_id,
            commentaire=requete.commentaire,
            auteur_id=utilisateur.id,
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    except DocumentNonModifiable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="document non modifiable"
        ) from exc
    return DocumentDetailReponse.model_validate(detail)


@router.post(
    "/documents/{document_id}/extraction", response_model=DocumentDetailReponse
)
async def relancer_extraction_endpoint(
    document_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    ocr: Annotated[Callable[[bytes, str], Awaitable[dict[str, Any]]], Depends(get_ocr)],
) -> DocumentDetailReponse:
    try:
        detail = await relancer_extraction(
            session, document_id, settings.docs_dir, ocr, auteur_id=utilisateur.id
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    except DocumentNonModifiable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="document non « à vérifier »",
        ) from exc
    except LectureImpossible as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return DocumentDetailReponse.model_validate(detail)
