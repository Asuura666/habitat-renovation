"""Tests des garde-fous non destructifs de ``deploy/restore.sh``."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESTORE_SCRIPT = REPO_ROOT / "deploy" / "restore.sh"


def _environnement_restore(tmp_path: Path) -> tuple[dict[str, str], Path]:
    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()
    restic_repo = tmp_path / "restic-repo"
    restic_repo.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "POSTGRES_USER=utilisateur_fictif",
                "POSTGRES_PASSWORD=mot_de_passe_fictif",
                "POSTGRES_DB=base_fictive",
                f"DOCS_HOST_DIR={docs_dir}",
                f"RESTIC_REPOSITORY={restic_repo}",
                "RESTIC_PASSWORD=secret_restic_fictif",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    appels_docker = tmp_path / "appels-docker.txt"
    faux_bin = tmp_path / "bin"
    faux_bin.mkdir()
    faux_docker = faux_bin / "docker"
    faux_docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$APPELS_DOCKER"\n',
        encoding="utf-8",
    )
    faux_docker.chmod(0o755)

    env = os.environ.copy()
    for nom in (  # une variable héritée du processus masquerait un .env incomplet
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DOCS_HOST_DIR",
        "RESTIC_REPOSITORY",
        "RESTIC_PASSWORD",
    ):
        env.pop(nom, None)
    env.update(
        {
            "APPELS_DOCKER": str(appels_docker),
            "COMPOSE_PROJECT_NAME": "habitat_reno_test",
            "HABITAT_RENO_ENV_FILE": str(env_file),
            "HABITAT_RENO_SAUVEGARDES_DIR": str(tmp_path / "sauvegardes"),
            "PATH": f"{faux_bin}:{env['PATH']}",
        }
    )
    return env, appels_docker


def _executer_restore(
    snapshot: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(RESTORE_SCRIPT), snapshot, "--confirmer"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_restore_refuse_latest_sans_appeler_docker(tmp_path: Path) -> None:
    env, appels_docker = _environnement_restore(tmp_path)

    resultat = _executer_restore("latest", env)

    assert resultat.returncode == 1
    assert "identifiant de snapshot précis obligatoire" in resultat.stderr
    assert "latest" in resultat.stderr
    assert not appels_docker.exists()


def test_restore_refuse_un_conteneur_api_absent_avant_tout_effet(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 1
    assert "conteneur api introuvable" in resultat.stderr
    appels = appels_docker.read_text(encoding="utf-8").splitlines()
    assert len(appels) == 1
    assert appels[0].startswith("compose ")
    assert appels[0].endswith(" ps -a -q api")
    assert all(" run " not in appel and " stop api" not in appel for appel in appels)


# --- Ordre des contrôles et droits des documents (audit F-02, C-02, C-03) ---
#
# Faux `docker` qui répond comme la vraie chaîne : le conteneur api existe,
# `restic restore` dépose un dump et un document sous --target, `pg_dump`
# crée le fichier demandé. Chaque appel est consigné ; les codes de retour
# de `pg_restore --list`, de `restic restore` et de `pg_dump` se règlent par
# variable. Faux `cp`, `mv`, `chown` côté hôte : ils échouent et se
# consignent (« HOTE ... »), car la bascule des documents ne doit plus se
# faire avec les droits de l'opérateur.

FAUX_DOCKER_COMPLET = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$APPELS_DOCKER"
joined=" $* "
if [[ "$1" == "compose" ]]; then
  if [[ "$joined" == *" ps "* ]]; then echo "conteneur-api-fictif"; fi
  exit 0
fi
if [[ "$1" == "run" ]]; then
  if [[ "$joined" == *" restore "* ]]; then
    [[ "${FAUX_RESTIC_RC:-0}" -eq 0 ]] || exit "$FAUX_RESTIC_RC"
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--target" ]]; then target="$2"; fi
      shift
    done
    mkdir -p "$target/dump" "$target$FAUX_DOCS"
    echo dump > "$target/dump/bl.dump"
    echo pdf > "$target$FAUX_DOCS/a.pdf"
  elif [[ "$joined" == *" pg_restore --list"* ]]; then
    # 1er appel : validation du dump du snapshot ; 2e : de la copie de sécurité.
    if [[ "$(grep -c 'pg_restore --list' "$APPELS_DOCKER")" -ge 2 ]]; then
      exit "${FAUX_LISTE_COPIE_RC:-0}"
    fi
    exit "${FAUX_LISTE_RC:-0}"
  elif [[ "$joined" == *" pg_database "* ]]; then
    [[ -n "${FAUX_BASE_ABSENTE:-}" ]] || echo 1
  elif [[ "$joined" == *" pg_dump "* ]]; then
    # La copie de sécurité sort sur stdout (redirigée côté hôte en 0600).
    echo dump
    [[ "${FAUX_PGDUMP_RC:-0}" -eq 0 ]] || exit "$FAUX_PGDUMP_RC"
  fi
fi
exit 0
"""


def _preparer_faux_docker_complet(tmp_path: Path, env: dict[str, str]) -> None:
    faux_bin = tmp_path / "bin"
    (faux_bin / "docker").write_text(FAUX_DOCKER_COMPLET, encoding="utf-8")
    for commande in ("cp", "mv", "chown"):
        faux = faux_bin / commande
        faux.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "HOTE {commande} $*" >> "$APPELS_DOCKER"\n'
            "exit 1\n",
            encoding="utf-8",
        )
        faux.chmod(0o755)
    env["FAUX_DOCS"] = _docs_dir(env)


def _docs_dir(env: dict[str, str]) -> str:
    for ligne in Path(env["HABITAT_RENO_ENV_FILE"]).read_text().splitlines():
        if ligne.startswith("DOCS_HOST_DIR="):
            return ligne.split("=", 1)[1]
    raise AssertionError("DOCS_HOST_DIR absent du .env de test")


def _appels(appels_docker: Path) -> list[str]:
    if not appels_docker.exists():
        return []
    return appels_docker.read_text(encoding="utf-8").splitlines()


def _indice(appels: list[str], motif: str) -> int:
    for i, appel in enumerate(appels):
        if motif in appel:
            return i
    raise AssertionError(f"aucun appel ne contient {motif!r} : {appels}")


def _pas_de_destruction(appels: list[str]) -> bool:
    return not any(
        "DROP DATABASE" in a or " stop api" in a or "basculer-documents" in a
        for a in appels
    )


def test_restore_valide_le_dump_et_copie_la_base_avant_le_drop(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 0, resultat.stderr
    appels = _appels(appels_docker)
    validation = _indice(appels, "pg_restore --list")
    arret = _indice(appels, " stop api")
    copie = _indice(appels, "pg_dump")
    destruction = _indice(appels, "DROP DATABASE")
    restauration = _indice(appels, "pg_restore --exit-on-error")
    assert _indice(appels, " restore abcd1234 ") < validation
    assert validation < arret < copie < destruction < restauration
    # Copie de sécurité : dossier des sauvegardes, horodatée, droits 600.
    sauvegardes = tmp_path / "sauvegardes"
    copies = sorted(sauvegardes.glob("avant-restauration-base_fictive-*.dump"))
    assert len(copies) == 1
    assert copies[0].stat().st_mode & 0o777 == 0o600
    # Créée d'emblée en 0600 côté hôte (sortie de pg_dump redirigée sous
    # umask 077), puis validée par un second `pg_restore --list`.
    assert " -f " not in appels[copie]
    assert appels[copie + 1 :][0].count("pg_restore --list") == 1
    assert copie < destruction


def test_restore_ne_detruit_rien_si_le_dump_est_invalide(tmp_path: Path) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env["FAUX_LISTE_RC"] = "1"

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert _pas_de_destruction(_appels(appels_docker))


def test_restore_ne_detruit_rien_si_restic_echoue(tmp_path: Path) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env["FAUX_RESTIC_RC"] = "1"

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert _pas_de_destruction(_appels(appels_docker))


def test_restore_ne_detruit_pas_la_base_si_la_copie_de_securite_echoue(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env["FAUX_PGDUMP_RC"] = "1"

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert not any("DROP DATABASE" in a for a in _appels(appels_docker))


def test_restore_refuse_un_dossier_de_sauvegardes_inutilisable_avant_docker(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    fichier = tmp_path / "un-fichier"
    fichier.write_text("x", encoding="utf-8")
    env["HABITAT_RENO_SAUVEGARDES_DIR"] = str(fichier)

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 1
    assert "sauvegardes" in resultat.stderr
    assert _appels(appels_docker) == []


def test_restore_bascule_les_documents_dans_un_conteneur_root_jetable(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 0, resultat.stderr
    appels = _appels(appels_docker)
    assert not any(a.startswith("HOTE ") for a in appels), appels
    bascule = appels[_indice(appels, "basculer-documents.sh")]
    assert _indice(appels, "pg_restore --exit-on-error") < _indice(
        appels, "basculer-documents.sh"
    )
    assert bascule.startswith("run --rm ")
    assert " -u " not in bascule  # root : chown 10001 et parent possédé par root
    assert f"-v {tmp_path}:{tmp_path}" in bascule  # parent de DOCS_HOST_DIR
    assert "--entrypoint sh" in bascule


def test_restore_refuse_un_docs_host_dir_parent_absent_avant_docker(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env_file = Path(env["HABITAT_RENO_ENV_FILE"])
    texte = env_file.read_text(encoding="utf-8").replace(
        f"DOCS_HOST_DIR={tmp_path}/documents",
        f"DOCS_HOST_DIR={tmp_path}/absent/documents",
    )
    env_file.write_text(texte, encoding="utf-8")

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 1
    assert "parent" in resultat.stderr
    assert _appels(appels_docker) == []


def test_restore_refuse_sans_variable_obligatoire(tmp_path: Path) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    env_file = Path(env["HABITAT_RENO_ENV_FILE"])
    env_file.write_text(
        "".join(
            ligne + "\n"
            for ligne in env_file.read_text(encoding="utf-8").splitlines()
            if not ligne.startswith("RESTIC_PASSWORD=")
        ),
        encoding="utf-8",
    )

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert "RESTIC_PASSWORD manquant" in resultat.stderr
    assert not appels_docker.exists()


def test_restore_sans_confirmer_ne_touche_a_rien(tmp_path: Path) -> None:
    env, appels_docker = _environnement_restore(tmp_path)

    resultat = subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(RESTORE_SCRIPT), "abcd1234"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultat.returncode == 1
    assert "--confirmer" in resultat.stderr
    assert not appels_docker.exists()


def _copies(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "sauvegardes").glob("avant-restauration-*.dump"))


def test_restore_ne_detruit_pas_la_base_si_la_copie_de_securite_est_invalide(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env["FAUX_LISTE_COPIE_RC"] = "1"

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert not any("DROP DATABASE" in a for a in _appels(appels_docker))
    assert _copies(tmp_path) == []  # copie partielle supprimée


def test_restore_supprime_la_copie_partielle_si_pg_dump_echoue(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env["FAUX_PGDUMP_RC"] = "1"

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert _copies(tmp_path) == []
    assert not any("DROP DATABASE" in a for a in _appels(appels_docker))


def test_restore_reprise_base_absente_sans_copie_et_sans_toucher_aux_anciennes(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env["FAUX_BASE_ABSENTE"] = "1"
    sauvegardes = tmp_path / "sauvegardes"
    sauvegardes.mkdir()
    ancienne = sauvegardes / "avant-restauration-base_fictive-20200101-000000.dump"
    ancienne.write_text("première copie", encoding="utf-8")

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 0, resultat.stderr
    appels = _appels(appels_docker)
    assert not any(" pg_dump " in a for a in appels)
    assert any("DROP DATABASE" in a for a in appels)
    assert "absente" in resultat.stdout
    assert "aucune copie de sécurité" in resultat.stdout
    assert _copies(tmp_path) == [ancienne]
    assert ancienne.read_text(encoding="utf-8") == "première copie"


def test_test_restauration_lit_les_documents_10001_par_le_conteneur_root() -> None:
    script = (REPO_ROOT / "deploy" / "test-restauration.sh").read_text(encoding="utf-8")
    assert 'if [[ -f "$DOCUMENT_UID_10001" ]]' not in script
    assert "if sh_root \"test -f '$DOCUMENT_UID_10001'\"; then" in script


def test_restauration_md_documente_le_retour_arriere_exact() -> None:
    doc = (REPO_ROOT / "deploy" / "RESTAURATION.md").read_text(encoding="utf-8")
    assert "Retour arrière avec la copie de sécurité" in doc
    assert "pg_restore --no-owner" in doc
    assert "première" in doc and "copie de sécurité" in doc
    assert ".restaure-*" in doc and "sudo rm -rf" in doc


@pytest.mark.parametrize("variable", ["FAUX_PGDUMP_RC", "FAUX_LISTE_COPIE_RC"])
def test_restore_dit_que_l_api_est_arretee_et_comment_la_redemarrer(
    tmp_path: Path, variable: str
) -> None:
    """Constat final 4 : une sortie de la phase « copie de sécurité » arrive
    après l'arrêt de l'API ; le message le dit et donne la commande exacte."""
    env, appels_docker = _environnement_restore(tmp_path)
    _preparer_faux_docker_complet(tmp_path, env)
    env[variable] = "1"

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode != 0
    assert any("stop api" in a for a in _appels(appels_docker))
    assert "Base non touchée" in resultat.stderr
    assert "API est ARRÊTÉE" in resultat.stderr
    assert "docker compose" in resultat.stderr
    assert "start api" in resultat.stderr
