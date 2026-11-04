"""`GET /api/grilles/modele`, `GET /api/grilles/fournisseurs/{id}` (et son
historique et ses contestations de prix),
`POST /api/grilles/fournisseurs/{id}/prix`, `/retrait`, `/import/apercu` et
`/import` (phase 3, tâche P4, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §10).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`).
Toutes les routes sont réservées à l'admin (`admin_requis`, spec §9 : « Admin
seulement ») : ni les grilles ni le contrôle des prix ne regardent l'agent
de terrain.

Lecture bornée du fichier de grille (même principe que `api/factures.py`) :
5 Mo + 1 octet au plus, `413` au-delà -- avant tout appel à
`ingest.grilles.apercu_import`/`importer_grille` (spec §7.2).

Aucune règle métier ici : ce routeur valide, appelle `ingest.grilles`,
sérialise -- toute la logique (comparaison au prix en vigueur, historique
inaltérable, écriture disque) vit dans `ingest/grilles.py`."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.fuseau import FUSEAU_PARIS
from app.modules.api.schemas import (
    ApercuImportReponse,
    ContestationReponse,
    EntreeHistoriqueReponse,
    GrilleFournisseurReponse,
    ImportEffectueReponse,
    LigneHistoriqueReponse,
    ProduitGrilleReponse,
    RetraitProduitRequete,
    SaisiePrixRequete,
)
from app.modules.ingest.contestations_prix import contestations_du_fournisseur
from app.modules.ingest.grilles import (
    AucuneLigneValide,
    EcritureImpossible,
    FichierGrilleInvalide,
    FournisseurIntrouvable,
    PrixInchange,
    ProduitIntrouvable,
    SaisieInvalide,
    SaisiePrix,
    apercu_import,
    enregistrer_prix,
    historique_produit,
    importer_grille,
    lister_grille,
    modele_excel,
    retirer_produit,
)
from app.modules.ingest.historique_prix import historique_complet

router = APIRouter()

# 5 Mo maximum (spec §7.2) : lu en 5 Mo + 1 octet pour détecter un
# dépassement sans jamais charger un fichier de taille illimitée en mémoire
# (même principe que `api.factures._TAILLE_MAX_OCTETS`).
_TAILLE_MAX_GRILLE_OCTETS = 5 * 1024 * 1024

_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _erreur_fournisseur_introuvable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="fournisseur introuvable"
    )


async def _lire_fichier_grille(fichier: UploadFile) -> bytes:
    contenu = await fichier.read(_TAILLE_MAX_GRILLE_OCTETS + 1)
    if len(contenu) > _TAILLE_MAX_GRILLE_OCTETS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Fichier trop volumineux (5 Mo maximum).",
        )
    return contenu


@router.get("/grilles/modele")
async def modele_grille_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
) -> Response:
    del utilisateur
    contenu = modele_excel()
    return Response(
        content=contenu,
        media_type=_MIME_XLSX,
        headers={
            "Content-Disposition": ('attachment; filename="modele-grille-de-prix.xlsx"')
        },
    )


@router.get(
    "/grilles/fournisseurs/{fournisseur_id}",
    response_model=GrilleFournisseurReponse,
)
async def grille_fournisseur_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    recherche: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> GrilleFournisseurReponse:
    del utilisateur
    try:
        grille = await lister_grille(
            session, fournisseur_id, recherche=recherche, page=page
        )
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    return GrilleFournisseurReponse.model_validate(grille)


@router.get(
    "/grilles/fournisseurs/{fournisseur_id}/produits/{cle_produit}/historique",
    response_model=list[LigneHistoriqueReponse],
)
async def historique_produit_endpoint(
    fournisseur_id: uuid.UUID,
    cle_produit: str,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LigneHistoriqueReponse]:
    del utilisateur
    try:
        historique = await historique_produit(session, fournisseur_id, cle_produit)
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    except ProduitIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="produit introuvable"
        ) from exc
    return [LigneHistoriqueReponse.model_validate(ligne) for ligne in historique]


@router.get(
    "/grilles/fournisseurs/{fournisseur_id}/produits/{cle_produit}/historique-complet",
    response_model=list[EntreeHistoriqueReponse],
)
async def historique_complet_endpoint(
    fournisseur_id: uuid.UUID,
    cle_produit: str,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[EntreeHistoriqueReponse]:
    """Lot 2 du 31/10/2026 (B4) : tout l'historique d'un produit -- versions
    de la grille, prix vus sur les bons et factures du fournisseur, prix
    observés importés. Trié par date décroissante, 100 lignes au plus."""
    del utilisateur
    try:
        entrees = await historique_complet(session, fournisseur_id, cle_produit)
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    return [EntreeHistoriqueReponse.model_validate(entree) for entree in entrees]


@router.get(
    "/grilles/fournisseurs/{fournisseur_id}/contestations",
    response_model=list[ContestationReponse],
)
async def contestations_fournisseur_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContestationReponse]:
    del utilisateur
    try:
        contestations = await contestations_du_fournisseur(session, fournisseur_id)
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    return [ContestationReponse.model_validate(c) for c in contestations]


@router.post(
    "/grilles/fournisseurs/{fournisseur_id}/prix",
    status_code=status.HTTP_201_CREATED,
    response_model=ProduitGrilleReponse,
)
async def enregistrer_prix_endpoint(
    fournisseur_id: uuid.UUID,
    requete: SaisiePrixRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProduitGrilleReponse:
    date_effet = requete.date_effet or datetime.now(FUSEAU_PARIS).date()
    saisie = SaisiePrix(
        designation=requete.designation,
        prix_ht=requete.prix_ht,
        date_effet=date_effet,
        reference=requete.reference,
        unite=requete.unite,
        remise_pct=requete.remise_pct,
        marque=requete.marque,
        famille=requete.famille,
    )
    try:
        produit = await enregistrer_prix(
            session, fournisseur_id, saisie, auteur_id=utilisateur.id
        )
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    except (SaisieInvalide, PrixInchange) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ProduitGrilleReponse.model_validate(produit)


@router.post("/grilles/fournisseurs/{fournisseur_id}/retrait")
async def retirer_produit_endpoint(
    fournisseur_id: uuid.UUID,
    requete: RetraitProduitRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    try:
        await retirer_produit(
            session,
            fournisseur_id,
            requete.cle_produit,
            requete.date_effet,
            auteur_id=utilisateur.id,
        )
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    except ProduitIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="produit introuvable"
        ) from exc
    return {"detail": "produit retiré de la grille"}


@router.post(
    "/grilles/fournisseurs/{fournisseur_id}/import/apercu",
    response_model=ApercuImportReponse,
)
async def apercu_import_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    fichier: UploadFile,
    date_effet: Annotated[date, Form()],
) -> ApercuImportReponse:
    del utilisateur
    contenu = await _lire_fichier_grille(fichier)
    try:
        apercu = await apercu_import(
            session,
            fournisseur_id,
            contenu,
            fichier.filename or "grille.xlsx",
            date_effet,
        )
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    except SaisieInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except FichierGrilleInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ApercuImportReponse.model_validate(apercu)


@router.post(
    "/grilles/fournisseurs/{fournisseur_id}/import",
    status_code=status.HTTP_201_CREATED,
    response_model=ImportEffectueReponse,
)
async def importer_grille_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    fichier: UploadFile,
    date_effet: Annotated[date, Form()],
) -> ImportEffectueReponse:
    contenu = await _lire_fichier_grille(fichier)
    try:
        resultat = await importer_grille(
            session,
            fournisseur_id,
            contenu,
            fichier.filename or "grille.xlsx",
            date_effet,
            auteur_id=utilisateur.id,
            docs_dir=settings.docs_dir,
        )
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    except SaisieInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except FichierGrilleInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except AucuneLigneValide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except EcritureImpossible as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return ImportEffectueReponse.model_validate(resultat)
