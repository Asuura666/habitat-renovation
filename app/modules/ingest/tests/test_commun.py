"""Tests de `app.modules.ingest.commun` : droits d'écriture des documents
clients sur disque (audit rapidité/sécurité du 25/09/2026, tâche T3,
constat CRITIQUE).

L'umask du conteneur en production est 0022 (constat de l'audit) : chaque
test qui vérifie un mode précis le fixe explicitement le temps du test
(`os.umask`, restauré dans un `finally`) pour un résultat déterministe,
indépendant de l'umask du poste qui exécute la suite.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

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
