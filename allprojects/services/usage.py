"""«Структура використання»: як запускати проект, точки входу, залежності, скрипти, змінні оточення."""
from __future__ import annotations

import re
from pathlib import Path

from . import fs, runner, scanner

ENTRY_NAMES = (
    "main.py", "app.py", "run.py", "manage.py", "wsgi.py", "asgi.py", "server.py", "bot.py", "cli.py",
    "__main__.py", "index.js", "server.js", "app.js", "main.js", "src/index.js", "src/index.ts", "src/main.ts",
    "src/main.js", "src/main.tsx", "src/index.tsx", "main.go", "cmd/main.go", "src/main.rs", "index.php",
    "index.html",
)

CONFIG_FILES = (
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml", "Makefile", "Procfile",
    "pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", "requirements.txt", "requirements-dev.txt",
    "package.json", "tsconfig.json", "vite.config.js", "vite.config.ts", "webpack.config.js", ".env.example",
    ".env.sample", ".env.template", ".gitignore", ".editorconfig", "alembic.ini", "nginx.conf", "go.mod",
    "Cargo.toml", "composer.json", "Gemfile", ".pre-commit-config.yaml",
)

_ENV_PY = re.compile(r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]|os\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]")
_ENV_JS = re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)|process\.env\[['\"]([A-Z][A-Z0-9_]*)['\"]\]")
_MAIN_GUARD = re.compile(r"^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", re.M)


def _env_file_keys(path: Path) -> list[str]:
    """Тільки назви змінних — значення (секрети) не показуємо."""
    text = fs.read_text_quick(path, 256 * 1024) or ""
    keys = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].replace("export ", "").strip()
        if key:
            keys.append(key)
    return keys


def _makefile_targets(root: Path) -> list[dict]:
    mk = root / "Makefile"
    if not mk.exists():
        return []
    targets = []
    lines = (fs.read_text_quick(mk) or "").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*:(?!=)", line)
        if m and not m.group(1).startswith("."):
            body = []
            for nxt in lines[i + 1:i + 4]:
                if nxt.startswith("\t"):
                    body.append(nxt.strip())
                else:
                    break
            targets.append({"name": f"make {m.group(1)}", "command": " && ".join(body)})
    return targets


def _compose_services(root: Path) -> list[str]:
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"):
        f = root / name
        if not f.exists():
            continue
        services, inside = [], False
        for line in (fs.read_text_quick(f) or "").splitlines():
            if re.match(r"^services\s*:", line):
                inside = True
                continue
            if inside:
                if line and not line[0].isspace():
                    break
                m = re.match(r"^ {2}([\w.\-]+)\s*:", line)
                if m:
                    services.append(m.group(1))
        return services
    return []


def analyze(root: Path) -> dict:
    # Точки входу
    entries = [name for name in ENTRY_NAMES if (root / name).is_file()]
    env_used: set[str] = set()
    main_guards: list[str] = []
    for path in fs.walk_files(root, max_files=5000):
        suffix = path.suffix.lower()
        if suffix not in {".py", ".js", ".ts", ".mjs", ".cjs"}:
            continue
        text = fs.read_text_quick(path, 512 * 1024)
        if not text:
            continue
        rel = fs.rel_path(root, path)
        if suffix == ".py":
            for m in _ENV_PY.finditer(text):
                env_used.add(m.group(1) or m.group(2))
            if _MAIN_GUARD.search(text) and rel not in entries and "test" not in rel.lower():
                main_guards.append(rel)
        else:
            for m in _ENV_JS.finditer(text):
                env_used.add(m.group(1) or m.group(2))
    entries.extend(main_guards[:20])

    # Залежності
    dependencies: dict[str, list[str]] = {}
    py = scanner.python_dependencies(root)
    if py:
        dependencies["Python"] = py
    pkg = scanner.package_json(root)
    if pkg.get("dependencies"):
        dependencies["npm"] = sorted(pkg["dependencies"])
    if pkg.get("devDependencies"):
        dependencies["npm (dev)"] = sorted(pkg["devDependencies"])
    gomod = root / "go.mod"
    if gomod.exists():
        deps = re.findall(r"^\s*([\w./\-]+)\s+v[\d.]+", fs.read_text_quick(gomod) or "", re.M)
        if deps:
            dependencies["Go"] = deps

    # Скрипти / команди
    scripts = []
    for name, cmd in (pkg.get("scripts") or {}).items():
        scripts.append({"name": f"npm run {name}", "command": str(cmd)})
    scripts.extend(_makefile_targets(root))
    proj = scanner.pyproject(root).get("project") or {}
    for name, target in (proj.get("scripts") or {}).items():
        scripts.append({"name": name, "command": str(target)})
    procfile = root / "Procfile"
    if procfile.exists():
        for line in (fs.read_text_quick(procfile) or "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                scripts.append({"name": f"Procfile {k.strip()}", "command": v.strip()})

    # Змінні оточення
    env_files = {}
    for name in (".env.example", ".env.sample", ".env.template", ".env"):
        f = root / name
        if f.is_file():
            env_files[name] = _env_file_keys(f)

    return {
        "commands": {
            "install": runner.detect_install_command(root),
            "run": runner.detect_run_command(root),
            "test": runner.detect_test_command(root),
        },
        "entry_points": entries,
        "dependencies": dependencies,
        "scripts": scripts,
        "env_files": env_files,
        "env_used": sorted(env_used),
        "config_files": [name for name in CONFIG_FILES if (root / name).exists()],
        "ci": sorted(fs.rel_path(root, p) for p in (root / ".github" / "workflows").glob("*.y*ml"))
        if (root / ".github" / "workflows").is_dir() else [],
        "docker_services": _compose_services(root),
    }
