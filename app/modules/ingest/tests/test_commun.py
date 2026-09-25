"""Tests de `app.modules.ingest.commun` : droits d'écriture des documents
clients sur disque (audit rapidité/sécurité du 25/09/2026, tâche T3, constat
CRITIQUE) et signature binaire attendue par extension (même audit, tâche T9,
constat CRITIQUE).

L'umask du conteneur en production est 0022 (constat de l'audit) : chaque
test qui vérifie un mode précis le fixe explicitement le temps du test
(`os.umask`, restauré dans un `finally`) pour un résultat déterministe,
indépendant de l'umask du poste qui exécute la suite.

`signature_conforme` est une fonction pure (aucune base, aucun réseau) :
un positif et un négatif par extension (`jpg`, `png`, `webp`, `pdf`, `tiff`,
`heic`, `heif`), plus l'extension inconnue.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.modules.ingest import commun as ingest_commun


def _mode(chemin: Path) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


def test_ecrire_atomique_fichier_final_en_0640_et_dossier_nouveau_en_0750(
    tmp_path: Path,
) -> None:
    """Cas positif : sous l'umask 0022 du conteneur, le fichier final porte
    exactement 0640 et un dossier de documents nouvellement créé exactement
    0750 -- jamais 0644/0755 (umask du conteneur non pris en compte),
    lisibles par tout autre compte Unix du VPS partagé, hors de toute
    authentification."""
    docs_dir = tmp_path / "docs"
    chemin_final = docs_dir / "un-document.pdf"
    chemin_temporaire = docs_dir / "un-document.pdf.tmp"

    umask_avant = os.umask(0o022)
    try:
        ingest_commun._ecrire_atomique(
            docs_dir, chemin_temporaire, chemin_final, b"contenu invente"
        )
    finally:
        os.umask(umask_avant)

    assert chemin_final.is_file()
    assert not chemin_temporaire.exists()
    assert chemin_final.read_bytes() == b"contenu invente"
    assert _mode(chemin_final) == 0o640
    assert _mode(docs_dir) == 0o750


def test_ecrire_atomique_reecriture_fichier_existant_garde_0640(
    tmp_path: Path,
) -> None:
    """Cas négatif/robustesse : réécrire un document déjà présent (relance
    d'extraction, nouveau dépôt sur le même chemin) garde exactement 0640 --
    `os.open` n'applique le mode voulu qu'à la création du fichier (règle
    POSIX), jamais après coup sur un fichier déjà existant."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    chemin_final = docs_dir / "un-document.pdf"
    chemin_final.write_bytes(b"ancien contenu")
    chemin_final.chmod(0o640)
    chemin_temporaire = docs_dir / "un-document.pdf.tmp"

    umask_avant = os.umask(0o022)
    try:
        ingest_commun._ecrire_atomique(
            docs_dir, chemin_temporaire, chemin_final, b"nouveau contenu"
        )
    finally:
        os.umask(umask_avant)

    assert chemin_final.read_bytes() == b"nouveau contenu"
    assert not chemin_temporaire.exists()
    assert _mode(chemin_final) == 0o640


@pytest.mark.parametrize(
    ("extension", "contenu"),
    [
        pytest.param("jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", id="jpg"),
        pytest.param("png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", id="png"),
        pytest.param("webp", b"RIFF\x24\x00\x00\x00WEBPVP8 ", id="webp"),
        pytest.param("pdf", b"%PDF-1.4\n%invente-pour-les-tests\n", id="pdf"),
        pytest.param("tiff", b"II*\x00\x08\x00\x00\x00", id="tiff-petit-boutiste"),
        pytest.param("tiff", b"MM\x00*\x00\x08\x00\x00", id="tiff-gros-boutiste"),
        pytest.param("heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00", id="heic"),
        pytest.param("heif", b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00", id="heif"),
    ],
)
def test_signature_conforme_accepte_une_signature_valide(
    extension: str, contenu: bytes
) -> None:
    """Cas positif, un par extension reconnue (T9)."""
    assert ingest_commun.signature_conforme(extension, contenu) is True


@pytest.mark.parametrize(
    ("extension", "contenu"),
    [
        pytest.param("jpg", b"\x89PNG\r\n\x1a\n reste invente", id="jpg-contenu-png"),
        pytest.param("png", b"\xff\xd8\xff reste invente", id="png-contenu-jpg"),
        pytest.param(
            "webp",
            b"RIFF\x24\x00\x00\x00AVI reste invente",
            id="webp-riff-sans-marque-webp",
        ),
        pytest.param("webp", b"texte quelconque invente", id="webp-sans-riff"),
        pytest.param("pdf", b"pas-un-pdf-du-tout", id="pdf"),
        pytest.param("tiff", b"texte quelconque invente", id="tiff"),
        pytest.param(
            "heic",
            b"\x00\x00\x00\x18toto1234\x00\x00\x00\x00",
            id="heic-sans-ftyp",
        ),
        pytest.param("heif", b"", id="heif-vide"),
        pytest.param(
            "heic",
            b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41",
            id="heic-ftyp-mp4-non-heic",
        ),
        pytest.param(
            "heif",
            b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00",
            id="heif-ftyp-mov-non-heic",
        ),
    ],
)
def test_signature_conforme_refuse_une_signature_invalide(
    extension: str, contenu: bytes
) -> None:
    """Cas négatif, un par extension reconnue (T9) : un contenu qui ne
    correspond pas à la signature attendue est refusé -- jamais d'exception
    (y compris un contenu trop court ou vide, `heif-vide`). `heic-ftyp-mp4-
    non-heic`/`heif-ftyp-mov-non-heic` (constat SEC-1 de la revue finale du
    25/09/2026) : un conteneur ISOBMFF `ftyp` valide mais dont la marque
    (octets 8-12) désigne un format non-HEIC/HEIF (ici un MP4 et un MOV
    minimaux, inventés pour le test) doit être refusé -- `ftyp` seul aux
    octets 4-8 est commun à tout conteneur ISOBMFF, y compris des vidéos."""
    assert ingest_commun.signature_conforme(extension, contenu) is False


def test_signature_conforme_extension_inconnue_renvoie_false() -> None:
    """Une extension absente de la table est refusée, quel que soit le
    contenu (T9) -- défensif : mieux vaut refuser un type non prévu que le
    stocker sans vérification."""
    assert ingest_commun.signature_conforme("exe", b"\xff\xd8\xff peu importe") is False
    assert ingest_commun.signature_conforme("gif", b"GIF89a") is False
