"""R18 — chantier à confirmer (avenant du 27/09/2026).

Le nom de chantier lu sur un BL/enlèvement et la légende saisie par
l'employé au dépôt Telegram ne désignent pas sans ambiguïté un seul et même
chantier (table de décision de `normalize.chantier`, en amont, hors de ce
module pur) : gravité moyenne, justification chiffrée = nom lu, légende et
chantiers candidats.

Point d'entrée séparé (`evaluer_chantier`, `REGLES_CHANTIER`) : R18 ne fait
partie ni de `evaluer_facture` (elle ne porte pas sur une facture), ni de
`evaluer_suivi` (elle ne dépend pas du temps écoulé, mais du résultat de la
décision de chantier au moment du dépôt) — décision du contrôleur, même
principe de séparation que `evaluer_suivi` vis-à-vis de `evaluer_facture`.
`evaluer_chantier` n'est pas encore appelée par `ingest` (câblage prévu à
une tâche ultérieure)."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, ChantierIncertainControle, Gravite

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R18(controle: ChantierIncertainControle) -> Anomalie | None:
    """`None` si `controle.incertain` est faux (le nom lu et la légende
    désignent le même chantier, ou un seul candidat suffisait)."""
    if not controle.incertain:
        return None

    return Anomalie(
        regle="R18",
        gravite=Gravite.MOYENNE,
        detail={
            "nom_lu": controle.nom_lu or TIRET,
            "legende": controle.legende or TIRET,
            "candidats": " / ".join(controle.candidats),
            "candidats_ids": ",".join(str(cid) for cid in controle.candidats_ids),
        },
        document_id=controle.document_id,
    )
