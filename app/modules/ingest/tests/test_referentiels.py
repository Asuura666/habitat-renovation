"""Tests de `ingest/referentiels.py` (L3-T5) : chargement des référentiels
fournisseur/agence pour `normalize.fournisseur`, résolution d'un alias
chantier (`resoudre_chantier`, L3-D6/L3-D7), rattachement d'un article
(`rattacher_article`, L3-D9), lecture d'un paramètre décimal
(`lire_parametre_decimal`, L3-D4) et définition d'un fournisseur
(`definir_fournisseur`, journal d'audit — fix round 1 de la revue de cette
tâche).

Base de test réelle (`bl_test`), données entièrement inventées (R17).
`db_session` (fixture locale, `app/modules/ingest/tests/conftest.py`) vide
toutes les tables après chaque test : aucun nettoyage manuel nécessaire ici.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    AgenceFournisseur,
    Article,
    ChantierAlias,
    Fournisseur,
    Journal,
    Parametre,
)
from app.modules.ingest.referentiels import (
    ResolutionChantier,
    charger_agences,
    charger_fournisseurs,
    definir_fournisseur,
    lire_parametre_decimal,
    rattacher_article,
    resoudre_chantier,
)
from app.modules.normalize.article import PropositionArticle
from app.modules.normalize.fournisseur import AgenceRef, FournisseurRef

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_fournisseur(
    db_session: AsyncSession,
    *,
    nom: str = "Peintures Exemple",
    siret: str | None = None,
    tva: str | None = None,
    aliases: list[str] | None = None,
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom, siret=siret, tva=tva, aliases=aliases)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


# ---------------------------------------------------------------------------
# charger_fournisseurs / charger_agences
# ---------------------------------------------------------------------------


async def test_charger_fournisseurs_renvoie_le_referentiel_complet(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(
        db_session,
        nom="Peintures Exemple",
        siret="123456789012 34",
        tva="FR12345678901",
        aliases=["Peintures Ex."],
    )

    referentiel = await charger_fournisseurs(db_session)

    assert referentiel == [
        FournisseurRef(
            id=fournisseur.id,
            nom="Peintures Exemple",
            siret="123456789012 34",
            tva="FR12345678901",
            aliases=("Peintures Ex.",),
        )
    ]


async def test_charger_fournisseurs_alias_absent_devient_tuple_vide(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, aliases=None)

    referentiel = await charger_fournisseurs(db_session)

    assert referentiel == [
        FournisseurRef(
            id=fournisseur.id,
            nom="Peintures Exemple",
            siret=None,
            tva=None,
            aliases=(),
        )
    ]


async def test_charger_agences_filtre_par_fournisseur(
    db_session: AsyncSession,
) -> None:
    fournisseur_1 = await _creer_fournisseur(db_session, nom="Fournisseur Un")
    fournisseur_2 = await _creer_fournisseur(db_session, nom="Fournisseur Deux")
    agence_1 = AgenceFournisseur(fournisseur_id=fournisseur_1.id, nom="Agence Nord")
    agence_2 = AgenceFournisseur(fournisseur_id=fournisseur_2.id, nom="Agence Sud")
    db_session.add_all([agence_1, agence_2])
    await db_session.commit()
    await db_session.refresh(agence_1)

    agences = await charger_agences(db_session, fournisseur_1.id)

    assert agences == [AgenceRef(id=agence_1.id, nom="Agence Nord")]


# ---------------------------------------------------------------------------
# resoudre_chantier
# ---------------------------------------------------------------------------


async def test_resoudre_chantier_brut_vide_ne_cree_rien(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)

    resolution = await resoudre_chantier(db_session, fournisseur.id, None)

    assert resolution == ResolutionChantier(
        chantier_id=None, libelle=None, alias_id=None, demande_creee=False
    )
    nombre_alias = (await db_session.execute(select(ChantierAlias))).scalars().all()
    assert nombre_alias == []


async def test_resoudre_chantier_cree_une_demande_puis_la_retrouve_sans_doublon(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)

    premiere = await resoudre_chantier(db_session, fournisseur.id, "Maison Test")
    await db_session.commit()

    assert premiere.demande_creee is True
    assert premiere.chantier_id is None
    assert premiere.alias_id is not None
    assert premiere.libelle == "maison test"

    seconde = await resoudre_chantier(db_session, fournisseur.id, "Maison Test")
    await db_session.commit()

    assert seconde.demande_creee is False
    assert seconde.chantier_id is None
    assert seconde.alias_id == premiere.alias_id

    lignes = (await db_session.execute(select(ChantierAlias))).scalars().all()
    assert len(lignes) == 1


async def test_resoudre_chantier_deux_bruts_differents_meme_alias(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)

    premiere = await resoudre_chantier(db_session, fournisseur.id, "Maison Test")
    await db_session.commit()
    seconde = await resoudre_chantier(
        db_session, fournisseur.id, "MAISON TEST (99-002)"
    )
    await db_session.commit()

    assert premiere.libelle == seconde.libelle == "maison test"
    assert seconde.alias_id == premiere.alias_id
    assert seconde.demande_creee is False

    lignes = (await db_session.execute(select(ChantierAlias))).scalars().all()
    assert len(lignes) == 1


async def test_resoudre_chantier_alias_valide_renvoie_le_chantier(
    db_session: AsyncSession,
) -> None:
    from app.modules.ingest.models import Chantier

    fournisseur = await _creer_fournisseur(db_session)
    chantier = Chantier(nom_canonique="Maison Test (canonique)")
    db_session.add(chantier)
    await db_session.flush()

    premiere = await resoudre_chantier(db_session, fournisseur.id, "Maison Test")
    await db_session.commit()

    alias = await db_session.get(ChantierAlias, premiere.alias_id)
    assert alias is not None
    alias.chantier_id = chantier.id
    await db_session.commit()

    resolution = await resoudre_chantier(db_session, fournisseur.id, "Maison Test")

    assert resolution.chantier_id == chantier.id
    assert resolution.demande_creee is False


# ---------------------------------------------------------------------------
# rattacher_article
# ---------------------------------------------------------------------------


async def test_rattacher_article_proposition_none_renvoie_none(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)

    resultat = await rattacher_article(db_session, fournisseur.id, None)

    assert resultat is None


async def test_rattacher_article_cree_un_nouvel_article_non_valide(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    proposition = PropositionArticle(
        code="AB1234",
        libelle="Peinture blanche",
        unite_cdt="seau",
        unite_fact=None,
        ratio=None,
    )

    article_id = await rattacher_article(db_session, fournisseur.id, proposition)
    await db_session.commit()

    assert article_id is not None
    article = await db_session.get(Article, article_id)
    assert article is not None
    assert article.fournisseur_id == fournisseur.id
    assert article.code == "AB1234"
    assert article.libelle == "Peinture blanche"
    assert article.unite_cdt == "seau"
    assert article.valide is False


async def test_rattacher_article_complete_sans_ecraser(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    existant = Article(
        fournisseur_id=fournisseur.id,
        code="AB1234",
        libelle="Libellé déjà connu",
        unite_cdt=None,
        unite_fact=None,
        ratio=None,
        valide=False,
    )
    db_session.add(existant)
    await db_session.commit()
    await db_session.refresh(existant)

    proposition = PropositionArticle(
        code="AB1234",
        libelle="Nouveau libellé (ne doit pas remplacer)",
        unite_cdt="seau",
        unite_fact=None,
        ratio=Decimal("2.5"),
    )

    article_id = await rattacher_article(db_session, fournisseur.id, proposition)
    await db_session.commit()

    assert article_id == existant.id
    article = await db_session.get(Article, existant.id)
    assert article is not None
    # Champ déjà renseigné : jamais écrasé.
    assert article.libelle == "Libellé déjà connu"
    # Champs vides : complétés depuis la proposition.
    assert article.unite_cdt == "seau"
    assert article.ratio == Decimal("2.5")


async def test_rattacher_article_valide_reste_inchange(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    existant = Article(
        fournisseur_id=fournisseur.id,
        code="AB1234",
        libelle="Libellé validé",
        unite_cdt=None,
        unite_fact=None,
        ratio=None,
        valide=True,
    )
    db_session.add(existant)
    await db_session.commit()
    await db_session.refresh(existant)

    proposition = PropositionArticle(
        code="AB1234",
        libelle="Ne doit jamais apparaître",
        unite_cdt="seau",
        unite_fact=None,
        ratio=Decimal("9.9"),
    )

    article_id = await rattacher_article(db_session, fournisseur.id, proposition)
    await db_session.commit()

    assert article_id == existant.id
    article = await db_session.get(Article, existant.id)
    assert article is not None
    assert article.libelle == "Libellé validé"
    assert article.unite_cdt is None
    assert article.ratio is None
    assert article.valide is True


# ---------------------------------------------------------------------------
# lire_parametre_decimal
# ---------------------------------------------------------------------------


async def test_lire_parametre_decimal_absent_renvoie_le_defaut(
    db_session: AsyncSession,
) -> None:
    valeur = await lire_parametre_decimal(
        db_session, "cle_inventee_absente", Decimal("0.80")
    )

    assert valeur == Decimal("0.80")


async def test_lire_parametre_decimal_present_renvoie_la_valeur(
    db_session: AsyncSession,
) -> None:
    db_session.add(Parametre(cle="seuil_invente", valeur="0.95"))
    await db_session.commit()

    valeur = await lire_parametre_decimal(db_session, "seuil_invente", Decimal("0.80"))

    assert valeur == Decimal("0.95")


async def test_lire_parametre_decimal_non_convertible_renvoie_le_defaut(
    db_session: AsyncSession,
) -> None:
    db_session.add(Parametre(cle="seuil_invalide", valeur="pas-un-nombre"))
    await db_session.commit()

    valeur = await lire_parametre_decimal(db_session, "seuil_invalide", Decimal("0.80"))

    assert valeur == Decimal("0.80")


# ---------------------------------------------------------------------------
# definir_fournisseur — journal d'audit (fix round 1)
# ---------------------------------------------------------------------------


async def _journal_pour_fournisseur(
    db_session: AsyncSession, fournisseur_id: uuid.UUID
) -> Journal:
    """La seule ligne `journal` `fournisseur_defini` ciblant `fournisseur_id`
    (erreur si aucune ou plusieurs, même mécanique que `_journal_pour` dans
    `app/core/tests/test_auth.py`)."""
    return (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(fournisseur_id),
                Journal.action == "fournisseur_defini",
            )
        )
    ).scalar_one()


async def test_definir_fournisseur_creation_journal_avant_none(
    db_session: AsyncSession,
) -> None:
    resultat = await definir_fournisseur(
        db_session,
        nom="Peintures Journal Création",
        siret="123456789",
        tva=None,
        alias=["Alias Journal"],
        agence=["Agence Journal"],
    )
    await db_session.commit()

    assert resultat.cree is True
    fournisseur = (
        await db_session.execute(
            select(Fournisseur).where(Fournisseur.nom == "Peintures Journal Création")
        )
    ).scalar_one()

    journal = await _journal_pour_fournisseur(db_session, fournisseur.id)
    assert journal.utilisateur_id is None
    assert journal.cible_table == "fournisseur"
    assert journal.avant is None
    assert journal.apres is not None
    assert journal.apres["nom"] == "Peintures Journal Création"
    assert journal.apres["siret"] == "123456789"
    assert journal.apres["tva"] is None
    assert journal.apres["aliases"] == ["Alias Journal"]
    assert journal.apres["agences_ajoutees"] == ["Agence Journal"]


async def test_definir_fournisseur_mise_a_jour_journal_avant_apres(
    db_session: AsyncSession,
) -> None:
    await definir_fournisseur(
        db_session,
        nom="Peintures Journal Mise À Jour",
        siret="111111111",
        tva=None,
        alias=["Alias Un"],
        agence=["Agence Nord"],
    )
    await db_session.commit()
    fournisseur = (
        await db_session.execute(
            select(Fournisseur).where(
                Fournisseur.nom == "Peintures Journal Mise À Jour"
            )
        )
    ).scalar_one()

    # Une seule ligne journal pour l'instant (la création ci-dessus) :
    # `_journal_pour_fournisseur` échouerait s'il y en avait déjà plusieurs.
    # Son `id` sert ensuite à distinguer la ligne de la mise à jour, la
    # seconde, après le second appel ci-dessous.
    journal_creation = await _journal_pour_fournisseur(db_session, fournisseur.id)

    resultat = await definir_fournisseur(
        db_session,
        nom="peintures journal mise à jour",  # casse différente
        siret=None,  # non fourni : conservé
        tva="FR99999999999",  # fourni : remplacé
        alias=["alias un"],  # doublon (normalisé) : ignoré
        agence=["Agence Sud"],  # nouvelle agence
    )
    await db_session.commit()

    assert resultat.cree is False

    journaux = (
        (
            await db_session.execute(
                select(Journal)
                .where(
                    Journal.cible_id == str(fournisseur.id),
                    Journal.action == "fournisseur_defini",
                )
                .order_by(Journal.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(journaux) == 2
    journal_mise_a_jour = journaux[1]
    assert journal_mise_a_jour.id != journal_creation.id
    assert journal_mise_a_jour.utilisateur_id is None
    assert journal_mise_a_jour.avant == {
        "siret": "111111111",
        "tva": None,
        "aliases": ["Alias Un"],
    }
    assert journal_mise_a_jour.apres is not None
    assert journal_mise_a_jour.apres["siret"] == "111111111"  # non fourni, conservé
    assert journal_mise_a_jour.apres["tva"] == "FR99999999999"
    assert journal_mise_a_jour.apres["aliases"] == ["Alias Un"]  # doublon non ajouté
    assert journal_mise_a_jour.apres["agences_ajoutees"] == ["Agence Sud"]
