"""Tests de `lire_facture`, `BlocReception`, `blocs_avec_reception` et
`formater_blocs` (`app/modules/ingest/service.py`, T7, livrable
« bl-non-recus »).

Toutes les valeurs (numéros, chantiers, montants) sont inventées (R17,
aucune donnée réelle dans un test commité). `lire_facture` est testée en
isolation de l'analyse Unikalo elle-même (déjà exhaustivement couverte par
`app/modules/extract/tests/test_unikalo.py`) : `analyser_facture_unikalo`
est monkeypatchée pour vérifier uniquement l'enchaînement OCR -> analyse,
jamais un vrai contenu de facture.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.facture import (
    BlocBL,
    Facture,
    FactureIllisible,
    LigneFacture,
    TypeLigne,
)
from app.modules.ingest import service as ingest_service
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import Document
from app.modules.ingest.service import (
    BlocReception,
    blocs_avec_reception,
    formater_blocs,
    lire_facture,
)

# --------------------------------------------------------------------------
# Constructeurs de données inventées
# --------------------------------------------------------------------------


def _bloc_invente(
    numero_bl: str,
    *,
    date_bl: date | None = date(2026, 8, 1),
    chantier: str | None = "CHANTIER INVENTE",
    lignes: tuple[LigneFacture, ...] = (),
) -> BlocBL:
    return BlocBL(
        numero_bl=numero_bl,
        date_bl=date_bl,
        numero_commande=None,
        chantier_brut=chantier,
        lignes=lignes,
    )


def _facture_invente(*blocs: BlocBL) -> Facture:
    return Facture(
        fournisseur_brut="FOURNISSEUR INVENTE",
        numero="INV0001",
        date_facture=date(2026, 8, 1),
        client=None,
        echeance=None,
        total_ht=Decimal("0"),
        blocs=tuple(blocs),
    )


def _document_invente(
    *, type_: str, statut: str, numero: str | None, source: str = "telegram"
) -> Document:
    return Document(
        type=type_,
        source=source,
        statut=statut,
        fichier_path="/var/docs/invente.jpg",
        numero=numero,
    )


# --------------------------------------------------------------------------
# lire_facture : enchaînement OCR -> analyse, sans DB (analyser_facture_unikalo
# monkeypatchée : ce fichier ne teste pas le parseur Unikalo lui-même).
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lire_facture_appelle_locr_puis_lanalyse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appels_ocr: list[tuple[bytes, str]] = []
    appels_analyse: list[dict[str, Any]] = []
    facture_attendue = _facture_invente(_bloc_invente("L1"))

    async def _ocr_invente(contenu: bytes, mime: str) -> dict[str, Any]:
        appels_ocr.append((contenu, mime))
        return {"pages": ["reponse-ocr-inventee"]}

    def _analyse_invente(reponse: dict[str, Any]) -> Facture:
        appels_analyse.append(reponse)
        return facture_attendue

    monkeypatch.setattr(ingest_service, "analyser_facture_unikalo", _analyse_invente)

    resultat = await lire_facture(b"contenu-pdf-invente", _ocr_invente)

    assert resultat is facture_attendue
    assert appels_ocr == [(b"contenu-pdf-invente", "application/pdf")]
    assert appels_analyse == [{"pages": ["reponse-ocr-inventee"]}]


@pytest.mark.anyio
async def test_lire_facture_propage_erreur_ocr_sans_appeler_lanalyse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _analyse_jamais_appelee(reponse: dict[str, Any]) -> Facture:
        raise AssertionError("l'analyse ne doit pas être appelée si l'OCR échoue")

    monkeypatch.setattr(
        ingest_service, "analyser_facture_unikalo", _analyse_jamais_appelee
    )

    async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
        raise ErreurOCR("échec factice de l'OCR")

    with pytest.raises(ErreurOCR):
        await lire_facture(b"contenu-pdf-invente", _ocr_en_echec)


@pytest.mark.anyio
async def test_lire_facture_propage_facture_illisible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _analyse_en_echec(reponse: dict[str, Any]) -> Facture:
        raise FactureIllisible("facture illisible factice")

    monkeypatch.setattr(ingest_service, "analyser_facture_unikalo", _analyse_en_echec)

    async def _ocr_invente(contenu: bytes, mime: str) -> dict[str, Any]:
        return {"pages": []}

    with pytest.raises(FactureIllisible):
        await lire_facture(b"contenu-pdf-invente", _ocr_invente)


# --------------------------------------------------------------------------
# blocs_avec_reception (base de test réelle)
# --------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_document_bon_numero_photo_recue(
    db_session: AsyncSession,
) -> None:
    db_session.add(_document_invente(type_="bl", statut="recu", numero="L1000000001"))
    await db_session.commit()

    resultat = await blocs_avec_reception(
        db_session, _facture_invente(_bloc_invente("L1000000001"))
    )

    assert len(resultat) == 1
    assert resultat[0].photo_recue is True


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_document_archive_photo_non_recue(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        _document_invente(type_="bl", statut="archive", numero="L1000000002")
    )
    await db_session.commit()

    resultat = await blocs_avec_reception(
        db_session, _facture_invente(_bloc_invente("L1000000002"))
    )

    assert resultat[0].photo_recue is False


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_aucun_document_photo_non_recue(
    db_session: AsyncSession,
) -> None:
    resultat = await blocs_avec_reception(
        db_session, _facture_invente(_bloc_invente("L1000000003"))
    )

    assert resultat[0].photo_recue is False


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_document_enlevement_photo_recue(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        _document_invente(type_="enlevement", statut="recu", numero="9000000004")
    )
    await db_session.commit()

    resultat = await blocs_avec_reception(
        db_session, _facture_invente(_bloc_invente("9000000004"))
    )

    assert resultat[0].photo_recue is True


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_document_type_facture_photo_non_recue(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        _document_invente(
            type_="facture", statut="recu", numero="L1000000005", source="upload"
        )
    )
    await db_session.commit()

    resultat = await blocs_avec_reception(
        db_session, _facture_invente(_bloc_invente("L1000000005"))
    )

    assert resultat[0].photo_recue is False


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_normalise_casse_et_espaces(
    db_session: AsyncSession,
) -> None:
    """Décision du contrôleur T7 : comparaison exacte après `strip()` et
    mise en majuscules des deux côtés (préfixe `L` parfois en minuscule)."""
    db_session.add(_document_invente(type_="bl", statut="recu", numero="l1000000006"))
    await db_session.commit()

    resultat = await blocs_avec_reception(
        db_session, _facture_invente(_bloc_invente("  L1000000006  "))
    )

    assert resultat[0].photo_recue is True


@pytest.mark.anyio
@pytest.mark.db
async def test_blocs_avec_reception_conserve_valeurs_et_ordre(
    db_session: AsyncSession,
) -> None:
    ligne = LigneFacture(
        ordre=0,
        type_ligne=TypeLigne.ARTICLE,
        code_article="ART1",
        designation="désignation inventée",
        qte_livree=Decimal("2"),
        qte_totale=Decimal("2"),
        unite=None,
        pu_ht=Decimal("10.00"),
        pu_cdt=None,
        remise_pct=None,
        montant_ht=Decimal("20.00"),
        tva=Decimal("20"),
    )
    bloc_a = _bloc_invente(
        "L1000000010", date_bl=date(2026, 8, 3), chantier="CHANTIER A", lignes=(ligne,)
    )
    bloc_b = _bloc_invente("L1000000011", chantier="CHANTIER B")

    resultat = await blocs_avec_reception(db_session, _facture_invente(bloc_a, bloc_b))

    assert [bloc.numero_bl for bloc in resultat] == ["L1000000010", "L1000000011"]
    assert resultat[0].date_bl == date(2026, 8, 3)
    assert resultat[0].chantier_brut == "CHANTIER A"
    assert resultat[0].montant_ht == Decimal("20.00")


# --------------------------------------------------------------------------
# formater_blocs (fonction pure, sans base ni réseau)
# --------------------------------------------------------------------------


def test_formater_blocs_colonnes_oui_non_et_synthese() -> None:
    blocs = [
        BlocReception(
            numero_bl="L1",
            date_bl=date(2026, 8, 3),
            chantier_brut="Chantier court",
            montant_ht=Decimal("1234.5"),
            photo_recue=True,
        ),
        BlocReception(
            numero_bl="L20000000000",
            date_bl=None,
            chantier_brut=None,
            montant_ht=Decimal("-42"),
            photo_recue=False,
        ),
    ]

    sortie = formater_blocs(blocs)
    lignes = sortie.split("\n")

    assert len(lignes) == 4  # en-tête + 2 blocs + synthèse
    assert lignes[0].startswith("N° BL")
    assert "03/08/2026" in lignes[1]
    assert "1 234,50" in lignes[1]
    assert lignes[1].rstrip().endswith("oui")
    assert "-42,00" in lignes[2]
    assert lignes[2].rstrip().endswith("non")
    assert lignes[3] == "2 blocs — 1 reçus — 1 non reçus"


def test_formater_blocs_colonnes_alignees() -> None:
    blocs = [
        BlocReception(
            numero_bl="L1",
            date_bl=date(2026, 8, 3),
            chantier_brut="C",
            montant_ht=Decimal("1"),
            photo_recue=True,
        ),
        BlocReception(
            numero_bl="L200000000000",
            date_bl=date(2026, 8, 4),
            chantier_brut="Chantier bien plus long",
            montant_ht=Decimal("123456.78"),
            photo_recue=False,
        ),
    ]

    lignes = formater_blocs(blocs).split("\n")[:3]  # en-tête + 2 blocs

    # Les 4 premières colonnes (tout sauf « Photo reçue », dépadée par
    # rstrip) ont la même largeur sur l'en-tête et chaque ligne de données :
    # c'est la définition même d'un tableau aligné.
    segments_par_ligne = [ligne.split(" | ") for ligne in lignes]
    for indice_colonne in range(4):
        largeurs = {len(segments[indice_colonne]) for segments in segments_par_ligne}
        assert len(largeurs) == 1, f"colonne {indice_colonne} non alignée"


def test_formater_blocs_liste_vide() -> None:
    lignes = formater_blocs([]).split("\n")

    assert lignes[0].startswith("N° BL")
    assert lignes[-1] == "0 blocs — 0 reçus — 0 non reçus"
    assert len(lignes) == 2
