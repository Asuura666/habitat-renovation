"""R12 — doublon de facturation (CDC §5, L4-T2).

Un bloc dont le n° de BL a déjà été affecté à un bloc antérieur, dans une
autre facture du même fournisseur (`bloc.autre_facture_id`, L4-D5 : « les
autres sont signalés en doublon par R12 ») est un doublon de facturation :
gravité haute, justification chiffrée = les deux factures et le n° de BL en
cause (CDC §5 : « Les deux factures, le BL »).

Indépendante de `bloc.bl` (le rapprochement au BL déposé est un sujet
distinct, matière de R01/R02) et de R11 : Ruling R2 ne saute que les règles
de *ligne* d'un bloc dont le BL est incohérent, jamais les règles de bloc."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, BlocControle, Gravite

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R12(bloc: BlocControle, facture_numero: str | None) -> Anomalie | None:
    """`facture_numero` est le numéro de la facture en cours de contrôle
    (celle qui porte `bloc`) ; `bloc.autre_facture_numero` celui de la
    facture où le même n° de BL a déjà été rapproché (L4-D5). `None` si le
    bloc n'a pas été détecté en doublon (`autre_facture_id` absent)."""
    if bloc.autre_facture_id is None:
        return None

    return Anomalie(
        regle="R12",
        gravite=Gravite.HAUTE,
        detail={
            "numero_bl": bloc.numero_bl or TIRET,
            "facture": facture_numero or TIRET,
            "autre_facture": bloc.autre_facture_numero or TIRET,
            "montant_ht": str(bloc.montant_ht),
        },
        bloc_id=bloc.id,
    )
