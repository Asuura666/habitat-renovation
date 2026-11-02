"""Tests de `ingest/fusion_fournisseur.py` (lot 4 du 02/11/2026) : fusion de
deux fournisseurs. Base de test réelle, données entièrement inventées."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base
from app.modules.ingest.fusion_fournisseur import (
    FusionFournisseurImpossible,
    fusionner_fournisseurs,
    tables_referencant_fournisseur,
)
from app.modules.ingest.models import (
    AgenceFournisseur,
    Anomalie,
    Article,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    GrilleImport,
    GrillePrix,
    Journal,
    Ligne,
    PrixInternet,
    PrixObserve,
)

pytestmark = pytest.mark.anyio

# Ensemble attendu : si une table référence `fournisseur`, ce test échoue
# tant que quelqu'un n'a pas relu `fusion_fournisseur.py` et ajouté la table
# ici ET dans `_peupler` (le test de couverture ci-dessous s'en sert).
TABLES_ATTENDUES = {
    "agence_fournisseur",
    "article",
    "chantier_alias",
    "document",
    "grille_import",
    "grille_prix",
    "prix_internet",
    "prix_observe",
}


def test_tables_referencant_fournisseur_sont_toutes_connues() -> None:
    trouvees = {table.name for table, _ in tables_referencant_fournisseur()}
    assert trouvees == TABLES_ATTENDUES


async def _fournisseur(
    s: AsyncSession,
    nom: str,
    *,
    tva: str | None = None,
    aliases: list[str] | None = None,
) -> Fournisseur:
    f = Fournisseur(nom=nom, tva=tva, siret=None, aliases=aliases)
    s.add(f)
    await s.flush()
    return f


async def _document(
    s: AsyncSession, f: Fournisseur, numero: str | None = None
) -> Document:
    d = Document(
        type="bl",
        fournisseur_id=f.id,
        numero=numero,
        fichier_path="x/y.jpg",
        source="upload",
        statut="recu",
    )
    s.add(d)
    await s.flush()
    return d


async def _peupler(s: AsyncSession, f: Fournisseur) -> dict[str, uuid.UUID]:
    """Une ligne dans chacune des tables de `TABLES_ATTENDUES` pour `f`."""
    ids: dict[str, uuid.UUID] = {}
    agence = AgenceFournisseur(fournisseur_id=f.id, nom=f"Agence {f.nom}")
    article = Article(fournisseur_id=f.id, code=f"ART-{f.nom}")
    chantier = Chantier(nom_canonique=f"Chantier {f.nom}")
    s.add_all([agence, article, chantier])
    await s.flush()
    alias = ChantierAlias(
        fournisseur_id=f.id,
        libelle_brut=f"alias {f.nom}",
        code_brut=None,
        chantier_id=chantier.id,
    )
    doc = Document(
        type="bl",
        fournisseur_id=f.id,
        agence_fournisseur_id=agence.id,
        numero=f"N-{f.nom}",
        fichier_path="x/y.jpg",
        source="upload",
        statut="recu",
    )
    imp = GrilleImport(
        fournisseur_id=f.id,
        nom_fichier="g.xlsx",
        empreinte=f"e-{f.nom}",
        chemin="g/g.xlsx",
        date_effet=date(2026, 1, 1),
        nb_nouveaux=1,
        nb_modifies=0,
        nb_inchanges=0,
        nb_erreurs=0,
    )
    s.add_all([alias, doc, imp])
    await s.flush()
    s.add_all(
        [
            Ligne(
                document_id=doc.id, article_id=article.id, type_ligne="article", ordre=1
            ),
            Anomalie(
                regle="R18",
                gravite="moyenne",
                alias_id=alias.id,
                document_id=doc.id,
                detail={"k": 1},
                statut="ouverte",
            ),
            GrillePrix(
                fournisseur_id=f.id,
                cle_produit="k",
                designation="d",
                prix_ht=Decimal("1"),
                prix_net=Decimal("1"),
                date_effet=date(2026, 1, 1),
                source="import",
                import_id=imp.id,
            ),
            PrixInternet(
                fournisseur_id=f.id,
                cle="k",
                designation="d",
                statut="echec",
                consulte_le=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            PrixObserve(
                fournisseur_id=f.id,
                cle_produit="k",
                designation="d",
                date_observation=date(2026, 1, 1),
                prix_ht=Decimal("1"),
                source_libelle="essai",
            ),
        ]
    )
    await s.flush()
    ids.update(agence=agence.id, article=article.id, alias=alias.id, document=doc.id)
    return ids


async def test_fusion_deplace_toutes_les_tables_et_supprime_la_source(
    db_session: AsyncSession,
) -> None:
    source = await _fournisseur(db_session, "Source Test", tva="FR00", aliases=["Src"])
    cible = await _fournisseur(db_session, "Cible Test", tva="FR11")
    await _peupler(db_session, source)
    await _peupler(db_session, cible)
    source_id, cible_id = source.id, cible.id

    res = await fusionner_fournisseurs(
        db_session, source_nom="source test", cible_nom="Cible Test"
    )
    await db_session.commit()

    # Aucune ligne, dans aucune table, ne référence plus la source.
    for table, colonne in tables_referencant_fournisseur():
        n = (
            await db_session.execute(
                select(func.count()).select_from(table).where(colonne == source_id)
            )
        ).scalar_one()
        assert n == 0, table.name
    assert set(res.deplacees) | set(res.doublons) >= {
        t.name for t, _ in tables_referencant_fournisseur()
    }
    assert (
        await db_session.execute(select(Fournisseur).where(Fournisseur.id == source_id))
    ).scalar_one_or_none() is None
    gardee = (
        await db_session.execute(select(Fournisseur).where(Fournisseur.id == cible_id))
    ).scalar_one()
    assert gardee.tva == "FR11"  # inchangée
    assert gardee.siret is None
    assert sorted(gardee.aliases or []) == ["Source Test", "Src"]
    # Les deux documents sont chez la cible, l'historique des prix aussi.
    nb_docs = (
        await db_session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.fournisseur_id == cible_id)
        )
    ).scalar_one()
    assert nb_docs == 2
    nb_prix = (
        await db_session.execute(
            select(func.count())
            .select_from(GrillePrix)
            .where(GrillePrix.fournisseur_id == cible_id)
        )
    ).scalar_one()
    assert nb_prix == 2


async def test_fusion_le_declencheur_de_l_historique_est_remis(
    db_session: AsyncSession,
) -> None:
    source = await _fournisseur(db_session, "Source Test")
    await _fournisseur(db_session, "Cible Test")
    await _peupler(db_session, source)
    await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test"
    )
    etat = (
        await db_session.execute(
            text(
                "SELECT tgenabled FROM pg_trigger "
                "WHERE tgname = 'grille_prix_inalterable'"
            )
        )
    ).scalar_one()
    assert etat in ("O", b"O")  # actif
    with pytest.raises(Exception, match="inaltérable"):
        await db_session.execute(text("UPDATE grille_prix SET designation = 'autre'"))
    await db_session.rollback()


async def test_conflits_alias_article_agence_gardent_la_cible(
    db_session: AsyncSession,
) -> None:
    source = await _fournisseur(db_session, "Source Test")
    cible = await _fournisseur(db_session, "Cible Test")
    chantier_s = Chantier(nom_canonique="Chantier S")
    chantier_c = Chantier(nom_canonique="Chantier C")
    db_session.add_all([chantier_s, chantier_c])
    await db_session.flush()
    alias_s = ChantierAlias(
        fournisseur_id=source.id,
        libelle_brut="meme",
        code_brut=None,
        chantier_id=chantier_s.id,
    )
    alias_c = ChantierAlias(
        fournisseur_id=cible.id,
        libelle_brut="meme",
        code_brut=None,
        chantier_id=chantier_c.id,
    )
    article_s = Article(fournisseur_id=source.id, code="A1")
    article_c = Article(fournisseur_id=cible.id, code="A1")
    ag_s = AgenceFournisseur(fournisseur_id=source.id, nom="Béziers Centre")
    ag_c = AgenceFournisseur(fournisseur_id=cible.id, nom="beziers  centre")
    ag_autre = AgenceFournisseur(fournisseur_id=source.id, nom="Nîmes")
    db_session.add_all([alias_s, alias_c, article_s, article_c, ag_s, ag_c, ag_autre])
    await db_session.flush()
    doc = Document(
        type="bl",
        fournisseur_id=source.id,
        agence_fournisseur_id=ag_s.id,
        fichier_path="x",
        source="upload",
        statut="recu",
    )
    db_session.add(doc)
    await db_session.flush()
    ligne = Ligne(
        document_id=doc.id, article_id=article_s.id, type_ligne="article", ordre=1
    )
    anomalie = Anomalie(
        regle="R18",
        gravite="moyenne",
        alias_id=alias_s.id,
        detail={"k": 1},
        statut="ouverte",
    )
    db_session.add_all([ligne, anomalie])
    await db_session.flush()
    ids = dict(
        doc=doc.id,
        ligne=ligne.id,
        anomalie=anomalie.id,
        alias_c=alias_c.id,
        article_c=article_c.id,
        ag_c=ag_c.id,
        ag_autre=ag_autre.id,
        cible=cible.id,
        chantier_c=chantier_c.id,
    )

    res = await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test"
    )
    await db_session.commit()
    db_session.expire_all()

    assert res.doublons == {"chantier_alias": 1, "article": 1, "agence_fournisseur": 1}
    ligne_lue = await db_session.get(Ligne, ids["ligne"])
    anomalie_lue = await db_session.get(Anomalie, ids["anomalie"])
    doc_lu = await db_session.get(Document, ids["doc"])
    alias_lu = await db_session.get(ChantierAlias, ids["alias_c"])
    agence_lue = await db_session.get(AgenceFournisseur, ids["ag_autre"])
    assert ligne_lue is not None and ligne_lue.article_id == ids["article_c"]
    assert anomalie_lue is not None and anomalie_lue.alias_id == ids["alias_c"]
    assert doc_lu is not None and doc_lu.agence_fournisseur_id == ids["ag_c"]
    # Le chantier de l'alias gardé est celui de la cible.
    assert alias_lu is not None and alias_lu.chantier_id == ids["chantier_c"]
    # L'agence sans homonyme est déplacée.
    assert agence_lue is not None and agence_lue.fournisseur_id == ids["cible"]
    nb_agences = (
        await db_session.execute(select(func.count()).select_from(AgenceFournisseur))
    ).scalar_one()
    assert nb_agences == 2


async def test_alias_null_egaux_pour_chantier_alias(db_session: AsyncSession) -> None:
    """`code_brut` NULL des deux côtés : c'est un doublon (NULLS NOT DISTINCT),
    jamais d'erreur d'intégrité."""
    source = await _fournisseur(db_session, "Source Test")
    cible = await _fournisseur(db_session, "Cible Test")
    db_session.add_all(
        [
            ChantierAlias(fournisseur_id=source.id, libelle_brut="x", code_brut=None),
            ChantierAlias(fournisseur_id=cible.id, libelle_brut="x", code_brut=None),
            ChantierAlias(fournisseur_id=source.id, libelle_brut="y", code_brut="12"),
            ChantierAlias(fournisseur_id=cible.id, libelle_brut="y", code_brut="13"),
        ]
    )
    await db_session.flush()
    res = await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test"
    )
    assert res.doublons == {"chantier_alias": 1}
    assert res.deplacees["chantier_alias"] == 1


async def test_simulation_n_ecrit_rien_et_compte(db_session: AsyncSession) -> None:
    source = await _fournisseur(db_session, "Source Test")
    cible = await _fournisseur(db_session, "Cible Test")
    await _peupler(db_session, source)
    await _peupler(db_session, cible)
    res = await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test", simulation=True
    )
    assert res.simulation
    assert res.deplacees["document"] == 1 and res.deplacees["grille_prix"] == 1
    assert (await db_session.get(Fournisseur, source.id)) is not None
    nb = (
        await db_session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.fournisseur_id == source.id)
        )
    ).scalar_one()
    assert nb == 1
    assert (
        await db_session.execute(select(func.count()).select_from(Journal))
    ).scalar_one() == 0


async def test_simulation_et_reel_donnent_les_memes_nombres(
    db_session: AsyncSession,
) -> None:
    source = await _fournisseur(db_session, "Source Test")
    cible = await _fournisseur(db_session, "Cible Test")
    await _peupler(db_session, source)
    db_session.add_all(
        [
            AgenceFournisseur(fournisseur_id=source.id, nom="Même"),
            AgenceFournisseur(fournisseur_id=cible.id, nom="même"),
        ]
    )
    await db_session.flush()
    sim = await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test", simulation=True
    )
    reel = await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test"
    )
    assert (sim.deplacees, sim.doublons, sim.reconduites) == (
        reel.deplacees,
        reel.doublons,
        reel.reconduites,
    )


async def test_journal_fournisseur_fusionne(db_session: AsyncSession) -> None:
    source = await _fournisseur(db_session, "Source Test", aliases=["Src"])
    cible = await _fournisseur(db_session, "Cible Test")
    await _document(db_session, source, "A")
    await fusionner_fournisseurs(
        db_session, source_nom="Source Test", cible_nom="Cible Test"
    )
    j = (
        await db_session.execute(
            select(Journal).where(Journal.action == "fournisseur_fusionne")
        )
    ).scalar_one()
    assert j.utilisateur_id is None
    assert j.cible_id == str(cible.id)
    assert j.avant is not None and j.avant["fournisseur_absorbe"] == "Source Test"
    assert j.avant["aliases_absorbe"] == ["Src"]
    assert j.avant["nom"] == "Cible Test" and j.avant["aliases"] == []
    assert j.apres is not None
    assert j.apres["lignes_deplacees"] == {"documents": 1}
    assert j.apres["aliases"] == ["Source Test", "Src"]


async def test_refus_meme_fournisseur_et_introuvable(db_session: AsyncSession) -> None:
    await _fournisseur(db_session, "Seul Test")
    with pytest.raises(FusionFournisseurImpossible, match="même fournisseur"):
        await fusionner_fournisseurs(
            db_session, source_nom="Seul Test", cible_nom="SEUL test"
        )
    with pytest.raises(FusionFournisseurImpossible, match="introuvable"):
        await fusionner_fournisseurs(
            db_session, source_nom="Absent", cible_nom="Seul Test"
        )
    with pytest.raises(FusionFournisseurImpossible, match="introuvable"):
        await fusionner_fournisseurs(
            db_session, source_nom="Seul Test", cible_nom="Absent"
        )


async def test_refus_documents_de_meme_numero_sans_rien_ecrire(
    db_session: AsyncSession,
) -> None:
    source = await _fournisseur(db_session, "Source Test")
    cible = await _fournisseur(db_session, "Cible Test")
    await _document(db_session, source, "42")
    await _document(db_session, source, "43")
    await _document(db_session, cible, "42")
    with pytest.raises(FusionFournisseurImpossible, match="document"):
        await fusionner_fournisseurs(
            db_session, source_nom="Source Test", cible_nom="Cible Test"
        )
    nb = (
        await db_session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.fournisseur_id == source.id)
        )
    ).scalar_one()
    assert nb == 2
    assert (await db_session.get(Fournisseur, source.id)) is not None


def test_toutes_les_tables_ont_un_id_simple() -> None:
    """La fusion rattache les dépendants d'un doublon par `id`."""
    for table, _ in tables_referencant_fournisseur():
        assert "id" in table.c, table.name
    assert Base.metadata.tables  # métadonnées chargées
