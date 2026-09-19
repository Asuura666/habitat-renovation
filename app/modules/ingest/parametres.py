"""Lecture et modification des seuils métier administrables (L5-T10).

Ce module est l'unique source des neuf clés, de leurs valeurs par défaut et de
leurs bornes. Les couches API et web ne portent aucune validation métier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

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


@dataclass(frozen=True)
class ParametreAffiche:
    cle: str
    valeur: str
    libelle: str
    unite: str
    minimum: str
    maximum: str
    entier: bool


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
        "Occurrences minimales pour l'historique",
        "occurrences",
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
        "Durée d'ignorance d'une anomalie",
        "jours",
        Decimal("90"),
        Decimal("1"),
        Decimal("3650"),
        True,
    ),
)

DEFINITIONS_PAR_CLE = {
    definition.cle: definition for definition in DEFINITIONS_PARAMETRES
}
PARAMETRES_DEFAUT = tuple(
    (definition.cle, definition.defaut) for definition in DEFINITIONS_PARAMETRES
)
_CLES_SEUILS_PRIX = ("seuil_prix_fort_pct", "seuil_prix_pct")
_DECIMALES_MAX = 6


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
    """Liste toujours les neuf seuils connus, dans l'ordre de présentation."""

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
        )
        for definition in DEFINITIONS_PARAMETRES
    ]


async def modifier_parametre(
    session: AsyncSession,
    cle: str,
    valeur: str,
    *,
    auteur_id: uuid.UUID | None,
) -> ParametreAffiche:
    """Valide, modifie et journalise un des neuf seuils connus."""

    definition = DEFINITIONS_PAR_CLE.get(cle)
    if definition is None:
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
    )
