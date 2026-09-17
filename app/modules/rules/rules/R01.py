"""R01 — BL facturé non reçu (CDC §5, L4-T2).

Un bloc de facture sans BL rapproché (`bloc.bl is None`, L4-D5) et sans
mention « pas de bon » lue sur son commentaire (matière de R02, exclusivité
décrite ci-dessous) est un BL qu'on attend encore : gravité haute,
justification chiffrée = les identifiants du bloc facturé (CDC §5 : « N°
BL, chantier, date, montant HT du bloc »).

R01 et R02 s'excluent : elles partagent la garde `bloc.bl is None` et se
distinguent uniquement par la présence ou l'absence d'une mention « pas de
bon »/« sans bon », jamais les deux à la fois — d'où l'import de
`mention_pas_de_bon` depuis `R02` plutôt qu'une seconde implémentation."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, BlocControle, Gravite
from app.modules.rules.rules.R02 import mention_pas_de_bon

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R01(bloc: BlocControle) -> Anomalie | None:
    """`None` si le bloc a un BL rapproché, ou si son commentaire porte une
    mention « pas de bon »/« sans bon » (matière de R02, pas de R01)."""
    if bloc.bl is not None:
        return None
    if mention_pas_de_bon(bloc.commentaire) is not None:
        return None

    return Anomalie(
        regle="R01",
        gravite=Gravite.HAUTE,
        detail={
            "numero_bl": bloc.numero_bl or TIRET,
            "chantier": bloc.chantier or bloc.chantier_brut or TIRET,
            "date_bl": bloc.date_bl.isoformat() if bloc.date_bl is not None else TIRET,
            "montant_ht": str(bloc.montant_ht),
        },
        bloc_id=bloc.id,
    )
