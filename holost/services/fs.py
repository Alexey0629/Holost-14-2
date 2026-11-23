"""Робота з файлами проекту: безпечні шляхи, читання/запис, дерево, обхід."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator

# Папки, які не потрібні для аналізу коду (залежності, кеші, збірки).
IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "bower_components",
    "venv",
    ".venv",
    "env",
    ".env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    ".next",
    ".nuxt",
    ".cache",
    "dist",
    "build",
    "target",
    "vendor",
    "coverage",
    "htmlcov",
    ".gradle",
    ".terraform",
    "Pods",
    "DerivedData",
}

MAX_EDIT_SIZE = 2 * 1024 * 1024  # 2 МБ — більше в редакторі не відкриваємо

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".avif"}

LANGUAGES = {
    ".py": "Python",
    ".pyw": "Python",
    ".ipynb": "Jupyter",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".html": "HTML",
    ".htm": "HTML",
    ".jinja": "HTML",
    ".jinja2": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SCSS",
    ".less": "Less",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "INI",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".txt": "Text",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".bat": "Batch",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".dart": "Dart",
    ".lua": "Lua",
    ".r": "R",
    ".xml": "XML",
    ".graphql": "GraphQL",
    ".proto": "Protobuf",
}

SPECIAL_FILES = {"Dockerfile": "Dockerfile", "Makefile": "Makefile", "Procfile": "Procfile"}


class PathError(ValueError):
    """Шлях виходить за межі проекту або некоректний."""


class ConflictError(RuntimeError):
    """Файл змінився на диску після того, як його відкрили в редакторі."""


class NotTextError(ValueError):
    """Файл бінарний або занадто великий для редактора."""


# ------------------------------------------------------------------ шляхи


def project_root(path: str) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Папка проекту не знайдена: {root}")
    return root


def safe_path(root: Path | str, rel: str | None) -> Path:
    """Повертає абсолютний шлях всередині root або кидає PathError."""
    root_r = Path(root).resolve()
    rel = (rel or "").replace("\\", "/").strip()
    if "\x00" in rel:
        raise PathError("Некоректний шлях")
    rel = rel.lstrip("/")
    candidate = (root_r / rel).resolve()
    if candidate != root_r and root_r not in candidate.parents:
        raise PathError("Шлях виходить за межі проекту")
    return candidate


def rel_path(root: Path | str, path: Path) -> str:
    rel = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    return "" if rel == "." else rel


def language_of(path: Path | str) -> str:
    p = Path(path)
    if p.name in SPECIAL_FILES:
        return SPECIAL_FILES[p.name]
    return LANGUAGES.get(p.suffix.lower(), "")


def is_ignored_dir(name: str) -> bool:
    return name in IGNORED_DIRS or name.endswith(".egg-info")


# ------------------------------------------------------------------ обхід


def walk_files(root: Path | str, max_files: int = 20000) -> Iterator[Path]:
    """Обходить файли проекту, пропускаючи залежності та кеші."""
    count = 0
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not is_ignored_dir(d))
        for name in sorted(filenames):
            yield Path(dirpath) / name
            count += 1
            if count >= max_files:
                return


def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def decode_bytes(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def read_text_quick(path: Path, limit: int = 1024 * 1024) -> str | None:
    """Читає текстовий файл для аналізу (None — якщо бінарний/великий)."""
    try:
        if path.stat().st_size > limit:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return decode_bytes(data)[0]


# ------------------------------------------------------------------ папки


def list_dir(root: Path, rel: str) -> dict:
    target = safe_path(root, rel)
    if not target.is_dir():
        raise FileNotFoundError("Папка не знайдена")
    entries = []
    base = rel_path(root, target)
    with os.scandir(target) as it:
        for entry in it:
            try:
                st = entry.stat(follow_symlinks=False)
                is_dir = entry.is_dir()
            except OSError:
                continue
            entries.append(
                {
                    "name": entry.name,
                    "path": f"{base}/{entry.name}" if base else entry.name,
                    "type": "dir" if is_dir else "file",
                    "size": 0 if is_dir else st.st_size,
                    "mtime": st.st_mtime,
                    "ignored": is_dir and is_ignored_dir(entry.name),
                    "symlink": entry.is_symlink(),
                    "language": "" if is_dir else language_of(entry.name),
                    "image": (not is_dir) and Path(entry.name).suffix.lower() in IMAGE_EXTS,
                }
            )
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return {"path": rel_path(root, target), "abs_path": str(target), "entries": entries}


def tree(root: Path, max_depth: int = 8, max_entries: int = 5000) -> dict:
    """Дерево проекту для вкладки «Структура проекту»."""
    counter = {"n": 0, "truncated": False}

    def build(path: Path, depth: int) -> dict:
        node = {"name": path.name or str(path), "path": rel_path(root, path), "type": "dir", "children": []}
        if depth >= max_depth:
            node["truncated"] = True
            return node
        try:
            items = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return node
        for entry in items:
            if counter["n"] >= max_entries:
                counter["truncated"] = True
                break
            counter["n"] += 1
            if entry.is_dir(follow_symlinks=False):
                if is_ignored_dir(entry.name):
                    node["children"].append(
                        {"name": entry.name, "path": rel_path(root, Path(entry.path)), "type": "dir",
                         "ignored": True, "children": []}
                    )
                else:
                    node["children"].append(build(Path(entry.path), depth + 1))
            else:
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
                node["children"].append(
                    {"name": entry.name, "path": rel_path(root, Path(entry.path)), "type": "file", "size": size}
                )
        return node

    result = build(root, 0)
    result["name"] = root.name
    return {"tree": result, "count": counter["n"], "truncated": counter["truncated"]}


# ------------------------------------------------------------------ файли


def read_file(root: Path, rel: str) -> dict:
    path = safe_path(root, rel)
    if not path.is_file():
        raise FileNotFoundError("Файл не знайдено")
    st = path.stat()
    if st.st_size > MAX_EDIT_SIZE:
        raise NotTextError("Файл завеликий для редактора (більше 2 МБ)")
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise NotTextError("Це бінарний файл — його не можна відкрити в редакторі")
    content, encoding = decode_bytes(data)
    newline = "\r\n" if "\r\n" in content else "\n"
    return {
        "path": rel_path(root, path),
        "content": content.replace("\r\n", "\n"),
        "encoding": encoding,
        "newline": newline,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "language": language_of(path),
    }


def write_file(root: Path, rel: str, content: str, expected_mtime: float | None = None,
               encoding: str | None = None) -> dict:
    """Записує файл. Повертає старий вміст (для історії змін) і новий mtime."""
    path = safe_path(root, rel)
    if path.is_dir():
        raise PathError("Це папка, а не файл")
    old_content = ""
    newline = "\n"
    if path.exists():
        st = path.stat()
        if expected_mtime is not None and abs(st.st_mtime - float(expected_mtime)) > 1e-6:
            raise ConflictError("Файл змінився на диску після відкриття. Перезавантажте його.")
        if st.st_size <= MAX_EDIT_SIZE:
            raw = path.read_bytes()
            if b"\x00" not in raw[:8192]:
                old_content, detected = decode_bytes(raw)
                encoding = encoding or detected
                if "\r\n" in old_content:
                    newline = "\r\n"
                old_content = old_content.replace("\r\n", "\n")
    encoding = encoding or "utf-8"
    content = content.replace("\r\n", "\n")
    out = content.replace("\n", newline) if newline != "\n" else content
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(out.encode(encoding))
    except UnicodeEncodeError:
        encoding = "utf-8"
        path.write_bytes(out.encode(encoding))
    return {"old_content": old_content, "mtime": path.stat().st_mtime, "encoding": encoding}


def create(root: Path, rel: str, kind: str, content: str = "") -> Path:
    path = safe_path(root, rel)
    if path == Path(root).resolve():
        raise PathError("Вкажіть ім'я")
    if path.exists():
        raise PathError("Такий файл або папка вже існує")
    if kind == "dir":
        path.mkdir(parents=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return path


def rename(root: Path, rel: str, new_rel: str) -> Path:
    src = safe_path(root, rel)
    dst = safe_path(root, new_rel)
    root_r = Path(root).resolve()
    if src == root_r or dst == root_r:
        raise PathError("Не можна перейменувати корінь проекту")
    if not src.exists():
        raise FileNotFoundError("Файл не знайдено")
    if dst.exists():
        raise PathError("Ціль уже існує")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return dst


def delete(root: Path, rel: str) -> str:
    """Видаляє файл/папку. Повертає вміст файлу (для історії) або ''."""
    path = safe_path(root, rel)
    if path == Path(root).resolve():
        raise PathError("Не можна видалити корінь проекту")
    if not path.exists() and not path.is_symlink():
        raise FileNotFoundError("Файл не знайдено")
    old = ""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        old = read_text_quick(path, MAX_EDIT_SIZE) or ""
        path.unlink()
    return old


def open_in_file_manager(path: Path) -> None:
    """Відкриває папку в провіднику ОС (Finder / Explorer / файловий менеджер Linux)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":  # pragma: no cover
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
