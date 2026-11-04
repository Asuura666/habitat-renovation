"""Lecture et modification des seuils métier administrables (L5-T10).

Ce module est l'unique source des clés, de leurs valeurs par défaut et de
leurs bornes. Les couches API et web ne portent aucune validation métier.

Masquage des réglages d'un contrôle désactivé (24/09/2026, en écho à la
décision d'Ilane sur les contrôles de prix et R06, `docs/dette.md`) : quand
un contrôle est désactivé côté serveur (`ingest.commun.controle_prix_actif`/
`controle_livre_non_facture_actif`), ses réglages propres n'apparaissent
plus du tout dans `lister_parametres`, et `modifier_parametre` les refuse
comme une clé inconnue -- ce module est le **seul** endroit qui porte la
correspondance réglage -> contrôle (`_cle_masquee`), jamais dupliquée côté
API ni côté front. Rien n'est supprimé en base : `_assurer_parametres`
continue d'amorcer toutes les lignes, et une valeur modifiée avant
désactivation reste lue telle quelle dès la réactivation du contrôle (voir
les tests dédiés).

Phase 3 (contrôle des prix des bons, §3.4 de
`docs/superpowers/specs/2026-09-27-prix-design.md`) : douze clés `prix_…`
ajoutées à la fin de `DEFINITIONS_PARAMETRES`, toujours visibles (aucun
masquage -- il faut pouvoir tout préparer avant d'allumer l'interrupteur
général `prix_controle_bl_actif`, lui-même toujours visible). `interrupteur`
et `groupe`, ajoutés à `DefinitionParametre`/`ParametreAffiche`, ne
changent aucune définition existante (défauts `False`/`""`, soit le
comportement actuel : un nombre, section générale)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.commun import (
    controle_livre_non_facture_actif,
    controle_prix_actif,
)
from app.modules.ingest.models import Journal, Parametre


@dataclass(frozen=True)
class DefinitionParametre:
    cle: str
    libelle: str
    unite: str
    defaut: Decimal
    minimum: Decimal
    maximum: Decimal
    entier: bool = False
    # Champs du contrôle des prix des bons (phase 3, §3.4 de
    # `docs/superpowers/specs/2026-09-27-prix-design.md`), ajoutés à la fin :
    # aucune définition existante ne change. `interrupteur` affiche « Oui /
    # Non » côté écran au lieu d'un nombre (bornes 0-1, entier) ; `groupe`
    # ("" par défaut, soit la section générale actuelle) titre la section de
    # l'écran Réglages qui régit ce paramètre.
    interrupteur: bool = False
    groupe: str = ""


@dataclass(frozen=True)
class ParametreAffiche:
    cle: str
    valeur: str
    libelle: str
    unite: str
    minimum: str
    maximum: str
    entier: bool
    interrupteur: bool = False
    groupe: str = ""


DEFINITIONS_PARAMETRES: tuple[DefinitionParametre, ...] = (
    DefinitionParametre(
        "tolerance_total_ht",
        "Tolérance sur le total HT",
        "€",
        Decimal("0.05"),
        Decimal("0"),
        Decimal("1000"),
    ),
    DefinitionParametre(
        "seuil_prix_pct",
        "Écart de prix",
        "%",
        Decimal("5"),
        Decimal("0"),
        Decimal("100"),
    ),
    DefinitionParametre(
        "seuil_prix_fort_pct",
        "Écart de prix important",
        "%",
        Decimal("15"),
        Decimal("0"),
        Decimal("1000"),
    ),
    DefinitionParametre(
        "occurrences_prix_min",
        "Nombre minimum de factures pour établir le prix habituel",
        "factures",
        Decimal("3"),
        Decimal("1"),
        Decimal("100"),
        True,
    ),
    DefinitionParametre(
        "delai_ligne_bl_non_facturee_j",
        "Délai avant alerte d'une ligne de BL non facturée",
        "jours",
        Decimal("45"),
        Decimal("1"),
        Decimal("3650"),
        True,
    ),
    DefinitionParametre(
        "delai_alias_non_resolu_h",
        "Délai avant alerte d'un chantier non reconnu",
        "heures",
        Decimal("48"),
        Decimal("1"),
        Decimal("8760"),
        True,
    ),
    DefinitionParametre(
        "seuil_ressemblance_chantier_pct",
        "Ressemblance minimale d'un nom de chantier",
        "%",
        Decimal("80"),
        Decimal("50"),
        Decimal("100"),
        True,
    ),
    DefinitionParametre(
        "delai_confirmation_bl_h",
        "Délai de confirmation d'un BL",
        "heures",
        Decimal("24"),
        Decimal("1"),
        Decimal("8760"),
        True,
    ),
    DefinitionParametre(
        "delai_chantier_silencieux_j",
        "Délai d'inactivité d'un chantier",
        "jours",
        Decimal("7"),
        Decimal("1"),
        Decimal("3650"),
        True,
    ),
    DefinitionParametre(
        "duree_ignorance_j",
        "Durée pendant laquelle un problème ignoré reste masqué",
        "jours",
        Decimal("90"),
        Decimal("1"),
        Decimal("3650"),
        True,
    ),
    # Contrôle des prix des bons (phase 3, §3.4 de la conception) : douze
    # réglages ajoutés à la fin, groupés à l'écran sous « Contrôle des prix
    # des bons ». Interrupteur général éteint par défaut (`prix_controle
    # _bl_actif`) : rien de ce contrôle ne s'affiche avant sa mise en
    # service ; les sept alertes et les quatre seuils restent toujours
    # visibles (spec §3.4) pour pouvoir tout préparer avant de l'allumer.
    DefinitionParametre(
        "prix_controle_bl_actif",
        "Contrôler les prix des bons",
        "",
        Decimal("0"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_plus_cher_grille",
        "Alerter : plus cher que la grille",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_plus_cher_dernier_prix",
        "Alerter : plus cher que la dernière fois",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_moins_cher_grille",
        "Alerter : moins cher que la grille",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_absent_grille",
        "Alerter : produit absent de la grille",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_reconnu_par_nom",
        "Alerter : produit reconnu seulement par son nom",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_unites_differentes",
        "Alerter : unités différentes",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_alerte_grille_ancienne",
        "Alerter : grille ancienne",
        "",
        Decimal("1"),
        Decimal("0"),
        Decimal("1"),
        True,
        True,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_seuil_hausse_pct",
        "Hausse tolérée avant alerte",
        "%",
        Decimal("0"),
        Decimal("0"),
        Decimal("100"),
        False,
        False,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_seuil_baisse_pct",
        "Baisse tolérée avant alerte",
        "%",
        Decimal("5"),
        Decimal("0"),
        Decimal("100"),
        False,
        False,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_age_grille_mois",
        "Âge à partir duquel une grille est ancienne",
        "mois",
        Decimal("12"),
        Decimal("1"),
        Decimal("60"),
        True,
        False,
        "Contrôle des prix des bons",
    ),
    DefinitionParametre(
        "prix_seuil_ressemblance_produit_pct",
        "Ressemblance minimale pour reconnaître un produit par son nom",
        "%",
        Decimal("80"),
        Decimal("50"),
        Decimal("100"),
        True,
        False,
        "Contrôle des prix des bons",
    ),
)

# Clé du seuil de ressemblance minimale d'un nom de chantier (avenant du
# 27/09/2026, rattachement automatique des chantiers) : nommée ici plutôt
# que recopiée en texte libre par les modules qui la liront (`normalize
# .chantier`, tâches suivantes du même plan), même idiome que les `CLE_*`
# définis au plus près de leur usage ailleurs dans `ingest` (`anomalies.py`,
# `extraction_bl.py`, `referentiels_vue.py`) -- placée ici, seul module qui
# connaît les dix clés.
CLE_SEUIL_RESSEMBLANCE_CHANTIER = "seuil_ressemblance_chantier_pct"

DEFINITIONS_PAR_CLE = {
    definition.cle: definition for definition in DEFINITIONS_PARAMETRES
}
PARAMETRES_DEFAUT = tuple(
    (definition.cle, definition.defaut) for definition in DEFINITIONS_PARAMETRES
)
_CLES_SEUILS_PRIX = ("seuil_prix_fort_pct", "seuil_prix_pct")
_DECIMALES_MAX = 6

# Réglages propres aux contrôles de prix (R07/R08/R09) ou à la remise (R09
# réutilise `occurrences_prix_min`, aucun seuil ne lui est propre) : masqués
# quand `controle_prix_actif()` est faux.
_CLES_CONTROLE_PRIX: frozenset[str] = frozenset(
    {"seuil_prix_pct", "seuil_prix_fort_pct", "occurrences_prix_min"}
)

# Réglage propre à R06 (« Livré mais pas facturé ») : masqué quand
# `controle_livre_non_facture_actif()` est faux.
_CLES_CONTROLE_LIVRE_NON_FACTURE: frozenset[str] = frozenset(
    {"delai_ligne_bl_non_facturee_j"}
)


# Réglage propre à R15 (retirée pour de bon, 31/10/2026) : toujours masqué.
_CLES_REGLES_RETIREES: frozenset[str] = frozenset({"delai_confirmation_bl_h"})


def _cle_masquee(cle: str) -> bool:
    """Vrai si `cle` appartient à un contrôle désactivé côté serveur --
    unique point de correspondance réglage -> contrôle (voir docstring de
    module). Les deux drapeaux sont indépendants, comme dans
    `ingest.commun.regles_desactivees`."""
    if cle in _CLES_REGLES_RETIREES:
        return True
    if cle in _CLES_CONTROLE_PRIX and not controle_prix_actif():
        return True
    return (
        cle in _CLES_CONTROLE_LIVRE_NON_FACTURE
        and not controle_livre_non_facture_actif()
    )


def _texte_decimal(valeur: Decimal) -> str:
    texte = format(valeur, "f")
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return texte or "0"


async def _assurer_parametres(session: AsyncSession) -> None:
    for definition in DEFINITIONS_PARAMETRES:
        await session.execute(
            insert(Parametre)
            .values(cle=definition.cle, valeur=_texte_decimal(definition.defaut))
            .on_conflict_do_nothing(index_elements=[Parametre.cle])
        )


async def lister_parametres(session: AsyncSession) -> list[ParametreAffiche]:
    """Liste les seuils connus dans l'ordre de présentation, à l'exclusion
    de ceux dont le contrôle est désactivé côté serveur (`_cle_masquee`) --
    dix quand les deux contrôles sont actifs, moins sinon. Les lignes
    masquées restent amorcées en base par `_assurer_parametres` : leur
    valeur est conservée et réapparaît dès la réactivation du contrôle."""

    await _assurer_parametres(session)
    lignes = {
        parametre.cle: parametre
        for parametre in (await session.execute(select(Parametre))).scalars()
    }
    return [
        ParametreAffiche(
            cle=definition.cle,
            valeur=lignes[definition.cle].valeur,
            libelle=definition.libelle,
            unite=definition.unite,
            minimum=_texte_decimal(definition.minimum),
            maximum=_texte_decimal(definition.maximum),
            entier=definition.entier,
            interrupteur=definition.interrupteur,
            groupe=definition.groupe,
        )
        for definition in DEFINITIONS_PARAMETRES
        if not _cle_masquee(definition.cle)
    ]


async def modifier_parametre(
    session: AsyncSession,
    cle: str,
    valeur: str,
    *,
    auteur_id: uuid.UUID | None,
) -> ParametreAffiche:
    """Valide, modifie et journalise un des seuils connus. Une clé dont le
    contrôle est désactivé côté serveur (`_cle_masquee`) est refusée
    exactement comme une clé inconnue -- jamais un message distinct, elle
    n'existe pas plus qu'une clé qui n'a jamais existé pour cet appelant."""

    definition = DEFINITIONS_PAR_CLE.get(cle)
    if definition is None or _cle_masquee(cle):
        raise ValueError(f"Paramètre inconnu : {cle}")

    try:
        nombre = Decimal(valeur)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("La valeur doit être un nombre") from exc
    if not nombre.is_finite():
        raise ValueError("La valeur doit être un nombre fini")
    exposant = nombre.as_tuple().exponent
    if isinstance(exposant, int) and exposant < -_DECIMALES_MAX:
        raise ValueError("La valeur ne peut pas dépasser six décimales")
    if nombre < definition.minimum or nombre > definition.maximum:
        raise ValueError(
            f"La valeur doit être comprise entre {_texte_decimal(definition.minimum)} "
            f"et {_texte_decimal(definition.maximum)} {definition.unite}"
        )
    if definition.entier and nombre != nombre.to_integral_value():
        raise ValueError("La valeur doit être un nombre entier")

    await _assurer_parametres(session)
    if cle in _CLES_SEUILS_PRIX:
        seuils = {
            ligne.cle: ligne
            for ligne in (
                await session.execute(
                    select(Parametre)
                    .where(Parametre.cle.in_(_CLES_SEUILS_PRIX))
                    .order_by(Parametre.cle)
                    .with_for_update()
                )
            ).scalars()
        }
        seuil_simple = (
            nombre
            if cle == "seuil_prix_pct"
            else Decimal(seuils["seuil_prix_pct"].valeur)
        )
        seuil_fort = (
            nombre
            if cle == "seuil_prix_fort_pct"
            else Decimal(seuils["seuil_prix_fort_pct"].valeur)
        )
        if seuil_simple > seuil_fort:
            raise ValueError(
                "L'écart de prix doit être inférieur ou égal à l'écart "
                "de prix important"
            )
        parametre = seuils[cle]
    else:
        parametre = (
            await session.execute(
                select(Parametre).where(Parametre.cle == cle).with_for_update()
            )
        ).scalar_one()
    avant = parametre.valeur
    apres = _texte_decimal(nombre)
    parametre.valeur = apres
    parametre.modifie_par = auteur_id
    parametre.modifie_le = datetime.now(UTC)
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="parametre_modifie",
            cible_table="parametre",
            cible_id=cle,
            avant={"valeur": avant},
            apres={"valeur": apres},
        )
    )
    await session.flush()

    return ParametreAffiche(
        cle=cle,
        valeur=apres,
        libelle=definition.libelle,
        unite=definition.unite,
        minimum=_texte_decimal(definition.minimum),
        maximum=_texte_decimal(definition.maximum),
        entier=definition.entier,
        interrupteur=definition.interrupteur,
        groupe=definition.groupe,
    )
