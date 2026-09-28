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
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.ingest.a_traiter import compter_problemes_a_regler, lister_a_traiter
from app.modules.ingest.anomalies import lister_anomalies
from app.modules.ingest.models import (
    Anomalie,
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


async def test_alias_en_attente_plusieurs_alias_meme_fournisseur_et_autre(
    db_session: AsyncSession,
) -> None:
    """Plusieurs alias en attente d'un même fournisseur, plus un alias d'un
    autre fournisseur (tâche T5, chargement mutualisé par
    `fournisseur_id`) : chaque alias ne voit que les documents de SON
    fournisseur dont le libellé décomposé correspond au sien -- même
    résultat qu'avec une sélection refaite pour chaque alias."""
    fournisseur_a = await _creer_fournisseur(db_session, nom="Fournisseur A")
    fournisseur_b = await _creer_fournisseur(db_session, nom="Fournisseur B")

    alias_a1 = await _creer_alias(
        db_session, fournisseur=fournisseur_a, libelle_brut="maison test"
    )
    alias_a2 = await _creer_alias(
        db_session, fournisseur=fournisseur_a, libelle_brut="autre chantier"
    )
    alias_b1 = await _creer_alias(
        db_session, fournisseur=fournisseur_b, libelle_brut="maison test"
    )

    # Fournisseur A : un document par alias, plus un qui ne correspond à
    # aucun des deux (négatif : libellé différent).
    doc_a1 = await _creer_document(
        db_session,
        fournisseur=fournisseur_a,
        chantier_brut="MAISON TEST (1002)",
        created_at=_instant(0),
    )
    doc_a2 = await _creer_document(
        db_session,
        fournisseur=fournisseur_a,
        chantier_brut="AUTRE CHANTIER (2002)",
        created_at=_instant(10),
    )
    await _creer_document(
        db_session,
        fournisseur=fournisseur_a,
        chantier_brut="SANS RAPPORT (3002)",
        created_at=_instant(20),
    )

    # Fournisseur B : même libellé brut que alias_a1, mais un autre
    # fournisseur -- négatif : ne doit jamais compter pour alias_a1.
    doc_b1 = await _creer_document(
        db_session,
        fournisseur=fournisseur_b,
        chantier_brut="MAISON TEST (9002)",
        created_at=_instant(0),
    )

    a_traiter = await lister_a_traiter(db_session)

    lignes = {a.id: a for a in a_traiter.alias}
    assert lignes[alias_a1.id].nb_documents == 1
    assert lignes[alias_a1.id].exemple_brut == doc_a1.chantier_brut
    assert lignes[alias_a2.id].nb_documents == 1
    assert lignes[alias_a2.id].exemple_brut == doc_a2.chantier_brut
    assert lignes[alias_b1.id].nb_documents == 1
    assert lignes[alias_b1.id].exemple_brut == doc_b1.chantier_brut


async def test_alias_en_attente_sans_n_plus_1(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """Le nombre de requêtes SQL pour charger les alias en attente ne doit
    pas dépendre du nombre d'alias d'un même fournisseur (tâche T5,
    constat mesuré : 18 requêtes pour 9 alias avant correctif) : un alias
    puis cinq alias du même fournisseur doivent déclencher le même nombre
    de requêtes."""
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur N+1")
    await _creer_alias(
        db_session, fournisseur=fournisseur, libelle_brut="chantier n1 0"
    )

    sync_engine: Engine = db_engine.sync_engine

    compteur_un_alias = {"n": 0}

    def _compter_un_alias(*args: object, **kwargs: object) -> None:
        compteur_un_alias["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _compter_un_alias)
    try:
        a_traiter_un_alias = await lister_a_traiter(db_session)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _compter_un_alias)

    assert len(a_traiter_un_alias.alias) == 1

    for indice in range(1, 5):
        await _creer_alias(
            db_session, fournisseur=fournisseur, libelle_brut=f"chantier n1 {indice}"
        )

    compteur_cinq_alias = {"n": 0}

    def _compter_cinq_alias(*args: object, **kwargs: object) -> None:
        compteur_cinq_alias["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _compter_cinq_alias)
    try:
        a_traiter_cinq_alias = await lister_a_traiter(db_session)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _compter_cinq_alias)

    assert len(a_traiter_cinq_alias.alias) == 5
    # Même nombre de requêtes avec cinq alias du même fournisseur qu'avec
    # un seul : la charge ne croît plus avec le nombre d'alias (avant
    # correctif, cinq requêtes de plus pour les quatre alias
    # supplémentaires).
    assert compteur_cinq_alias["n"] == compteur_un_alias["n"]


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


# --------------------------------------------------------------------------
# Chantiers à compléter (avenant du 27/09/2026, spec §2.6)
# --------------------------------------------------------------------------


async def _creer_chantier(
    db_session: AsyncSession,
    *,
    nom: str = "Chantier Testeur",
    a_completer: bool = False,
    created_at: datetime | None = None,
) -> Chantier:
    chantier = Chantier(nom_canonique=nom, a_completer=a_completer)
    db_session.add(chantier)
    await db_session.flush()
    if created_at is not None:
        chantier.created_at = created_at
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def test_chantier_cree_auto_apparait_a_completer(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(
        db_session, nom="Villa Créée Auto", a_completer=True, created_at=_instant(0)
    )
    await _creer_document(
        db_session, numero="L500", chantier_id=chantier.id, statut="a_verifier"
    )
    await _creer_document(
        db_session, numero="L501", chantier_id=chantier.id, statut="recu"
    )
    # Une facture rattachée au même chantier ne compte pas comme un bon.
    await _creer_document(
        db_session, type_="facture", numero="F500", chantier_id=chantier.id
    )

    a_traiter = await lister_a_traiter(db_session)

    lignes = {c.id: c for c in a_traiter.chantiers_a_completer}
    assert chantier.id in lignes
    ligne = lignes[chantier.id]
    assert ligne.nom == "Villa Créée Auto"
    assert ligne.nb_bons == 2
    assert ligne.cree_le == chantier.created_at


async def test_chantier_non_a_completer_absent(db_session: AsyncSession) -> None:
    chantier = await _creer_chantier(db_session, a_completer=False)

    a_traiter = await lister_a_traiter(db_session)

    assert chantier.id not in {c.id for c in a_traiter.chantiers_a_completer}


async def test_chantier_a_completer_exclut_les_bons_archives(
    db_session: AsyncSession,
) -> None:
    """Fix round 1 : un bon archivé ne compte pas dans `nb_bons` -- même
    exclusion que partout ailleurs où un compte porte sur des documents
    (`ingest.bilan`, `corrections.archiver_document`)."""
    chantier = await _creer_chantier(
        db_session, nom="Villa Avec Archive", a_completer=True
    )
    await _creer_document(
        db_session, numero="L510", chantier_id=chantier.id, statut="a_verifier"
    )
    await _creer_document(
        db_session, numero="L511", chantier_id=chantier.id, statut="archive"
    )

    a_traiter = await lister_a_traiter(db_session)

    ligne = next(c for c in a_traiter.chantiers_a_completer if c.id == chantier.id)
    assert ligne.nb_bons == 1


# --------------------------------------------------------------------------
# Compte unique des problèmes « à régler » (revue finale de la refonte du
# front, constats LIENS-2, ECRAN-6, TELEPHONE-2, COUVERTURE-2)
# --------------------------------------------------------------------------


async def _creer_anomalie(
    db_session: AsyncSession,
    *,
    document: Document,
    regle: str,
    gravite: str,
    statut: str = "ouverte",
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        document_id=document.id,
        detail={"invente": "oui"},
        statut=statut,
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


async def test_compte_a_regler_vaut_la_liste_de_l_ecran(
    db_session: AsyncSession,
) -> None:
    """Le compte est exactement le nombre d'éléments de la liste « À
    régler » : anomalies ouvertes (tous mois) + documents à vérifier +
    chantiers à rattacher + articles à valider ; les urgents sont les
    anomalies ouvertes de gravité haute. Une anomalie traitée ou ignorée
    n'y entre plus."""
    fournisseur = await _creer_fournisseur(db_session)
    bon_recu = await _creer_document(db_session, statut="recu", numero="BL-INV-1")
    autre_bon = await _creer_document(db_session, statut="recu", numero="BL-INV-2")
    await _creer_anomalie(db_session, document=bon_recu, regle="R11", gravite="haute")
    await _creer_anomalie(db_session, document=bon_recu, regle="R15", gravite="basse")
    await _creer_anomalie(
        db_session, document=autre_bon, regle="R11", gravite="haute", statut="traitee"
    )
    await _creer_anomalie(
        db_session, document=autre_bon, regle="R15", gravite="haute", statut="ignoree"
    )
    await _creer_document(db_session, statut="a_verifier", numero="BL-INV-3")
    await _creer_alias(
        db_session, fournisseur=fournisseur, libelle_brut="chantier invente"
    )
    await _creer_article(db_session, fournisseur=fournisseur, ratio=Decimal("4"))

    compte = await compter_problemes_a_regler(db_session)

    ouvertes = await lister_anomalies(db_session, statut="ouverte", limite=10_000)
    a_traiter = await lister_a_traiter(db_session)
    assert compte.nb_problemes == (
        len(ouvertes)
        + len(a_traiter.documents)
        + len(a_traiter.alias)
        + len(a_traiter.articles)
        + len(a_traiter.chantiers_a_completer)
    )
    assert compte.nb_urgents == sum(1 for a in ouvertes if a.gravite == "haute")
    # Valeurs attendues du scénario (base vidée entre deux tests).
    assert compte.nb_problemes == 5
    assert compte.nb_urgents == 1


async def test_compte_a_regler_inclut_chantiers_a_completer(
    db_session: AsyncSession,
) -> None:
    """Un chantier créé automatiquement, encore à compléter, compte comme un
    problème « à régler » de plus (spec §2.6) -- même invariant que le test
    ci-dessus, isolé sur ce seul ajout."""
    await _creer_chantier(db_session, nom="Chantier À Compléter", a_completer=True)

    compte = await compter_problemes_a_regler(db_session)

    assert compte.nb_problemes == 1
    assert compte.nb_urgents == 0


async def test_compte_a_regler_vide(db_session: AsyncSession) -> None:
    compte = await compter_problemes_a_regler(db_session)

    assert compte.nb_problemes == 0
    assert compte.nb_urgents == 0
