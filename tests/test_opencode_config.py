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

# Modèles admis par OpenCode 1.18.32 avec l'abonnement ChatGPT : liste
# relevée le 29/09/2026 sur le serveur réel une fois l'abonnement connecté
# (`GET /config/providers`, fournisseur `openai`) — sous-ensemble utile.
# Les agents utilisent `gpt-5.6-sol` depuis le 29/09 (choix d'Ilane).
MODELES_ADMIS = {
    "openai/gpt-5.6-sol",
    "openai/gpt-5.6-sol-fast",
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
    """`websearch`/`webfetch` ne sont autorisés nulle part ailleurs, et aucun
    agent n'autorise un autre outil (`read`, `bash`, `edit`, ...).

    Seule exception, pour les trois agents : `StructuredOutput`, l'outil
    interne par lequel OpenCode rend la réponse au format JSON imposé
    (`format: json_schema`). Constaté le 29/09/2026 sur le serveur réel :
    sans cette autorisation, `"*": "deny"` retire aussi cet outil avant
    l'appel au modèle (`session/llm/request.ts::resolveTools`, OpenCode
    1.18.32) — « Model did not produce structured output » pour la synthèse
    et l'explication, et une recherche de prix qui tourne jusqu'au délai.
    La règle `"*"` doit venir en premier : la dernière règle qui correspond
    l'emporte."""
    config = _opencode_json()
    for nom, agent in config["agent"].items():
        permission = agent["permission"]
        assert next(iter(permission)) == "*", nom
        assert permission["*"] == "deny", nom
        autorisations = {cle: val for cle, val in permission.items() if cle != "*"}
        if nom == "habitat-prix":
            assert autorisations == {
                "StructuredOutput": "allow",
                "websearch": "allow",
                "webfetch": "allow",
            }, nom
        else:
            assert autorisations == {"StructuredOutput": "allow"}, nom


def test_dockerfile_rend_le_cache_opencode_inscriptible() -> None:
    """Fix round 1 (T8, essai en direct sur l'image construite) : `npm
    install -g` tourne en root avec `$HOME=/home/opencode` déjà fixé, donc
    `.cache` (dont `.cache/opencode`) est créé `root:root` à l'installation
    -- constaté en direct par un `EACCES` au démarrage (`opencode serve` ne
    peut plus écrire son cache de modèles). Le `chown` doit venir dans le
    `RUN` qui installe le paquet (ou juste après), jamais avant : un
    `chown` placé plus haut serait écrasé par l'installation elle-même."""
    dockerfile = (DEPLOY_OPENCODE / "Dockerfile").read_text(encoding="utf-8")
    indice_install = dockerfile.index("npm install -g opencode-ai")
    apres_install = dockerfile[indice_install:]
    assert "chown -R opencode:opencode /home/opencode/.cache" in apres_install


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
