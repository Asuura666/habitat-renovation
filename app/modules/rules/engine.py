"""Moteur qui enchaîne les règles dans l'ordre du CDC §5 (L4-D2).

Ordre complet du catalogue (CDC §5, « Ordre d'exécution ») :

1. R10 sur le document de la facture (cohérence arithmétique). Si elle
   produit une anomalie, le document reste « à vérifier » et **aucune**
   autre règle ne tourne pour cette facture : R10 est alors la seule
   anomalie renvoyée (Ruling R2).
2. Sinon, pour chaque bloc de la facture, dans l'ordre : R11 sur le BL
   rapproché à ce bloc, s'il y en a un. Si elle produit une anomalie pour
   ce bloc, les règles de ligne de ce bloc sont sautées (Ruling R2) — les
   autres blocs continuent d'être évalués normalement.
3. Puis, pour chaque bloc, toujours (que R11 se soit déclenchée ou non) :
   R01 (BL facturé non reçu), R02 (BL facturé « pas de bon »), R12
   (doublon de facturation) — L4-T2/L4-T4, pas encore écrites.
4. Puis, pour chaque ligne des blocs non sautés à l'étape 2 : R03, R04,
   R05, R07, R08, R09, R13, R17 — L4-T3 à L4-T5, pas encore écrites.

À ce stade (L4-T1), seules les étapes 1 et 2 (R10, R11) sont implémentées :
les tâches suivantes ajouteront leurs règles dans `_evaluer_bloc` (niveau
bloc) et une future fonction de niveau ligne, sans toucher à la structure
ci-dessous. Aucun code n'anticipe ces règles (YAGNI) : ni fonction ni
branche vide pour R01/R02/R12 ou les règles de ligne.

`evaluer_suivi` (R06, R14, R15, R16, contrôles différés au temps écoulé,
L4-D14) n'est pas de ce module (L4-T5/T11).
"""

from __future__ import annotations

from app.modules.rules.modeles import (
    Anomalie,
    BlocControle,
    FactureControlee,
    Parametres,
)
from app.modules.rules.rules.R10 import R10
from app.modules.rules.rules.R11 import R11


def evaluer_facture(
    facture: FactureControlee, parametres: Parametres
) -> tuple[Anomalie, ...]:
    """Point d'entrée du moteur pour une facture (niveau document)."""
    anomalie_r10 = R10(facture.document, parametres)
    if anomalie_r10 is not None:
        return (anomalie_r10,)

    anomalies: list[Anomalie] = []
    for bloc in facture.blocs:
        anomalies.extend(_evaluer_bloc(bloc, parametres))
    return tuple(anomalies)


def _evaluer_bloc(bloc: BlocControle, parametres: Parametres) -> tuple[Anomalie, ...]:
    """Règles de niveau bloc pour un bloc de la facture. R01, R02 et R12
    (toujours évaluées, indépendamment de R11) rejoindront cette fonction à
    partir de L4-T2/L4-T4 ; les règles de ligne rejoindront une nouvelle
    fonction appelée d'ici, sautée si R11 se déclenche (Ruling R2)."""
    if bloc.bl is None:
        return ()

    anomalie_r11 = R11(bloc.bl, parametres)
    if anomalie_r11 is not None:
        return (anomalie_r11,)
    return ()
