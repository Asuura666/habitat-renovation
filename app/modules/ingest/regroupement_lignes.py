"""Construction des lignes rapprochées d'un bloc (B-06).

Prend les appariements de `normalize.appariement.apparier_lignes` et les
lignes vues du moteur (`LigneControlee`), et décide, pour chaque groupe de
lignes de même code, si la comparaison se fait sur les quantités totales
(groupe agrégeable : lignes "article", conversion possible, unités
comparables) ou, par prudence, ligne à ligne comme avant (une ligne de
facture sans ligne de BL en face reste alors « non appariée »).
Fonction pure : aucune base, aucun réseau."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.normalize.appariement import Appariement
from app.modules.rules.agregation import agreger_lignes
from app.modules.rules.modeles import LigneControlee, LigneRapprochee


@dataclass(frozen=True)
class LienLigne:
    """Ligne de `rapprochement_ligne` à persister."""

    ligne_facture_id: uuid.UUID
    ligne_bl_id: uuid.UUID
    methode: str
    ecart_qte: Decimal | None


@dataclass(frozen=True)
class LignesRapprochees:
    lignes: tuple[LigneRapprochee, ...]
    liens: tuple[LienLigne, ...]
    cles_bl_couvertes: frozenset[uuid.UUID]


def construire_lignes_rapprochees(
    lignes_facture: Sequence[LigneControlee],
    lignes_bl: Sequence[LigneControlee],
    appariements: Sequence[Appariement],
) -> LignesRapprochees:
    bl_par_id = {ligne.id: ligne for ligne in lignes_bl}
    facture_par_id = {ligne.id: ligne for ligne in lignes_facture}
    lignes: list[LigneRapprochee] = []
    liens: list[LienLigne] = []
    couvertes: set[uuid.UUID] = set()

    for facture, appariement in zip(lignes_facture, appariements, strict=True):
        bl = (
            bl_par_id.get(appariement.cle_bl)
            if appariement.cle_bl is not None
            else None
        )
        methode = appariement.methode
        groupe_facture: tuple[LigneControlee, ...] = ()
        groupe_bl: tuple[LigneControlee, ...] = ()
        secondaire = False
        ecart_groupe: Decimal | None = None

        if appariement.groupe_facture and appariement.groupe_bl:
            membres_facture = tuple(
                facture_par_id[cle]
                for cle in appariement.groupe_facture
                if cle in facture_par_id
            )
            membres_bl = tuple(
                bl_par_id[cle] for cle in appariement.groupe_bl if cle in bl_par_id
            )
            total_facture = agreger_lignes(membres_facture)
            total_bl = agreger_lignes(membres_bl)
            if total_facture is not None and total_bl is not None:
                couvertes.update(ligne.id for ligne in membres_bl)
                if appariement.groupe_facture[0] == facture.id:
                    groupe_facture, groupe_bl = membres_facture, membres_bl
                    ecart_groupe = _ecart(total_facture, total_bl)
                else:
                    secondaire = True
            else:
                # Prudence : pas d'agrégation, comparaison ligne à ligne
                # (une ligne de facture sans ligne de BL de même rang reste
                # non appariée).
                groupe = appariement.groupe_facture
                rang = groupe.index(facture.id) if facture.id in groupe else None
                if rang is None or rang >= len(appariement.groupe_bl):
                    bl, methode = None, None

        lignes.append(
            LigneRapprochee(
                facture=facture,
                bl=bl,
                methode=methode,
                groupe_facture=groupe_facture,
                groupe_bl=groupe_bl,
                secondaire=secondaire,
            )
        )
        if bl is not None and methode is not None:
            couvertes.add(bl.id)
            ecart = ecart_groupe
            if not groupe_facture and not secondaire:
                ecart = _ecart(facture, bl)
            liens.append(
                LienLigne(
                    ligne_facture_id=facture.id,
                    ligne_bl_id=bl.id,
                    methode=methode,
                    ecart_qte=ecart,
                )
            )

        if groupe_facture:
            # Lignes de BL du groupe sans ligne de facture de même rang
            # (BL plus fourni que la facture) : reliées à la tête du groupe,
            # pour qu'aucune ne passe pour « non facturée » (comparaison de
            # BL, suivi). Le bilan somme les quantités BL par ligne de
            # facture, il ne compte donc rien deux fois.
            for ligne_bl_en_plus in groupe_bl[len(groupe_facture) :]:
                liens.append(
                    LienLigne(
                        ligne_facture_id=facture.id,
                        ligne_bl_id=ligne_bl_en_plus.id,
                        methode="code",
                        ecart_qte=None,
                    )
                )

    return LignesRapprochees(tuple(lignes), tuple(liens), frozenset(couvertes))


def _ecart(facture: LigneControlee, bl: LigneControlee) -> Decimal | None:
    if facture.qte_fact is None or bl.qte_fact is None:
        return None
    return facture.qte_fact - bl.qte_fact
