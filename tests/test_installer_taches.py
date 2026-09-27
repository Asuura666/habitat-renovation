"""Tâches planifiées (phase 2, 27/09/2026) : `deploy/installer-taches.sh`
écrit les timers systemd utilisateur d'une instance, `deploy/alerte-echec.sh`
prévient le canal de supervision quand une tâche échoue.

Aucun appel à systemctl ni au réseau : l'installateur écrit dans un dossier
temporaire (`--dossier`, qui implique `--sans-activer`), et l'alerte est
testée avec un faux `curl` placé en tête du PATH. Les fichiers `.env` sont
inventés (jamais les vrais `.env.prod`/`.env.demo`)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLEUR = REPO_ROOT / "deploy" / "installer-taches.sh"
ALERTE = REPO_ROOT / "deploy" / "alerte-echec.sh"

JETON_INVENTE = "123456:jeton-invente-pour-le-test"


def _env_file(tmp_path: Path, *, restic: bool = True) -> Path:
    lignes = [
        f"TELEGRAM_BOT_TOKEN={JETON_INVENTE}",
        "TELEGRAM_CHAT_SUPERVISION_ID=-1000000000002",
    ]
    if restic:
        lignes += ["RESTIC_REPOSITORY=/tmp/depot-invente", "RESTIC_PASSWORD=invente"]
    fichier = tmp_path / "env-invente"
    fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return fichier


def _installer(
    tmp_path: Path, *args: str, env_file: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HABITAT_RENO_ENV_FILE"] = str(env_file or _env_file(tmp_path))
    return subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(INSTALLEUR), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installe_les_trois_taches_de_la_production(tmp_path: Path) -> None:
    dossier = tmp_path / "unites"
    resultat = _installer(tmp_path, "prod", "--dossier", str(dossier))

    assert resultat.returncode == 0, resultat.stderr
    noms = sorted(p.name for p in dossier.iterdir())
    assert noms == [
        "habitat-prod-alerte@.service",
        "habitat-prod-controles.service",
        "habitat-prod-controles.timer",
        "habitat-prod-photos.service",
        "habitat-prod-photos.timer",
        "habitat-prod-sauvegarde.service",
        "habitat-prod-sauvegarde.timer",
    ]
    sauvegarde = (dossier / "habitat-prod-sauvegarde.service").read_text(
        encoding="utf-8"
    )
    assert "OnFailure=habitat-prod-alerte@%n.service" in sauvegarde
    assert f"ExecStart={REPO_ROOT}/deploy/backup.sh" in sauvegarde
    assert "Environment=COMPOSE_PROJECT_NAME=habitat_prod" in sauvegarde
    assert "Environment=HABITAT_RENO_ENV_FILE=" in sauvegarde

    controles = (dossier / "habitat-prod-controles.service").read_text(encoding="utf-8")
    assert "-p habitat_prod" in controles
    assert "deploy/docker-compose.vps.yml" in controles
    assert controles.rstrip().endswith(
        "exec -T api python -m app.cli controles-differes"
    )

    photos = (dossier / "habitat-prod-photos.service").read_text(encoding="utf-8")
    assert photos.rstrip().endswith("exec -T api python -m app.cli ranger-photos")

    minuterie = (dossier / "habitat-prod-sauvegarde.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 03:00:00 Europe/Paris" in minuterie
    assert "Persistent=true" in minuterie
    assert "WantedBy=timers.target" in minuterie

    alerte = (dossier / "habitat-prod-alerte@.service").read_text(encoding="utf-8")
    assert f"ExecStart={REPO_ROOT}/deploy/alerte-echec.sh prod %i" in alerte


def _calendrier(minuterie: str) -> str:
    return next(
        ligne for ligne in minuterie.splitlines() if ligne.startswith("OnCalendar=")
    )


def test_la_demo_ne_tourne_jamais_en_meme_temps_que_la_production(
    tmp_path: Path,
) -> None:
    prod, demo = tmp_path / "prod", tmp_path / "demo"
    assert _installer(tmp_path, "prod", "--dossier", str(prod)).returncode == 0
    assert _installer(tmp_path, "demo", "--dossier", str(demo)).returncode == 0

    for tache in ("sauvegarde", "controles", "photos"):
        heure_prod = (prod / f"habitat-prod-{tache}.timer").read_text(encoding="utf-8")
        heure_demo = (demo / f"habitat-demo-{tache}.timer").read_text(encoding="utf-8")
        assert _calendrier(heure_prod) != _calendrier(heure_demo)


def test_sauvegarde_refusee_sans_depot_restic(tmp_path: Path) -> None:
    dossier = tmp_path / "unites"
    resultat = _installer(
        tmp_path,
        "prod",
        "--dossier",
        str(dossier),
        env_file=_env_file(tmp_path, restic=False),
    )

    assert resultat.returncode == 1
    assert "RESTIC_REPOSITORY absent" in resultat.stderr
    assert not dossier.exists()


def test_sous_ensemble_de_taches_sans_sauvegarde(tmp_path: Path) -> None:
    dossier = tmp_path / "unites"
    resultat = _installer(
        tmp_path,
        "prod",
        "--taches",
        "controles,photos",
        "--dossier",
        str(dossier),
        env_file=_env_file(tmp_path, restic=False),
    )

    assert resultat.returncode == 0, resultat.stderr
    assert not (dossier / "habitat-prod-sauvegarde.timer").exists()
    assert (dossier / "habitat-prod-controles.timer").exists()
    assert (dossier / "habitat-prod-photos.timer").exists()


def test_instance_inconnue_refusee(tmp_path: Path) -> None:
    resultat = _installer(tmp_path, "staging", "--dossier", str(tmp_path / "u"))

    assert resultat.returncode == 2
    assert "instance inconnue" in resultat.stderr


def _faux_curl(tmp_path: Path, code_http: str) -> Path:
    """Faux `curl` : enregistre sa configuration (entrée standard) et ses
    arguments, puis répond `code_http` comme `--write-out '%{http_code}'`."""
    dossier = tmp_path / "bin"
    dossier.mkdir()
    script = dossier / "curl"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'cat > "{tmp_path}/config-curl"\n'
        f'printf "%s\\n" "$@" > "{tmp_path}/args-curl"\n'
        f'printf "{code_http}"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return dossier


def _alerter(
    tmp_path: Path, env_file: Path, code_http: str = "200"
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HABITAT_RENO_ENV_FILE"] = str(env_file)
    env["PATH"] = f"{_faux_curl(tmp_path, code_http)}:{env['PATH']}"
    return subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(ALERTE), "prod", "habitat-prod-sauvegarde.service"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_alerte_envoyee_sans_jeton_dans_la_ligne_de_commande(tmp_path: Path) -> None:
    resultat = _alerter(tmp_path, _env_file(tmp_path))

    assert resultat.returncode == 0, resultat.stderr
    arguments = (tmp_path / "args-curl").read_text(encoding="utf-8")
    assert JETON_INVENTE not in arguments
    assert JETON_INVENTE in (tmp_path / "config-curl").read_text(encoding="utf-8")
    assert "chat_id=-1000000000002" in arguments
    assert "habitat-prod-sauvegarde.service" in arguments
    assert JETON_INVENTE not in resultat.stdout + resultat.stderr


def test_alerte_echoue_si_telegram_refuse(tmp_path: Path) -> None:
    resultat = _alerter(tmp_path, _env_file(tmp_path), code_http="404")

    assert resultat.returncode == 1
    assert "HTTP 404" in resultat.stderr
    assert JETON_INVENTE not in resultat.stdout + resultat.stderr


def test_alerte_refusee_sans_jeton(tmp_path: Path) -> None:
    fichier = tmp_path / "env-vide"
    fichier.write_text("TELEGRAM_CHAT_SUPERVISION_ID=-1\n", encoding="utf-8")

    resultat = _alerter(tmp_path, fichier)

    assert resultat.returncode == 1
    assert "jeton ou canal de supervision absent" in resultat.stderr
    assert not (tmp_path / "args-curl").exists()


def _faux_systemctl(tmp_path: Path) -> Path:
    """Faux `systemctl` : note chaque appel (il ne doit y en avoir aucun en
    mode essai)."""
    dossier = tmp_path / "bin-systemctl"
    dossier.mkdir()
    script = dossier / "systemctl"
    script.write_text(
        f'#!/usr/bin/env bash\necho "$@" >> "{tmp_path}/appels-systemctl"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return dossier


def test_desinstaller_en_essai_ne_touche_jamais_systemd(tmp_path: Path) -> None:
    dossier = tmp_path / "unites"
    assert _installer(tmp_path, "prod", "--dossier", str(dossier)).returncode == 0
    env = dict(os.environ)
    env["HABITAT_RENO_ENV_FILE"] = str(_env_file(tmp_path))
    env["PATH"] = f"{_faux_systemctl(tmp_path)}:{env['PATH']}"

    resultat = subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(INSTALLEUR), "prod", "--desinstaller", "--dossier", str(dossier)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultat.returncode == 0, resultat.stderr
    assert not (tmp_path / "appels-systemctl").exists()
    assert list(dossier.iterdir()) == []


def test_tache_inconnue_refusee_avant_toute_ecriture(tmp_path: Path) -> None:
    dossier = tmp_path / "unites"
    resultat = _installer(
        tmp_path, "prod", "--taches", "controles,inconnue", "--dossier", str(dossier)
    )

    assert resultat.returncode == 2
    assert "tâche inconnue" in resultat.stderr
    assert not dossier.exists()
