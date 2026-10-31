"""Tests de `ingest/anomalies.py` (L4-T8) : génération idempotente,
cycle de vie et lecture des anomalies.

Base de test réelle (`bl_test`), données entièrement inventées (R17).
`db_session` (fixture locale, `app/modules/ingest/tests/conftest.py`) vide
toutes les tables après chaque test : aucun nettoyage manuel nécessaire ici.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import (
    AnomalieIntrouvable,
    AnomalieLue,
    TransitionInterdite,
    compter_anomalies_hautes_ouvertes,
    compter_anomalies_ouvertes,
    lister_anomalies,
    synchroniser_anomalies,
    traiter_anomalie,
)
from app.modules.ingest.models import (
    Anomalie,
    Article,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Parametre,
    Utilisateur,
)
from app.modules.rules.modeles import Anomalie as AnomaliePure
from app.modules.rules.modeles import Gravite

pytestmark = [pytest.mark.anyio, pytest.mark.db]

# Ensemble exact que `rapprocher_facture` (L4-T7) passera en pratique à
# `portee_regles` (Ruling R8, fix round 1) : toutes les règles que
# `evaluer_facture` peut produire (CDC §5, hors R06/R14/R15/R16 qui ne
# viennent que des contrôles différés, L4-D14). Réutilisé par les tests
# ci-dessous plutôt que de deviner un sous-ensemble à chaque appel.
REGLES_FACTURE: tuple[str, ...] = (
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R07",
    "R08",
    "R09",
    "R10",
    "R11",
    "R12",
    "R13",
    "R17",
)


# --------------------------------------------------------------------------
# Aides de construction (données inventées)
# --------------------------------------------------------------------------


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


async def _creer_article(
    db_session: AsyncSession, *, fournisseur: Fournisseur, code: str = "ART1"
) -> Article:
    article = Article(fournisseur_id=fournisseur.id, code=code, valide=True)
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


async def _creer_chantier(
    db_session: AsyncSession, *, nom: str = "Chantier Testeur"
) -> Chantier:
    chantier = Chantier(nom_canonique=nom)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_document(
    db_session: AsyncSession,
    *,
    type_: str = "facture",
    statut: str = "recu",
    fournisseur: Fournisseur | None = None,
    numero: str | None = None,
    chantier_id: uuid.UUID | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="upload",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        chantier_id=chantier_id,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    ordre: int = 0,
    numero_bl: str | None = "L0001",
    chantier_id: uuid.UUID | None = None,
    bl_document_id: uuid.UUID | None = None,
    montant_ht: Decimal = Decimal("100.00"),
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        bl_document_id=bl_document_id,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture | None = None,
    article: Article | None = None,
    ordre: int = 0,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        article_id=article.id if article is not None else None,
        type_ligne="article",
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


def _anomalie_pure(
    *,
    regle: str = "R10",
    gravite: Gravite = Gravite.HAUTE,
    document_id: uuid.UUID | None = None,
    bloc_id: uuid.UUID | None = None,
    ligne_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
    detail: dict[str, str] | None = None,
) -> AnomaliePure:
    return AnomaliePure(
        regle=regle,
        gravite=gravite,
        detail=detail if detail is not None else {"cle": "valeur"},
        document_id=document_id,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
        article_id=article_id,
    )


async def _ignorer_anomalie(
    db_session: AsyncSession,
    *,
    regle: str,
    document_id: uuid.UUID,
    article_id: uuid.UUID,
    ligne_id: uuid.UUID | None = None,
    traitee_le: datetime,
) -> Anomalie:
    """Une anomalie déjà `ignoree`, insérée directement (pas via
    `synchroniser_anomalies`) pour préparer un scénario de règle des 90
    jours — équivalent d'une anomalie déjà traitée par l'admin lors d'un
    rapprochement précédent."""
    anomalie = Anomalie(
        regle=regle,
        gravite="moyenne",
        document_id=document_id,
        ligne_id=ligne_id,
        article_id=article_id,
        detail={"cle": "valeur"},
        statut="ignoree",
        traitee_le=traitee_le,
        commentaire="Ignorée en connaissance de cause (test).",
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


# --------------------------------------------------------------------------
# synchroniser_anomalies — upsert sans doublon sur rejeu
# --------------------------------------------------------------------------


async def test_synchroniser_anomalies_upsert_sans_doublon_sur_rejeu(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")

    premiere = _anomalie_pure(
        regle="R10", document_id=facture.id, detail={"ecart": "1.00"}
    )
    nb1 = await synchroniser_anomalies(
        db_session,
        anomalies=[premiere],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = len(lignes) == 1 and nb1 == 1
    assert ok, "une anomalie neuve doit produire exactement une ligne"

    rejouee = _anomalie_pure(
        regle="R10",
        gravite=Gravite.HAUTE,
        document_id=facture.id,
        detail={"ecart": "2.00"},
    )
    nb2 = await synchroniser_anomalies(
        db_session,
        anomalies=[rejouee],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    lignes_apres_rejeu = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = (
        len(lignes_apres_rejeu) == 1
        and lignes_apres_rejeu[0].id == lignes[0].id
        and lignes_apres_rejeu[0].detail == {"ecart": "2.00"}
        and nb2 == 1
    )
    assert ok, (
        "un rejeu identique doit mettre à jour la ligne existante, pas en créer"
        " une seconde"
    )


async def test_synchroniser_anomalies_met_a_jour_article_id_sur_rejeu(
    db_session: AsyncSession,
) -> None:
    """Le rejeu met aussi à jour `article_id` d'une anomalie `ouverte`
    (décision du contrôleur, énumérée avec `detail`/`gravite`)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    article = await _creer_article(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=facture)

    await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(
                regle="R03",
                gravite=Gravite.HAUTE,
                document_id=facture.id,
                ligne_id=ligne.id,
                article_id=None,
            )
        ],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(
                regle="R03",
                gravite=Gravite.HAUTE,
                document_id=facture.id,
                ligne_id=ligne.id,
                article_id=article.id,
            )
        ],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    anomalie_db = (await db_session.execute(select(Anomalie))).scalar_one()
    assert anomalie_db.article_id == article.id


# --------------------------------------------------------------------------
# synchroniser_anomalies — anomalie levée
# --------------------------------------------------------------------------


async def test_synchroniser_anomalies_leve_une_anomalie_disparue_avec_journal(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    autre_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F2"
    )

    await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(regle="R10", document_id=facture.id, detail={"a": "1"})
        ],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()
    # Une anomalie d'une AUTRE facture, même règle : ne doit jamais être
    # concernée par la synchronisation de `facture` ci-dessous.
    await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(regle="R10", document_id=autre_facture.id, detail={"a": "1"})
        ],
        portee_document_id=autre_facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    anomalie_a_lever = (
        await db_session.execute(
            select(Anomalie).where(Anomalie.document_id == facture.id)
        )
    ).scalar_one()

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    lignes_restantes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = (
        len(lignes_restantes) == 1
        and lignes_restantes[0].document_id == autre_facture.id
    )
    assert ok, (
        "l'anomalie de la facture synchronisée disparaît, celle de l'autre"
        " facture reste"
    )
    assert nb == 0

    journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.action == "anomalie_levee",
                Journal.cible_id == str(anomalie_a_lever.id),
            )
        )
    ).scalar_one()
    ok = journal.utilisateur_id is None and journal.avant == {
        "regle": "R10",
        "gravite": "haute",
        "detail": {"a": "1"},
    }
    assert ok, "le journal de levée doit porter auteur NULL et l'ancien detail/gravite"


async def test_synchroniser_anomalies_leve_via_bloc_sans_document_id(
    db_session: AsyncSession,
) -> None:
    """Robustesse de la portée facture (décision du contrôleur) : une
    anomalie dont seul `bloc_id` est renseigné (`document_id` absent) est
    tout de même reconnue comme appartenant à la facture du bloc."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(db_session, facture=facture)

    db_session.add(
        Anomalie(
            regle="R01",
            gravite="haute",
            document_id=None,
            bloc_id=bloc.id,
            detail={"numero_bl": "L0001"},
            statut="ouverte",
        )
    )
    await db_session.commit()

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    restantes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert restantes == []
    assert nb == 0


# --------------------------------------------------------------------------
# synchroniser_anomalies — anomalie traitée jamais touchée
# --------------------------------------------------------------------------


async def test_synchroniser_anomalies_ne_touche_jamais_une_anomalie_traitee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    admin = await _creer_utilisateur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")

    await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(regle="R10", document_id=facture.id, detail={"a": "1"})
        ],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    anomalie_db = (await db_session.execute(select(Anomalie))).scalar_one()
    await traiter_anomalie(
        db_session,
        anomalie_db.id,
        statut="traitee",
        commentaire="Corrigé côté fournisseur.",
        auteur_id=admin.id,
    )

    # Rejeu avec un detail différent pour la même clé : ne doit rien changer.
    await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(regle="R10", document_id=facture.id, detail={"a": "2"})
        ],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    inchangee = await db_session.get(Anomalie, anomalie_db.id)
    assert inchangee is not None
    ok = inchangee.statut == "traitee" and inchangee.detail == {"a": "1"}
    assert ok, "une anomalie traitée ne doit jamais être modifiée par un rejeu"

    # Rejeu SANS la reproduire du tout : ne doit pas non plus la supprimer.
    await synchroniser_anomalies(
        db_session,
        anomalies=[],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    toujours_la = await db_session.get(Anomalie, anomalie_db.id)
    assert toujours_la is not None
    assert toujours_la.statut == "traitee"


# --------------------------------------------------------------------------
# synchroniser_anomalies — règle des 90 jours (L4-D13)
# --------------------------------------------------------------------------


async def test_synchroniser_anomalies_regle_90_jours_bloque_si_recente(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(db_session, fournisseur=fournisseur)
    ancienne_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F-ANCIENNE"
    )
    ligne_ancienne = await _creer_ligne(db_session, document=ancienne_facture)
    await _ignorer_anomalie(
        db_session,
        regle="R07",
        document_id=ancienne_facture.id,
        article_id=article.id,
        ligne_id=ligne_ancienne.id,
        traitee_le=datetime.now(UTC) - timedelta(days=10),
    )

    nouvelle_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F-NOUVELLE"
    )
    ligne_nouvelle = await _creer_ligne(db_session, document=nouvelle_facture)

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(
                regle="R07",
                gravite=Gravite.MOYENNE,
                document_id=nouvelle_facture.id,
                ligne_id=ligne_nouvelle.id,
                article_id=article.id,
                detail={"pu": "12.00"},
            )
        ],
        portee_document_id=nouvelle_facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    ok = nb == 0
    assert ok, "une anomalie ignorée il y a 10 jours doit bloquer la régénération"
    lignes_nouvelle_facture = (
        (
            await db_session.execute(
                select(Anomalie).where(Anomalie.document_id == nouvelle_facture.id)
            )
        )
        .scalars()
        .all()
    )
    assert lignes_nouvelle_facture == []


async def test_synchroniser_anomalies_regle_90_jours_regenere_si_ancienne(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(db_session, fournisseur=fournisseur)
    ancienne_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F-ANCIENNE"
    )
    ligne_ancienne = await _creer_ligne(db_session, document=ancienne_facture)
    await _ignorer_anomalie(
        db_session,
        regle="R07",
        document_id=ancienne_facture.id,
        article_id=article.id,
        ligne_id=ligne_ancienne.id,
        traitee_le=datetime.now(UTC) - timedelta(days=100),
    )

    nouvelle_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F-NOUVELLE"
    )
    ligne_nouvelle = await _creer_ligne(db_session, document=nouvelle_facture)

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(
                regle="R07",
                gravite=Gravite.MOYENNE,
                document_id=nouvelle_facture.id,
                ligne_id=ligne_nouvelle.id,
                article_id=article.id,
                detail={"pu": "12.00"},
            )
        ],
        portee_document_id=nouvelle_facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    ok = nb == 1
    assert ok, (
        "une anomalie ignorée il y a 100 jours ne doit plus bloquer la régénération"
    )


async def test_synchroniser_anomalies_utilise_le_parametre_duree_ignorance(
    db_session: AsyncSession,
) -> None:
    """Le seuil est lu dans `parametre` (`lire_parametre_decimal`, L3-D4) :
    un `duree_ignorance_j` réduit à 5 jours ne bloque plus une anomalie
    ignorée il y a 10 jours."""
    db_session.add(Parametre(cle="duree_ignorance_j", valeur="5"))
    await db_session.commit()

    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(db_session, fournisseur=fournisseur)
    ancienne_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F-ANCIENNE"
    )
    ligne_ancienne = await _creer_ligne(db_session, document=ancienne_facture)
    await _ignorer_anomalie(
        db_session,
        regle="R07",
        document_id=ancienne_facture.id,
        article_id=article.id,
        ligne_id=ligne_ancienne.id,
        traitee_le=datetime.now(UTC) - timedelta(days=10),
    )

    nouvelle_facture = await _creer_document(
        db_session, fournisseur=fournisseur, numero="F-NOUVELLE"
    )
    ligne_nouvelle = await _creer_ligne(db_session, document=nouvelle_facture)

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(
                regle="R07",
                gravite=Gravite.MOYENNE,
                document_id=nouvelle_facture.id,
                ligne_id=ligne_nouvelle.id,
                article_id=article.id,
                detail={"pu": "12.00"},
            )
        ],
        portee_document_id=nouvelle_facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    assert nb == 1


# --------------------------------------------------------------------------
# synchroniser_anomalies — portées
# --------------------------------------------------------------------------


async def test_synchroniser_anomalies_leve_erreur_sans_aucune_portee(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError):
        await synchroniser_anomalies(db_session, anomalies=[])


async def test_synchroniser_anomalies_leve_erreur_si_portee_document_sans_regles(
    db_session: AsyncSession,
) -> None:
    """Ruling R8 (fix round 1) : `portee_regles` est obligatoire même quand
    `portee_document_id` est fourni — une portée facture sans son ensemble
    de règles ne borne rien, elle est refusée."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")

    with pytest.raises(ValueError):
        await synchroniser_anomalies(
            db_session, anomalies=[], portee_document_id=facture.id
        )


async def test_synchroniser_anomalies_ne_leve_pas_une_regle_de_suivi_hors_portee(
    db_session: AsyncSession,
) -> None:
    """Ruling R8 (fix round 1, constat Important de la revue) : un rejeu de
    `rapprocher_facture`, qui ne recalcule que les règles de
    `evaluer_facture` (`REGLES_FACTURE`, jamais R06/R14/R15/R16, produites
    seulement par les contrôles différés, L4-D14), ne doit jamais lever une
    anomalie de suivi (R06) attachée au même bloc de la même facture — ni la
    supprimer, ni journaliser de `anomalie_levee` pour elle."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(db_session, facture=facture)

    anomalie_suivi = Anomalie(
        regle="R06",
        gravite="basse",
        document_id=facture.id,
        bloc_id=bloc.id,
        detail={"article": "ART1"},
        statut="ouverte",
    )
    db_session.add(anomalie_suivi)
    await db_session.commit()
    await db_session.refresh(anomalie_suivi)

    # Rejeu de rapprochement classique : ne recalcule que les règles
    # « facture », jamais R06.
    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[
            _anomalie_pure(regle="R10", document_id=facture.id, detail={"a": "1"})
        ],
        portee_document_id=facture.id,
        portee_regles=REGLES_FACTURE,
    )
    await db_session.commit()

    toujours_la = await db_session.get(Anomalie, anomalie_suivi.id)
    ok = toujours_la is not None and toujours_la.statut == "ouverte"
    assert ok, "l'anomalie de suivi (R06) hors portée ne doit jamais être supprimée"

    journal_leve = (
        await db_session.execute(
            select(Journal).where(
                Journal.action == "anomalie_levee",
                Journal.cible_id == str(anomalie_suivi.id),
            )
        )
    ).scalar_one_or_none()
    assert journal_leve is None, (
        "aucun journal `anomalie_levee` pour une règle hors portée"
    )

    # Le compte renvoyé ne porte que sur la portée (règles facture) : R06
    # n'y entre jamais, seule la R10 nouvellement créée compte.
    assert nb == 1


async def test_synchroniser_anomalies_portee_suivi_restreint_aux_regles_donnees(
    db_session: AsyncSession,
) -> None:
    """Portée « suivi » (L4-T11, aucune facture) : `portee_regles` seul,
    sans `portee_document_id` — ne supprime que les règles listées, jamais
    les anomalies d'une facture."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    document_bl = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)

    db_session.add_all(
        [
            Anomalie(
                regle="R06",
                gravite="basse",
                document_id=document_bl.id,
                detail={"a": "1"},
                statut="ouverte",
            ),
            Anomalie(
                regle="R14",
                gravite="moyenne",
                document_id=document_bl.id,
                detail={"a": "1"},
                statut="ouverte",
            ),
            Anomalie(
                regle="R10",
                gravite="haute",
                document_id=facture.id,
                detail={"a": "1"},
                statut="ouverte",
            ),
        ]
    )
    await db_session.commit()

    nb = await synchroniser_anomalies(db_session, anomalies=[], portee_regles=("R06",))
    await db_session.commit()

    regles_restantes = sorted(
        r for (r,) in (await db_session.execute(select(Anomalie.regle))).all()
    )
    ok = regles_restantes == ["R10", "R14"]
    assert ok, (
        "seule la règle R06 doit être levée par une portée suivi restreinte à R06"
    )
    assert nb == 0


# --------------------------------------------------------------------------
# synchroniser_anomalies — identité étendue à chantier_id/alias_id
# (Ruling R13, tâche L4-T11 : ce module est le premier à persister des
# anomalies de suivi R06/R14/R15/R16, migration 0007)
# --------------------------------------------------------------------------


async def test_synchroniser_anomalies_deux_chantiers_silencieux_distincts_coexistent(
    db_session: AsyncSession,
) -> None:
    """Sans `chantier_id` dans la clé d'identité, deux anomalies R16 (deux
    chantiers silencieux distincts, ni document ni bloc ni ligne) se
    confondraient en une seule ligne — R16.py (déjà commité) le documente
    explicitement."""
    chantier_1 = await _creer_chantier(db_session, nom="Chantier Un")
    chantier_2 = await _creer_chantier(db_session, nom="Chantier Deux")

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[
            AnomaliePure(
                regle="R16",
                gravite=Gravite.BASSE,
                detail={"chantier": "1"},
                chantier_id=chantier_1.id,
            ),
            AnomaliePure(
                regle="R16",
                gravite=Gravite.BASSE,
                detail={"chantier": "2"},
                chantier_id=chantier_2.id,
            ),
        ],
        portee_regles=("R16",),
    )
    await db_session.commit()

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = (
        len(lignes) == 2
        and {ligne.chantier_id for ligne in lignes} == {chantier_1.id, chantier_2.id}
        and nb == 2
    )
    assert ok, "deux chantiers silencieux distincts doivent produire deux anomalies"


async def test_synchroniser_anomalies_deux_alias_en_attente_distincts_coexistent(
    db_session: AsyncSession,
) -> None:
    """Même besoin pour `alias_id` (R14) : `rules/rules/R14.py` documente
    explicitement que, sans lui, deux alias en attente distincts se
    confondraient en une seule anomalie une fois persistés (mention
    « L4-T11 » dans son docstring)."""
    fournisseur = await _creer_fournisseur(db_session)
    alias_1 = ChantierAlias(fournisseur_id=fournisseur.id, libelle_brut="ALIAS UN")
    alias_2 = ChantierAlias(fournisseur_id=fournisseur.id, libelle_brut="ALIAS DEUX")
    db_session.add_all([alias_1, alias_2])
    await db_session.commit()
    await db_session.refresh(alias_1)
    await db_session.refresh(alias_2)

    nb = await synchroniser_anomalies(
        db_session,
        anomalies=[
            AnomaliePure(
                regle="R14",
                gravite=Gravite.MOYENNE,
                detail={"alias": "1"},
                alias_id=alias_1.id,
            ),
            AnomaliePure(
                regle="R14",
                gravite=Gravite.MOYENNE,
                detail={"alias": "2"},
                alias_id=alias_2.id,
            ),
        ],
        portee_regles=("R14",),
    )
    await db_session.commit()

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = (
        len(lignes) == 2
        and {ligne.alias_id for ligne in lignes} == {alias_1.id, alias_2.id}
        and nb == 2
    )
    assert ok, "deux alias en attente distincts doivent produire deux anomalies"


async def test_synchroniser_anomalies_rejeu_chantier_silencieux_sans_doublon(
    db_session: AsyncSession,
) -> None:
    """Idempotence (L4-D3) sur la nouvelle clé d'identité : rejouer la même
    anomalie R16 (même `chantier_id`) met à jour la ligne existante, n'en
    crée jamais une seconde."""
    chantier = await _creer_chantier(db_session)

    await synchroniser_anomalies(
        db_session,
        anomalies=[
            AnomaliePure(
                regle="R16",
                gravite=Gravite.BASSE,
                detail={"jours": "8"},
                chantier_id=chantier.id,
            )
        ],
        portee_regles=("R16",),
    )
    await db_session.commit()

    await synchroniser_anomalies(
        db_session,
        anomalies=[
            AnomaliePure(
                regle="R16",
                gravite=Gravite.BASSE,
                detail={"jours": "9"},
                chantier_id=chantier.id,
            )
        ],
        portee_regles=("R16",),
    )
    await db_session.commit()

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = len(lignes) == 1 and lignes[0].detail == {"jours": "9"}
    assert ok, "un rejeu identique (même chantier) met à jour, ne duplique jamais"


# --------------------------------------------------------------------------
# lister_anomalies — filtres
# --------------------------------------------------------------------------


@pytest.fixture
async def jeu_anomalies(
    db_session: AsyncSession,
) -> dict[str, object]:
    """Un jeu de deux anomalies bien distinctes (fournisseur, chantier,
    règle, gravité, statut) pour tester chaque filtre de `lister_anomalies`
    indépendamment."""
    fournisseur_a = await _creer_fournisseur(db_session, nom="Fournisseur A")
    fournisseur_b = await _creer_fournisseur(db_session, nom="Fournisseur B")
    chantier_a = await _creer_chantier(db_session, nom="Chantier A")
    chantier_b = await _creer_chantier(db_session, nom="Chantier B")

    facture_a = await _creer_document(
        db_session, fournisseur=fournisseur_a, numero="FA"
    )
    facture_b = await _creer_document(
        db_session, fournisseur=fournisseur_b, numero="FB"
    )
    bloc_a = await _creer_bloc(db_session, facture=facture_a, chantier_id=chantier_a.id)
    bloc_b = await _creer_bloc(db_session, facture=facture_b, chantier_id=chantier_b.id)

    anomalie_a = Anomalie(
        regle="R01",
        gravite="haute",
        document_id=facture_a.id,
        bloc_id=bloc_a.id,
        detail={"a": "1"},
        statut="ouverte",
    )
    anomalie_b = Anomalie(
        regle="R17",
        gravite="basse",
        document_id=facture_b.id,
        bloc_id=bloc_b.id,
        detail={"a": "1"},
        statut="ignoree",
        traitee_le=datetime.now(UTC),
        commentaire="Ignorée (test).",
    )
    db_session.add_all([anomalie_a, anomalie_b])
    await db_session.commit()
    await db_session.refresh(anomalie_a)
    await db_session.refresh(anomalie_b)

    return {
        "anomalie_a": anomalie_a,
        "anomalie_b": anomalie_b,
        "fournisseur_a": fournisseur_a,
        "fournisseur_b": fournisseur_b,
        "chantier_a": chantier_a,
        "chantier_b": chantier_b,
    }


async def test_lister_anomalies_filtre_regle(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    resultat = await lister_anomalies(db_session, regle="R01")
    ok = len(resultat) == 1 and resultat[0].regle == "R01"
    assert ok


async def test_lister_anomalies_filtre_gravite(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    resultat = await lister_anomalies(db_session, gravite="basse")
    ok = len(resultat) == 1 and resultat[0].gravite == "basse"
    assert ok


async def test_lister_anomalies_filtre_statut(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    resultat = await lister_anomalies(db_session, statut="ignoree")
    ok = len(resultat) == 1 and resultat[0].statut == "ignoree"
    assert ok


async def test_lister_anomalies_filtre_bloc(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    anomalie_a = jeu_anomalies["anomalie_a"]
    assert isinstance(anomalie_a, Anomalie)
    assert anomalie_a.bloc_id is not None

    resultat = await lister_anomalies(db_session, bloc_id=anomalie_a.bloc_id)

    ok = len(resultat) == 1 and resultat[0].id == anomalie_a.id
    assert ok


async def test_lister_anomalies_filtre_chantier(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    chantier_a = jeu_anomalies["chantier_a"]
    assert isinstance(chantier_a, Chantier)
    resultat = await lister_anomalies(db_session, chantier_id=chantier_a.id)
    ok = len(resultat) == 1 and resultat[0].chantier_id == chantier_a.id
    assert ok


async def test_lister_anomalies_filtre_fournisseur(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    fournisseur_b = jeu_anomalies["fournisseur_b"]
    assert isinstance(fournisseur_b, Fournisseur)
    resultat = await lister_anomalies(db_session, fournisseur_id=fournisseur_b.id)
    ok = len(resultat) == 1 and resultat[0].fournisseur_id == fournisseur_b.id
    assert ok


async def test_lister_anomalies_filtre_depuis(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    resultat = await lister_anomalies(
        db_session, depuis=datetime.now(UTC) + timedelta(hours=1)
    )
    assert resultat == []


async def test_lister_anomalies_filtre_jusqu_a(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    resultat = await lister_anomalies(
        db_session, jusqu_a=datetime.now(UTC) - timedelta(hours=1)
    )
    assert resultat == []


async def test_lister_anomalies_tri_gravite_puis_date(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    resultat = await lister_anomalies(db_session)
    ok = (
        len(resultat) == 2
        and resultat[0].gravite == "haute"
        and resultat[1].gravite == "basse"
    )
    assert ok, "gravité haute avant basse (tri gravité puis date)"


async def test_lister_anomalies_expose_le_document_le_bloc_et_le_fournisseur(
    db_session: AsyncSession, jeu_anomalies: dict[str, object]
) -> None:
    anomalie_a = jeu_anomalies["anomalie_a"]
    fournisseur_a = jeu_anomalies["fournisseur_a"]
    assert isinstance(anomalie_a, Anomalie)
    assert isinstance(fournisseur_a, Fournisseur)

    resultat = await lister_anomalies(db_session, regle="R01")
    lue = resultat[0]
    ok = (
        isinstance(lue, AnomalieLue)
        and lue.document_id == anomalie_a.document_id
        and lue.numero == "FA"
        and lue.type == "facture"
        and lue.bloc_id == anomalie_a.bloc_id
        and lue.fournisseur_id == fournisseur_a.id
        and lue.fournisseur == "Fournisseur A"
    )
    assert ok


async def test_lister_anomalies_expose_bl_document_id_quand_il_existe(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    document_bl = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, bl_document_id=document_bl.id)
    db_session.add(
        Anomalie(
            regle="R01",
            gravite="haute",
            document_id=facture.id,
            bloc_id=bloc.id,
            detail={"a": "1"},
            statut="ouverte",
        )
    )
    await db_session.commit()

    resultat = await lister_anomalies(db_session)
    ok = len(resultat) == 1 and resultat[0].bl_document_id == document_bl.id
    assert ok


# --------------------------------------------------------------------------
# Ruling R19 (fix round 2, L4-T7) : chantier propre d'une anomalie de suivi,
# prioritaire sur celui déduit du bloc ou du document
# --------------------------------------------------------------------------


async def test_lister_anomalies_chantier_propre_anomalie_de_suivi(
    db_session: AsyncSession,
) -> None:
    """Une anomalie de suivi (R16, sans document ni bloc) porte son propre
    `chantier_id` -- avant Ruling R19, `_requete_anomalies` ne lisait jamais
    `Anomalie.chantier_id` et l'affichait sans chantier, invisible du
    filtre `chantier_id`."""
    chantier = await _creer_chantier(db_session, nom="Chantier Silencieux")
    db_session.add(
        Anomalie(
            regle="R16",
            gravite="basse",
            chantier_id=chantier.id,
            detail={"jours": "8"},
            statut="ouverte",
        )
    )
    await db_session.commit()

    tous = await lister_anomalies(db_session)
    ok = len(tous) == 1 and tous[0].chantier_id == chantier.id
    assert ok, "le chantier de l'anomalie de suivi doit être affiché"

    filtres = await lister_anomalies(db_session, chantier_id=chantier.id)
    assert len(filtres) == 1, (
        "le filtre doit retrouver l'anomalie de suivi par son chantier propre"
    )


async def test_lister_anomalies_chantier_du_document_sans_bloc(
    db_session: AsyncSession,
) -> None:
    """Non-régression : une anomalie de document (sans bloc, ex. R10/R11)
    garde le chantier du document quand `Anomalie.chantier_id` est absent."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Document")
    document = await _creer_document(
        db_session, type_="bl", fournisseur=fournisseur, chantier_id=chantier.id
    )
    db_session.add(
        Anomalie(
            regle="R11",
            gravite="moyenne",
            document_id=document.id,
            detail={"a": "1"},
            statut="ouverte",
        )
    )
    await db_session.commit()

    resultat = await lister_anomalies(db_session, chantier_id=chantier.id)
    ok = len(resultat) == 1 and resultat[0].chantier_id == chantier.id
    assert ok, "une anomalie de document sans bloc doit garder le chantier du document"


async def test_lister_anomalies_chantier_propre_prime_sur_celui_du_bloc(
    db_session: AsyncSession,
) -> None:
    """Une anomalie de bloc qui porterait aussi un `chantier_id` propre :
    c'est le sien qui l'emporte (Ruling R19)."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier_bloc = await _creer_chantier(db_session, nom="Chantier Du Bloc")
    chantier_propre = await _creer_chantier(db_session, nom="Chantier Propre")
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F19")
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier_bloc.id)
    db_session.add(
        Anomalie(
            regle="R01",
            gravite="haute",
            document_id=facture.id,
            bloc_id=bloc.id,
            chantier_id=chantier_propre.id,
            detail={"a": "1"},
            statut="ouverte",
        )
    )
    await db_session.commit()

    resultat = await lister_anomalies(db_session)
    ok = len(resultat) == 1 and resultat[0].chantier_id == chantier_propre.id
    assert ok, "le chantier propre de l'anomalie doit l'emporter sur celui du bloc"


async def test_lister_anomalies_limite(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    db_session.add_all(
        [
            Anomalie(
                regle=f"R0{i}",
                gravite="haute",
                document_id=facture.id,
                detail={"a": str(i)},
                statut="ouverte",
            )
            for i in range(1, 4)
        ]
    )
    await db_session.commit()

    resultat = await lister_anomalies(db_session, limite=2)
    assert len(resultat) == 2


# --------------------------------------------------------------------------
# compter_anomalies_hautes_ouvertes
# --------------------------------------------------------------------------


async def test_compter_anomalies_hautes_ouvertes(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    db_session.add_all(
        [
            Anomalie(
                regle="R01",
                gravite="haute",
                document_id=facture.id,
                detail={"a": "1"},
                statut="ouverte",
            ),
            Anomalie(
                regle="R02",
                gravite="haute",
                document_id=facture.id,
                detail={"a": "1"},
                statut="traitee",
                traitee_le=datetime.now(UTC),
                commentaire="Traitée (test).",
            ),
            Anomalie(
                regle="R17",
                gravite="moyenne",
                document_id=facture.id,
                detail={"a": "1"},
                statut="ouverte",
            ),
        ]
    )
    await db_session.commit()

    nb = await compter_anomalies_hautes_ouvertes(db_session)
    assert nb == 1


# --------------------------------------------------------------------------
# traiter_anomalie — cycle de vie
# --------------------------------------------------------------------------


async def test_traiter_anomalie_transition_traitee(db_session: AsyncSession) -> None:
    admin = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    anomalie = Anomalie(
        regle="R01",
        gravite="haute",
        document_id=facture.id,
        detail={"a": "1"},
        statut="ouverte",
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)

    resultat = await traiter_anomalie(
        db_session,
        anomalie.id,
        statut="traitee",
        commentaire="Corrigé côté fournisseur.",
        auteur_id=admin.id,
    )

    ok = (
        resultat.statut == "traitee"
        and resultat.commentaire == "Corrigé côté fournisseur."
        and resultat.traitee_par == admin.nom
        and resultat.traitee_le is not None
    )
    assert ok

    journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.action == "anomalie_traitee",
                Journal.cible_id == str(anomalie.id),
            )
        )
    ).scalar_one()
    ok = (
        journal.utilisateur_id == admin.id
        and journal.avant == {"statut": "ouverte", "commentaire": None}
        and journal.apres
        == {"statut": "traitee", "commentaire": "Corrigé côté fournisseur."}
    )
    assert ok


async def test_traiter_anomalie_transition_ignoree(db_session: AsyncSession) -> None:
    admin = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    anomalie = Anomalie(
        regle="R07",
        gravite="moyenne",
        document_id=facture.id,
        detail={"a": "1"},
        statut="ouverte",
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)

    resultat = await traiter_anomalie(
        db_session,
        anomalie.id,
        statut="ignoree",
        commentaire="Prix négocié, à ignorer.",
        auteur_id=admin.id,
    )

    assert resultat.statut == "ignoree"
    journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.action == "anomalie_ignoree",
                Journal.cible_id == str(anomalie.id),
            )
        )
    ).scalar_one()
    assert journal.utilisateur_id == admin.id


async def test_traiter_anomalie_refuse_si_deja_traitee(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    anomalie = Anomalie(
        regle="R01",
        gravite="haute",
        document_id=facture.id,
        detail={"a": "1"},
        statut="traitee",
        traitee_le=datetime.now(UTC),
        commentaire="Déjà traitée.",
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)

    with pytest.raises(TransitionInterdite):
        await traiter_anomalie(
            db_session,
            anomalie.id,
            statut="ignoree",
            commentaire="Nouvelle tentative.",
            auteur_id=admin.id,
        )


async def test_traiter_anomalie_refuse_commentaire_vide(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    anomalie = Anomalie(
        regle="R01",
        gravite="haute",
        document_id=facture.id,
        detail={"a": "1"},
        statut="ouverte",
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)

    with pytest.raises(ValueError):
        await traiter_anomalie(
            db_session,
            anomalie.id,
            statut="traitee",
            commentaire="   ",
            auteur_id=admin.id,
        )

    inchangee = await db_session.get(Anomalie, anomalie.id)
    assert inchangee is not None
    assert inchangee.statut == "ouverte"


async def test_traiter_anomalie_intouvable(db_session: AsyncSession) -> None:
    admin = await _creer_utilisateur(db_session)
    with pytest.raises(AnomalieIntrouvable):
        await traiter_anomalie(
            db_session,
            uuid.uuid4(),
            statut="traitee",
            commentaire="Peu importe.",
            auteur_id=admin.id,
        )


async def test_une_anomalie_r15_ouverte_n_est_ni_listee_ni_comptee(
    db_session: AsyncSession,
) -> None:
    """R15 est retirée pour de bon (31/10/2026) : même une ligne R15 encore
    ouverte en base (avant la migration 0017) est masquée de toute lecture."""
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)
    db_session.add(
        Anomalie(
            regle="R15",
            gravite="basse",
            document_id=document.id,
            detail={"a": "1"},
            statut="ouverte",
        )
    )
    await db_session.commit()

    assert await lister_anomalies(db_session) == []
    assert await compter_anomalies_ouvertes(db_session) == (0, 0)
