"""Exploitation de l'IA (T8, phase 4) : `deploy/opencode/opencode.json` (les
trois agents et leurs permissions), `deploy/opencode/docker-compose.yml`
(durcissement, aucun port publié) et `deploy/docker-compose.ia.yml`
(rattachement du réseau) sont des fichiers statiques du dépôt -- ces tests ne
font que les relire et les valider, sans docker ni réseau.

`deploy/opencode/.env` doit rester ignoré par git (secret, jamais commité) ;
`exemple.env`, son modèle, doit au contraire être suivi."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_OPENCODE = REPO_ROOT / "deploy" / "opencode"
# Chemin complet (jamais un nom nu) : `git` est résolu une seule fois, ici,
# plutôt que laissé à la recherche de `subprocess` dans `PATH` à chaque appel.
GIT = shutil.which("git") or "/usr/bin/git"

# Modèles admis par OpenCode 1.18.32 avec l'abonnement ChatGPT (faits
# vérifiés le 27/09/2026, brief T8).
MODELES_ADMIS = {
    "openai/gpt-5.5",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.3-codex-spark",
}

AGENTS_ATTENDUS = {"habitat-synthese", "habitat-explication", "habitat-prix"}


def _opencode_json() -> dict[str, Any]:
    with (DEPLOY_OPENCODE / "opencode.json").open(encoding="utf-8") as fichier:
        return cast("dict[str, Any]", json.load(fichier))


def _compose(chemin: Path) -> dict[str, Any]:
    with chemin.open(encoding="utf-8") as fichier:
        return cast("dict[str, Any]", yaml.safe_load(fichier))


def test_opencode_json_est_un_json_valide() -> None:
    config = _opencode_json()
    assert isinstance(config, dict)


def test_autoupdate_et_partage_desactives() -> None:
    config = _opencode_json()
    assert config["autoupdate"] is False
    assert config["share"] == "disabled"


def test_permission_globale_refuse_tout() -> None:
    config = _opencode_json()
    assert config["permission"] == {"*": "deny"}


def test_les_trois_agents_attendus_sont_presents() -> None:
    config = _opencode_json()
    assert set(config["agent"].keys()) == AGENTS_ATTENDUS


def test_chaque_agent_est_primaire_avec_une_description_et_une_consigne() -> None:
    config = _opencode_json()
    for nom, agent in config["agent"].items():
        assert agent["mode"] == "primary", nom
        assert isinstance(agent["description"], str) and agent["description"], nom
        assert isinstance(agent["prompt"], str) and len(agent["prompt"]) > 50, nom


def test_modeles_des_agents_parmi_ceux_admis() -> None:
    config = _opencode_json()
    for nom, agent in config["agent"].items():
        assert agent["model"] in MODELES_ADMIS, nom


def test_nombre_d_etapes_par_agent() -> None:
    config = _opencode_json()
    assert config["agent"]["habitat-synthese"]["steps"] == 3
    assert config["agent"]["habitat-explication"]["steps"] == 3
    assert config["agent"]["habitat-prix"]["steps"] == 8


def test_seul_habitat_prix_a_le_droit_de_chercher_ou_lire_le_web() -> None:
    """`websearch`/`webfetch` ne sont autorisés nulle part ailleurs : les deux
    autres agents gardent une permission strictement `{"*": "deny"}`, et
    aucun agent n'autorise un autre outil (`read`, `bash`, `edit`, ...)."""
    config = _opencode_json()
    for nom, agent in config["agent"].items():
        permission = agent["permission"]
        assert permission["*"] == "deny", nom
        autorisations = {cle: val for cle, val in permission.items() if cle != "*"}
        if nom == "habitat-prix":
            assert autorisations == {"websearch": "allow", "webfetch": "allow"}, nom
        else:
            assert autorisations == {}, nom


def test_compose_opencode_ne_publie_aucun_port() -> None:
    config = _compose(DEPLOY_OPENCODE / "docker-compose.yml")
    assert config["name"] == "habitat_ia"
    service = config["services"]["opencode"]
    assert "ports" not in service


def test_compose_opencode_est_durci() -> None:
    config = _compose(DEPLOY_OPENCODE / "docker-compose.yml")
    service = config["services"]["opencode"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["cap_drop"] == ["ALL"]
    assert service["pids_limit"] == 200
    assert service["mem_limit"] == "512m"
    assert service["restart"] == "unless-stopped"


def test_compose_opencode_mot_de_passe_obligatoire_et_cle_exa_facultative() -> None:
    config = _compose(DEPLOY_OPENCODE / "docker-compose.yml")
    environnement = config["services"]["opencode"]["environment"]
    assert environnement["OPENCODE_SERVER_PASSWORD"].startswith(
        "${OPENCODE_SERVER_PASSWORD:?"
    )
    assert environnement["EXA_API_KEY"] == "${EXA_API_KEY:-}"
    assert environnement["OPENCODE_ENABLE_EXA"] == "1"
    assert environnement["OPENCODE_WEBSEARCH_PROVIDER"] == "exa"
    assert config["services"]["opencode"]["env_file"] == [".env"]


def test_compose_opencode_donnees_sur_volume_nomme() -> None:
    config = _compose(DEPLOY_OPENCODE / "docker-compose.yml")
    volumes = config["services"]["opencode"]["volumes"]
    assert "opencode-donnees:/home/opencode/.local/share/opencode" in volumes
    assert "opencode-donnees" in config["volumes"]
    assert config["networks"]["default"]["name"] == "habitat_ia"


def test_surcouche_ia_rattache_api_au_reseau_externe_en_plus_du_defaut() -> None:
    config = _compose(REPO_ROOT / "deploy" / "docker-compose.ia.yml")
    reseaux = config["services"]["api"]["networks"]
    assert set(reseaux) == {"default", "habitat_ia"}
    assert config["networks"]["habitat_ia"]["external"] is True


def test_surcouche_ia_variables_avec_defauts_surs() -> None:
    config = _compose(REPO_ROOT / "deploy" / "docker-compose.ia.yml")
    environnement = config["services"]["api"]["environment"]
    assert environnement["IA_ACTIVE"] == "${IA_ACTIVE:-false}"
    assert environnement["OPENCODE_URL"] == "${OPENCODE_URL:-http://opencode:4096}"
    assert environnement["OPENCODE_MOT_DE_PASSE"] == "${OPENCODE_MOT_DE_PASSE:-}"
    assert environnement["IA_APPELS_MAX_JOUR"] == "${IA_APPELS_MAX_JOUR:-40}"


def test_env_opencode_ignore_par_git_mais_pas_son_modele() -> None:
    ignore = subprocess.run(  # noqa: S603 -- chemin complet, arguments fixes
        [GIT, "check-ignore", "-q", "deploy/opencode/.env"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ignore.returncode == 0, "deploy/opencode/.env devrait être ignoré par git"

    suivi = subprocess.run(  # noqa: S603 -- chemin complet, arguments fixes
        [GIT, "check-ignore", "-q", "deploy/opencode/exemple.env"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert suivi.returncode == 1, "exemple.env ne doit pas être ignoré par git"
