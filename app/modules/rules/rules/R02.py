"""R02 — BL facturé « pas de bon » (CDC §5, L4-T2).

Un bloc sans BL rapproché (`bloc.bl is None`) dont le commentaire porte une
mention explicite d'absence de bon (« pas de bon », « sans bon ») est
distingué de R01 (BL facturé non reçu) : le livreur a prévenu qu'aucun bon
ne serait remis, ce qui n'enlève rien à la haute gravité (CDC §5) mais
change la justification affichée à l'admin — l'extrait du commentaire lu,
`detail["mention"]` (décision du contrôleur).

R01 et R02 s'excluent : elles partagent la garde `bloc.bl is None` et se
distinguent uniquement par la présence (`mention_pas_de_bon(...)` non
`None`) ou l'absence de cette mention, jamais les deux à la fois — `R01`
importe donc `mention_pas_de_bon` d'ici pour poser sa propre garde.

`mention_pas_de_bon` reste dans le module pur `rules` (L4-D1) : elle
réimplémente sa propre normalisation minimale (majuscules, sans accents,
ponctuation réduite en espaces) au lieu de réutiliser
`normalize.texte.normaliser_libelle`, que `rules` n'a pas le droit
d'importer (frontière CLAUDE.md/L4-D1)."""

from __future__ import annotations

import re
import unicodedata

from app.modules.rules.modeles import Anomalie, BlocControle, Gravite

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)
_LONGUEUR_EXTRAIT_MAX = 200
_MOTIFS = (re.compile(r"PAS\s+DE\s+BON"), re.compile(r"SANS\s+BON"))


def _normaliser_caractere(caractere: str) -> str:
    """Normalise un seul caractère en préservant la longueur (un caractère
    d'entrée -> exactement un caractère de sortie), pour que les indices du
    texte normalisé restent alignés avec ceux du commentaire d'origine et
    permettent d'en extraire un passage centré sur la mention trouvée."""
    decompose = unicodedata.normalize("NFKD", caractere)
    sans_accent = next((c for c in decompose if not unicodedata.combining(c)), "")
    if not sans_accent.isalnum():
        return " "
    return sans_accent.upper()


def _normaliser(texte: str) -> str:
    """Majuscules, sans accents, ponctuation -> espace — décision du
    contrôleur. Longueur identique à `texte` (voir `_normaliser_caractere`)
    afin que les positions trouvées par `_MOTIFS` soient réutilisables
    directement sur le commentaire d'origine."""
    return "".join(_normaliser_caractere(c) for c in texte)


def mention_pas_de_bon(commentaire: str | None) -> str | None:
    """Extrait du commentaire **d'origine** (200 caractères au plus, centré
    sur la mention trouvée) quand son texte normalisé contient « pas de
    bon » ou « sans bon » (espaces multiples et ponctuation entre les mots
    tolérés), sinon `None`. `None` en entrée -> `None` en sortie."""
    if not commentaire:
        return None

    normalise = _normaliser(commentaire)
    correspondance = next(
        (m for motif in _MOTIFS if (m := motif.search(normalise)) is not None), None
    )
    if correspondance is None:
        return None
    return _extraire(commentaire, correspondance.start(), correspondance.end())


def _extraire(commentaire: str, debut: int, fin: int) -> str:
    """Passage de `commentaire` d'au plus `_LONGUEUR_EXTRAIT_MAX`
    caractères, centré sur `[debut, fin)`, borné aux limites du texte."""
    longueur_totale = len(commentaire)
    if longueur_totale <= _LONGUEUR_EXTRAIT_MAX:
        return commentaire

    marge = max(_LONGUEUR_EXTRAIT_MAX - (fin - debut), 0)
    debut_extrait = max(debut - marge // 2, 0)
    fin_extrait = min(debut_extrait + _LONGUEUR_EXTRAIT_MAX, longueur_totale)
    debut_extrait = max(fin_extrait - _LONGUEUR_EXTRAIT_MAX, 0)
    return commentaire[debut_extrait:fin_extrait]


def R02(bloc: BlocControle) -> Anomalie | None:
    """`None` si le bloc a un BL rapproché (le bon a été remis, même si le
    commentaire porte la mention), ou si son commentaire ne porte pas de
    mention « pas de bon »/« sans bon » (matière de R01, pas de R02)."""
    if bloc.bl is not None:
        return None
    mention = mention_pas_de_bon(bloc.commentaire)
    if mention is None:
        return None

    return Anomalie(
        regle="R02",
        gravite=Gravite.HAUTE,
        detail={
            "numero_bl": bloc.numero_bl or TIRET,
            "chantier": bloc.chantier or bloc.chantier_brut or TIRET,
            "date_bl": bloc.date_bl.isoformat() if bloc.date_bl is not None else TIRET,
            "montant_ht": str(bloc.montant_ht),
            "mention": mention,
        },
        bloc_id=bloc.id,
    )
