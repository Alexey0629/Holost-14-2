"""Пошук проектів на диску, визначення стеку та статистика коду."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from . import fs

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

# Файли/папки, за якими папка вважається проектом з кодом.
PROJECT_MARKERS = (
    ".git",
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "manage.py",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "Gemfile",
    "CMakeLists.txt",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
    "pubspec.yaml",
)

PY_FRAMEWORKS = {
    "flask": "Flask",
    "django": "Django",
    "fastapi": "FastAPI",
    "sqlalchemy": "SQLAlchemy",
    "flask-sqlalchemy": "SQLAlchemy",
    "aiogram": "aiogram",
    "python-telegram-bot": "Telegram Bot",
    "pytest": "pytest",
    "celery": "Celery",
    "pandas": "pandas",
    "streamlit": "Streamlit",
    "scrapy": "Scrapy",
    "selenium": "Selenium",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
}

JS_FRAMEWORKS = {
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "nuxt": "Nuxt",
    "svelte": "Svelte",
    "@angular/core": "Angular",
    "express": "Express",
    "@nestjs/core": "NestJS",
    "electron": "Electron",
    "vite": "Vite",
    "jest": "Jest",
    "vitest": "Vitest",
    "prisma": "Prisma",
    "@prisma/client": "Prisma",
    "typescript": "TypeScript",
}


def looks_like_project(path: Path) -> bool:
    return any((path / marker).exists() for marker in PROJECT_MARKERS)


def discover(roots: list[str], max_depth: int = 3) -> list[Path]:
    """Знаходить проекти в зазначених папках (не заглиблюючись у знайдені проекти)."""
    found: list[Path] = []
    seen: set[Path] = set()

    def visit(path: Path, depth: int) -> None:
        try:
            real = path.resolve()
        except OSError:
            return
        if real in seen:
            return
        seen.add(real)
        if looks_like_project(real):
            found.append(real)
            return
        if depth >= max_depth:
            return
        try:
            children = sorted(p for p in real.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or fs.is_ignored_dir(child.name):
                continue
            visit(child, depth + 1)

    for root in roots:
        root = (root or "").strip()
        if not root:
            continue
        p = Path(root).expanduser()
        if p.is_dir():
            visit(p, 0)
    return found


# ------------------------------------------------------------------ стек


def _requirements(root: Path) -> list[str]:
    names = []
    for f in sorted(root.glob("requirements*.txt")):
        text = fs.read_text_quick(f) or ""
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            names.append(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower())
    return names


def pyproject(root: Path) -> dict:
    f = root / "pyproject.toml"
    if not f.exists() or tomllib is None:
        return {}
    try:
        return tomllib.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def package_json(root: Path) -> dict:
    try:
        return json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def python_dependencies(root: Path) -> list[str]:
    deps = _requirements(root)
    data = pyproject(root)
    for dep in (data.get("project") or {}).get("dependencies") or []:
        deps.append(re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0].lower())
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    deps.extend(k.lower() for k in poetry if k.lower() != "python")
    return sorted(set(filter(None, deps)))


def detect_stack(root: Path) -> list[str]:
    stack: list[str] = []

    def add(name: str) -> None:
        if name not in stack:
            stack.append(name)

    py_deps = python_dependencies(root)
    if py_deps or (root / "setup.py").exists() or (root / "manage.py").exists() or any(root.glob("*.py")):
        add("Python")
    for dep in py_deps:
        if dep in PY_FRAMEWORKS:
            add(PY_FRAMEWORKS[dep])
    if (root / "manage.py").exists():
        add("Django")

    pkg = package_json(root)
    if pkg:
        add("Node.js")
        all_deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        for dep, label in JS_FRAMEWORKS.items():
            if dep in all_deps:
                add(label)
    if (root / "go.mod").exists():
        add("Go")
    if (root / "Cargo.toml").exists():
        add("Rust")
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        add("Java/Kotlin")
    if (root / "composer.json").exists():
        add("PHP")
    if (root / "Gemfile").exists():
        add("Ruby")
    if (root / "pubspec.yaml").exists():
        add("Flutter")
    if (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists() or (root / "compose.yaml").exists():
        add("Docker")
    if not stack and (any(root.glob("*.html"))):
        add("HTML")
    return stack


def find_readme(root: Path) -> Path | None:
    for name in ("README.md", "readme.md", "Readme.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            return p
    return None


def readme_summary(root: Path) -> str:
    """Перший змістовний абзац README — як короткий опис при імпорті проекту."""
    readme = find_readme(root)
    if not readme:
        return ""
    text = fs.read_text_quick(readme, 512 * 1024) or ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block or block.startswith(("#", "!", "[!", "<", "```", "=", "-")):
            continue
        line = " ".join(block.split())
        return line[:300]
    return ""


# ------------------------------------------------------------------ статистика


def stats(root: Path, max_files: int = 20000) -> dict:
    files = 0
    total_size = 0
    lines_by_lang: Counter = Counter()
    files_by_lang: Counter = Counter()
    largest: list[tuple[int, str]] = []
    total_lines = 0
    for path in fs.walk_files(root, max_files=max_files):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        files += 1
        total_size += size
        largest.append((size, fs.rel_path(root, path)))
        lang = fs.language_of(path)
        if not lang:
            continue
        files_by_lang[lang] += 1
        if size <= 1024 * 1024:
            try:
                with open(path, "rb") as fh:
                    n = sum(1 for _ in fh)
            except OSError:
                n = 0
            lines_by_lang[lang] += n
            total_lines += n
    largest.sort(reverse=True)
    languages = [
        {"language": lang, "files": files_by_lang[lang], "lines": lines_by_lang[lang]}
        for lang in sorted(files_by_lang, key=lambda k: (-lines_by_lang[k], -files_by_lang[k]))
    ]
    key_files = [
        name for name in (
            "README.md", "requirements.txt", "pyproject.toml", "package.json", "Dockerfile",
            "docker-compose.yml", "Makefile", ".env.example", ".gitignore", "setup.py", "manage.py",
            "app.py", "main.py", "run.py", "go.mod", "Cargo.toml", "tsconfig.json", "pytest.ini",
        ) if (root / name).exists()
    ]
    return {
        "files": files,
        "size": total_size,
        "lines": total_lines,
        "languages": languages,
        "largest": [{"path": p, "size": s} for s, p in largest[:15]],
        "key_files": key_files,
        "truncated": files >= max_files,
        "dirs": sum(1 for _ in _iter_dirs(root)),
    }


def _iter_dirs(root: Path):
    for _dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not fs.is_ignored_dir(d)]
        yield from dirnames
