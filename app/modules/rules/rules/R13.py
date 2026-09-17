"""R13 — avoir sans origine (CDC §5, L4-T5).

Une ligne négative sans ligne positive antérieure de même article et
chantier a déjà été identifiée par `ingest`
(`FactureControlee.lignes_negatives_sans_origine`, couples ligne + chantier
cherché, décision du contrôleur) : R13 ne recalcule rien, elle se contente
de construire l'anomalie, gravité moyenne, justification chiffrée = article,
montant de la ligne et chantier cherché (CDC §5 : « Article, montant,
chantiers cherchés »).

`chantier` est le nom du chantier auquel `ingest` a tenté de rattacher la
ligne d'origine, ou `None` si aucun chantier n'a pu être déterminé pour
cette recherche — affiché avec un tiret dans ce cas (décision du
contrôleur, même convention que les autres règles).

Le seul filtre posé ici (`type_ligne == "article"`) est la même garde
défensive que toutes les autres règles de ligne (R05, R09, R17…), pas un
recalcul de la détection « négative sans origine » elle-même."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, Gravite, LigneControlee

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R13(ligne: LigneControlee, chantier: str | None) -> Anomalie | None:
    """`None` si la ligne n'est pas de type "article" (les lignes `eco`/
    `commentaire` ne produisent jamais d'anomalie de ligne)."""
    if ligne.type_ligne != "article":
        return None

    montant = str(ligne.montant_ht) if ligne.montant_ht is not None else TIRET
    return Anomalie(
        regle="R13",
        gravite=Gravite.MOYENNE,
        detail={
            "article": ligne.designation or TIRET,
            "code": ligne.code or TIRET,
            "montant": montant,
            "chantier": chantier or TIRET,
        },
        ligne_id=ligne.id,
        article_id=ligne.article_id,
    )
