"""Tests d'`ingest/a_traiter.py` (L3-T8b) : contenu de l'écran « À traiter »
— documents « à vérifier » (tous types), alias chantier en attente, articles
à valider.

Base de test réelle (`bl_test`), données entièrement inventées (R17).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.a_traiter import lister_a_traiter
from app.modules.ingest.models import (
    Article,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_BASE_TEMPS = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _instant(decalage_s: int) -> datetime:
    """Horodatage déterministe, distinct par appel — même principe
    qu'`ingest/tests/test_lecture.py::_instant` (évite de dépendre de
    `func.now()`, identique pour toutes les lignes d'une même transaction,
    pour les tests qui portent justement sur le tri par date)."""
    return _BASE_TEMPS + timedelta(seconds=decalage_s)


async def _creer_utilisateur(
    db_session: AsyncSession, *, role: str = "admin", nom: str | None = "Nom Testeur"
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"{role}.{uuid.uuid4()}@example.invalid",
        role=role,
        nom=nom,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Testeur"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_document(
    db_session: AsyncSession,
    *,
    type_: str = "bl",
    statut: str = "a_verifier",
    numero: str | None = None,
    fournisseur: Fournisseur | None = None,
    chantier_brut: str | None = None,
    chantier_id: uuid.UUID | None = None,
    deposant: Utilisateur | None = None,
    motifs: list[dict[str, object]] | None = None,
    created_at: datetime | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        chantier_brut=chantier_brut,
        chantier_id=chantier_id,
        deposant_id=deposant.id if deposant is not None else None,
        motifs=motifs,
    )
    if created_at is not None:
        document.created_at = created_at
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_alias(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    libelle_brut: str,
    chantier_id: uuid.UUID | None = None,
) -> ChantierAlias:
    alias = ChantierAlias(
        fournisseur_id=fournisseur.id,
        libelle_brut=libelle_brut,
        code_brut=None,
        chantier_id=chantier_id,
    )
    db_session.add(alias)
    await db_session.commit()
    await db_session.refresh(alias)
    return alias


async def _creer_article(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    code: str = "AB1234",
    ratio: Decimal | None = Decimal("4.0000"),
    valide: bool = False,
) -> Article:
    article = Article(
        fournisseur_id=fournisseur.id,
        code=code,
        libelle="Article inventé",
        unite_cdt="seau",
        unite_fact="kg",
        ratio=ratio,
        valide=valide,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


# --------------------------------------------------------------------------
# Documents « à vérifier »
# --------------------------------------------------------------------------


async def test_document_a_verifier_avec_motifs_present(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(
        db_session,
        fournisseur=fournisseur,
        numero="L100",
        chantier_brut="CHANTIER TEST",
        motifs=[{"code": "champ_absent", "champ": "date_doc", "detail": {}}],
    )

    a_traiter = await lister_a_traiter(db_session)

    lignes = {d.id: d for d in a_traiter.documents}
    assert document.id in lignes
    ligne = lignes[document.id]
    assert ligne.fournisseur == "Fournisseur Testeur"
    assert ligne.chantier_brut == "CHANTIER TEST"
    assert len(ligne.motifs) == 1
    assert ligne.motifs[0].code == "champ_absent"


async def test_ecart_constate_sans_motif_present_avec_confirmation(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session)
    document = await _creer_document(db_session, numero="L200", motifs=[])
    db_session.add(
        Journal(
            utilisateur_id=admin.id,
            action="ecart_constate",
            cible_table="document",
            cible_id=str(document.id),
            avant=None,
            apres=None,
        )
    )
    await db_session.commit()

    a_traiter = await lister_a_traiter(db_session)

    lignes = {d.id: d for d in a_traiter.documents}
    assert document.id in lignes
    ligne = lignes[document.id]
    assert ligne.confirmation == "ecart"
    assert ligne.motifs == []


async def test_document_recu_absent(db_session: AsyncSession) -> None:
    document = await _creer_document(db_session, statut="recu", numero="L300")

    a_traiter = await lister_a_traiter(db_session)

    assert document.id not in {d.id for d in a_traiter.documents}


async def test_facture_a_verifier_presente(db_session: AsyncSession) -> None:
    facture = await _creer_document(db_session, type_="facture", numero="F100")

    a_traiter = await lister_a_traiter(db_session)

    lignes = {d.id: d for d in a_traiter.documents}
    assert facture.id in lignes
    assert lignes[facture.id].type == "facture"


async def test_documents_ordre_du_plus_ancien_au_plus_recent(
    db_session: AsyncSession,
) -> None:
    plus_recent = await _creer_document(
        db_session, numero="L410", created_at=_instant(10)
    )
    plus_ancien = await _creer_document(
        db_session, numero="L400", created_at=_instant(0)
    )

    a_traiter = await lister_a_traiter(db_session)

    ids = [d.id for d in a_traiter.documents]
    assert ids.index(plus_ancien.id) < ids.index(plus_recent.id)


# --------------------------------------------------------------------------
# Alias chantier en attente
# --------------------------------------------------------------------------


async def test_alias_en_attente_compte_et_exemple(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Alias")
    alias = await _creer_alias(
        db_session, fournisseur=fournisseur, libelle_brut="maison test"
    )
    await _creer_document(
        db_session,
        fournisseur=fournisseur,
        chantier_brut="MAISON TEST (1002)",
        created_at=_instant(0),
    )
    plus_recent = await _creer_document(
        db_session,
        fournisseur=fournisseur,
        chantier_brut="Maison Test",
        created_at=_instant(50),
    )
    # Autre libellé : ne doit pas compter pour cet alias.
    await _creer_document(
        db_session, fournisseur=fournisseur, chantier_brut="AUTRE CHANTIER"
    )

    a_traiter = await lister_a_traiter(db_session)

    lignes = {a.id: a for a in a_traiter.alias}
    assert alias.id in lignes
    ligne = lignes[alias.id]
    assert ligne.fournisseur == "Fournisseur Alias"
    assert ligne.libelle == "maison test"
    assert ligne.nb_documents == 2
    assert ligne.exemple_brut == plus_recent.chantier_brut


async def test_alias_deja_valide_absent(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = Chantier(nom_canonique="Chantier Canonique")
    db_session.add(chantier)
    await db_session.flush()
    alias = await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        libelle_brut="chantier resolu",
        chantier_id=chantier.id,
    )

    a_traiter = await lister_a_traiter(db_session)

    assert alias.id not in {a.id for a in a_traiter.alias}


async def test_alias_sans_document_correspondant_compte_zero(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    alias = await _creer_alias(
        db_session, fournisseur=fournisseur, libelle_brut="chantier isole"
    )

    a_traiter = await lister_a_traiter(db_session)

    lignes = {a.id: a for a in a_traiter.alias}
    assert lignes[alias.id].nb_documents == 0
    assert lignes[alias.id].exemple_brut is None


# --------------------------------------------------------------------------
# Articles à valider
# --------------------------------------------------------------------------


async def test_article_ratio_different_de_un_present(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, ratio=Decimal("4")
    )

    a_traiter = await lister_a_traiter(db_session)

    ids = {a.id for a in a_traiter.articles}
    assert article.id in ids


async def test_article_ratio_un_absent(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, ratio=Decimal("1")
    )

    a_traiter = await lister_a_traiter(db_session)

    assert article.id not in {a.id for a in a_traiter.articles}


async def test_article_deja_valide_absent(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, ratio=Decimal("4"), valide=True
    )

    a_traiter = await lister_a_traiter(db_session)

    assert article.id not in {a.id for a in a_traiter.articles}


async def test_article_sans_ratio_absent(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(db_session, fournisseur=fournisseur, ratio=None)

    a_traiter = await lister_a_traiter(db_session)

    assert article.id not in {a.id for a in a_traiter.articles}
