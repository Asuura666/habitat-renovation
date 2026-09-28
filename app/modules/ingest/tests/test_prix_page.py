"""Tests de la page « Prix à vérifier » (phase 3, tâche P8) :
`ingest.prix_bl.lister_alertes_prix`, `valider_prix`, `contester_prix`,
`ignorer_prix`, `recontroler_depuis_page` -- spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §8. Base de test réelle
(`bl_test`), données entièrement inventées.

Trois volets :
- `lister_alertes_prix` : regroupement par produit (plusieurs bons, prix
  différents), tri, filtre « aujourd'hui »/fournisseur, masquage.
- `valider_prix` : nouvelle ligne de grille, alertes au même prix réglées,
  autres bons recontrôlés, produit absent ajouté à la grille, 409.
- `contester_prix`/`ignorer_prix` : commentaire obligatoire ou non, grille
  inchangée, 409 ; `recontroler_depuis_page`."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.anomalies import lister_anomalies
from app.modules.ingest.grilles import prix_en_vigueur
from app.modules.ingest.models import (
    Anomalie,
    Document,
    Fournisseur,
    GrillePrix,
    Journal,
    Ligne,
    Utilisateur,
)
from app.modules.ingest.parametres import modifier_parametre
from app.modules.ingest.prix_bl import (
    AlertesInvalides,
    contester_prix,
    controler_prix_bl,
    ignorer_prix,
    lister_alertes_prix,
    recontroler_depuis_page,
    valider_prix,
)
from app.modules.normalize.prix import cle_produit, prix_net

pytestmark = [pytest.mark.anyio, pytest.mark.db]


# --------------------------------------------------------------------------
# Aides de construction (données inventées, mêmes conventions que
# `test_prix_bl.py`).
# --------------------------------------------------------------------------


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"Fournisseur page prix {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_utilisateur(db_session: AsyncSession) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"admin.page-prix.{uuid.uuid4()}@example.invalid",
        role="admin",
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_bl(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    date_doc: date = date(2026, 6, 1),
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=f"L-{uuid.uuid4()}",
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    code_brut: str | None = "REF1",
    article_brut: str = "Produit inventé",
    pu_ht: Decimal = Decimal("10.00"),
    unite_brut: str | None = None,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut=code_brut,
        article_brut=article_brut,
        pu_ht=pu_ht,
        unite_brut=unite_brut,
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_prix_grille(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    reference: str | None = "REF1",
    designation: str = "Produit inventé",
    prix_ht: str = "10.00",
    unite: str | None = None,
    date_effet: date = date(2026, 1, 1),
) -> GrillePrix:
    ligne = GrillePrix(
        fournisseur_id=fournisseur.id,
        cle_produit=cle_produit(reference, designation),
        reference=reference,
        designation=designation,
        unite_brut=unite,
        unite=unite,
        prix_ht=Decimal(prix_ht),
        prix_net=prix_net(Decimal(prix_ht), None),
        date_effet=date_effet,
        source="saisie",
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _activer_controle(db_session: AsyncSession) -> None:
    await modifier_parametre(db_session, "prix_controle_bl_actif", "1", auteur_id=None)


async def _controler(db_session: AsyncSession, document_id: uuid.UUID) -> None:
    await controler_prix_bl(db_session, document_id)
    await db_session.commit()


async def _anomalies_ouvertes_du_bon(
    db_session: AsyncSession, document_id: uuid.UUID
) -> list[Anomalie]:
    resultat = await db_session.execute(
        select(Anomalie).where(
            Anomalie.document_id == document_id, Anomalie.statut == "ouverte"
        )
    )
    return list(resultat.scalars().all())


async def _dernier_journal(db_session: AsyncSession, action: str) -> Journal | None:
    resultat = await db_session.execute(
        select(Journal)
        .where(Journal.action == action)
        .order_by(Journal.horodatage.desc())
    )
    return resultat.scalars().first()


# --------------------------------------------------------------------------
# Regroupement (spec §8.1).
# --------------------------------------------------------------------------


async def test_regroupement_meme_produit_plusieurs_bons_prix_differents(
    db_session: AsyncSession,
) -> None:
    """Trois bons du même produit, deux prix distincts -> une seule
    rangée : compteurs, champs pris sur le bon le plus récent."""
    await _activer_controle(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")

    bon1 = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 1)
    )
    await _creer_ligne(db_session, document=bon1, pu_ht=Decimal("15.00"))
    bon2 = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 5)
    )
    await _creer_ligne(db_session, document=bon2, pu_ht=Decimal("15.00"))
    bon3 = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 10)
    )
    ligne3 = await _creer_ligne(db_session, document=bon3, pu_ht=Decimal("20.00"))

    for bon in (bon1, bon2, bon3):
        await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)

    assert len(produits) == 1
    produit = produits[0]
    assert produit.nb_bons == 3
    assert produit.nb_prix_differents == 2
    assert produit.prix_bon == Decimal("20.00")
    assert produit.date_bon == date(2026, 6, 10)
    assert produit.document_id == bon3.id
    assert produit.ligne_id == ligne3.id
    assert "R19" in produit.regles
    assert produit.prix_grille == Decimal("10.0000")
    assert len(produit.anomalie_ids) == 3


async def test_produits_sans_grille_regroupes_par_ligne_du_bon(
    db_session: AsyncSession,
) -> None:
    """Sans grille du tout : R22 (« absent de la grille »), regroupement
    sur la clé calculée sur la ligne du bon (spec §4.1)."""
    await _activer_controle(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(
        db_session, document=bon, code_brut=None, article_brut="Produit fantome"
    )

    await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)
    assert len(produits) == 1
    assert produits[0].regles == ("R22",)
    assert produits[0].prix_grille is None


async def test_tri_gravite_puis_ecart(db_session: AsyncSession) -> None:
    """Gravité haute (R19) avant gravité basse (R21 seul) -- deux produits
    distincts."""
    await _activer_controle(db_session)
    fournisseur = await _creer_fournisseur(db_session)

    await _creer_prix_grille(
        db_session, fournisseur=fournisseur, reference="REF-HAUSSE", prix_ht="10.00"
    )
    bon_hausse = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(
        db_session, document=bon_hausse, code_brut="REF-HAUSSE", pu_ht=Decimal("20.00")
    )

    await _creer_prix_grille(
        db_session, fournisseur=fournisseur, reference="REF-BAISSE", prix_ht="10.00"
    )
    bon_baisse = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(
        db_session, document=bon_baisse, code_brut="REF-BAISSE", pu_ht=Decimal("5.00")
    )

    for bon in (bon_hausse, bon_baisse):
        await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)

    assert len(produits) == 2
    assert produits[0].regles == ("R19",)
    assert produits[1].regles == ("R21",)


async def test_filtre_periode_jour_et_fournisseur(db_session: AsyncSession) -> None:
    await _activer_controle(db_session)
    fournisseur_a = await _creer_fournisseur(db_session)
    fournisseur_b = await _creer_fournisseur(db_session)

    await _creer_prix_grille(db_session, fournisseur=fournisseur_a, prix_ht="10.00")
    bon_a = await _creer_bl(db_session, fournisseur=fournisseur_a)
    await _creer_ligne(db_session, document=bon_a, pu_ht=Decimal("15.00"))
    await _controler(db_session, bon_a.id)

    await _creer_prix_grille(db_session, fournisseur=fournisseur_b, prix_ht="10.00")
    bon_b = await _creer_bl(db_session, fournisseur=fournisseur_b)
    await _creer_ligne(db_session, document=bon_b, pu_ht=Decimal("15.00"))
    await _controler(db_session, bon_b.id)

    # Toutes deux créées aujourd'hui : `periode="jour"` ne filtre rien ici,
    # `periode="tout"` (défaut) non plus -- seul le filtre fournisseur doit
    # isoler la première.
    produits_jour = await lister_alertes_prix(db_session, periode="jour")
    assert len(produits_jour) == 2

    resultat = await db_session.execute(
        select(Anomalie).where(Anomalie.document_id == bon_b.id)
    )
    for anomalie in resultat.scalars().all():
        anomalie.created_at = datetime(2020, 1, 1, tzinfo=FUSEAU_PARIS)
    await db_session.commit()

    produits_jour_apres = await lister_alertes_prix(db_session, periode="jour")
    assert len(produits_jour_apres) == 1
    assert produits_jour_apres[0].fournisseur_id == fournisseur_a.id

    produits_fournisseur_a = await lister_alertes_prix(
        db_session, fournisseur_id=fournisseur_a.id
    )
    assert len(produits_fournisseur_a) == 1
    assert produits_fournisseur_a[0].fournisseur_id == fournisseur_a.id


async def test_alerte_masquee_absente_de_la_liste(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, code_brut=None)

    await _activer_controle(db_session)
    await _controler(db_session, bon.id)
    assert len(await lister_alertes_prix(db_session)) == 1

    await modifier_parametre(db_session, "prix_controle_bl_actif", "0", auteur_id=None)
    assert await lister_alertes_prix(db_session) == ()


# --------------------------------------------------------------------------
# valider_prix (spec §8.2).
# --------------------------------------------------------------------------


async def test_valider_prix_ajoute_une_ligne_de_grille_et_regle_les_alertes(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")

    bon_ancien = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 1)
    )
    await _creer_ligne(db_session, document=bon_ancien, pu_ht=Decimal("15.00"))
    bon_recent = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 10)
    )
    ligne_recente = await _creer_ligne(
        db_session, document=bon_recent, pu_ht=Decimal("18.00")
    )

    for bon in (bon_ancien, bon_recent):
        await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)
    assert len(produits) == 1
    produit = produits[0]
    assert produit.ligne_id == ligne_recente.id

    resultat = await valider_prix(
        db_session,
        anomalie_ids=list(produit.anomalie_ids),
        ligne_id=ligne_recente.id,
        auteur_id=utilisateur.id,
    )

    assert resultat.prix_net == Decimal("18.0000")
    assert resultat.date_effet == date(2026, 6, 10)
    assert resultat.nb_alertes_reglees == 1

    vigueur = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 6, 10))
    cle = cle_produit("REF1", "Produit inventé")
    assert vigueur[cle].prix_net == Decimal("18.0000")

    # L'alerte du bon récent (même prix) est réglée...
    anomalies_recent = await _anomalies_ouvertes_du_bon(db_session, bon_recent.id)
    assert anomalies_recent == []
    # ... celle du bon ancien (prix différent) reste ouverte après recontrôle
    # (toujours plus cher que la nouvelle grille, 18,00 €).
    anomalies_ancien = await _anomalies_ouvertes_du_bon(db_session, bon_ancien.id)
    assert len(anomalies_ancien) == 1

    journal_valide = await _dernier_journal(db_session, "prix_valide")
    assert journal_valide is not None
    assert journal_valide.apres is not None
    assert journal_valide.apres["nb_alertes_reglees"] == 1

    anomalies_toutes = await lister_anomalies(db_session, statut="traitee")
    reglees = [a for a in anomalies_toutes if a.document_id == bon_recent.id]
    assert len(reglees) == 1
    assert reglees[0].commentaire is not None
    assert "18,00 €" in reglees[0].commentaire
    assert "grille mise à jour" in reglees[0].commentaire


async def test_valider_prix_produit_absent_de_la_grille_est_ajoute(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 1)
    )
    ligne = await _creer_ligne(
        db_session,
        document=bon,
        code_brut=None,
        article_brut="Produit nouveau",
        pu_ht=Decimal("12.34"),
        unite_brut="sac",
    )
    await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)
    assert len(produits) == 1
    assert produits[0].regles == ("R22",)

    resultat = await valider_prix(
        db_session,
        anomalie_ids=list(produits[0].anomalie_ids),
        ligne_id=ligne.id,
        auteur_id=utilisateur.id,
    )
    assert resultat.nb_alertes_reglees == 1

    vigueur = await prix_en_vigueur(db_session, fournisseur.id, date(2026, 6, 1))
    cle = cle_produit(None, "Produit nouveau")
    assert cle in vigueur
    assert vigueur[cle].prix_net == Decimal("12.3400")
    assert vigueur[cle].unite == "sac"


async def test_valider_prix_409_si_alerte_deja_reglee(db_session: AsyncSession) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=bon, pu_ht=Decimal("15.00"))
    await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)
    anomalie_id = produits[0].anomalie_ids[0]

    await ignorer_prix(
        db_session,
        anomalie_ids=[anomalie_id],
        commentaire=None,
        auteur_id=utilisateur.id,
    )

    with pytest.raises(AlertesInvalides):
        await valider_prix(
            db_session,
            anomalie_ids=[anomalie_id],
            ligne_id=ligne.id,
            auteur_id=utilisateur.id,
        )

    # Rien n'a été modifié par la tentative refusée : toujours une seule
    # ligne de grille (`source="saisie"`, celle de départ) pour ce produit.
    resultat = await db_session.execute(
        select(GrillePrix).where(GrillePrix.fournisseur_id == fournisseur.id)
    )
    assert len(resultat.scalars().all()) == 1


async def test_valider_prix_409_si_produits_differents(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)

    await _creer_prix_grille(
        db_session, fournisseur=fournisseur, reference="REF-A", prix_ht="10.00"
    )
    bon_a = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne_a = await _creer_ligne(
        db_session, document=bon_a, code_brut="REF-A", pu_ht=Decimal("15.00")
    )
    await _controler(db_session, bon_a.id)

    await _creer_prix_grille(
        db_session, fournisseur=fournisseur, reference="REF-B", prix_ht="10.00"
    )
    bon_b = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(
        db_session, document=bon_b, code_brut="REF-B", pu_ht=Decimal("15.00")
    )
    await _controler(db_session, bon_b.id)

    produits = await lister_alertes_prix(db_session)
    assert len(produits) == 2
    tous_les_ids = [i for p in produits for i in p.anomalie_ids]

    with pytest.raises(AlertesInvalides):
        await valider_prix(
            db_session,
            anomalie_ids=tous_les_ids,
            ligne_id=ligne_a.id,
            auteur_id=utilisateur.id,
        )


# --------------------------------------------------------------------------
# contester_prix / ignorer_prix (spec §8.2).
# --------------------------------------------------------------------------


async def test_contester_prix_sans_commentaire_leve_value_error(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, code_brut=None)
    await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)

    with pytest.raises(ValueError):
        await contester_prix(
            db_session,
            anomalie_ids=list(produits[0].anomalie_ids),
            commentaire="   ",
            auteur_id=utilisateur.id,
        )


async def test_contester_prix_ferme_les_alertes_sans_toucher_la_grille(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, pu_ht=Decimal("15.00"))
    await _controler(db_session, bon.id)

    produits = await lister_alertes_prix(db_session)

    nb = await contester_prix(
        db_session,
        anomalie_ids=list(produits[0].anomalie_ids),
        commentaire="Prix confirmé par le fournisseur au téléphone",
        auteur_id=utilisateur.id,
    )

    assert nb == 1
    assert await _anomalies_ouvertes_du_bon(db_session, bon.id) == []

    resultat = await db_session.execute(
        select(GrillePrix).where(GrillePrix.fournisseur_id == fournisseur.id)
    )
    assert len(resultat.scalars().all()) == 1  # jamais une seconde ligne

    journal = await _dernier_journal(db_session, "prix_conteste")
    assert journal is not None

    anomalies = await lister_anomalies(db_session, statut="traitee")
    contestees = [a for a in anomalies if a.document_id == bon.id]
    assert len(contestees) == 1
    assert contestees[0].commentaire == (
        "Contesté : Prix confirmé par le fournisseur au téléphone"
    )


async def test_contester_prix_409_alerte_deja_traitee(db_session: AsyncSession) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, code_brut=None)
    await _controler(db_session, bon.id)
    produits = await lister_alertes_prix(db_session)
    anomalie_id = produits[0].anomalie_ids[0]

    await ignorer_prix(
        db_session,
        anomalie_ids=[anomalie_id],
        commentaire=None,
        auteur_id=utilisateur.id,
    )

    with pytest.raises(AlertesInvalides):
        await contester_prix(
            db_session,
            anomalie_ids=[anomalie_id],
            commentaire="peu importe",
            auteur_id=utilisateur.id,
        )


async def test_ignorer_prix_sans_commentaire_utilise_le_texte_par_defaut(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, code_brut=None)
    await _controler(db_session, bon.id)
    produits = await lister_alertes_prix(db_session)

    nb = await ignorer_prix(
        db_session,
        anomalie_ids=list(produits[0].anomalie_ids),
        commentaire=None,
        auteur_id=utilisateur.id,
    )

    assert nb == 1
    anomalies = await lister_anomalies(db_session, statut="ignoree")
    ignorees = [a for a in anomalies if a.document_id == bon.id]
    assert len(ignorees) == 1
    assert ignorees[0].commentaire == "Ignoré depuis la page Prix"

    journal = await _dernier_journal(db_session, "prix_ignore")
    assert journal is not None


async def test_ignorer_prix_avec_commentaire(db_session: AsyncSession) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, code_brut=None)
    await _controler(db_session, bon.id)
    produits = await lister_alertes_prix(db_session)

    await ignorer_prix(
        db_session,
        anomalie_ids=list(produits[0].anomalie_ids),
        commentaire="Produit ponctuel, sans suite",
        auteur_id=utilisateur.id,
    )

    anomalies = await lister_anomalies(db_session, statut="ignoree")
    ignorees = [a for a in anomalies if a.document_id == bon.id]
    assert ignorees[0].commentaire == "Produit ponctuel, sans suite"


async def test_ignorer_prix_commentaire_trop_long_leve_value_error(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=bon, code_brut=None)
    await _controler(db_session, bon.id)
    produits = await lister_alertes_prix(db_session)

    with pytest.raises(ValueError):
        await ignorer_prix(
            db_session,
            anomalie_ids=list(produits[0].anomalie_ids),
            commentaire="x" * 501,
            auteur_id=utilisateur.id,
        )


async def test_charger_groupe_alerte_introuvable(db_session: AsyncSession) -> None:
    utilisateur = await _creer_utilisateur(db_session)
    with pytest.raises(AlertesInvalides):
        await contester_prix(
            db_session,
            anomalie_ids=[uuid.uuid4()],
            commentaire="peu importe",
            auteur_id=utilisateur.id,
        )


# --------------------------------------------------------------------------
# recontroler_depuis_page (spec §8.2, §6.2).
# --------------------------------------------------------------------------


async def test_recontroler_depuis_page_journalise_et_recalcule(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    bon = await _creer_bl(
        db_session,
        fournisseur=fournisseur,
        date_doc=datetime.now(FUSEAU_PARIS).date(),
    )
    await _creer_ligne(db_session, document=bon, pu_ht=Decimal("15.00"))

    resultat = await recontroler_depuis_page(db_session, auteur_id=utilisateur.id)

    assert resultat.nb_bons >= 1
    assert resultat.nb_alertes_ouvertes >= 1

    journal = await _dernier_journal(db_session, "prix_recontrole")
    assert journal is not None
    assert journal.apres is not None
    assert journal.apres["nb_bons"] == resultat.nb_bons
