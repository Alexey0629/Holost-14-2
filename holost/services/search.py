"""Пошук по файлах проекту (текст або регулярний вираз) + список картинок."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from . import fs


class SearchError(ValueError):
    pass


def search(root: Path, query: str, regex: bool = False, case: bool = False, glob: str = "",
           max_results: int = 500) -> dict:
    query = query or ""
    if not query.strip():
        raise SearchError("Введіть, що шукати")
    flags = 0 if case else re.IGNORECASE
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error as exc:
        raise SearchError(f"Помилка в регулярному виразі: {exc}") from exc

    globs = [g.strip() for g in (glob or "").split(",") if g.strip()]
    matches: list[dict] = []
    file_names: list[str] = []
    files_scanned = 0
    truncated = False
    for path in fs.walk_files(root):
        rel = fs.rel_path(root, path)
        if globs and not any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(path.name, g) for g in globs):
            continue
        if pattern.search(path.name):
            file_names.append(rel)
        text = fs.read_text_quick(path, 2 * 1024 * 1024)
        if text is None:
            continue
        files_scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            m = pattern.search(line)
            if not m:
                continue
            matches.append({
                "path": rel,
                "line": lineno,
                "text": line[:400],
                "start": m.start() if m.start() < 400 else 0,
                "end": min(m.end(), 400) if m.start() < 400 else 0,
            })
            if len(matches) >= max_results:
                truncated = True
                break
        if truncated:
            break
    return {"matches": matches, "files": file_names[:200], "files_scanned": files_scanned, "truncated": truncated}


def list_images(root: Path, max_items: int = 1000) -> list[dict]:
    images = []
    for path in fs.walk_files(root):
        if path.suffix.lower() in fs.IMAGE_EXTS:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            images.append({"path": fs.rel_path(root, path), "name": path.name, "size": size,
                           "ext": path.suffix.lower().lstrip(".")})
            if len(images) >= max_items:
                break
    return images
