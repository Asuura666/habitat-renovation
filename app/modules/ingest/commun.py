"""Aides internes partagées par les sous-modules de `ingest` : écriture
atomique sur disque, journalisation d'échec, correspondance extension ->
type MIME, et le `Deposant` partagé par le dépôt Telegram
(`ingest/depot_telegram.py`) et le dépôt de facture (`ingest/factures.py`).

Issu du découpage de l'ancien `ingest/service.py` (vague finale du lot 2,
point 1 : simple déplacement de code, aucun changement de comportement).
N'est pas un module façade : chaque symbole d'ici est repris par au moins
deux des autres sous-modules d'`ingest`, jamais un ré-export de
complaisance.

`logger` garde le nom historique `"app.modules.ingest.service"` (plutôt que
`__name__`, qui vaudrait `"app.modules.ingest.commun"`) : les tests qui
filtrent les journaux avec
`caplog.at_level(..., logger="app.modules.ingest.service")` n'ont donc pas
besoin d'être modifiés par ce découpage (règle de la tâche : seuls les
imports changent).

`controle_prix_actif`/`regles_desactivees` (décision d'Ilane du 24/09/2026,
`docs/dette.md`) : un seul mois de factures ne fonde aucun « prix habituel »,
les contrôles de prix (R07, R08, R09) sont désactivés côté serveur tant que
`app.core.config.Settings.controle_prix_actif` n'est pas explicitement à
`true`. Ce module est le **seul** endroit d'`ingest` qui lit ce drapeau
(`controle_prix_actif`) et en dérive l'ensemble des règles à masquer
(`regles_desactivees`) — aucune autre source de vérité : `rapprochement.py`
(calcul), `anomalies.py`/`bilan.py`/`comparaison_bl.py` (masquage de chaque
lecture) et `a_traiter.py` (exposition au front) importent `regles_
desactivees`/`controle_prix_actif` d'ici, jamais `get_settings()`
directement pour cette décision. `rules` reste pur : c'est cette fonction,
côté `ingest` (l'orchestrateur), qui lit la configuration et la traduit en
un ensemble de codes de règle, un type que `rules.engine.evaluer_facture`
accepte sans jamais importer `app.core`.

`controle_livre_non_facture_actif` (même décision, seconde demande d'Ilane
le 24/09/2026) : R06 (« Livré mais pas facturé », contrôle différé de
`ingest.suivi`) est désactivée par le même mécanisme, tant que
`Settings.controle_livre_non_facture_actif` n'est pas explicitement à
`true` — aucune preuve encore constatée que ce cas se produise. Même point
unique : `regles_desactivees` combine les deux drapeaux (`REGLES_PRIX` et/ou
`REGLES_LIVRE_NON_FACTURE`, indépendamment) ; `ingest.suivi.controles_
differes` lit `regles_desactivees` exactement comme `rapprochement.py`, pour
que R06 ne soit ni évaluée ni considérée comme « recalculée » par le
balayage de suppression (`synchroniser_anomalies`, Ruling R8) quand elle est
désactivée — ses anomalies déjà ouvertes restent en base (masquées, jamais
fermées ni supprimées) jusqu'à réactivation.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("app.modules.ingest.service")

# Les seules règles que la décision d'Ilane du 24/09/2026 désactive
# (`docs/dette.md`) : les trois règles de *prix* du moteur (`rules.engine
# ._evaluer_prix`), jamais une autre catégorie.
REGLES_PRIX: frozenset[str] = frozenset({"R07", "R08", "R09"})

# Seconde demande d'Ilane, même jour (`docs/dette.md`) : R06 (« Livré mais
# pas facturé », contrôle différé de `ingest.suivi`), jamais une autre règle
# de suivi (R14/R15/R16 restent actives).
REGLES_LIVRE_NON_FACTURE: frozenset[str] = frozenset({"R06"})


def controle_prix_actif() -> bool:
    """Reflet direct de `Settings.controle_prix_actif` -- voir le docstring
    de module. Exposée séparément de `regles_desactivees` pour que le front
    puisse afficher le drapeau lui-même (`ingest.a_traiter.CompteProblemes
    .controle_prix_actif`) sans avoir à déduire un booléen d'un ensemble de
    règles."""
    return get_settings().controle_prix_actif


def controle_livre_non_facture_actif() -> bool:
    """Reflet direct de `Settings.controle_livre_non_facture_actif` -- voir
    le docstring de module. Appelants : `regles_desactivees` ci-dessous
    (donc, indirectement, `ingest.suivi`, `ingest.rapprochement` et
    `ingest.anomalies`) et `ingest.parametres._cle_masquee`, qui masque
    `delai_ligne_bl_non_facturee_j` côté serveur (absent de
    `GET /api/parametres`, refusé par `PUT` comme une clé inconnue) quand ce
    drapeau est faux. N'est plus repris par `ingest.a_traiter
    .CompteProblemes` : le masquage du seuil se fait déjà entièrement côté
    serveur, le front n'a donc plus besoin de connaître ce drapeau
    lui-même pour l'écran Réglages. R06 reste par ailleurs rangée dans la
    catégorie « quantites » (`ingest.anomalies.CATEGORIES_REGLE`), sans
    libellé ni filtre qui lui soit propre sur les écrans d'anomalies --
    exposée séparément de `regles_desactivees`, par symétrie avec
    `controle_prix_actif`."""
    return get_settings().controle_livre_non_facture_actif


def regles_desactivees() -> frozenset[str]:
    """Union des règles désactivées par chacun des deux drapeaux
    indépendants (voir le docstring de module) -- la seule fonction qui
    décide quelles règles sont désactivées dans toute l'application.
    `REGLES_PRIX` et `REGLES_LIVRE_NON_FACTURE` ne se recouvrent jamais,
    chaque drapeau se lit et s'active indépendamment de l'autre."""
    desactivees: frozenset[str] = frozenset()
    if not controle_prix_actif():
        desactivees |= REGLES_PRIX
    if not controle_livre_non_facture_actif():
        desactivees |= REGLES_LIVRE_NON_FACTURE
    return desactivees


def _journaliser_echec(etape: str, update_id: int, exc: Exception) -> None:
    """Ne journalise jamais le token, le contenu d'un fichier ni le nom de
    fichier d'origine : uniquement l'`update_id` et le type de l'exception."""
    logger.error(
        "échec ingest (%s) pour update_id=%s : %s",
        etape,
        update_id,
        type(exc).__name__,
    )


def _supprimer_si_existe(chemin: Path) -> None:
    chemin.unlink(missing_ok=True)


def _ecrire_atomique(
    docs_dir: Path, chemin_temporaire: Path, chemin_final: Path, contenu: bytes
) -> None:
    """Écriture atomique (décision du contrôleur T6) : fichier temporaire
    dans `docs_dir`, rempli, puis `os.replace` (rename atomique sur un même
    système de fichiers). Fonction synchrone, exécutée hors de la boucle
    asyncio via `asyncio.to_thread` (I/O disque bloquante)."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    chemin_temporaire.write_bytes(contenu)
    os.replace(chemin_temporaire, chemin_final)


# Mapping extension de stockage (`FichierTelecharge.extension`, décidée par
# `Messagerie.telecharger` — pas le type MIME Telegram d'origine, absent pour
# une photo) -> type MIME attendu par l'API Mistral OCR (`ingest/mistral.py`,
# `ocr_document`). Mapping explicite, même esprit que
# `messaging/telegram.py` : pas de bibliothèque `mimetypes` dépendante de la
# machine.
_MIME_PAR_EXTENSION: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
    "tiff": "image/tiff",
    "pdf": "application/pdf",
}


def _mime_pour_extension(extension: str) -> str:
    return _MIME_PAR_EXTENSION.get(extension, "application/octet-stream")


@dataclass(frozen=True)
class Deposant:
    """Auteur d'un dépôt : un utilisateur actif rattaché à un envoi Telegram
    (résolu par `depot_telegram.utilisateur_rattache`, liste blanche L2-D7,
    et utilisé par `traiter_fichier`/la ligne de supervision L2-D8), ou déjà
    authentifié via l'API (`api/factures.py`, dépôt d'une facture, L2-T4).
    Ne porte que les champs utiles à ces deux appelants, jamais l'entité ORM
    `Utilisateur` (le dépôt Telegram s'exécute en tâche de fond, après la
    fermeture de la session de la requête qui a fait la résolution)."""

    id: uuid.UUID
    nom_affichage: str
