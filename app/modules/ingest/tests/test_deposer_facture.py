"""Tests de `deposer_facture` (`app/modules/ingest/factures.py`, L2-T4).

Base de test réelle, `docs_dir` temporaire (`tmp_path`), faux OCR (jamais
d'appel réseau réel, R17). Deux familles :

- des tests synthétiques (`analyser_facture_unikalo` monkeypatchée, comme le
  fait déjà `test_bl_non_recus.py` pour `lire_facture`) pour chaque branche
  d'erreur et le format de stockage (fournisseur, blocs, lignes, journal,
  commentaires joints) ;
- un test sur la vraie fixture `tests/fixtures/unikalo/
  facture_2026-08.mistral-ocr.json` (`pytest.skip` si absente), qui compare
  les comptes de blocs/lignes en base à ceux d'`analyser_facture_unikalo`
  sur la même réponse — jamais une valeur du document (R17 : aucune donnée
  réelle affichée ni recopiée).

Les tests HTTP du routeur (`POST /api/factures` : autorisation, taille,
codes HTTP) vivent dans `app/modules/api/tests/test_factures.py` : `api` ne
peut pas importer `extract` (L2-D3, `tests/test_frontieres.py`), donc la
comparaison avec `analyser_facture_unikalo` ne peut vivre qu'ici, dans
`ingest`, le seul module autorisé à importer un module métier pur.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.facture import (
    BlocBL,
    Facture,
    FactureIllisible,
    LigneFacture,
    TypeLigne,
)
from app.modules.extract.unikalo import analyser_facture_unikalo
from app.modules.ingest import factures as ingest_factures
from app.modules.ingest.commun import Deposant
from app.modules.ingest.factures import (
    EcritureImpossible,
    FactureEnDouble,
    FichierInvalide,
    FormatNonPrisEnCharge,
    LectureImpossible,
    deposer_facture,
)
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import (
    Article,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_OcrFn = Callable[[bytes, str], Awaitable[dict[str, Any]]]

_SIGNATURE_PDF_INVENTEE = b"%PDF-1.4\n%invente-pour-les-tests\n"

_DOSSIER_FIXTURES = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "unikalo"
)
_FICHIER_FIXTURE_OCR = _DOSSIER_FIXTURES / "facture_2026-08.mistral-ocr.json"


# --------------------------------------------------------------------------
# Constructeurs de données inventées
# --------------------------------------------------------------------------


async def _creer_utilisateur(
    db_session: AsyncSession, *, nom: str | None = "Admin Testeur"
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid",
        role="admin",
        nom=nom,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


def _deposant_depuis(utilisateur: Utilisateur) -> Deposant:
    return Deposant(
        id=utilisateur.id, nom_affichage=utilisateur.nom or utilisateur.email
    )


def _ligne_invente(
    ordre: int = 0,
    *,
    type_ligne: TypeLigne = TypeLigne.ARTICLE,
    designation: str = "Article inventé",
    code_article: str | None = "ART1",
    montant_ht: Decimal | None = Decimal("20.00"),
    qte_livree: Decimal | None = Decimal("2"),
    qte_totale: Decimal | None = Decimal("2"),
) -> LigneFacture:
    return LigneFacture(
        ordre=ordre,
        type_ligne=type_ligne,
        code_article=code_article,
        designation=designation,
        qte_livree=qte_livree,
        qte_totale=qte_totale,
        unite="U",
        pu_ht=Decimal("10.00"),
        pu_cdt=Decimal("10.00"),
        remise_pct=None,
        montant_ht=montant_ht,
        tva=Decimal("20"),
    )


def _bloc_invente(
    numero_bl: str = "L1", *, lignes: tuple[LigneFacture, ...] = ()
) -> BlocBL:
    return BlocBL(
        numero_bl=numero_bl,
        date_bl=date(2026, 8, 1),
        numero_commande=None,
        chantier_brut="CHANTIER INVENTE",
        lignes=lignes,
    )


def _facture_invente(
    *,
    numero: str = "FAC-INVENTE-0001",
    blocs: tuple[BlocBL, ...],
    total_ht: Decimal | None = None,
) -> Facture:
    """`total_ht` par défaut (`None`) : somme des `montant_ht` des `blocs`
    (L3-T7, `verifier_facture`) — une facture inventée est cohérente par
    défaut (statut `recu`, aucun motif) ; un total explicite sert aux tests
    qui veulent justement un écart (`somme_incoherente`)."""
    if total_ht is None:
        total_ht = sum((bloc.montant_ht for bloc in blocs), Decimal("0"))
    return Facture(
        fournisseur_brut="UNIKALO INVENTE",
        numero=numero,
        date_facture=date(2026, 8, 1),
        client=None,
        echeance=None,
        total_ht=total_ht,
        blocs=blocs,
    )


async def _ocr_quelconque(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR dont la réponse importe peu : soit `analyser_facture_unikalo`
    est monkeypatchée (réponse ignorée), soit le test attend justement
    qu'elle échoue sur cette réponse."""
    return {
        "pages": [{"markdown": "peu importe, monkeypatché ou volontairement illisible"}]
    }


# --------------------------------------------------------------------------
# Fichier non PDF -> FichierInvalide, avant tout appel OCR
# --------------------------------------------------------------------------


async def test_fichier_non_pdf_leve_fichier_invalide_sans_appeler_ocr(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    utilisateur = await _creer_utilisateur(db_session)
    appels: list[bytes] = []

    async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
        appels.append(contenu)
        return {}

    with pytest.raises(FichierInvalide):
        await deposer_facture(
            db_session,
            b"pas-un-pdf-du-tout",
            _deposant_depuis(utilisateur),
            tmp_path,
            _ocr_jamais_appele,
        )

    assert appels == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Échec de l'OCR -> LectureImpossible, rien stocké
# --------------------------------------------------------------------------


async def test_ocr_en_echec_leve_lecture_impossible_rien_stocke(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    utilisateur = await _creer_utilisateur(db_session)

    async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
        raise ErreurOCR("échec factice de l'OCR")

    with pytest.raises(LectureImpossible):
        await deposer_facture(
            db_session,
            _SIGNATURE_PDF_INVENTEE,
            _deposant_depuis(utilisateur),
            tmp_path,
            _ocr_en_echec,
        )

    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Réponse OCR non reconnue (format non Unikalo) -> FormatNonPrisEnCharge
# --------------------------------------------------------------------------


async def test_reponse_ocr_non_reconnue_leve_format_non_pris_en_charge_rien_stocke(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    utilisateur = await _creer_utilisateur(db_session)

    def _analyse_leve(reponse: dict[str, Any]) -> Facture:
        raise FactureIllisible("motif inventé")

    monkeypatch.setattr(ingest_factures, "analyser_facture_unikalo", _analyse_leve)

    with pytest.raises(FormatNonPrisEnCharge):
        await deposer_facture(
            db_session,
            _SIGNATURE_PDF_INVENTEE,
            _deposant_depuis(utilisateur),
            tmp_path,
            _ocr_quelconque,
        )

    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Échec de l'écriture disque (Ruling L2-R5, constat mineur) -> EcritureImpossible
# --------------------------------------------------------------------------


async def test_echec_ecriture_disque_leve_ecriture_impossible_rien_stocke(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    def _ecriture_qui_echoue(
        docs_dir: Path, chemin_temporaire: Path, chemin_final: Path, contenu: bytes
    ) -> None:
        raise OSError("disque plein (simulé pour le test)")

    monkeypatch.setattr(ingest_factures, "_ecrire_atomique", _ecriture_qui_echoue)

    with pytest.raises(EcritureImpossible) as exc_info:
        await deposer_facture(
            db_session,
            _SIGNATURE_PDF_INVENTEE,
            _deposant_depuis(utilisateur),
            tmp_path,
            _ocr_quelconque,
        )

    assert str(exc_info.value) == "Enregistrement impossible, réessayez."
    assert (await db_session.execute(select(Document))).scalars().all() == []
    # Aucun fichier résiduel (ni `.pdf` ni `.tmp`) : `_ecrire_atomique` étant
    # monkeypatchée, elle ne crée jamais réellement le `.tmp` ici, mais ce
    # test garantit surtout qu'aucun nettoyage ne plante et que rien n'est
    # laissé dans `docs_dir`.
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Dépôt réussi : fournisseur, document, blocs, lignes, commentaires, journal
# --------------------------------------------------------------------------


async def test_depot_reussi_cree_fournisseur_document_blocs_lignes_et_journal(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    utilisateur = await _creer_utilisateur(db_session)
    ligne = _ligne_invente()
    bloc = _bloc_invente(lignes=(ligne,))
    facture = _facture_invente(blocs=(bloc,))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    reponse_ocr_invente = {"pages": [{"markdown": "peu importe, monkeypatché"}]}

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return reponse_ocr_invente

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr,
    )

    assert resultat.numero == facture.numero
    assert resultat.nb_blocs == 1

    document = await db_session.get(Document, resultat.id)
    assert document is not None
    assert (document.type, document.source, document.statut) == (
        "facture",
        "upload",
        "recu",
    )
    assert document.numero == facture.numero
    assert document.date_doc == facture.date_facture
    assert document.total_ht == facture.total_ht
    assert document.deposant_id == utilisateur.id
    assert document.ocr_brut == reponse_ocr_invente
    # L3-T7 : facture cohérente (total = somme des blocs, `_facture_invente`)
    # -> aucun motif ; `reponse_ocr_invente` n'a pas de `confidence_scores`
    # -> `confiance_min` reste `None` (aucun score disponible).
    assert document.motifs == []
    assert document.confiance_min is None

    assert document.fournisseur_id is not None
    fournisseur = await db_session.get(Fournisseur, document.fournisseur_id)
    assert fournisseur is not None
    assert fournisseur.nom == "Unikalo"

    blocs_db = (
        (
            await db_session.execute(
                select(BlocFacture).where(BlocFacture.facture_id == document.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(blocs_db) == 1
    assert blocs_db[0].numero_bl == bloc.numero_bl
    assert blocs_db[0].chantier_brut == bloc.chantier_brut
    # L3-T7 : demande d'alias créée (aucun chantier du référentiel ne
    # correspond) -> `chantier_id` reste `NULL` (L3-D7).
    assert blocs_db[0].chantier_id is None
    assert blocs_db[0].commentaire is None

    lignes_db = (
        (
            await db_session.execute(
                select(Ligne).where(Ligne.document_id == document.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(lignes_db) == 1
    assert lignes_db[0].article_brut == ligne.designation
    assert lignes_db[0].code_brut == ligne.code_article
    # L3-T7 : article créé automatiquement (L3-D9), non validé.
    assert lignes_db[0].article_id is not None
    assert lignes_db[0].unite_brut == ligne.unite
    assert lignes_db[0].montant_ht == ligne.montant_ht
    assert lignes_db[0].type_ligne == ligne.type_ligne.value
    assert lignes_db[0].bloc_id == blocs_db[0].id

    journaux = (
        (
            await db_session.execute(
                select(Journal).where(Journal.cible_id == str(document.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(journaux) == 1
    assert journaux[0].action == "facture_deposee"
    assert journaux[0].utilisateur_id == utilisateur.id
    assert journaux[0].cible_table == "document"
    assert journaux[0].apres is not None
    assert journaux[0].apres["statut"] == "recu"
    assert journaux[0].apres["motifs"] == []
    assert journaux[0].apres["nb_demandes_alias"] == 1
    assert journaux[0].apres["nb_articles"] == 1

    fichiers = list(tmp_path.glob("*.pdf"))
    assert len(fichiers) == 1
    assert fichiers[0].read_bytes() == _SIGNATURE_PDF_INVENTEE
    assert document.fichier_path == str(fichiers[0])


async def test_commentaires_du_bloc_joints_par_saut_de_ligne(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ligne_article = _ligne_invente()
    ligne_commentaire_1 = _ligne_invente(
        1,
        type_ligne=TypeLigne.COMMENTAIRE,
        designation="Premier commentaire",
        code_article=None,
        montant_ht=None,
    )
    ligne_commentaire_2 = _ligne_invente(
        2,
        type_ligne=TypeLigne.COMMENTAIRE,
        designation="Second commentaire",
        code_article=None,
        montant_ht=None,
    )
    bloc = _bloc_invente(
        lignes=(ligne_article, ligne_commentaire_1, ligne_commentaire_2)
    )
    facture = _facture_invente(blocs=(bloc,))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    bloc_db = (
        await db_session.execute(
            select(BlocFacture).where(BlocFacture.facture_id == resultat.id)
        )
    ).scalar_one()
    assert bloc_db.commentaire == "Premier commentaire\nSecond commentaire"


async def test_bloc_sans_commentaire_a_commentaire_null(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    bloc_db = (
        await db_session.execute(
            select(BlocFacture).where(BlocFacture.facture_id == resultat.id)
        )
    ).scalar_one()
    assert bloc_db.commentaire is None


# --------------------------------------------------------------------------
# Doublon (même fournisseur, même numéro) -> FactureEnDouble(original_id)
# --------------------------------------------------------------------------


async def test_second_depot_meme_fournisseur_meme_numero_leve_facture_en_double(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    premier = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    with pytest.raises(FactureEnDouble) as exc_info:
        await deposer_facture(
            db_session,
            _SIGNATURE_PDF_INVENTEE,
            _deposant_depuis(utilisateur),
            tmp_path,
            _ocr_quelconque,
        )

    assert exc_info.value.original_id == premier.id
    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    assert len(list(tmp_path.glob("*.pdf"))) == 1


async def test_course_entre_deux_depots_leve_facture_en_double_via_contrainte_unique(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simule la fenêtre de course décrite par le contrôleur : le contrôle
    applicatif de doublon (`_facture_en_double`) est monkeypatché pour ne
    rien voir, comme si un second dépôt concurrent s'exécutait juste avant
    lui — la contrainte unique `(fournisseur_id, numero)` de `document`
    protège quand même, et `deposer_facture` traduit l'`IntegrityError` en
    `FactureEnDouble` (409), en supprimant le fichier déjà écrit."""
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    fournisseur = Fournisseur(nom="Unikalo")
    db_session.add(fournisseur)
    await db_session.flush()
    document_existant = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path="/var/docs/deja-la.pdf",
        fournisseur_id=fournisseur.id,
        numero=facture.numero,
        date_doc=facture.date_facture,
        total_ht=facture.total_ht,
        deposant_id=utilisateur.id,
    )
    db_session.add(document_existant)
    await db_session.commit()
    await db_session.refresh(document_existant)
    # `deposer_facture` va faire un `rollback()` sur cette même session (le
    # test partage `db_session` avec le code testé) : un `rollback()`
    # expire tous les objets de la session, quel que soit `expire_on_commit`
    # — l'identifiant est donc capturé ici, avant tout accès après l'appel,
    # pour ne jamais déclencher un rechargement implicite hors contexte
    # async (`MissingGreenlet`).
    document_existant_id = document_existant.id

    # Le contrôle de doublon (`_facture_en_double`) est appelé deux fois par
    # `deposer_facture` : une fois avant l'insertion (celle qu'on simule
    # aveugle, comme si un dépôt concurrent venait tout juste de committer),
    # une fois après le `rollback()` pour retrouver l'original (celle-là
    # doit fonctionner normalement, sinon `deposer_facture` ne pourrait
    # jamais traduire l'`IntegrityError` en `FactureEnDouble`).
    fonction_reelle = ingest_factures._facture_en_double
    appels = 0

    async def _facture_en_double_aveugle_une_fois(
        session: AsyncSession, fournisseur_id: uuid.UUID, numero: str
    ) -> uuid.UUID | None:
        nonlocal appels
        appels += 1
        if appels == 1:
            return None
        return await fonction_reelle(session, fournisseur_id, numero)

    monkeypatch.setattr(
        ingest_factures, "_facture_en_double", _facture_en_double_aveugle_une_fois
    )

    with pytest.raises(FactureEnDouble) as exc_info:
        await deposer_facture(
            db_session,
            _SIGNATURE_PDF_INVENTEE,
            _deposant_depuis(utilisateur),
            tmp_path,
            _ocr_quelconque,
        )

    assert exc_info.value.original_id == document_existant_id
    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# L3-T7 (L3-D16) : contrôle et normalisation d'une facture déposée — total
# incohérent, confiance par page, résolution chantier/article.
# --------------------------------------------------------------------------


async def test_depot_total_incoherent_a_verifier_motif_somme_incoherente(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(
        blocs=(_bloc_invente(lignes=(_ligne_invente(),)),),
        total_ht=Decimal("999.99"),
    )
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    document = await db_session.get(Document, resultat.id)
    assert document is not None
    assert document.statut == "a_verifier"
    assert document.motifs is not None
    assert [m["code"] for m in document.motifs] == ["somme_incoherente"]
    motif = document.motifs[0]
    assert motif["champ"] == "total_ht"
    assert motif["detail"]["somme"] == "20.00"
    assert motif["detail"]["total"] == "999.99"

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.cible_id == str(resultat.id))
        )
    ).scalar_one()
    assert journal.apres is not None
    assert journal.apres["statut"] == "a_verifier"
    assert journal.apres["motifs"] == ["somme_incoherente"]


async def test_depot_confiance_min_calculee_depuis_les_pages(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)
    reponse_avec_confiance = {
        "pages": [
            {"confidence_scores": {"minimum_page_confidence_score": 0.91}},
            {"confidence_scores": {"minimum_page_confidence_score": 0.62}},
        ]
    }

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return reponse_avec_confiance

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr,
    )

    document = await db_session.get(Document, resultat.id)
    assert document is not None
    assert document.confiance_min == Decimal("0.62")


async def test_depot_bloc_avec_chantier_cree_une_demande_dalias(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    document = await db_session.get(Document, resultat.id)
    assert document is not None
    alias = (
        await db_session.execute(
            select(ChantierAlias).where(
                ChantierAlias.fournisseur_id == document.fournisseur_id
            )
        )
    ).scalar_one()
    # « CHANTIER INVENTE » -> préfixe « CHANTIER » retiré (`decomposer_
    # chantier`), reste normalisé « invente ».
    assert alias.libelle_brut == "invente"
    assert alias.chantier_id is None

    bloc_db = (
        await db_session.execute(
            select(BlocFacture).where(BlocFacture.facture_id == resultat.id)
        )
    ).scalar_one()
    assert bloc_db.chantier_id is None

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.cible_id == str(resultat.id))
        )
    ).scalar_one()
    assert journal.apres is not None
    assert journal.apres["nb_demandes_alias"] == 1


async def test_depot_bloc_avec_alias_valide_propage_le_chantier_id(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facture = _facture_invente(blocs=(_bloc_invente(lignes=(_ligne_invente(),)),))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    fournisseur = Fournisseur(nom="Unikalo")
    db_session.add(fournisseur)
    await db_session.flush()
    chantier = Chantier(nom_canonique="Chantier de test inventé")
    db_session.add(chantier)
    await db_session.flush()
    db_session.add(
        ChantierAlias(
            fournisseur_id=fournisseur.id,
            libelle_brut="invente",
            code_brut=None,
            chantier_id=chantier.id,
        )
    )
    await db_session.commit()

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    bloc_db = (
        await db_session.execute(
            select(BlocFacture).where(BlocFacture.facture_id == resultat.id)
        )
    ).scalar_one()
    assert bloc_db.chantier_id == chantier.id

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.cible_id == str(resultat.id))
        )
    ).scalar_one()
    assert journal.apres is not None
    assert journal.apres["nb_demandes_alias"] == 0


async def test_depot_ligne_article_avec_code_cree_article_avec_ratio_propose(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ligne = _ligne_invente(
        code_article="ART-RATIO", qte_livree=Decimal("4"), qte_totale=Decimal("100")
    )
    bloc = _bloc_invente(lignes=(ligne,))
    facture = _facture_invente(blocs=(bloc,))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    document = await db_session.get(Document, resultat.id)
    assert document is not None
    article = (
        await db_session.execute(
            select(Article).where(
                Article.fournisseur_id == document.fournisseur_id,
                Article.code == "ART-RATIO",
            )
        )
    ).scalar_one()
    assert article.valide is False
    assert article.ratio == Decimal("25")

    ligne_db = (
        await db_session.execute(select(Ligne).where(Ligne.document_id == resultat.id))
    ).scalar_one()
    assert ligne_db.article_id == article.id

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.cible_id == str(resultat.id))
        )
    ).scalar_one()
    assert journal.apres is not None
    assert journal.apres["nb_articles"] == 1


async def test_depot_ligne_eco_avec_code_ne_cree_pas_darticle(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L3-D9/décision du contrôleur : seule une ligne `ARTICLE` avec un code
    rattache un article — jamais une éco-participation, même si elle porte
    un code."""
    ligne_eco = _ligne_invente(
        type_ligne=TypeLigne.ECO,
        code_article="ECO1",
        designation="Eco-participation inventée",
    )
    bloc = _bloc_invente(lignes=(ligne_eco,))
    facture = _facture_invente(blocs=(bloc,))
    monkeypatch.setattr(
        ingest_factures, "analyser_facture_unikalo", lambda reponse: facture
    )
    utilisateur = await _creer_utilisateur(db_session)

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr_quelconque,
    )

    assert (await db_session.execute(select(Article))).scalars().all() == []
    ligne_db = (
        await db_session.execute(select(Ligne).where(Ligne.document_id == resultat.id))
    ).scalar_one()
    assert ligne_db.article_id is None

    journal = (
        await db_session.execute(
            select(Journal).where(Journal.cible_id == str(resultat.id))
        )
    ).scalar_one()
    assert journal.apres is not None
    assert journal.apres["nb_articles"] == 0


# --------------------------------------------------------------------------
# Test sur la vraie fixture (skip si absente) : comptes = analyser_facture_unikalo
# --------------------------------------------------------------------------


@pytest.fixture
def reponse_ocr_reelle() -> dict[str, Any]:
    if not _FICHIER_FIXTURE_OCR.is_file():
        pytest.skip(
            "aucune fixture facture_2026-08.mistral-ocr.json dans "
            "tests/fixtures/unikalo/ (clone neuf ou fixtures non déposées)"
        )
    donnees: dict[str, Any] = json.loads(
        _FICHIER_FIXTURE_OCR.read_text(encoding="utf-8")
    )
    return donnees


async def test_fixture_reelle_comptes_de_blocs_et_lignes_egaux_a_lanalyse(
    db_session: AsyncSession, tmp_path: Path, reponse_ocr_reelle: dict[str, Any]
) -> None:
    facture_attendue = analyser_facture_unikalo(reponse_ocr_reelle)
    utilisateur = await _creer_utilisateur(db_session)

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return reponse_ocr_reelle

    resultat = await deposer_facture(
        db_session,
        _SIGNATURE_PDF_INVENTEE,
        _deposant_depuis(utilisateur),
        tmp_path,
        _ocr,
    )

    assert resultat.nb_blocs == len(facture_attendue.blocs)

    nb_blocs_db = len(
        (
            await db_session.execute(
                select(BlocFacture.id).where(BlocFacture.facture_id == resultat.id)
            )
        )
        .scalars()
        .all()
    )
    assert nb_blocs_db == len(facture_attendue.blocs)

    nb_lignes_attendu = sum(len(bloc.lignes) for bloc in facture_attendue.blocs)
    nb_lignes_db = len(
        (
            await db_session.execute(
                select(Ligne.id).where(Ligne.document_id == resultat.id)
            )
        )
        .scalars()
        .all()
    )
    assert nb_lignes_db == nb_lignes_attendu

    # L3-T7 (Ruling R7, décision du contrôleur) : la facture réelle doit
    # être reçue sans motif — booléen calculé puis affirmé avec un message
    # fixe, jamais `assert document.motifs == []` (qui afficherait les
    # motifs, potentiellement porteurs de montants réels, à l'échec).
    document = await db_session.get(Document, resultat.id)
    assert document is not None
    conforme = document.statut == "recu" and not document.motifs
    assert conforme, "la facture réelle doit être reçue sans motif"
