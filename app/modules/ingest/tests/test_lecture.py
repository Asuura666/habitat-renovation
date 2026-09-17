"""Tests de la lecture des factures et documents (`ingest/lecture.py`,
L2-T5) : `documents_bl_par_numeros`, `lister_factures`, `facture_detail`,
`lister_documents`, `fichier_facture`, `fichier_document`.

Base de test réelle (`bl_test`), `docs_dir` temporaire (`tmp_path`). Les
routes HTTP (droits, codes de statut) vivent dans
`app/modules/api/tests/test_factures_lecture.py` et `test_documents.py` —
`api` ne peut pas importer `extract` ni construire les objets ORM
directement (L2-D3) ; ce fichier teste donc la couche service en isolation,
avec des données entièrement inventées (R17).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.ingest.lecture import (
    DocumentIntrouvable,
    FactureIntrouvable,
    documents_bl_par_numeros,
    facture_detail,
    fichier_document,
    fichier_facture,
    lister_documents,
    lister_factures,
)
from app.modules.ingest.models import (
    BlocFacture,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_BASE_TEMPS = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _instant(decalage_s: int) -> datetime:
    """Horodatage déterministe, distinct par appel — évite de dépendre de
    `func.now()` (identique pour toutes les lignes d'une même transaction,
    voir le commentaire de `BlocFacture.ordre` dans `ingest/models.py`) pour
    les tests qui portent justement sur le tri/le filtrage par date."""
    return _BASE_TEMPS + timedelta(seconds=decalage_s)


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    role: str = "agent",
    nom: str | None = "Nom Testeur",
    email: str | None = None,
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email or f"{role}.{uuid.uuid4()}@example.invalid",
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


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "FAC0001",
    date_doc: object = None,
    total_ht: Decimal | None = Decimal("100.00"),
    deposant: Utilisateur | None = None,
    fichier_path: str = "/var/docs/facture-invente.pdf",
    created_at: datetime | None = None,
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=fichier_path,
        fournisseur_id=fournisseur.id,
        numero=numero,
        date_doc=date_doc,
        total_ht=total_ht,
        deposant_id=deposant.id if deposant is not None else None,
    )
    if created_at is not None:
        document.created_at = created_at
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    ordre: int,
    numero_bl: str | None = "L1",
    chantier: str | None = "CHANTIER INVENTE",
    commentaire: str | None = None,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        numero_commande=None,
        chantier_brut=chantier,
        commentaire=commentaire,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture | None,
    ordre: int,
    montant_ht: Decimal | None = Decimal("10.00"),
    type_ligne: str = "article",
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        article_brut="Article inventé",
        code_brut="ART1",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("1"),
        unite_brut="U",
        pu_ht=Decimal("10.00"),
        pu_cdt=Decimal("10.00"),
        remise_pct=None,
        montant_ht=montant_ht,
        tva=Decimal("20"),
        type_ligne=type_ligne,
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    return ligne


async def _creer_document_bl(
    db_session: AsyncSession,
    *,
    numero: str | None,
    type_: str = "bl",
    statut: str = "recu",
    deposant: Utilisateur | None = None,
    created_at: datetime | None = None,
    confirme_par: Utilisateur | None = None,
    confirme_le: datetime | None = None,
    photo_compressee: bool | None = None,
    fichier_path: str | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=fichier_path or f"/var/docs/{uuid.uuid4()}.jpg",
        numero=numero,
        deposant_id=deposant.id if deposant is not None else None,
        confirme_par=confirme_par.id if confirme_par is not None else None,
        confirme_le=confirme_le,
        photo_compressee=photo_compressee,
    )
    if created_at is not None:
        document.created_at = created_at
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_journal_confirmation(
    db_session: AsyncSession,
    *,
    document: Document,
    action: str,
    utilisateur: Utilisateur | None = None,
    horodatage: datetime | None = None,
) -> Journal:
    """Entrée de journal telle qu'écrite par `_decider_clic`
    (`quantites_verifiees`/`ecart_constate`), construite directement (pas via
    `traiter_clic`, testé dans `test_service.py`) : ce fichier teste
    `lister_documents` en isolation (Ruling L2-R8)."""
    entree = Journal(
        utilisateur_id=utilisateur.id if utilisateur is not None else None,
        action=action,
        cible_table="document",
        cible_id=str(document.id),
    )
    if horodatage is not None:
        entree.horodatage = horodatage
    db_session.add(entree)
    await db_session.commit()
    await db_session.refresh(entree)
    return entree


# --------------------------------------------------------------------------
# documents_bl_par_numeros
# --------------------------------------------------------------------------


async def test_documents_bl_par_numeros_vide_ne_requete_pas(
    db_session: AsyncSession,
) -> None:
    assert await documents_bl_par_numeros(db_session, []) == {}


async def test_documents_bl_par_numeros_normalise_espaces_et_casse(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document_bl(db_session, numero="l1000000001")

    resultat = await documents_bl_par_numeros(db_session, ["  L1000000001  "])

    assert resultat == {"L1000000001": document.id}


async def test_documents_bl_par_numeros_exclut_archive(
    db_session: AsyncSession,
) -> None:
    await _creer_document_bl(db_session, numero="L2", statut="archive")

    assert await documents_bl_par_numeros(db_session, ["L2"]) == {}


async def test_documents_bl_par_numeros_exclut_type_facture(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_facture(db_session, fournisseur=fournisseur, numero="L3")

    assert await documents_bl_par_numeros(db_session, ["L3"]) == {}


async def test_documents_bl_par_numeros_espace_insecable_de_bord_trouve(
    db_session: AsyncSession,
) -> None:
    """Dette L2-T5, vague finale du lot 2, point 5 : un numéro stocké entouré
    d'espaces insécables (U+00A0, fréquent en sortie d'OCR) doit être trouvé
    par le filtre SQL (`btrim`, pas seulement l'espace ASCII de `trim()`),
    aligné sur `_normaliser_numero` (`str.strip()` côté Python)."""
    document = await _creer_document_bl(db_session, numero="\u00a0L5000000001\u00a0")

    resultat = await documents_bl_par_numeros(db_session, ["L5000000001"])

    assert resultat == {"L5000000001": document.id}


async def test_documents_bl_par_numeros_tabulation_de_bord_trouve(
    db_session: AsyncSession,
) -> None:
    """Même correction (point 5) pour la tabulation de bord."""
    document = await _creer_document_bl(db_session, numero="\tL5000000002\t")

    resultat = await documents_bl_par_numeros(db_session, ["L5000000002"])

    assert resultat == {"L5000000002": document.id}


async def test_documents_bl_par_numeros_doublon_le_plus_ancien_gagne(
    db_session: AsyncSession,
) -> None:
    """Décision du contrôleur L2-T5 : en cas de plusieurs documents pour un
    même numéro normalisé, le plus ancien fait foi."""
    plus_ancien = await _creer_document_bl(
        db_session, numero="L4", created_at=_instant(0)
    )
    await _creer_document_bl(db_session, numero="l4", created_at=_instant(10))

    resultat = await documents_bl_par_numeros(db_session, ["L4"])

    assert resultat == {"L4": plus_ancien.id}


# --------------------------------------------------------------------------
# lister_factures
# --------------------------------------------------------------------------


async def test_lister_factures_vide(db_session: AsyncSession) -> None:
    assert await lister_factures(db_session) == []


async def test_lister_factures_trie_par_date_doc_puis_created_at_decroissants(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    ancienne = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="FAC-ANCIENNE",
        date_doc=datetime(2026, 7, 1).date(),
    )
    recente = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="FAC-RECENTE",
        date_doc=datetime(2026, 8, 1).date(),
    )
    # Même `date_doc` que `recente`, mais insérée avant (`created_at`
    # antérieur) : doit apparaître après `recente`, avant `ancienne`.
    meme_date_plus_ancienne = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="FAC-MEME-DATE",
        date_doc=datetime(2026, 8, 1).date(),
        created_at=_instant(0),
    )
    await db_session.refresh(recente)
    recente.created_at = _instant(10)
    await db_session.commit()

    resultat = await lister_factures(db_session)

    assert [resume.numero for resume in resultat] == [
        "FAC-RECENTE",
        "FAC-MEME-DATE",
        "FAC-ANCIENNE",
    ]
    assert {r.id for r in resultat} == {
        ancienne.id,
        recente.id,
        meme_date_plus_ancienne.id,
    }


async def test_lister_factures_nb_blocs_et_nb_blocs_recus(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="FAC0002"
    )
    await _creer_bloc(db_session, facture=facture, ordre=0, numero_bl="L100")
    await _creer_bloc(db_session, facture=facture, ordre=1, numero_bl="L101")
    # Un seul des deux numéros a un BL reçu.
    await _creer_document_bl(db_session, numero="L100")

    resultat = await lister_factures(db_session)

    assert len(resultat) == 1
    assert resultat[0].nb_blocs == 2
    assert resultat[0].nb_blocs_recus == 1


async def test_lister_factures_sans_n_plus_1(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """`nb_blocs`/`nb_blocs_recus` sans N+1 (décision du contrôleur L2-T5) :
    le nombre de requêtes SQL ne doit pas dépendre du nombre de factures ni
    de blocs."""
    fournisseur = await _creer_fournisseur(db_session)
    for indice_facture in range(3):
        facture = await _creer_facture(
            db_session, fournisseur=fournisseur, numero=f"FAC-N1-{indice_facture}"
        )
        for indice_bloc in range(2):
            numero_bl = f"L-N1-{indice_facture}-{indice_bloc}"
            await _creer_bloc(
                db_session, facture=facture, ordre=indice_bloc, numero_bl=numero_bl
            )
            await _creer_document_bl(db_session, numero=numero_bl)

    compteur = {"n": 0}

    def _avant_execution(*args: object, **kwargs: object) -> None:
        compteur["n"] += 1

    sync_engine: Engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _avant_execution)
    try:
        resultat = await lister_factures(db_session)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _avant_execution)

    assert len(resultat) == 3
    assert all(resume.nb_blocs_recus == 2 for resume in resultat)
    # Trois requêtes au total (factures, blocs, correspondance BL) : jamais
    # une par facture (qui en ferait au moins 3 de plus).
    assert compteur["n"] <= 3


# --------------------------------------------------------------------------
# facture_detail
# --------------------------------------------------------------------------


async def test_facture_detail_id_absent_leve_facture_introuvable(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(FactureIntrouvable):
        await facture_detail(db_session, uuid.uuid4())


async def test_facture_detail_document_non_facture_leve_facture_introuvable(
    db_session: AsyncSession,
) -> None:
    document_bl = await _creer_document_bl(db_session, numero="L999")

    with pytest.raises(FactureIntrouvable):
        await facture_detail(db_session, document_bl.id)


async def test_facture_detail_entete_et_deposant(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Unikalo")
    deposant = await _creer_utilisateur(db_session, role="admin", nom="Admin Testeur")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="FAC0003",
        total_ht=Decimal("250.75"),
        deposant=deposant,
    )

    detail = await facture_detail(db_session, facture.id)

    assert detail.id == facture.id
    assert detail.numero == "FAC0003"
    assert detail.fournisseur == "Unikalo"
    assert detail.total_ht == Decimal("250.75")
    assert detail.deposant == "Admin Testeur"
    assert detail.blocs == []


async def test_facture_detail_deposant_sans_nom_utilise_lemail(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    deposant = await _creer_utilisateur(
        db_session, role="admin", nom=None, email="admin.sans-nom@example.invalid"
    )
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, deposant=deposant
    )

    detail = await facture_detail(db_session, facture.id)

    assert detail.deposant == "admin.sans-nom@example.invalid"


async def test_facture_detail_blocs_dans_lordre_malgre_linsertion(
    db_session: AsyncSession,
) -> None:
    """Les blocs sont insérés hors ordre (`ordre=2`, puis `0`, puis `1`) :
    la lecture doit malgré tout les renvoyer dans l'ordre de la facture."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, ordre=2, numero_bl="L-C")
    await _creer_bloc(db_session, facture=facture, ordre=0, numero_bl="L-A")
    await _creer_bloc(db_session, facture=facture, ordre=1, numero_bl="L-B")

    detail = await facture_detail(db_session, facture.id)

    assert [bloc.numero_bl for bloc in detail.blocs] == ["L-A", "L-B", "L-C"]


async def test_facture_detail_lignes_dans_lordre(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, ordre=0)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, ordre=1, montant_ht=Decimal("5")
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, ordre=0, montant_ht=Decimal("10")
    )

    detail = await facture_detail(db_session, facture.id)

    assert [ligne.ordre for ligne in detail.blocs[0].lignes] == [0, 1]


async def test_facture_detail_montant_ht_du_bloc_somme_des_lignes_non_nulles(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, ordre=0)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, ordre=0, montant_ht=Decimal("10.00")
    )
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        ordre=1,
        montant_ht=None,
        type_ligne="commentaire",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, ordre=2, montant_ht=Decimal("5.50")
    )

    detail = await facture_detail(db_session, facture.id)

    assert detail.blocs[0].montant_ht == Decimal("15.50")


async def test_facture_detail_bloc_sans_lignes_montant_ht_zero(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, ordre=0)

    detail = await facture_detail(db_session, facture.id)

    assert detail.blocs[0].montant_ht == Decimal("0")


async def test_facture_detail_photo_deposee_apres_facture_bl_recu_a_lecture_suivante(
    db_session: AsyncSession,
) -> None:
    """L2-D12 : le statut « reçu » est calculé à la lecture, jamais persisté
    — une photo déposée après coup doit apparaître reçue dès la lecture
    suivante, sans ré-analyser la facture."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, ordre=0, numero_bl="L200")

    premiere_lecture = await facture_detail(db_session, facture.id)
    assert premiere_lecture.blocs[0].bl_recu is False
    assert premiere_lecture.blocs[0].bl_document_id is None

    document_bl = await _creer_document_bl(db_session, numero="L200")

    seconde_lecture = await facture_detail(db_session, facture.id)
    assert seconde_lecture.blocs[0].bl_recu is True
    assert seconde_lecture.blocs[0].bl_document_id == document_bl.id


async def test_facture_detail_document_archive_ignore(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, ordre=0, numero_bl="L201")
    await _creer_document_bl(db_session, numero="L201", statut="archive")

    detail = await facture_detail(db_session, facture.id)

    assert detail.blocs[0].bl_recu is False
    assert detail.blocs[0].bl_document_id is None


# --------------------------------------------------------------------------
# lister_documents
# --------------------------------------------------------------------------


async def test_lister_documents_admin_voit_tout_sauf_factures_et_archives(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    agent = await _creer_utilisateur(db_session, role="agent")
    bl_agent = await _creer_document_bl(db_session, numero="L300", deposant=agent)
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_facture(db_session, fournisseur=fournisseur, numero="FAC-EXCLUE")
    await _creer_document_bl(db_session, numero="L301", statut="archive")

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert [doc.id for doc in resultat] == [bl_agent.id]


async def test_lister_documents_agent_limite_a_ses_propres_documents(
    db_session: AsyncSession,
) -> None:
    agent_1 = await _creer_utilisateur(db_session, role="agent")
    agent_2 = await _creer_utilisateur(db_session, role="agent")
    document_1 = await _creer_document_bl(db_session, numero="L310", deposant=agent_1)
    await _creer_document_bl(db_session, numero="L311", deposant=agent_2)

    resultat = await lister_documents(
        db_session, utilisateur_id=agent_1.id, role="agent", depuis=None, limite=100
    )

    assert [doc.id for doc in resultat] == [document_1.id]


async def test_lister_documents_trie_par_created_at_decroissant(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    plus_ancien = await _creer_document_bl(
        db_session, numero="L320", created_at=_instant(0)
    )
    plus_recent = await _creer_document_bl(
        db_session, numero="L321", created_at=_instant(10)
    )

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert [doc.id for doc in resultat] == [plus_recent.id, plus_ancien.id]


async def test_lister_documents_depuis_filtre_les_plus_anciens(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    await _creer_document_bl(db_session, numero="L330", created_at=_instant(0))
    recent = await _creer_document_bl(
        db_session, numero="L331", created_at=_instant(20)
    )

    resultat = await lister_documents(
        db_session,
        utilisateur_id=admin.id,
        role="admin",
        depuis=_instant(10),
        limite=100,
    )

    assert [doc.id for doc in resultat] == [recent.id]


async def test_lister_documents_limite_borne_le_nombre_de_resultats(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    for indice in range(3):
        await _creer_document_bl(
            db_session, numero=f"L34{indice}", created_at=_instant(indice)
        )

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=2
    )

    assert len(resultat) == 2


async def test_lister_documents_deposant_et_confirme_par_noms_affiches(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    deposant = await _creer_utilisateur(
        db_session, role="agent", nom="Déposant Testeur"
    )
    confirmateur = await _creer_utilisateur(
        db_session, role="agent", nom="Confirmateur Testeur"
    )
    document = await _creer_document_bl(
        db_session,
        numero="L350",
        deposant=deposant,
        confirme_par=confirmateur,
        confirme_le=_instant(0),
        photo_compressee=True,
    )

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert len(resultat) == 1
    resume = resultat[0]
    assert resume.id == document.id
    assert resume.deposant == "Déposant Testeur"
    assert resume.confirme_par == "Confirmateur Testeur"
    assert resume.photo_compressee is True
    assert resume.numero_interne == document.numero_interne


async def test_lister_documents_sans_deposant_ni_confirmateur(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    await _creer_document_bl(db_session, numero="L351")

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert resultat[0].deposant is None
    assert resultat[0].confirme_par is None


# --------------------------------------------------------------------------
# lister_documents — confirmation (Ruling L2-R8, revue L2-T7 tour 1/5)
#
# Constat de revue corrigé ici : `statut` seul ne dit jamais si un document
# a été confirmé « vérifié » ou « écart » — un document `a_verifier` (OCR
# sans numéro de BL détecté, voir `traiter_fichier`) peut tout à fait
# recevoir ensuite « Quantités vérifiées ». `confirmation` est donc dérivée
# du journal, jamais de `statut`.
# --------------------------------------------------------------------------


async def test_lister_documents_confirmation_verifiee_meme_si_statut_a_verifier(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    confirmateur = await _creer_utilisateur(db_session, role="agent")
    # Statut `a_verifier` d'origine OCR (numéro de BL non détecté), sans lien
    # avec l'action de confirmation reçue ensuite : c'est exactement le cas
    # que `statut` seul interprétait à tort comme un écart.
    document = await _creer_document_bl(
        db_session,
        numero=None,
        statut="a_verifier",
        confirme_par=confirmateur,
        confirme_le=_instant(0),
    )
    await _creer_journal_confirmation(
        db_session,
        document=document,
        action="quantites_verifiees",
        utilisateur=confirmateur,
    )

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert len(resultat) == 1
    assert resultat[0].confirmation == "verifiee"


async def test_lister_documents_confirmation_ecart(db_session: AsyncSession) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    confirmateur = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document_bl(
        db_session,
        numero="L360",
        statut="a_verifier",
        confirme_par=confirmateur,
        confirme_le=_instant(0),
    )
    await _creer_journal_confirmation(
        db_session, document=document, action="ecart_constate", utilisateur=confirmateur
    )

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert len(resultat) == 1
    assert resultat[0].confirmation == "ecart"


async def test_lister_documents_confirmation_absente_sans_clic(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    await _creer_document_bl(db_session, numero="L361")

    resultat = await lister_documents(
        db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
    )

    assert len(resultat) == 1
    assert resultat[0].confirmation is None


async def test_lister_documents_confirmation_sans_n_plus_1(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """La jointure vers `journal` (confirmation, Ruling L2-R8) ne doit pas
    ajouter de requête par document : toujours une seule requête au total,
    quel que soit le nombre de documents."""
    admin = await _creer_utilisateur(db_session, role="admin")
    confirmateur = await _creer_utilisateur(db_session, role="agent")
    for indice in range(3):
        document = await _creer_document_bl(
            db_session,
            numero=f"L-N1-DOC-{indice}",
            confirme_par=confirmateur,
            confirme_le=_instant(indice),
        )
        action = "quantites_verifiees" if indice % 2 == 0 else "ecart_constate"
        await _creer_journal_confirmation(
            db_session, document=document, action=action, utilisateur=confirmateur
        )

    compteur = {"n": 0}

    def _avant_execution(*args: object, **kwargs: object) -> None:
        compteur["n"] += 1

    sync_engine: Engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _avant_execution)
    try:
        resultat = await lister_documents(
            db_session, utilisateur_id=admin.id, role="admin", depuis=None, limite=100
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _avant_execution)

    assert len(resultat) == 3
    assert {document.confirmation for document in resultat} == {"verifiee", "ecart"}
    # Une seule requête (jointure sur une sous-requête), jamais une par
    # document.
    assert compteur["n"] <= 1


# --------------------------------------------------------------------------
# fichier_facture / fichier_document
# --------------------------------------------------------------------------


async def test_fichier_facture_id_absent_leve_document_introuvable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    with pytest.raises(DocumentIntrouvable):
        await fichier_facture(db_session, uuid.uuid4(), tmp_path)


async def test_fichier_facture_document_non_facture_leve_document_introuvable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    document_bl = await _creer_document_bl(db_session, numero="L400")

    with pytest.raises(DocumentIntrouvable):
        await fichier_facture(db_session, document_bl.id, tmp_path)


async def test_fichier_facture_chemin_valide_renvoie_pdf(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    chemin = tmp_path / "facture.pdf"
    chemin.write_bytes(b"%PDF-1.4\ncontenu-invente")
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, fichier_path=str(chemin)
    )

    fichier = await fichier_facture(db_session, facture.id, tmp_path)

    assert fichier.chemin == chemin.resolve()
    assert fichier.type_mime == "application/pdf"


async def test_fichier_document_admin_voit_nimporte_quel_document(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    admin = await _creer_utilisateur(db_session, role="admin")
    agent = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document_bl(
        db_session, numero="L410", deposant=agent, fichier_path=str(chemin)
    )

    fichier = await fichier_document(
        db_session, document.id, tmp_path, utilisateur_id=admin.id, role="admin"
    )

    assert fichier.chemin == chemin.resolve()
    assert fichier.type_mime == "image/jpeg"


async def test_fichier_document_agent_autre_agent_leve_document_introuvable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    agent_1 = await _creer_utilisateur(db_session, role="agent")
    agent_2 = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document_bl(
        db_session, numero="L420", deposant=agent_1, fichier_path=str(chemin)
    )

    with pytest.raises(DocumentIntrouvable):
        await fichier_document(
            db_session, document.id, tmp_path, utilisateur_id=agent_2.id, role="agent"
        )


async def test_fichier_document_agent_son_propre_document_ok(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    agent = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document_bl(
        db_session, numero="L430", deposant=agent, fichier_path=str(chemin)
    )

    fichier = await fichier_document(
        db_session, document.id, tmp_path, utilisateur_id=agent.id, role="agent"
    )

    assert fichier.chemin == chemin.resolve()


async def test_fichier_document_chemin_hors_docs_dir_leve_sans_journaliser_le_chemin(
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    hors_docs_dir = tmp_path / "hors-docs" / "secret.jpg"
    hors_docs_dir.parent.mkdir()
    hors_docs_dir.write_bytes(b"contenu-invente")
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document_bl(
        db_session, numero="L440", fichier_path=str(hors_docs_dir)
    )

    with (
        caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"),
        pytest.raises(DocumentIntrouvable),
    ):
        await fichier_document(
            db_session, document.id, docs_dir, utilisateur_id=admin.id, role="admin"
        )

    assert "secret.jpg" not in caplog.text
    assert "hors-docs" not in caplog.text
    assert str(document.id) in caplog.text


async def test_fichier_document_fichier_absent_du_disque_leve_document_introuvable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document_bl(
        db_session, numero="L450", fichier_path=str(tmp_path / "jamais-ecrit.jpg")
    )

    with pytest.raises(DocumentIntrouvable):
        await fichier_document(
            db_session, document.id, tmp_path, utilisateur_id=admin.id, role="admin"
        )
