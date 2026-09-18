"""Tests de `ingest/corrections.py` (L3-T8a) : détail, correction,
validation, archivage et relance d'un BL.

Base de test réelle (`bl_test`), données entièrement inventées (R17). La
donnée synthétique de relance (fournisseur, BL, chantier et articles
inventés) est relue depuis `app/modules/extract/tests/donnees/
bl_synthetique.mistral-ocr.json` (même fichier que `test_extraction_bl.py`).
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.verification import CodeMotif
from app.modules.ingest import extraction_bl as ingest_extraction_bl
from app.modules.ingest import rapprochement as ingest_rapprochement
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
from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import (
    Article,
    BlocFacture,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_ADMIN_ID = uuid.uuid4()

_DONNEES_SYNTHETIQUES = (
    Path(__file__).resolve().parent.parent.parent
    / "extract"
    / "tests"
    / "donnees"
    / "bl_synthetique.mistral-ocr.json"
)
with _DONNEES_SYNTHETIQUES.open(encoding="utf-8") as _fichier:
    _REPONSE_SYNTHETIQUE_BASE: dict[str, Any] = json.load(_fichier)

NUMERO_BL_SYNTHETIQUE = "L209900000123"


def _reponse_synthetique() -> dict[str, Any]:
    return copy.deepcopy(_REPONSE_SYNTHETIQUE_BASE)


# --------------------------------------------------------------------------
# Aides de construction (données inventées)
# --------------------------------------------------------------------------


@pytest.fixture
async def admin(db_session: AsyncSession) -> Utilisateur:
    """Auteur réel des corrections (`journal.utilisateur_id` porte une clé
    étrangère vers `utilisateur` : un UUID inventé ferait échouer l'écriture
    du journal, pas seulement l'assertion)."""
    return await _creer_utilisateur(db_session, role="admin")


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
    db_session: AsyncSession,
    *,
    nom: str = "Fournisseur Testeur",
    aliases: list[str] | None = None,
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom, aliases=aliases)
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
    total_ht: Decimal | None = None,
    total_tva: Decimal | None = None,
    total_ttc: Decimal | None = None,
    numero_commande: str | None = None,
    enleve_par: str | None = None,
    date_doc: object = None,
    deposant: Utilisateur | None = None,
    extraction: dict[str, Any] | None = None,
    fichier_path: str | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=fichier_path or f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        chantier_brut=chantier_brut,
        chantier_id=chantier_id,
        total_ht=total_ht,
        total_tva=total_tva,
        total_ttc=total_ttc,
        numero_commande=numero_commande,
        enleve_par=enleve_par,
        date_doc=date_doc,
        deposant_id=deposant.id if deposant is not None else None,
    )
    if extraction is not None:
        document.extraction = extraction
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    ordre: int,
    montant_ht: Decimal | None = Decimal("10.00"),
    confiance: Decimal | None = Decimal("0.90"),
    type_ligne: str = "article",
    code_brut: str | None = "ART1",
    qte_livree: Decimal | None = Decimal("1"),
    qte_totale: Decimal | None = Decimal("1"),
    unite_brut: str | None = "U",
    pu_ht: Decimal | None = Decimal("10.00"),
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne=type_ligne,
        code_brut=code_brut,
        article_brut="Article inventé",
        qte_livree=qte_livree,
        qte_totale=qte_totale,
        unite_brut=unite_brut,
        pu_ht=pu_ht,
        montant_ht=montant_ht,
        confiance=confiance,
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


def _extraction_minimale(
    *, numero_brut: str = "L999-OCR", numero_confiance: str | None = "0.42"
) -> dict[str, Any]:
    champ_vide: dict[str, str | None] = {
        "brut": None,
        "valeur": None,
        "confiance": None,
    }
    return {
        "version": 1,
        "champs": {
            "fournisseur": {
                "brut": "FOURNISSEUR OCR INVENTE",
                "valeur": "fournisseur ocr invente",
                "confiance": "0.91",
            },
            "numero": {
                "brut": numero_brut,
                "valeur": numero_brut,
                "confiance": numero_confiance,
            },
            "date_doc": {
                "brut": "01/01/2026",
                "valeur": "2026-01-01",
                "confiance": "0.80",
            },
            "chantier_brut": {
                "brut": "CHANTIER OCR INVENTE",
                "valeur": "chantier ocr invente",
                "confiance": "0.77",
            },
            "numero_commande": dict(champ_vide),
            "enleve_par": dict(champ_vide),
            "total_ht": {"brut": "100,00", "valeur": "100.00", "confiance": "0.88"},
            "total_tva": dict(champ_vide),
            "total_ttc": dict(champ_vide),
        },
        "lignes": [],
        "numero_detecte": None,
        "motifs": [],
    }


async def _dernier_journal(
    db_session: AsyncSession, document_id: uuid.UUID, action: str
) -> Journal:
    """La plus récente entrée `action` de ce document — échoue
    (`NoResultFound`) si elle est absente, jamais un `None` implicite à
    vérifier dans chaque test appelant."""
    return (
        (
            await db_session.execute(
                select(Journal)
                .where(Journal.cible_id == str(document_id), Journal.action == action)
                .order_by(Journal.horodatage.desc())
                .limit(1)
            )
        )
        .scalars()
        .one()
    )


async def _tous_journaux(
    db_session: AsyncSession, document_id: uuid.UUID, action: str
) -> list[Journal]:
    return list(
        (
            await db_session.execute(
                select(Journal).where(
                    Journal.cible_id == str(document_id), Journal.action == action
                )
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------
# detail_document
# --------------------------------------------------------------------------


async def test_detail_document_agent_voit_son_document(
    db_session: AsyncSession,
) -> None:
    agent = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document(db_session, deposant=agent)

    detail = await detail_document(
        db_session, document.id, utilisateur_id=agent.id, role="agent"
    )

    assert detail.id == document.id
    assert detail.modifiable is False


async def test_detail_document_agent_autre_document_leve_document_introuvable(
    db_session: AsyncSession,
) -> None:
    agent_1 = await _creer_utilisateur(db_session, role="agent")
    agent_2 = await _creer_utilisateur(db_session, role="agent")
    document = await _creer_document(db_session, deposant=agent_1)

    with pytest.raises(DocumentIntrouvable):
        await detail_document(
            db_session, document.id, utilisateur_id=agent_2.id, role="agent"
        )


async def test_detail_document_champs_valeur_ocr_et_confiance(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(
        db_session,
        numero="L999-CORRIGE",
        extraction=_extraction_minimale(
            numero_brut="L999-OCR", numero_confiance="0.42"
        ),
    )

    detail = await detail_document(
        db_session, document.id, utilisateur_id=_ADMIN_ID, role="admin"
    )

    champ_numero = detail.champs["numero"]
    assert champ_numero.valeur == "L999-CORRIGE"
    assert champ_numero.valeur_ocr == "L999-OCR"
    assert champ_numero.confiance == Decimal("0.42")
    assert champ_numero.corrige is False


async def test_detail_document_confiance_absente_du_snapshot_est_none(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(
        db_session, extraction=_extraction_minimale(numero_confiance=None)
    )

    detail = await detail_document(
        db_session, document.id, utilisateur_id=_ADMIN_ID, role="admin"
    )

    assert detail.champs["numero"].confiance is None


async def test_detail_document_facture_renvoie_document_introuvable(
    db_session: AsyncSession,
) -> None:
    facture = await _creer_document(db_session, type_="facture")

    with pytest.raises(DocumentIntrouvable):
        await detail_document(
            db_session, facture.id, utilisateur_id=_ADMIN_ID, role="admin"
        )


async def test_detail_document_admin_modifiable_sauf_archive(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session, statut="a_verifier")
    archive = await _creer_document(db_session, statut="archive")

    detail = await detail_document(
        db_session, document.id, utilisateur_id=_ADMIN_ID, role="admin"
    )
    detail_archive = await detail_document(
        db_session, archive.id, utilisateur_id=_ADMIN_ID, role="admin"
    )

    assert detail.modifiable is True
    assert detail_archive.modifiable is False


# --------------------------------------------------------------------------
# corriger_entete
# --------------------------------------------------------------------------


async def test_corriger_entete_champ_journalise_et_marque_corrige(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    document = await _creer_document(db_session, numero_commande="CDE-AVANT")

    detail = await corriger_entete(
        db_session,
        document.id,
        CorrectionEntete(valeurs={"numero_commande": "CDE-APRES"}),
        auteur_id=admin.id,
    )

    champ = detail.champs["numero_commande"]
    assert champ.valeur == "CDE-APRES"
    assert champ.corrige is True
    assert champ.corrige_par == "Nom Testeur"  # pas d'utilisateur admin réel créé ici

    journal = await _dernier_journal(db_session, document.id, "document_corrige")
    assert journal.utilisateur_id == admin.id
    assert journal.avant == {"numero_commande": "CDE-AVANT"}
    assert journal.apres == {"numero_commande": "CDE-APRES"}


async def test_corriger_entete_valeur_ocr_conservee(
    db_session: AsyncSession, admin: Utilisateur
) -> None:
    document = await _creer_document(
        db_session,
        numero="L999-CORRIGE",
        extraction=_extraction_minimale(numero_brut="L999-OCR"),
    )

    detail = await corriger_entete(
        db_session,
        document.id,
        CorrectionEntete(valeurs={"numero": "L999-ENCORE-CORRIGE"}),
        auteur_id=admin.id,
    )

    champ = detail.champs["numero"]
    assert champ.valeur == "L999-ENCORE-CORRIGE"
    assert champ.valeur_ocr == "L999-OCR"


async def test_corriger_entete_sans_changement_ne_journalise_pas(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session, numero_commande="CDE-INCHANGE")

    await corriger_entete(
        db_session,
        document.id,
        CorrectionEntete(valeurs={"numero_commande": "CDE-INCHANGE"}),
        auteur_id=_ADMIN_ID,
    )

    journaux = await _tous_journaux(db_session, document.id, "document_corrige")
    assert journaux == []


async def test_corriger_entete_chaine_blanche_devient_none(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    document = await _creer_document(db_session, numero_commande="CDE-AVANT")

    detail = await corriger_entete(
        db_session,
        document.id,
        CorrectionEntete(valeurs={"numero_commande": "   "}),
        auteur_id=admin.id,
    )

    assert detail.champs["numero_commande"].valeur is None


async def test_corriger_entete_fournisseur_resout_chantier_et_articles(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Cible")
    document = await _creer_document(
        db_session, chantier_brut="CHANTIER RATTACHE (12345)"
    )
    await _creer_ligne(
        db_session, document=document, ordre=0, code_brut="ART-RATTACHE", confiance=None
    )

    detail = await corriger_entete(
        db_session,
        document.id,
        CorrectionEntete(valeurs={"fournisseur_id": fournisseur.id}),
        auteur_id=admin.id,
    )

    assert detail.fournisseur_id == fournisseur.id
    # L3-D7 : un alias inconnu obtient une ligne « demande de validation »
    # (`chantier_id NULL` tant qu'un admin ne l'a pas rattaché à un chantier
    # existant) — jamais un motif de mise « à vérifier ».
    assert detail.chantier_id is None
    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.fournisseur_id == fournisseur.id)
        )
    ).scalar_one()
    assert alias.libelle_brut == "rattache"
    assert alias.chantier_id is None

    article = (
        await db_session.execute(
            select(Article).where(
                Article.fournisseur_id == fournisseur.id, Article.code == "ART-RATTACHE"
            )
        )
    ).scalar_one()
    assert detail.lignes[0].article_id == article.id


async def test_corriger_entete_numero_deja_utilise(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    original = await _creer_document(
        db_session, statut="recu", numero="L100", fournisseur=fournisseur
    )
    cible = await _creer_document(db_session, fournisseur=fournisseur, numero=None)

    with pytest.raises(NumeroDejaUtilise) as exc_info:
        await corriger_entete(
            db_session,
            cible.id,
            CorrectionEntete(valeurs={"numero": "L100"}),
            auteur_id=_ADMIN_ID,
        )

    assert exc_info.value.original_id == original.id


async def test_corriger_entete_fournisseur_introuvable(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)

    with pytest.raises(FournisseurIntrouvable):
        await corriger_entete(
            db_session,
            document.id,
            CorrectionEntete(valeurs={"fournisseur_id": uuid.uuid4()}),
            auteur_id=_ADMIN_ID,
        )


async def test_corriger_entete_document_archive_leve_document_non_modifiable(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session, statut="archive")

    with pytest.raises(DocumentNonModifiable):
        await corriger_entete(
            db_session,
            document.id,
            CorrectionEntete(valeurs={"numero_commande": "CDE"}),
            auteur_id=_ADMIN_ID,
        )


async def test_corriger_entete_facture_leve_document_introuvable(
    db_session: AsyncSession,
) -> None:
    facture = await _creer_document(db_session, type_="facture")

    with pytest.raises(DocumentIntrouvable):
        await corriger_entete(
            db_session,
            facture.id,
            CorrectionEntete(valeurs={"numero_commande": "CDE"}),
            auteur_id=_ADMIN_ID,
        )


async def test_corriger_entete_recu_devient_a_verifier_si_motif(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Motif")
    document = await _creer_document(
        db_session,
        statut="recu",
        fournisseur=fournisseur,
        numero="L200",
        date_doc=date(2026, 1, 1),
        chantier_brut="CHANTIER OK",
        total_ht=Decimal("10.00"),
    )
    await _creer_ligne(
        db_session, document=document, ordre=0, montant_ht=Decimal("10.00")
    )

    detail = await corriger_entete(
        db_session,
        document.id,
        CorrectionEntete(valeurs={"total_ht": Decimal("999.00")}),
        auteur_id=admin.id,
    )

    assert detail.statut == "a_verifier"
    codes = {m.code for m in detail.motifs}
    assert CodeMotif.SOMME_INCOHERENTE.value in codes


# --------------------------------------------------------------------------
# corriger_lignes
# --------------------------------------------------------------------------


async def test_corriger_lignes_modification_remet_confiance_a_none(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(
        db_session,
        document=document,
        ordre=0,
        montant_ht=Decimal("10.00"),
        confiance=Decimal("0.9"),
    )

    detail = await corriger_lignes(
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
                montant_ht=Decimal("20.00"),
            )
        ],
        auteur_id=admin.id,
    )

    assert len(detail.lignes) == 1
    assert detail.lignes[0].montant_ht == Decimal("20.00")
    assert detail.lignes[0].confiance is None


async def test_corriger_lignes_ajout_nouvelle_ligne(
    db_session: AsyncSession, admin: Utilisateur
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document=document, ordre=0)

    detail = await corriger_lignes(
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
                montant_ht=ligne.montant_ht,
            ),
            LigneSaisie(
                id=None,
                code_brut="ART-NOUVEAU",
                article_brut="Nouvel article",
                qte_livree=Decimal("2"),
                qte_totale=Decimal("2"),
                unite_brut="U",
                pu_ht=Decimal("5.00"),
                montant_ht=Decimal("10.00"),
            ),
        ],
        auteur_id=admin.id,
    )

    assert len(detail.lignes) == 2
    nouvelle = detail.lignes[1]
    assert nouvelle.code_brut == "ART-NOUVEAU"
    assert nouvelle.type_ligne == "article"
    assert nouvelle.confiance is None
    assert nouvelle.ordre == 1


async def test_corriger_lignes_suppression_ligne_absente(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    document = await _creer_document(db_session)
    await _creer_ligne(db_session, document=document, ordre=0, code_brut="A")
    ligne_2 = await _creer_ligne(db_session, document=document, ordre=1, code_brut="B")

    detail = await corriger_lignes(
        db_session,
        document.id,
        [
            LigneSaisie(
                id=ligne_2.id,
                code_brut=ligne_2.code_brut,
                article_brut=ligne_2.article_brut,
                qte_livree=ligne_2.qte_livree,
                qte_totale=ligne_2.qte_totale,
                unite_brut=ligne_2.unite_brut,
                pu_ht=ligne_2.pu_ht,
                montant_ht=ligne_2.montant_ht,
            )
        ],
        auteur_id=admin.id,
    )

    assert len(detail.lignes) == 1
    assert detail.lignes[0].code_brut == "B"


async def test_corriger_lignes_id_etranger_leve_ligne_inconnue(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)

    with pytest.raises(LigneInconnue):
        await corriger_lignes(
            db_session,
            document.id,
            [
                LigneSaisie(
                    id=uuid.uuid4(),
                    code_brut="X",
                    article_brut=None,
                    qte_livree=None,
                    qte_totale=None,
                    unite_brut=None,
                    pu_ht=None,
                    montant_ht=None,
                )
            ],
            auteur_id=_ADMIN_ID,
        )


async def test_corriger_lignes_sans_changement_ne_journalise_pas(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document=document, ordre=0)

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
                montant_ht=ligne.montant_ht,
            )
        ],
        auteur_id=_ADMIN_ID,
    )

    journaux = await _tous_journaux(db_session, document.id, "lignes_corrigees")
    assert journaux == []


async def test_corriger_lignes_journal_avant_apres(
    db_session: AsyncSession, admin: Utilisateur
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(
        db_session, document=document, ordre=0, montant_ht=Decimal("10.00")
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
                montant_ht=Decimal("30.00"),
            )
        ],
        auteur_id=admin.id,
    )

    journal = await _dernier_journal(db_session, document.id, "lignes_corrigees")
    assert journal.avant is not None
    assert journal.apres is not None
    assert journal.avant["lignes"][0]["montant_ht"] == "10.00"
    assert journal.apres["lignes"][0]["montant_ht"] == "30.00"


async def test_corriger_lignes_document_archive_leve_document_non_modifiable(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session, statut="archive")

    with pytest.raises(DocumentNonModifiable):
        await corriger_lignes(db_session, document.id, [], auteur_id=_ADMIN_ID)


# --------------------------------------------------------------------------
# valider_document
# --------------------------------------------------------------------------


async def test_valider_document_motifs_subsistants_refuse(
    db_session: AsyncSession,
    admin: Utilisateur,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Validation")
    document = await _creer_document(
        db_session,
        statut="a_verifier",
        fournisseur=fournisseur,
        numero="L500",
        date_doc=date(2026, 1, 1),
        chantier_brut=None,
        total_ht=Decimal("10.00"),
    )
    await _creer_ligne(
        db_session, document=document, ordre=0, montant_ht=Decimal("10.00")
    )

    with pytest.raises(ValidationRefusee) as exc_info:
        await valider_document(db_session, document.id, auteur_id=admin.id)

    codes = {m.code for m in exc_info.value.motifs}
    assert CodeMotif.CHAMP_ABSENT.value in codes

    await db_session.refresh(document)
    assert document.statut == "a_verifier"


async def test_valider_document_ok_passe_recu(
    db_session: AsyncSession, admin: Utilisateur
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Validation Ok")
    document = await _creer_document(
        db_session,
        statut="a_verifier",
        fournisseur=fournisseur,
        numero="L501",
        date_doc=date(2026, 1, 1),
        chantier_brut="CHANTIER OK",
        total_ht=Decimal("10.00"),
    )
    await _creer_ligne(
        db_session, document=document, ordre=0, montant_ht=Decimal("10.00")
    )

    detail = await valider_document(db_session, document.id, auteur_id=admin.id)

    assert detail.statut == "recu"
    assert detail.motifs == []

    journal = await _dernier_journal(db_session, document.id, "document_valide")
    assert journal.utilisateur_id == admin.id
    assert journal.apres == {"statut": "recu"}


async def test_valider_document_rafraichit_document_apres_rapprochement_en_echec(
    db_session: AsyncSession,
    admin: Utilisateur,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling R23 (revue finale du lot 4) : si `rapprocher_factures_du_bl`
    échoue en interne (`rapprocher_facture_sans_echec` avale l'exception
    après un `rollback()`), `document` est expiré par ce `rollback()`.
    Reproduit exactement la trouvaille de la revue : sans le second
    `session.refresh(document)` (même correctif que `relancer_extraction`),
    l'accès synchrone suivant à un attribut de `document` dans
    `_charger_detail` lève `sqlalchemy.exc.MissingGreenlet` au lieu de
    renvoyer le détail attendu, alors que la validation est déjà commitée."""
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur R23")
    bl = await _creer_document(
        db_session,
        type_="bl",
        statut="a_verifier",
        fournisseur=fournisseur,
        numero="BL-R23",
        date_doc=date(2026, 1, 1),
        chantier_brut="CHANTIER R23",
        total_ht=Decimal("10.00"),
    )
    await _creer_ligne(db_session, document=bl, ordre=0, montant_ht=Decimal("10.00"))

    facture = await _creer_document(
        db_session,
        type_="facture",
        statut="recu",
        fournisseur=fournisseur,
        numero="F-R23",
    )
    db_session.add(BlocFacture(facture_id=facture.id, ordre=0, numero_bl="BL-R23"))
    await db_session.commit()

    async def _rapprocher_facture_qui_echoue(
        session: AsyncSession, facture_id: uuid.UUID
    ) -> None:
        # Touche la session avant d'échouer (même repro que la revue) :
        # garantit qu'une transaction est bien active au moment du
        # `rollback()` de `rapprocher_facture_sans_echec`, donc que
        # `document` est effectivement expiré ensuite.
        await session.execute(select(Document.id).where(Document.id == facture_id))
        raise RuntimeError("échec inventé pour le test")

    monkeypatch.setattr(
        ingest_rapprochement, "rapprocher_facture", _rapprocher_facture_qui_echoue
    )

    # Avant le correctif : lève `sqlalchemy.exc.MissingGreenlet` ici (le
    # `rollback()` interne à `rapprocher_facture_sans_echec` expire
    # `document`, déjà rafraîchi juste avant l'appel à
    # `rapprocher_factures_du_bl`). Après le correctif : renvoie le détail,
    # la validation reste effective.
    detail = await valider_document(db_session, bl.id, auteur_id=admin.id)

    assert detail.statut == "recu"
    await db_session.refresh(bl)
    assert bl.statut == "recu"


async def test_valider_document_statut_non_a_verifier_refuse(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session, statut="recu")

    with pytest.raises(DocumentNonModifiable):
        await valider_document(db_session, document.id, auteur_id=_ADMIN_ID)


async def test_valider_document_archive_refuse(db_session: AsyncSession) -> None:
    document = await _creer_document(db_session, statut="archive")

    with pytest.raises(DocumentNonModifiable):
        await valider_document(db_session, document.id, auteur_id=_ADMIN_ID)


# --------------------------------------------------------------------------
# archiver_document
# --------------------------------------------------------------------------


async def test_archiver_document_journal_et_statut(
    db_session: AsyncSession, admin: Utilisateur
) -> None:
    document = await _creer_document(db_session, statut="a_verifier")

    detail = await archiver_document(
        db_session,
        document.id,
        commentaire="doublon d'un autre dépôt",
        auteur_id=admin.id,
    )

    assert detail.statut == "archive"
    journal = await _dernier_journal(db_session, document.id, "document_archive")
    assert journal.utilisateur_id == admin.id
    assert journal.apres is not None
    assert journal.apres["commentaire"] == "doublon d'un autre dépôt"


async def test_archiver_document_deja_archive_refuse(
    db_session: AsyncSession, admin: Utilisateur
) -> None:
    document = await _creer_document(db_session, statut="a_verifier")
    await archiver_document(
        db_session, document.id, commentaire="premier archivage", auteur_id=admin.id
    )

    with pytest.raises(DocumentNonModifiable):
        await archiver_document(
            db_session, document.id, commentaire="second archivage", auteur_id=admin.id
        )


# --------------------------------------------------------------------------
# relancer_extraction
# --------------------------------------------------------------------------


async def _ocr_synthetique(contenu: bytes, mime: str) -> dict[str, Any]:
    return _reponse_synthetique()


async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
    raise ErreurOCR("échec inventé pour le test")


async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
    raise AssertionError("l'OCR ne doit pas être appelé")


async def test_relancer_extraction_remplace_valeurs_reste_a_verifier(
    db_session: AsyncSession, admin: Utilisateur, tmp_path: Path
) -> None:
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    document = await _creer_document(
        db_session,
        statut="a_verifier",
        numero="ANCIEN-NUMERO",
        fichier_path=str(chemin),
    )

    detail = await relancer_extraction(
        db_session, document.id, tmp_path, _ocr_synthetique, auteur_id=admin.id
    )

    assert detail.statut == "a_verifier"
    assert detail.champs["numero"].valeur == NUMERO_BL_SYNTHETIQUE

    journal = await _dernier_journal(db_session, document.id, "extraction_relancee")
    assert journal.utilisateur_id == admin.id
    assert journal.avant is not None
    assert journal.avant["numero"] == "ANCIEN-NUMERO"
    assert journal.avant["nb_lignes"] == "0"
    assert journal.apres is None


async def test_relancer_extraction_journal_survit_a_la_reprise_sur_doublon(
    db_session: AsyncSession,
    admin: Utilisateur,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix round 1 (revue de cette tâche) : si l'extraction relancée
    déclenche la reprise sur `IntegrityError` d'`enregistrer_extraction_bl`
    (course sur un doublon de numéro, `_avec_reprise_doublon`), le
    `rollback()` interne à cette reprise ne doit jamais emporter avec lui le
    journal `extraction_relancee` — il doit rester exactement une seule
    entrée, portant les valeurs d'avant la relance. Même mécanisme de
    simulation qu'`app/modules/ingest/tests/test_extraction_bl.py
    ::test_enregistrer_extraction_bl_doublon_concurrent_rejoue_apres_erreur`
    (`_numero_interne_doublon` ment une fois)."""
    fournisseur = await _creer_fournisseur(
        db_session, nom="Peintures Exemple", aliases=["Peintures Exemple SAS"]
    )
    concurrent = await _creer_document(db_session, statut="a_verifier")
    resultat_concurrent = await ingest_extraction_bl.enregistrer_extraction_bl(
        db_session, concurrent.id, _reponse_synthetique()
    )
    assert resultat_concurrent.statut == "recu"
    assert resultat_concurrent.numero == NUMERO_BL_SYNTHETIQUE

    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    document = await _creer_document(
        db_session,
        statut="a_verifier",
        fournisseur=fournisseur,
        numero="ANCIEN-NUMERO-RELANCE",
        fichier_path=str(chemin),
    )

    doublon_reel = ingest_extraction_bl._numero_interne_doublon
    appels = 0

    async def _doublon_ment_une_fois(
        session: AsyncSession,
        document_id: uuid.UUID,
        fournisseur_id: uuid.UUID | None,
        numero: str,
    ) -> int | None:
        nonlocal appels
        appels += 1
        if appels == 1:
            return None
        return await doublon_reel(session, document_id, fournisseur_id, numero)

    monkeypatch.setattr(
        ingest_extraction_bl, "_numero_interne_doublon", _doublon_ment_une_fois
    )

    detail = await relancer_extraction(
        db_session, document.id, tmp_path, _ocr_synthetique, auteur_id=admin.id
    )

    assert appels == 2
    assert detail.statut == "a_verifier"
    # Doublon détecté à la reprise : le numéro de l'extraction relancée
    # (celui du document concurrent) n'est pas écrit.
    assert detail.champs["numero"].valeur is None

    journaux = await _tous_journaux(db_session, document.id, "extraction_relancee")
    assert len(journaux) == 1
    journal = journaux[0]
    # `journal` et `admin` sont tous deux expirés par les multiples
    # `commit()`/`rollback()` internes à la reprise sur doublon
    # d'`enregistrer_extraction_bl` (`expire_on_commit`, comportement par
    # défaut de la session) : rafraîchis explicitement avant lecture, comme
    # `relancer_extraction` le fait déjà pour `document` — sans quoi un accès
    # synchrone à un attribut expiré hors d'un `await` lève `MissingGreenlet`.
    await db_session.refresh(journal)
    await db_session.refresh(admin)
    assert journal.utilisateur_id == admin.id
    assert journal.avant is not None
    assert journal.avant["numero"] == "ANCIEN-NUMERO-RELANCE"
    assert journal.avant["nb_lignes"] == "0"
    assert journal.apres is None


async def test_relancer_extraction_ocr_en_echec_leve_lecture_impossible(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    document = await _creer_document(
        db_session, statut="a_verifier", fichier_path=str(chemin)
    )

    with pytest.raises(LectureImpossible):
        await relancer_extraction(
            db_session, document.id, tmp_path, _ocr_en_echec, auteur_id=_ADMIN_ID
        )

    await db_session.refresh(document)
    assert document.statut == "a_verifier"


async def test_relancer_extraction_statut_non_a_verifier_refuse(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    document = await _creer_document(db_session, statut="recu")

    with pytest.raises(DocumentNonModifiable):
        await relancer_extraction(
            db_session, document.id, tmp_path, _ocr_jamais_appele, auteur_id=_ADMIN_ID
        )


async def test_relancer_extraction_fichier_absent_leve_document_introuvable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    document = await _creer_document(
        db_session,
        statut="a_verifier",
        fichier_path=str(tmp_path / "absent.jpg"),
    )

    with pytest.raises(DocumentIntrouvable):
        await relancer_extraction(
            db_session, document.id, tmp_path, _ocr_jamais_appele, auteur_id=_ADMIN_ID
        )
