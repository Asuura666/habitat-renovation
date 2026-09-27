"""Tests de la table `commentaire` (migration 0012, tâche C1 de la phase 3)
et du service `ingest/commentaires.py` (tâche C2) : ajout et lecture des
commentaires sur les lignes d'un bon. Base de test réelle (`bl_test`),
données entièrement inventées.
"""

from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.commentaires import (
    LONGUEUR_COMMENTAIRE_MAX,
    CommentaireInvalide,
    LigneIntrouvable,
    ajouter_commentaire,
    commentaires_du_bon,
)
from app.modules.ingest.corrections import LigneSaisie, corriger_lignes
from app.modules.ingest.extraction_bl import enregistrer_extraction_bl
from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.models import (
    Commentaire,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

# Même fixture que `test_extraction_bl.py`/`test_corrections.py` (donnée
# synthétique, fournisseur/BL/chantier/articles entièrement inventés) --
# relue ici plutôt qu'importée depuis un autre fichier de tests (même
# principe que `test_corrections.py`, qui ne réimporte pas non plus
# `test_extraction_bl.py`).
_DONNEES_SYNTHETIQUES = (
    Path(__file__).resolve().parent.parent.parent
    / "extract"
    / "tests"
    / "donnees"
    / "bl_synthetique.mistral-ocr.json"
)
with _DONNEES_SYNTHETIQUES.open(encoding="utf-8") as _fichier:
    _REPONSE_SYNTHETIQUE_BASE: dict[str, Any] = json.load(_fichier)


def _reponse_synthetique() -> dict[str, Any]:
    return copy.deepcopy(_REPONSE_SYNTHETIQUE_BASE)


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
    await db_session.flush()
    return utilisateur


async def _creer_document(
    db_session: AsyncSession,
    *,
    type_: str = "bl",
    deposant: Utilisateur | None = None,
) -> Document:
    fournisseur = Fournisseur(nom="Fournisseur Invente Commentaires")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type=type_,
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
        deposant_id=deposant.id if deposant is not None else None,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _creer_ligne(
    db_session: AsyncSession, document: Document, *, ordre: int = 0
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="ART-INVENTE",
        article_brut="Article inventé",
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.flush()
    return ligne


async def _dernier_journal_commentaire(
    db_session: AsyncSession, commentaire_id: uuid.UUID
) -> Journal:
    return (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_table == "commentaire",
                Journal.cible_id == str(commentaire_id),
                Journal.action == "commentaire_ajoute",
            )
        )
    ).scalar_one()


async def test_texte_vide_refuse_par_le_controle_de_longueur(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    db_session.add(
        Commentaire(
            document_id=document.id,
            ligne_id=ligne.id,
            ligne_libelle="ART-INVENTE — Article inventé",
            texte="",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_texte_trop_long_refuse_par_le_controle_de_longueur(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    db_session.add(
        Commentaire(
            document_id=document.id,
            ligne_id=ligne.id,
            ligne_libelle="ART-INVENTE — Article inventé",
            texte="a" * 1001,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_suppression_de_la_ligne_commentee_laisse_le_commentaire_sans_ligne(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    commentaire = Commentaire(
        document_id=document.id,
        ligne_id=ligne.id,
        ligne_libelle="ART-INVENTE — Article inventé",
        texte="Commentaire inventé.",
    )
    db_session.add(commentaire)
    await db_session.commit()

    await db_session.delete(ligne)
    await db_session.commit()

    # `expire_on_commit=False` (`creer_sessionmaker`) : le commentaire déjà
    # chargé n'est pas automatiquement rafraîchi par le commit --
    # `refresh()` va relire la ligne mise à `NULL` par la base (`ON DELETE
    # SET NULL`), pas par l'ORM (aucune relation SQLAlchemy entre les deux
    # tables).
    await db_session.refresh(commentaire)
    assert commentaire.ligne_id is None
    assert commentaire.ligne_libelle == "ART-INVENTE — Article inventé"


async def test_suppression_du_document_supprime_le_commentaire(
    db_session: AsyncSession,
) -> None:
    """`document_id` en `ON DELETE CASCADE` : un commentaire ne survit pas à
    la suppression physique de son bon (qui n'arrive jamais en usage normal,
    aucune route ne le fait -- seule cette contrainte de base est testée).
    Pas de ligne créée ici : une ligne encore présente empêcherait la
    suppression du document (`ligne.document_id` sans `ondelete`, comme
    toutes les autres clés étrangères vers `document`)."""
    document = await _creer_document(db_session)
    commentaire = Commentaire(
        document_id=document.id,
        ligne_id=None,
        ligne_libelle="ART-INVENTE — Article inventé",
        texte="Commentaire inventé.",
    )
    db_session.add(commentaire)
    await db_session.commit()

    await db_session.delete(document)
    await db_session.commit()

    resultat = await db_session.execute(
        select(Commentaire).where(Commentaire.id == commentaire.id)
    )
    assert resultat.scalar_one_or_none() is None


# --------------------------------------------------------------------------
# ajouter_commentaire / commentaires_du_bon (tâche C2)
# --------------------------------------------------------------------------


async def test_ajouter_commentaire_puis_lecture_sous_sa_ligne(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin", nom="Léa Testeuse")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    ajoute = await ajouter_commentaire(
        db_session,
        ligne.id,
        "Commentaire inventé.",
        utilisateur_id=admin.id,
        role="admin",
    )

    assert ajoute.texte == "Commentaire inventé."
    assert ajoute.auteur == "Léa Testeuse"
    assert ajoute.ligne_libelle == "ART-INVENTE — Article inventé"
    assert ajoute.cree_le is not None

    resultat = await commentaires_du_bon(
        db_session, document.id, utilisateur_id=admin.id, role="admin"
    )

    assert resultat.nb_commentaires == 1
    assert resultat.sans_ligne == []
    assert len(resultat.lignes) == 1
    ligne_lue = resultat.lignes[0]
    assert ligne_lue.ligne_id == ligne.id
    assert ligne_lue.code == "ART-INVENTE"
    assert ligne_lue.article == "Article inventé"
    assert len(ligne_lue.commentaires) == 1
    assert ligne_lue.commentaires[0].auteur == "Léa Testeuse"
    assert ligne_lue.commentaires[0].texte == "Commentaire inventé."


async def test_commentaires_du_bon_deux_commentaires_meme_ligne_ordre_chronologique(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    await ajouter_commentaire(
        db_session,
        ligne.id,
        "Premier commentaire.",
        utilisateur_id=admin.id,
        role="admin",
    )
    await ajouter_commentaire(
        db_session,
        ligne.id,
        "Second commentaire.",
        utilisateur_id=admin.id,
        role="admin",
    )

    resultat = await commentaires_du_bon(
        db_session, document.id, utilisateur_id=admin.id, role="admin"
    )

    assert resultat.nb_commentaires == 2
    textes = [c.texte for c in resultat.lignes[0].commentaires]
    assert textes == ["Premier commentaire.", "Second commentaire."]


async def test_ajouter_commentaire_texte_blanc_leve_commentaire_invalide(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    with pytest.raises(CommentaireInvalide):
        await ajouter_commentaire(
            db_session, ligne.id, "   ", utilisateur_id=admin.id, role="admin"
        )


async def test_ajouter_commentaire_texte_trop_long_leve_commentaire_invalide(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    with pytest.raises(CommentaireInvalide):
        await ajouter_commentaire(
            db_session,
            ligne.id,
            "a" * (LONGUEUR_COMMENTAIRE_MAX + 1),
            utilisateur_id=admin.id,
            role="admin",
        )


async def test_commentaires_du_bon_agent_sur_bon_dun_autre_introuvable(
    db_session: AsyncSession,
) -> None:
    agent_1 = await _creer_utilisateur(db_session, role="agent")
    agent_2 = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document(db_session, deposant=agent_1)

    with pytest.raises(DocumentIntrouvable):
        await commentaires_du_bon(
            db_session, document.id, utilisateur_id=agent_2.id, role="agent"
        )


async def test_ajouter_commentaire_agent_sur_bon_dun_autre_leve_ligne_introuvable(
    db_session: AsyncSession,
) -> None:
    agent_1 = await _creer_utilisateur(db_session, role="agent")
    agent_2 = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document(db_session, deposant=agent_1)
    ligne = await _creer_ligne(db_session, document)

    with pytest.raises(LigneIntrouvable):
        await ajouter_commentaire(
            db_session,
            ligne.id,
            "Commentaire inventé.",
            utilisateur_id=agent_2.id,
            role="agent",
        )


async def test_ajouter_commentaire_agent_sur_son_propre_bon_accepte(
    db_session: AsyncSession,
) -> None:
    agent = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document(db_session, deposant=agent)
    ligne = await _creer_ligne(db_session, document)

    ajoute = await ajouter_commentaire(
        db_session,
        ligne.id,
        "Commentaire inventé.",
        utilisateur_id=agent.id,
        role="agent",
    )

    assert ajoute.texte == "Commentaire inventé."

    resultat = await commentaires_du_bon(
        db_session, document.id, utilisateur_id=agent.id, role="agent"
    )
    assert resultat.nb_commentaires == 1


async def test_commentaires_du_bon_facture_introuvable(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    facture = await _creer_document(db_session, type_="facture")

    with pytest.raises(DocumentIntrouvable):
        await commentaires_du_bon(
            db_session, facture.id, utilisateur_id=admin.id, role="admin"
        )


async def test_ajouter_commentaire_ligne_de_facture_leve_ligne_introuvable(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    facture = await _creer_document(db_session, type_="facture")
    ligne = await _creer_ligne(db_session, facture)

    with pytest.raises(LigneIntrouvable):
        await ajouter_commentaire(
            db_session,
            ligne.id,
            "Commentaire inventé.",
            utilisateur_id=admin.id,
            role="admin",
        )


async def test_ajouter_commentaire_ligne_id_inconnu_leve_ligne_introuvable(
    db_session: AsyncSession,
) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")

    with pytest.raises(LigneIntrouvable):
        await ajouter_commentaire(
            db_session,
            uuid.uuid4(),
            "Commentaire inventé.",
            utilisateur_id=admin.id,
            role="admin",
        )


async def test_ajouter_commentaire_ecrit_le_journal(db_session: AsyncSession) -> None:
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    ajoute = await ajouter_commentaire(
        db_session,
        ligne.id,
        "Commentaire inventé.",
        utilisateur_id=admin.id,
        role="admin",
    )

    journal = await _dernier_journal_commentaire(db_session, ajoute.id)
    assert journal.utilisateur_id == admin.id
    assert journal.apres is not None
    assert journal.apres["document_id"] == str(document.id)
    assert journal.apres["numero"] == document.numero
    assert journal.apres["ligne"] == "ART-INVENTE — Article inventé"
    assert journal.apres["texte"] == "Commentaire inventé."


async def test_commentaires_du_bon_relance_lecture_passe_en_sans_ligne(
    db_session: AsyncSession,
) -> None:
    """Une relance de la lecture (`enregistrer_extraction_bl` rejouée sur le
    même document) supprime puis recrée les lignes -- le commentaire perd sa
    ligne (`ON DELETE SET NULL`) mais reste affichable grâce à son libellé
    figé (`CommentairesBon.sans_ligne`)."""
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    await ajouter_commentaire(
        db_session,
        ligne.id,
        "Commentaire avant relance.",
        utilisateur_id=admin.id,
        role="admin",
    )

    await enregistrer_extraction_bl(
        db_session, document.id, _reponse_synthetique(), relance=True
    )

    resultat = await commentaires_du_bon(
        db_session, document.id, utilisateur_id=admin.id, role="admin"
    )

    assert resultat.nb_commentaires == 1
    assert all(ligne_lue.commentaires == [] for ligne_lue in resultat.lignes)
    assert len(resultat.sans_ligne) == 1
    assert resultat.sans_ligne[0].texte == "Commentaire avant relance."
    assert resultat.sans_ligne[0].ligne_libelle == "ART-INVENTE — Article inventé"


async def test_commentaires_du_bon_correction_lignes_garde_la_ligne_commentaire_reste(
    db_session: AsyncSession,
) -> None:
    """`corriger_lignes` qui conserve l'`id` d'une ligne (mise à jour, pas
    suppression) laisse le commentaire attaché dessus (jamais dans
    `sans_ligne`)."""
    admin = await _creer_utilisateur(db_session, role="admin")
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)

    await ajouter_commentaire(
        db_session,
        ligne.id,
        "Commentaire avant correction.",
        utilisateur_id=admin.id,
        role="admin",
    )

    await corriger_lignes(
        db_session,
        document.id,
        [
            LigneSaisie(
                id=ligne.id,
                code_brut=ligne.code_brut,
                article_brut=ligne.article_brut,
                qte_livree=ligne.qte_livree,
                qte_totale=ligne.qte_totale,
                unite_brut=ligne.unite_brut,
                pu_ht=ligne.pu_ht,
                montant_ht=Decimal("42.00"),
            )
        ],
        auteur_id=admin.id,
    )

    resultat = await commentaires_du_bon(
        db_session, document.id, utilisateur_id=admin.id, role="admin"
    )

    assert resultat.sans_ligne == []
    assert len(resultat.lignes) == 1
    assert resultat.lignes[0].ligne_id == ligne.id
    assert len(resultat.lignes[0].commentaires) == 1
    assert resultat.lignes[0].commentaires[0].texte == "Commentaire avant correction."
