"""Запуск команд проекту (тести, оновлення з проду) з таймаутом і обрізанням виводу."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

MAX_OUTPUT = 400_000  # символів виводу, які зберігаємо


def _trim(output: str) -> str:
    if len(output) <= MAX_OUTPUT:
        return output
    return "… (початок виводу обрізано)\n" + output[-MAX_OUTPUT:]


def run_command(command: str, cwd: Path | str, timeout: int = 600, env: dict | None = None) -> dict:
    """Запускає shell-команду в папці проекту. Ніколи не кидає виняток через саму команду."""
    full_env = os.environ.copy()
    full_env.update({"PYTHONUNBUFFERED": "1", "CI": "1", "NO_COLOR": "1", "FORCE_COLOR": "0",
                     "GIT_TERMINAL_PROMPT": "0"})
    # Не передаємо проекту віртуальне оточення самого Holost.
    full_env.pop("VIRTUAL_ENV", None)
    if env:
        full_env.update(env)

    started_at = datetime.now().isoformat(timespec="seconds")
    start = time.monotonic()
    popen_kwargs = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    else:  # pragma: no cover - Windows
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=full_env,
            **popen_kwargs,
        )
    except OSError as exc:
        return {"exit_code": -1, "output": f"Не вдалося запустити команду: {exc}", "timed_out": False,
                "duration": 0.0, "started_at": started_at}

    timed_out = False
    try:
        raw, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(proc)
        raw, _ = proc.communicate()
    output = raw.decode("utf-8", errors="replace") if raw else ""
    if timed_out:
        output += f"\n\n⏱ Команду зупинено: перевищено ліміт {timeout} с."
    return {
        "exit_code": proc.returncode,
        "output": _trim(output),
        "timed_out": timed_out,
        "duration": round(time.monotonic() - start, 2),
        "started_at": started_at,
    }


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


# ------------------------------------------------------------ автодетект команд


def project_python(root: Path) -> str:
    """Python із віртуального оточення проекту, якщо воно є."""
    for venv in ("venv", ".venv", "env"):
        unix = root / venv / "bin" / "python"
        win = root / venv / "Scripts" / "python.exe"
        if unix.exists():
            return f"{venv}/bin/python"
        if win.exists():  # pragma: no cover
            return f"{venv}\\Scripts\\python.exe"
    return "python3" if os.name == "posix" else "python"


def _package_json(root: Path) -> dict:
    try:
        return json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _has_python_tests(root: Path) -> bool:
    if (root / "pytest.ini").exists() or (root / "conftest.py").exists():
        return True
    for name in ("pyproject.toml", "setup.cfg", "tox.ini"):
        f = root / name
        if f.exists():
            try:
                if "pytest" in f.read_text(encoding="utf-8", errors="ignore"):
                    return True
            except OSError:
                pass
    for folder in ("tests", "test"):
        if (root / folder).is_dir() and any((root / folder).rglob("test*.py")):
            return True
    return any(root.glob("test_*.py")) or any(root.glob("*_test.py"))


def _makefile_targets(root: Path) -> set[str]:
    mk = root / "Makefile"
    if not mk.exists():
        return set()
    targets = set()
    try:
        for line in mk.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line and not line[0].isspace() and ":" in line and not line.startswith((".", "#")):
                name = line.split(":", 1)[0].strip()
                if name and " " not in name and "=" not in name:
                    targets.add(name)
    except OSError:
        pass
    return targets


def detect_test_command(root: Path) -> str:
    if "test" in _makefile_targets(root):
        return "make test"
    if _has_python_tests(root):
        return f"{project_python(root)} -m pytest -q"
    scripts = _package_json(root).get("scripts") or {}
    if "test" in scripts and "no test specified" not in str(scripts.get("test")):
        return "npm test"
    if (root / "go.mod").exists():
        return "go test ./..."
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "manage.py").exists():
        return f"{project_python(root)} manage.py test"
    if (root / "pom.xml").exists():
        return "mvn -q test"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "./gradlew test"
    if (root / "composer.json").exists():
        return "vendor/bin/phpunit"
    return ""


def detect_run_command(root: Path) -> str:
    py = project_python(root)
    if (root / "manage.py").exists():
        return f"{py} manage.py runserver"
    scripts = _package_json(root).get("scripts") or {}
    for name in ("dev", "start", "serve"):
        if name in scripts:
            return f"npm run {name}" if name != "start" else "npm start"
    for name in ("run.py", "app.py", "main.py", "server.py", "wsgi.py"):
        if (root / name).exists():
            return f"{py} {name}"
    if (root / "go.mod").exists():
        return "go run ."
    if (root / "Cargo.toml").exists():
        return "cargo run"
    if "run" in _makefile_targets(root):
        return "make run"
    if (root / "docker-compose.yml").exists() or (root / "compose.yaml").exists():
        return "docker compose up"
    return ""


def detect_install_command(root: Path) -> str:
    if (root / "requirements.txt").exists():
        return f"{project_python(root)} -m pip install -r requirements.txt"
    if (root / "pyproject.toml").exists():
        return f"{project_python(root)} -m pip install -e ."
    if (root / "package.json").exists():
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm install"
        if (root / "yarn.lock").exists():
            return "yarn install"
        return "npm install"
    if (root / "go.mod").exists():
        return "go mod download"
    if (root / "Cargo.toml").exists():
        return "cargo build"
    if (root / "composer.json").exists():
        return "composer install"
    if (root / "Gemfile").exists():
        return "bundle install"
    return ""
