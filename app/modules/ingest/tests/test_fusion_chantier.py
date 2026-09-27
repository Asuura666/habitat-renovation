"""Tests de `ingest/fusion_chantier.py` (Task 7, avenant du 27/09/2026,
décision d'Ilane, spec §2.7) : fusion de deux chantiers -- tout ce que
portait la source est déplacé vers la cible, la source n'est jamais
supprimée physiquement.

Base de test réelle (`bl_test`), données entièrement inventées (« Villa
Test », « Résidence des Tilleuls »…), jamais `tests/fixtures/` (R17)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.fusion_chantier import (
    FusionImpossible,
    ResultatFusion,
    fusionner_chantiers,
)
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Utilisateur,
)
from app.modules.ingest.rattachement_chantier import rattacher_chantier_document
from app.modules.ingest.referentiels import ChantierIntrouvable

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _fournisseur(
    db_session: AsyncSession, nom: str = "Fournisseur Test"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.flush()
    return fournisseur


async def _chantier(
    db_session: AsyncSession,
    nom: str,
    *,
    actif: bool = True,
    a_completer: bool = False,
    fusionne_dans_id: uuid.UUID | None = None,
) -> Chantier:
    chantier = Chantier(
        nom_canonique=nom,
        actif=actif,
        a_completer=a_completer,
        fusionne_dans_id=fusionne_dans_id,
    )
    db_session.add(chantier)
    await db_session.flush()
    return chantier


async def _admin(db_session: AsyncSession) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid",
        role="admin",
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.flush()
    return utilisateur


async def _bon(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    chantier_id: uuid.UUID | None,
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
        chantier_id=chantier_id,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _facture(db_session: AsyncSession, *, fournisseur: Fournisseur) -> Document:
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        fournisseur_id=fournisseur.id,
    )
    db_session.add(facture)
    await db_session.flush()
    return facture


async def _bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    chantier_id: uuid.UUID | None,
    ordre: int = 0,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl="L0001",
        chantier_id=chantier_id,
    )
    db_session.add(bloc)
    await db_session.flush()
    return bloc


async def _alias(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    libelle_brut: str,
    chantier_id: uuid.UUID | None,
) -> ChantierAlias:
    alias = ChantierAlias(
        fournisseur_id=fournisseur.id,
        libelle_brut=libelle_brut,
        code_brut=None,
        chantier_id=chantier_id,
    )
    db_session.add(alias)
    await db_session.flush()
    return alias


async def _anomalie_r16(
    db_session: AsyncSession, *, chantier_id: uuid.UUID, detail: dict[str, str]
) -> Anomalie:
    """Seule règle qui pose `Anomalie.chantier_id` sans document/bloc/ligne
    ni alias (« chantier silencieux ») -- voir docstring d'`ingest/models
    .py::Anomalie`. Créée directement (pas via le moteur de règles) : ce
    module ne teste que la fusion, pas R16."""
    anomalie = Anomalie(
        regle="R16",
        gravite="moyenne",
        chantier_id=chantier_id,
        detail=detail,
        statut="ouverte",
    )
    db_session.add(anomalie)
    await db_session.flush()
    return anomalie


# --------------------------------------------------------------------------
# fusionner_chantiers -- déplacement
# --------------------------------------------------------------------------


async def test_fusion_deplace_bons_blocs_noms(db_session: AsyncSession) -> None:
    f = await _fournisseur(db_session)
    admin = await _admin(db_session)
    source = await _chantier(db_session, "Ormeaux", a_completer=True)
    cible = await _chantier(db_session, "Résidence les Ormeaux")

    bon = await _bon(db_session, fournisseur=f, chantier_id=source.id)
    facture = await _facture(db_session, fournisseur=f)
    bloc = await _bloc(db_session, facture=facture, chantier_id=source.id)
    alias = await _alias(
        db_session, fournisseur=f, libelle_brut="ormeaux", chantier_id=source.id
    )
    await db_session.commit()

    resultat = await fusionner_chantiers(
        db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
    )

    assert resultat == ResultatFusion(
        cible_id=cible.id, nb_documents=1, nb_blocs=1, nb_alias=1, nb_anomalies=0
    )

    await db_session.refresh(bon)
    await db_session.refresh(bloc)
    await db_session.refresh(alias)
    await db_session.refresh(source)
    assert bon.chantier_id == cible.id
    assert bloc.chantier_id == cible.id
    assert alias.chantier_id == cible.id

    # Source jamais supprimée, mais désactivée et marquée fusionnée --
    # « à compléter » retombe aussi (elle ne sera plus jamais complétée).
    assert source.actif is False
    assert source.a_completer is False
    assert source.fusionne_dans_id == cible.id

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.action == "chantier_fusionne")
        )
    ).scalar_one()
    assert journal.cible_id == str(source.id)
    assert journal.avant == {"chantier_id": str(source.id), "nom": "Ormeaux"}
    assert journal.apres == {
        "cible_id": str(cible.id),
        "cible_nom": "Résidence les Ormeaux",
        "nb_documents": 1,
        "nb_blocs": 1,
        "nb_alias": 1,
        "nb_anomalies": 0,
    }


async def test_fusion_conflit_r16_leve_l_anomalie_de_la_source(
    db_session: AsyncSession,
) -> None:
    admin = await _admin(db_session)
    source = await _chantier(db_session, "Villa Test")
    cible = await _chantier(db_session, "Résidence des Tilleuls")

    anomalie_source = await _anomalie_r16(
        db_session, chantier_id=source.id, detail={"depuis": "source"}
    )
    anomalie_cible = await _anomalie_r16(
        db_session, chantier_id=cible.id, detail={"depuis": "cible"}
    )
    await db_session.commit()

    resultat = await fusionner_chantiers(
        db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
    )

    assert resultat.nb_anomalies == 1

    # L'anomalie de la source est levée (supprimée), pas déplacée -- sinon
    # elle violerait l'index unique `(regle, ..., chantier_id, ...)`, déjà
    # porté par celle de la cible.
    assert await db_session.get(Anomalie, anomalie_source.id) is None
    restante = await db_session.get(Anomalie, anomalie_cible.id)
    assert restante is not None
    assert restante.detail == {"depuis": "cible"}

    journal_levee = (
        await db_session.execute(
            select(Journal).where(Journal.action == "anomalie_levee")
        )
    ).scalar_one()
    assert journal_levee.cible_id == str(anomalie_source.id)
    assert journal_levee.avant is not None
    assert journal_levee.avant["regle"] == "R16"
    assert journal_levee.apres is None


async def test_fusion_deplace_une_anomalie_ouverte_sans_conflit(
    db_session: AsyncSession,
) -> None:
    """Sans anomalie déjà identique côté cible, celle de la source est
    déplacée (pas levée)."""
    admin = await _admin(db_session)
    source = await _chantier(db_session, "Villa Test")
    cible = await _chantier(db_session, "Résidence des Tilleuls")
    anomalie = await _anomalie_r16(
        db_session, chantier_id=source.id, detail={"depuis": "source"}
    )
    await db_session.commit()

    resultat = await fusionner_chantiers(
        db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
    )

    assert resultat.nb_anomalies == 1
    await db_session.refresh(anomalie)
    assert anomalie.chantier_id == cible.id
    assert anomalie.statut == "ouverte"


async def test_fusion_ignore_les_anomalies_fermees(db_session: AsyncSession) -> None:
    """Une anomalie fermée (`traitee`/`ignoree`) de la source reste un
    historique sur la source -- jamais déplacée ni levée (spec §2.7)."""
    admin = await _admin(db_session)
    source = await _chantier(db_session, "Villa Test")
    cible = await _chantier(db_session, "Résidence des Tilleuls")
    fermee = await _anomalie_r16(
        db_session, chantier_id=source.id, detail={"depuis": "source"}
    )
    fermee.statut = "traitee"
    await db_session.commit()

    resultat = await fusionner_chantiers(
        db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
    )

    assert resultat.nb_anomalies == 0
    await db_session.refresh(fermee)
    assert fermee.chantier_id == source.id
    assert fermee.statut == "traitee"


# --------------------------------------------------------------------------
# fusionner_chantiers -- refus
# --------------------------------------------------------------------------


async def test_fusion_refuse_meme_chantier(db_session: AsyncSession) -> None:
    admin = await _admin(db_session)
    chantier = await _chantier(db_session, "Villa Test")
    await db_session.commit()

    with pytest.raises(FusionImpossible, match="même chantier"):
        await fusionner_chantiers(
            db_session,
            source_id=chantier.id,
            cible_id=chantier.id,
            auteur_id=admin.id,
        )


async def test_fusion_refuse_source_deja_fusionnee(db_session: AsyncSession) -> None:
    admin = await _admin(db_session)
    ailleurs = await _chantier(db_session, "Chantier Ailleurs")
    source = await _chantier(
        db_session, "Villa Test", fusionne_dans_id=ailleurs.id, actif=False
    )
    cible = await _chantier(db_session, "Résidence des Tilleuls")
    await db_session.commit()

    with pytest.raises(FusionImpossible, match="déjà fusionné"):
        await fusionner_chantiers(
            db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
        )


async def test_fusion_refuse_cible_fusionnee(db_session: AsyncSession) -> None:
    admin = await _admin(db_session)
    ailleurs = await _chantier(db_session, "Chantier Ailleurs")
    source = await _chantier(db_session, "Villa Test")
    cible = await _chantier(
        db_session,
        "Résidence des Tilleuls",
        fusionne_dans_id=ailleurs.id,
        actif=False,
    )
    await db_session.commit()

    with pytest.raises(FusionImpossible, match="cible"):
        await fusionner_chantiers(
            db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
        )


async def test_fusion_source_inconnue_leve_chantier_introuvable(
    db_session: AsyncSession,
) -> None:
    admin = await _admin(db_session)
    cible = await _chantier(db_session, "Résidence des Tilleuls")
    await db_session.commit()

    with pytest.raises(ChantierIntrouvable):
        await fusionner_chantiers(
            db_session, source_id=uuid.uuid4(), cible_id=cible.id, auteur_id=admin.id
        )


async def test_fusion_cible_inconnue_leve_chantier_introuvable(
    db_session: AsyncSession,
) -> None:
    admin = await _admin(db_session)
    source = await _chantier(db_session, "Villa Test")
    await db_session.commit()

    with pytest.raises(ChantierIntrouvable):
        await fusionner_chantiers(
            db_session, source_id=source.id, cible_id=uuid.uuid4(), auteur_id=admin.id
        )


# --------------------------------------------------------------------------
# fusionner_chantiers -- redirection des anciennes fusions
# --------------------------------------------------------------------------


async def test_fusion_redirige_les_anciens_fusionnes(db_session: AsyncSession) -> None:
    """Un chantier déjà fusionné dans la source (fusion antérieure) doit
    pointer directement vers la nouvelle cible -- jamais de chaîne à deux
    sauts."""
    admin = await _admin(db_session)
    ancien = await _chantier(db_session, "Ormeaux Bis", actif=False)
    source = await _chantier(
        db_session, "Ormeaux", fusionne_dans_id=None, a_completer=True
    )
    ancien.fusionne_dans_id = source.id
    cible = await _chantier(db_session, "Résidence les Ormeaux")
    await db_session.commit()

    await fusionner_chantiers(
        db_session, source_id=source.id, cible_id=cible.id, auteur_id=admin.id
    )

    await db_session.refresh(ancien)
    assert ancien.fusionne_dans_id == cible.id


# --------------------------------------------------------------------------
# Rattachement automatique après fusion (redirection via `chantier_effectif`)
# --------------------------------------------------------------------------


async def test_nom_d_un_chantier_fusionne_mene_a_la_cible(
    db_session: AsyncSession,
) -> None:
    """Après fusion de « Villa Test » dans « Résidence des Tilleuls », un
    bon « VILLA TEST » passé à `rattacher_chantier_document` est rattaché à
    la cible, aucun chantier créé (Task 5 : `charger_noms_chantiers`/
    `chantier_effectif` suivent `fusionne_dans_id`)."""
    f = await _fournisseur(db_session)
    admin = await _admin(db_session)
    villa = await _chantier(db_session, "Villa Test")
    tilleuls = await _chantier(db_session, "Résidence des Tilleuls")
    await db_session.commit()

    await fusionner_chantiers(
        db_session, source_id=villa.id, cible_id=tilleuls.id, auteur_id=admin.id
    )

    nb_chantiers_avant = (await db_session.execute(select(Chantier.id))).scalars().all()
    assert len(nb_chantiers_avant) == 2

    bon = await _bon(db_session, fournisseur=f, chantier_id=None)
    bon.chantier_brut = "VILLA TEST (123)"
    await db_session.flush()

    resultat = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()

    assert resultat.chantier_id == tilleuls.id

    nb_chantiers_apres = (await db_session.execute(select(Chantier.id))).scalars().all()
    assert len(nb_chantiers_apres) == 2  # aucun chantier créé.
