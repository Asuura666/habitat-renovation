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


# Droits restreints des documents clients sur disque (audit rapidité/
# sécurité du 25/09/2026, tâche T3, constat CRITIQUE) : avec l'umask 0022 du
# conteneur, `Path.mkdir`/`Path.write_bytes` créaient respectivement un
# dossier 0755 et des fichiers 0644 -- lisibles par tout autre compte Unix
# du VPS partagé, hors de toute authentification. 0750/0640 restreignent la
# lecture (et, pour le dossier, le listage) au seul compte du conteneur.
_MODE_DOSSIER_DOCUMENTS = 0o750
_MODE_FICHIER_DOCUMENT = 0o640


def _creer_dossier_documents(dossier: Path) -> None:
    """Crée `dossier` (et ses parents éventuels) en 0750 s'il n'existe pas
    déjà -- voir le commentaire sur `_MODE_DOSSIER_DOCUMENTS`. Le mode passé
    à `mkdir` reste combiné à l'umask du process comme tout appel `mkdir`
    POSIX (déterministe une fois l'umask du conteneur, 0022, connu -- les
    deux bits qu'il retire ici, écriture groupe/autre, sont déjà absents de
    0750). N'aggrave jamais les droits d'un dossier déjà présent : cette
    fonction ne fait qu'ajouter `exist_ok=True`, jamais un `chmod` sur
    l'existant (dossiers déjà déployés à corriger à la main, voir
    `docs/dette.md`)."""
    dossier.mkdir(mode=_MODE_DOSSIER_DOCUMENTS, parents=True, exist_ok=True)


def _ecrire_fichier_prive(chemin: Path, contenu: bytes) -> None:
    """Écrit `contenu` dans `chemin` (créé, ou tronqué s'il existe déjà) en
    0640 -- voir le commentaire sur `_MODE_FICHIER_DOCUMENT`. Le mode est
    fixé dès la création du descripteur (`os.open` avec
    `O_WRONLY|O_CREAT|O_TRUNC` et le mode voulu), jamais appliqué après coup
    par un `chmod` séparé : le fichier n'existe donc jamais, même
    momentanément, avec des droits plus larges. Réécrire un fichier déjà
    existant à ce chemin conserve le mode qu'il avait déjà (règle POSIX de
    `open` : le mode passé n'est appliqué qu'à la création) -- seule la
    création initiale fixe 0640."""
    descripteur = os.open(
        chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _MODE_FICHIER_DOCUMENT
    )
    with os.fdopen(descripteur, "wb") as fichier:
        fichier.write(contenu)


def _ecrire_atomique(
    docs_dir: Path, chemin_temporaire: Path, chemin_final: Path, contenu: bytes
) -> None:
    """Écriture atomique (décision du contrôleur T6) : fichier temporaire
    dans `docs_dir`, rempli, puis `os.replace` (rename atomique sur un même
    système de fichiers). Fonction synchrone, exécutée hors de la boucle
    asyncio via `asyncio.to_thread` (I/O disque bloquante).

    `docs_dir` est créé en 0750 (`_creer_dossier_documents`) et le fichier
    temporaire directement en 0640 (`_ecrire_fichier_prive`) -- tâche T3,
    voir le commentaire sur `_MODE_DOSSIER_DOCUMENTS`/
    `_MODE_FICHIER_DOCUMENT`. `os.replace` ne touche pas au mode du fichier
    temporaire : le fichier final porte donc le même 0640."""
    _creer_dossier_documents(docs_dir)
    _ecrire_fichier_prive(chemin_temporaire, contenu)
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


# Signature (« magic bytes ») attendue pour chaque extension de stockage
# (audit rapidité/sécurité du 25/09/2026, tâche T9, constat CRITIQUE) : un
# document reçu par Telegram (`depot_telegram.traiter_fichier`) n'était
# accepté que sur le type MIME déclaré par le client Telegram
# (`messaging.telegram._fichier_depuis_document`) — jamais confronté au
# contenu réel — alors que le dépôt de facture (`factures.deposer_facture`)
# vérifie déjà `%PDF-` avant tout. `signature_conforme` généralise ce
# contrôle aux extensions de `_MIME_PAR_EXTENSION` ci-dessus (sauf `jpeg`,
# jamais produite par `messaging.telegram._extension`/`_EXTENSIONS_PAR_MIME`
# — seule `jpg` l'est) et devient la seule source de vérité pour les deux
# appelants : `factures.py` (PDF) et `depot_telegram.traiter_fichier`
# (toutes les extensions), fonction pure (aucune base, aucun réseau).
_SIGNATURE_JPG = b"\xff\xd8\xff"
_SIGNATURE_PNG = b"\x89PNG\r\n\x1a\n"
_SIGNATURE_PDF = b"%PDF-"
_SIGNATURE_TIFF_LITTLE_ENDIAN = b"II*\x00"
_SIGNATURE_TIFF_BIG_ENDIAN = b"MM\x00*"


def signature_conforme(extension: str, contenu: bytes) -> bool:
    """`True` si `contenu` porte la signature binaire attendue pour
    `extension`, `False` sinon -- y compris pour une extension absente de
    cette table (défensif : mieux vaut refuser un fichier d'un type non
    prévu que le stocker sans vérification).

    - `jpg` : `FF D8 FF` en tête.
    - `png` : les 8 octets de signature PNG (`89 50 4E 47 0D 0A 1A 0A`).
    - `webp` : `RIFF` en tête (octets 0-4) et `WEBP` aux octets 8-12 (le
      conteneur RIFF, entre les deux, porte la taille du fichier -- jamais
      vérifiée ici, seule la structure du conteneur importe).
    - `pdf` : `%PDF-` en tête (même signature que celle utilisée par
      `factures.deposer_facture`, via cette fonction).
    - `tiff` : `II*\\x00` (petit-boutiste) ou `MM\\x00*` (gros-boutiste) en
      tête -- les deux ordres d'octets valides du format TIFF.
    - `heic`/`heif` : `ftyp` aux octets 4-8, sans exiger de marque précise
      aux octets 8-12 (`heic`, `mif1`, `heix`, ... -- de nombreuses marques
      ISOBMFF valides, aucune liste exhaustive fiable).

    Une lecture hors bornes (`contenu` plus court que la signature attendue)
    ne lève jamais : une tranche Python au-delà de la fin d'un `bytes` est
    simplement plus courte, jamais une erreur -- elle ne correspond alors à
    aucune signature attendue et la fonction renvoie `False`.
    """
    if extension == "jpg":
        return contenu[: len(_SIGNATURE_JPG)] == _SIGNATURE_JPG
    if extension == "png":
        return contenu[: len(_SIGNATURE_PNG)] == _SIGNATURE_PNG
    if extension == "webp":
        return contenu[:4] == b"RIFF" and contenu[8:12] == b"WEBP"
    if extension == "pdf":
        return contenu[: len(_SIGNATURE_PDF)] == _SIGNATURE_PDF
    if extension == "tiff":
        return contenu[:4] in (
            _SIGNATURE_TIFF_LITTLE_ENDIAN,
            _SIGNATURE_TIFF_BIG_ENDIAN,
        )
    if extension in ("heic", "heif"):
        return contenu[4:8] == b"ftyp"
    return False


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
