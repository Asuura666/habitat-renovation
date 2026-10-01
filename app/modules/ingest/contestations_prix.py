"""Contestations de prix (spec 2026-10-01 §4 et §5) : lecture des alertes de
prix contestées depuis la page Prix (`ingest.prix_bl.contester_prix`), pour
la grille du fournisseur (`contestations_du_fournisseur`) et pour la synthèse
de la semaine (`charger_contestations`).

Aucune table propre : une contestation est une alerte de prix (R19-R25)
`traitee` dont le commentaire commence par `PREFIXE_CONTESTATION`, sur un bon
non archivé ; une ligne de bon et un commentaire donnent une seule
contestation (R19 et R20 contestées ensemble n'en font qu'une)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.grilles import FournisseurIntrouvable, prix_en_vigueur
from app.modules.ingest.models import (
    Anomalie,
    Document,
    Fournisseur,
    Ligne,
    Utilisateur,
)
from app.modules.ingest.prix_bl import PREFIXE_CONTESTATION, cle_produit_alerte
from app.modules.rules.engine import REGLES_PRIX_BL

CONTESTATIONS_MAX = 500
_TIRET = "—"


@dataclass(frozen=True)
class Contestation:
    """Une contestation (une ligne de bon) -- `dans_la_grille` n'est
    renseigné que par `contestations_du_fournisseur`."""

    conteste_le: datetime
    auteur: str | None
    fournisseur_id: uuid.UUID
    fournisseur_nom: str
    document_id: uuid.UUID
    numero_bon: str | None
    date_bon: date | None
    produit: str
    code: str | None
    prix_bon: Decimal | None
    unite_bon: str | None
    prix_grille: Decimal | None
    regles: tuple[str, ...]
    commentaire: str
    cle_produit: str
    dans_la_grille: bool = False


def _texte_utile(valeur: object) -> str | None:
    """Valeur de `detail` utilisable : texte non vide et différent du tiret
    que les règles écrivent à la place d'une valeur absente."""
    if not isinstance(valeur, str):
        return None
    nettoyee = valeur.strip()
    if not nettoyee or nettoyee == _TIRET:
        return None
    return nettoyee


def _premiere_valeur(anomalies: Sequence[Anomalie], cle: str) -> str | None:
    for anomalie in anomalies:
        valeur = _texte_utile(anomalie.detail.get(cle))
        if valeur is not None:
            return valeur
    return None


def _decimal_ou_aucun(valeur: str | None) -> Decimal | None:
    if valeur is None:
        return None
    try:
        return Decimal(valeur)
    except InvalidOperation:
        return None


async def charger_contestations(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None = None,
    depuis: datetime | None = None,
    avant: datetime | None = None,
    limite: int = CONTESTATIONS_MAX,
) -> list[Contestation]:
    """Contestations, plus récentes d'abord (`traitee_le` décroissant),
    `limite` au plus -- filtrées par fournisseur et/ou par date de
    contestation (`depuis` inclus, `avant` exclu)."""
    conditions = [
        Anomalie.statut == "traitee",
        Anomalie.regle.in_(tuple(REGLES_PRIX_BL)),
        Anomalie.commentaire.startswith(PREFIXE_CONTESTATION, autoescape=True),
        Anomalie.ligne_id.is_not(None),
        Anomalie.traitee_le.is_not(None),
        Document.statut != "archive",
    ]
    if fournisseur_id is not None:
        conditions.append(Document.fournisseur_id == fournisseur_id)
    if depuis is not None:
        conditions.append(Anomalie.traitee_le >= depuis)
    if avant is not None:
        conditions.append(Anomalie.traitee_le < avant)

    resultat = await session.execute(
        select(
            Anomalie,
            Ligne,
            Document,
            Fournisseur.nom,
            Utilisateur.nom,
            Utilisateur.email,
        )
        .join(Ligne, Ligne.id == Anomalie.ligne_id)
        .join(Document, Document.id == Anomalie.document_id)
        .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .outerjoin(Utilisateur, Utilisateur.id == Anomalie.traitee_par)
        .where(*conditions)
        .order_by(Anomalie.traitee_le.desc(), Anomalie.id)
    )

    # Une contestation = une ligne de bon + un commentaire ; l'ordre de la
    # requête garde chaque groupe à la place de sa contestation la plus récente.
    groupes: dict[tuple[uuid.UUID, str], list[Anomalie]] = {}
    tetes: dict[
        tuple[uuid.UUID, str], tuple[Ligne, Document, str, str | None, str]
    ] = {}
    for (
        anomalie,
        ligne,
        document,
        fournisseur_nom,
        auteur_nom,
        auteur_email,
    ) in resultat.all():
        cle = (ligne.id, anomalie.commentaire or "")
        if cle not in groupes:
            groupes[cle] = []
            tetes[cle] = (
                ligne,
                document,
                fournisseur_nom,
                auteur_nom,
                auteur_email,
            )
        groupes[cle].append(anomalie)

    contestations: list[Contestation] = []
    for cle, anomalies in list(groupes.items())[:limite]:
        ligne, document, fournisseur_nom, auteur_nom, auteur_email = tetes[cle]
        plus_recente = anomalies[0]
        if plus_recente.traitee_le is None or document.fournisseur_id is None:
            continue  # exclu par la requête, pour le typage seulement
        contestations.append(
            Contestation(
                conteste_le=plus_recente.traitee_le,
                auteur=auteur_nom or auteur_email,
                fournisseur_id=document.fournisseur_id,
                fournisseur_nom=fournisseur_nom,
                document_id=document.id,
                numero_bon=document.numero,
                date_bon=document.date_doc,
                produit=_premiere_valeur(anomalies, "produit")
                or ligne.article_brut
                or _TIRET,
                code=_premiere_valeur(anomalies, "code"),
                prix_bon=_decimal_ou_aucun(_premiere_valeur(anomalies, "prix_bon")),
                unite_bon=_premiere_valeur(anomalies, "unite_bon"),
                prix_grille=_decimal_ou_aucun(
                    _premiere_valeur(anomalies, "prix_grille")
                ),
                regles=tuple(sorted({a.regle for a in anomalies})),
                commentaire=(plus_recente.commentaire or "").removeprefix(
                    PREFIXE_CONTESTATION
                ),
                cle_produit=cle_produit_alerte(ligne, anomalies),
            )
        )
    return contestations


async def contestations_du_fournisseur(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> list[Contestation]:
    """Contestations d'un fournisseur pour sa grille (spec 2026-10-01 §4.1) :
    `dans_la_grille` vaut vrai si la clé produit correspond à un produit
    actuellement dans sa grille (un produit retiré n'y est plus). Lève
    `FournisseurIntrouvable`."""
    if await session.get(Fournisseur, fournisseur_id) is None:
        raise FournisseurIntrouvable(str(fournisseur_id))
    contestations = await charger_contestations(session, fournisseur_id=fournisseur_id)
    if not contestations:
        return []
    en_vigueur = await prix_en_vigueur(
        session,
        fournisseur_id,
        datetime.now(FUSEAU_PARIS).date(),
        cles={c.cle_produit for c in contestations},
    )
    return [
        replace(c, dans_la_grille=c.cle_produit in en_vigueur) for c in contestations
    ]
