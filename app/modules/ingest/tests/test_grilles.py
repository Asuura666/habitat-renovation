"""Tests de `app/modules/ingest/grilles.py` (phase 3, tâche P4) : prix en
vigueur, écran « Grille de prix » (liste, recherche, pagination),
historique, saisie, retrait, import Excel (aperçu puis confirmation) et
modèle. Base de test réelle (`bl_test`), données entièrement inventées
(spec `docs/superpowers/specs/2026-09-27-prix-design.md`)."""

from __future__ import annotations

import os
import stat
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.extract.grille_excel import lire_grille_excel
from app.modules.ingest.grilles import (
    AucuneLigneValide,
    FournisseurIntrouvable,
    PrixInchange,
    ProduitIntrouvable,
    SaisieInvalide,
    SaisiePrix,
    _valider_date_effet,
    apercu_import,
    enregistrer_prix,
    historique_produit,
    importer_grille,
    lister_grille,
    modele_excel,
    prix_en_vigueur,
    retirer_produit,
)
from app.modules.ingest.models import (
    Fournisseur,
    GrilleImport,
    GrillePrix,
    Journal,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


# --------------------------------------------------------------------------
# Constructeurs de données inventées
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, nom: str = "Fournisseur Inventé"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"{nom} {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.flush()
    await db_session.commit()
    return fournisseur


async def _creer_utilisateur(
    db_session: AsyncSession, *, role: str = "admin"
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"{role}.{uuid.uuid4()}@example.invalid", role=role, is_active=True
    )
    db_session.add(utilisateur)
    await db_session.flush()
    await db_session.commit()
    return utilisateur


async def _creer_ligne(
    db_session: AsyncSession,
    fournisseur: Fournisseur,
    *,
    cle_produit: str = "nom:produit invente",
    designation: str = "Produit inventé",
    reference: str | None = None,
    prix_ht: str = "10.00",
    prix_net: str | None = None,
    date_effet: date = date(2026, 1, 1),
    source: str = "saisie",
    retire: bool = False,
    unite_brut: str | None = None,
    unite: str | None = None,
    **kwargs: object,
) -> GrillePrix:
    ligne = GrillePrix(
        fournisseur_id=fournisseur.id,
        cle_produit=cle_produit,
        reference=reference,
        designation=designation,
        unite_brut=unite_brut,
        unite=unite,
        prix_ht=Decimal(prix_ht),
        prix_net=Decimal(prix_net) if prix_net is not None else Decimal(prix_ht),
        date_effet=date_effet,
        retire=retire,
        source=source,
        **kwargs,
    )
    db_session.add(ligne)
    await db_session.flush()
    await db_session.commit()
    return ligne


def _classeur_grille(
    lignes: list[tuple[object, ...]],
    entetes: tuple[str, ...] = (
        "Référence",
        "Désignation",
        "Unité",
        "Prix unitaire HT (€)",
        "Remise %",
    ),
) -> bytes:
    """Construit un classeur `.xlsx` minimal en mémoire (feuille « Grille »,
    en-tête + lignes), pour les tests d'import -- jamais un fichier réel du
    client (spec §12, « fichiers générés par le test »)."""
    import io

    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.title = "Grille"
    feuille.append(entetes)
    for ligne in lignes:
        feuille.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


# --------------------------------------------------------------------------
# `prix_en_vigueur`
# --------------------------------------------------------------------------


async def test_prix_en_vigueur_avant_toute_ligne_aucune_ligne_du_tout(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 1, 1))

    assert resultat == {}


async def test_prix_en_vigueur_entre_deux_dates(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )
    await _creer_ligne(
        db_session, fournisseur, prix_ht="12.00", date_effet=date(2026, 6, 1)
    )

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 3, 1))

    assert resultat["nom:produit invente"].prix_net == Decimal("10.00")
    assert resultat["nom:produit invente"].posterieure is False


async def test_prix_en_vigueur_apres_les_deux_dates(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )
    await _creer_ligne(
        db_session, fournisseur, prix_ht="12.00", date_effet=date(2026, 6, 1)
    )

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 12, 1))

    assert resultat["nom:produit invente"].prix_net == Decimal("12.00")
    assert resultat["nom:produit invente"].posterieure is False


async def test_prix_en_vigueur_meme_date_le_plus_recent_cree(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )
    await _creer_ligne(
        db_session, fournisseur, prix_ht="15.00", date_effet=date(2026, 1, 1)
    )

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 1, 1))

    assert resultat["nom:produit invente"].prix_net == Decimal("15.00")


async def test_prix_en_vigueur_produit_retire_absent(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )
    await _creer_ligne(
        db_session,
        fournisseur,
        prix_ht="10.00",
        date_effet=date(2026, 2, 1),
        retire=True,
    )

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 3, 1))

    assert resultat == {}


async def test_prix_en_vigueur_grille_posterieure_au_bon(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 6, 1)
    )

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 1, 1))

    produit = resultat["nom:produit invente"]
    assert produit.prix_net == Decimal("10.00")
    assert produit.posterieure is True


async def test_prix_en_vigueur_avec_cles_ne_calcule_que_celles_demandees(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(db_session, fournisseur, cle_produit="nom:a", designation="A")
    await _creer_ligne(db_session, fournisseur, cle_produit="nom:b", designation="B")

    resultat = await prix_en_vigueur(
        db_session, fournisseur.id, date(2026, 6, 1), cles=("nom:a",)
    )

    assert set(resultat) == {"nom:a"}


# --------------------------------------------------------------------------
# `lister_grille`
# --------------------------------------------------------------------------


async def test_lister_grille_fournisseur_inconnu(db_session: AsyncSession) -> None:
    with pytest.raises(FournisseurIntrouvable):
        await lister_grille(db_session, uuid.uuid4())


async def test_lister_grille_recherche_designation_insensible_accents_casse(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session,
        fournisseur,
        cle_produit="nom:cloison 48",
        designation="Cloison Été 48",
        date_effet=date(2020, 1, 1),
    )
    await _creer_ligne(
        db_session,
        fournisseur,
        cle_produit="nom:isolant",
        designation="Isolant laine",
        date_effet=date(2020, 1, 1),
    )

    grille = await lister_grille(db_session, fournisseur.id, recherche="CLOISON ete")

    assert [p.designation for p in grille.produits] == ["Cloison Été 48"]


async def test_lister_grille_recherche_reference(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session,
        fournisseur,
        cle_produit="ref:4000493",
        reference="4000493",
        designation="Article référencé",
        date_effet=date(2020, 1, 1),
    )
    await _creer_ligne(
        db_session,
        fournisseur,
        cle_produit="nom:autre",
        designation="Autre article",
        date_effet=date(2020, 1, 1),
    )

    grille = await lister_grille(db_session, fournisseur.id, recherche="4000493")

    assert [p.designation for p in grille.produits] == ["Article référencé"]


async def test_lister_grille_pagination(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    for i in range(60):
        await _creer_ligne(
            db_session,
            fournisseur,
            cle_produit=f"nom:produit {i:03d}",
            designation=f"Produit {i:03d}",
            date_effet=date(2020, 1, 1),
        )

    page_1 = await lister_grille(db_session, fournisseur.id, page=1)
    page_2 = await lister_grille(db_session, fournisseur.id, page=2)

    assert page_1.nb_produits == 60
    assert page_1.pages == 2
    assert len(page_1.produits) == 50
    assert len(page_2.produits) == 10
    assert page_1.produits[0].designation == "Produit 000"


# --------------------------------------------------------------------------
# `historique_produit`
# --------------------------------------------------------------------------


async def test_historique_produit_trie_du_plus_recent(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )
    await _creer_ligne(
        db_session, fournisseur, prix_ht="12.00", date_effet=date(2026, 6, 1)
    )

    historique = await historique_produit(
        db_session, fournisseur.id, "nom:produit invente"
    )

    assert [ligne.prix_net for ligne in historique] == [
        Decimal("12.00"),
        Decimal("10.00"),
    ]


async def test_historique_produit_inconnu_leve(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    with pytest.raises(ProduitIntrouvable):
        await historique_produit(db_session, fournisseur.id, "nom:jamais-vu")


async def test_historique_produit_fournisseur_inconnu_leve(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(FournisseurIntrouvable):
        await historique_produit(db_session, uuid.uuid4(), "nom:x")


# --------------------------------------------------------------------------
# `enregistrer_prix`
# --------------------------------------------------------------------------


async def test_enregistrer_prix_nouveau_produit(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)

    produit = await enregistrer_prix(
        db_session,
        fournisseur.id,
        SaisiePrix(
            designation="Produit saisi",
            prix_ht=Decimal("9.90"),
            date_effet=date(2026, 1, 1),
        ),
        auteur_id=utilisateur.id,
    )

    assert produit.prix_net == Decimal("9.90")
    lignes = (await db_session.execute(select(GrillePrix))).scalars().all()
    assert len(lignes) == 1
    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert any(j.action == "grille_prix_saisi" for j in journal)


async def test_enregistrer_prix_produit_existant_ajoute_une_ligne(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )

    await enregistrer_prix(
        db_session,
        fournisseur.id,
        SaisiePrix(
            designation="Produit inventé",
            prix_ht=Decimal("11.00"),
            date_effet=date(2026, 2, 1),
        ),
        auteur_id=utilisateur.id,
    )

    lignes = (await db_session.execute(select(GrillePrix))).scalars().all()
    assert len(lignes) == 2


async def test_enregistrer_prix_identique_refuse(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )

    with pytest.raises(PrixInchange):
        await enregistrer_prix(
            db_session,
            fournisseur.id,
            SaisiePrix(
                designation="Produit inventé",
                prix_ht=Decimal("10.00"),
                date_effet=date(2026, 3, 1),
            ),
            auteur_id=utilisateur.id,
        )


async def test_enregistrer_prix_designation_vide_refusee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)

    with pytest.raises(SaisieInvalide):
        await enregistrer_prix(
            db_session,
            fournisseur.id,
            SaisiePrix(
                designation="   ", prix_ht=Decimal("1.00"), date_effet=date(2026, 1, 1)
            ),
            auteur_id=utilisateur.id,
        )


async def test_enregistrer_prix_ht_negatif_refuse(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)

    with pytest.raises(SaisieInvalide):
        await enregistrer_prix(
            db_session,
            fournisseur.id,
            SaisiePrix(
                designation="Produit",
                prix_ht=Decimal("-1.00"),
                date_effet=date(2026, 1, 1),
            ),
            auteur_id=utilisateur.id,
        )


async def test_enregistrer_prix_fournisseur_inconnu_leve(
    db_session: AsyncSession,
) -> None:
    utilisateur = await _creer_utilisateur(db_session)
    with pytest.raises(FournisseurIntrouvable):
        await enregistrer_prix(
            db_session,
            uuid.uuid4(),
            SaisiePrix(
                designation="Produit",
                prix_ht=Decimal("1.00"),
                date_effet=date(2026, 1, 1),
            ),
            auteur_id=utilisateur.id,
        )


# --------------------------------------------------------------------------
# `retirer_produit`
# --------------------------------------------------------------------------


async def test_retirer_produit_ajoute_une_ligne_retiree(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    await _creer_ligne(
        db_session, fournisseur, prix_ht="10.00", date_effet=date(2026, 1, 1)
    )

    await retirer_produit(
        db_session,
        fournisseur.id,
        "nom:produit invente",
        date(2026, 2, 1),
        auteur_id=utilisateur.id,
    )

    resultat = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 3, 1))
    assert resultat == {}
    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert any(j.action == "grille_prix_retire" for j in journal)


async def test_retirer_produit_inconnu_leve(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)

    with pytest.raises(ProduitIntrouvable):
        await retirer_produit(
            db_session,
            fournisseur.id,
            "nom:jamais-vu",
            date(2026, 1, 1),
            auteur_id=utilisateur.id,
        )


# --------------------------------------------------------------------------
# `apercu_import` : ne modifie jamais la base.
# --------------------------------------------------------------------------


async def test_apercu_import_sans_ecriture(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session,
        fournisseur,
        cle_produit="nom:produit existant",
        designation="Produit existant",
        prix_ht="10.00",
        unite="kg",
        date_effet=date(2020, 1, 1),
    )
    contenu = _classeur_grille(
        [
            ("REF-1", "Produit nouveau", "sac", 5.5, None),
            (None, "Produit existant", "l", 12.0, None),
        ]
    )

    apercu = await apercu_import(
        db_session, fournisseur.id, contenu, "grille.xlsx", date(2026, 1, 1)
    )

    assert apercu.nb_nouveaux == 1
    assert apercu.nb_modifies == 1
    assert apercu.nb_inchanges == 0
    assert apercu.nb_erreurs == 0
    assert (await db_session.execute(select(GrillePrix))).scalars().all() != []
    # Toujours une seule ligne (celle créée par le test) : aucune écriture.
    lignes = (await db_session.execute(select(GrillePrix))).scalars().all()
    assert len(lignes) == 1

    # Constat de la relecture finale : le contenu de l'aperçu (ancien/nouveau
    # prix, ancienne/nouvelle unité), pas seulement les compteurs, n'était
    # vérifié par aucun test -- une inversion prix/unité passerait inaperçue.
    assert apercu.nouveaux[0].reference == "REF-1"
    assert apercu.nouveaux[0].nouveau_prix_net == Decimal("5.5000")
    assert apercu.nouveaux[0].ancien_prix_net is None
    assert apercu.nouveaux[0].nouvelle_unite == "sac"
    assert apercu.nouveaux[0].ancienne_unite is None

    assert apercu.modifies[0].designation == "Produit existant"
    assert apercu.modifies[0].nouveau_prix_net == Decimal("12.0000")
    assert apercu.modifies[0].ancien_prix_net == Decimal("10.0000")
    assert apercu.modifies[0].nouvelle_unite == "l"
    assert apercu.modifies[0].ancienne_unite == "kg"


async def test_apercu_import_produit_absent_du_fichier(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne(
        db_session,
        fournisseur,
        cle_produit="nom:produit oublie",
        designation="Produit oublié",
        prix_ht="10.00",
        date_effet=date(2020, 1, 1),
    )
    contenu = _classeur_grille([("REF-1", "Un autre produit", None, 5.0, None)])

    apercu = await apercu_import(
        db_session, fournisseur.id, contenu, "grille.xlsx", date(2026, 1, 1)
    )

    assert [p.designation for p in apercu.absents_du_fichier] == ["Produit oublié"]


async def test_apercu_import_fichier_invalide_leve(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    from app.modules.ingest.grilles import FichierGrilleInvalide

    with pytest.raises(FichierGrilleInvalide):
        await apercu_import(
            db_session, fournisseur.id, b"pas-un-xlsx", "grille.xlsx", date(2026, 1, 1)
        )


async def test_apercu_import_date_effet_hors_bornes_leve(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    contenu = _classeur_grille([("REF-1", "Produit", None, 5.0, None)])

    with pytest.raises(SaisieInvalide):
        await apercu_import(
            db_session, fournisseur.id, contenu, "grille.xlsx", date(1999, 1, 1)
        )


def test_valider_date_effet_29_fevrier_sans_annee_bissextile_suivante(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cas limite non testé jusqu'ici (constat de la relecture qualité) : si
    « aujourd'hui » est un 29 février dont l'année suivante n'est pas
    bissextile (prochain cas réel : 29/02/2028 -> 2029), la borne haute doit
    retomber sur le 28 février de cette année-là au lieu de lever
    `ValueError` (`date.replace` ne sait pas produire un 29 février qui
    n'existe pas)."""

    class _DatetimeFige(datetime):
        @classmethod
        def now(cls, tz: object = None) -> _DatetimeFige:
            return cls(2028, 2, 29, 12, 0, tzinfo=FUSEAU_PARIS)

    monkeypatch.setattr("app.modules.ingest.grilles.datetime", _DatetimeFige)

    _valider_date_effet(date(2029, 2, 28))  # borne haute exacte : accepté

    with pytest.raises(SaisieInvalide):
        _valider_date_effet(date(2029, 3, 1))


# --------------------------------------------------------------------------
# `importer_grille`
# --------------------------------------------------------------------------


async def test_importer_grille_cree_les_lignes_et_le_grille_import(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    contenu = _classeur_grille(
        [
            ("REF-1", "Produit un", "sac", 5.5, None),
            ("REF-2", "Produit deux", None, 12.0, 10),
        ]
    )

    resultat = await importer_grille(
        db_session,
        fournisseur.id,
        contenu,
        "grille-fournisseur.xlsx",
        date(2026, 1, 1),
        auteur_id=utilisateur.id,
        docs_dir=tmp_path,
    )

    assert resultat.nb_nouveaux == 2
    lignes = (await db_session.execute(select(GrillePrix))).scalars().all()
    assert len(lignes) == 2
    imports = (await db_session.execute(select(GrilleImport))).scalars().all()
    assert len(imports) == 1
    assert imports[0].nb_nouveaux == 2
    chemin = Path(imports[0].chemin)
    assert chemin.is_file()
    assert oct(chemin.stat().st_mode)[-3:] == "640"
    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert any(j.action == "grille_importee" for j in journal)


async def test_importer_grille_dossier_intermediaire_grilles_en_0750(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Constat de la relecture qualité : `docs_dir/grilles/` (le dossier
    intermédiaire, commun à tous les fournisseurs) doit être 0750 comme
    `docs_dir/grilles/<fournisseur_id>/` et le fichier -- pas 0755. Avec
    `Path.mkdir(parents=True)` seul, sous l'umask 0022 du conteneur, ce
    dossier intermédiaire hérite des droits par défaut (0755, listable par
    tout autre compte Unix du VPS partagé) puisque son mode n'est appliqué
    qu'au dossier terminal créé."""
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    contenu = _classeur_grille([("REF-1", "Produit un", "sac", 5.5, None)])

    umask_avant = os.umask(0o022)
    try:
        await importer_grille(
            db_session,
            fournisseur.id,
            contenu,
            "grille.xlsx",
            date(2026, 1, 1),
            auteur_id=utilisateur.id,
            docs_dir=tmp_path,
        )
    finally:
        os.umask(umask_avant)

    dossier_grilles = tmp_path / "grilles"
    dossier_fournisseur = dossier_grilles / str(fournisseur.id)
    assert stat.S_IMODE(dossier_grilles.stat().st_mode) == 0o750
    assert stat.S_IMODE(dossier_fournisseur.stat().st_mode) == 0o750


async def test_importer_grille_identique_ne_cree_aucune_ligne_de_prix(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    contenu = _classeur_grille([("REF-1", "Produit un", "sac", 5.5, None)])

    await importer_grille(
        db_session,
        fournisseur.id,
        contenu,
        "grille.xlsx",
        date(2026, 1, 1),
        auteur_id=utilisateur.id,
        docs_dir=tmp_path,
    )
    resultat_second = await importer_grille(
        db_session,
        fournisseur.id,
        contenu,
        "grille.xlsx",
        date(2026, 1, 1),
        auteur_id=utilisateur.id,
        docs_dir=tmp_path,
    )

    assert resultat_second.nb_nouveaux == 0
    assert resultat_second.nb_modifies == 0
    assert resultat_second.nb_inchanges == 1
    lignes = (await db_session.execute(select(GrillePrix))).scalars().all()
    assert len(lignes) == 1
    imports = (await db_session.execute(select(GrilleImport))).scalars().all()
    assert len(imports) == 2


async def test_importer_grille_aucune_ligne_valide_refuse(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    contenu = _classeur_grille([(None, "", None, None, None)])

    with pytest.raises(AucuneLigneValide):
        await importer_grille(
            db_session,
            fournisseur.id,
            contenu,
            "grille.xlsx",
            date(2026, 1, 1),
            auteur_id=utilisateur.id,
            docs_dir=tmp_path,
        )
    assert (await db_session.execute(select(GrilleImport))).scalars().all() == []


async def test_importer_grille_lignes_en_erreur_ignorees(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    contenu = _classeur_grille(
        [
            ("REF-1", "Produit valide", None, 5.0, None),
            ("REF-2", "", None, 5.0, None),  # désignation manquante -> erreur
        ]
    )

    resultat = await importer_grille(
        db_session,
        fournisseur.id,
        contenu,
        "grille.xlsx",
        date(2026, 1, 1),
        auteur_id=utilisateur.id,
        docs_dir=tmp_path,
    )

    assert resultat.nb_nouveaux == 1
    assert resultat.nb_erreurs == 1


# --------------------------------------------------------------------------
# `modele_excel`
# --------------------------------------------------------------------------


def test_modele_excel_relu_sans_erreur() -> None:
    contenu = modele_excel()

    grille_lue = lire_grille_excel(contenu)

    assert grille_lue.erreurs == ()
    assert len(grille_lue.lignes) == 2
    assert "Mode d'emploi" in grille_lue.feuilles_ignorees
