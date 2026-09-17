"""Moteur qui enchaîne les règles dans l'ordre du CDC §5 (L4-D2).

Ordre complet du catalogue (CDC §5, « Ordre d'exécution ») :

1. R10 sur le document de la facture (cohérence arithmétique). Si elle
   produit une anomalie, le document reste « à vérifier » et **aucune**
   autre règle ne tourne pour cette facture : R10 est alors la seule
   anomalie renvoyée (Ruling R2).
2. Sinon, pour chaque bloc de la facture, dans l'ordre : R11 sur le BL
   rapproché à ce bloc, s'il y en a un.
3. Puis, pour ce même bloc, toujours — que R11 se soit déclenchée ou non,
   qu'il ait ou non un BL rapproché : R01 (BL facturé non reçu), R02 (BL
   facturé « pas de bon »), R12 (doublon de facturation) — L4-T2. Ruling R2
   ne saute jamais les règles de *bloc* : seules les règles de *ligne*
   (étape 4) le sont, quand R11 se déclenche pour ce bloc.
4. Puis, pour chaque ligne des blocs dont R11 ne s'est pas déclenchée :
   R03, R04, R05, R07, R08, R09, R13, R17 — L4-T3 à L4-T5, pas encore
   écrites. Aucun code n'anticipe ces règles (YAGNI) : ni fonction ni
   branche vide.

L4-T1 posait la structure avec R10/R11 seules ; L4-T2 y ajoute R01/R02/R12
et restructure `_evaluer_bloc` en conséquence (revue de L4-T1 : la sortie
précoce sur R11 aurait sauté R01/R02/R12, contraire à Ruling R2).

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
from app.modules.rules.rules.R01 import R01
from app.modules.rules.rules.R02 import R02
from app.modules.rules.rules.R10 import R10
from app.modules.rules.rules.R11 import R11
from app.modules.rules.rules.R12 import R12


def evaluer_facture(
    facture: FactureControlee, parametres: Parametres
) -> tuple[Anomalie, ...]:
    """Point d'entrée du moteur pour une facture (niveau document)."""
    anomalie_r10 = R10(facture.document, parametres)
    if anomalie_r10 is not None:
        return (anomalie_r10,)

    anomalies: list[Anomalie] = []
    for bloc in facture.blocs:
        anomalies.extend(_evaluer_bloc(bloc, parametres, facture.document.numero))
    return tuple(anomalies)


def _evaluer_bloc(
    bloc: BlocControle, parametres: Parametres, facture_numero: str | None
) -> tuple[Anomalie, ...]:
    """Règles de niveau bloc (L4-T2) : R11 (si un BL est rapproché), puis
    R01, R02 et R12, **toujours** évaluées (Ruling R2 — seules les règles
    de ligne, pas encore écrites, seront sautées ici même quand R11 se
    déclenche)."""
    anomalies: list[Anomalie] = []

    if bloc.bl is not None:
        anomalie_r11 = R11(bloc.bl, parametres)
        if anomalie_r11 is not None:
            anomalies.append(anomalie_r11)

    for anomalie in (R01(bloc), R02(bloc), R12(bloc, facture_numero)):
        if anomalie is not None:
            anomalies.append(anomalie)

    return tuple(anomalies)
