"""«Падіння, помилки»: лог-файли проекту, пошук помилок і трейсбеків, групування інцидентів."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import fs

LOG_EXTS = {".log", ".out", ".err"}
_ERROR_RE = re.compile(
    r"\b(?:ERROR|CRITICAL|FATAL|EXCEPTION|Traceback|Unhandled\w*|SEVERE)\b|\b\w*(?:Error|Exception)\b"
    r"|panic:|Segmentation fault|\bE/|\[error\]"
)
_WARN_RE = re.compile(r"\b(WARNING|WARN|Warning)\b|\[warn")


def find_log_files(root: Path, limit: int = 200) -> list[dict]:
    result = []
    for path in fs.walk_files(root):
        rel = fs.rel_path(root, path)
        if path.suffix.lower() in LOG_EXTS or (
            path.suffix.lower() == ".txt" and any(part in {"logs", "log"} for part in Path(rel).parts[:-1])
        ):
            try:
                st = path.stat()
            except OSError:
                continue
            result.append({"path": rel, "size": st.st_size, "mtime": st.st_mtime})
            if len(result) >= limit:
                break
    result.sort(key=lambda x: -x["mtime"])
    return result


def _tail_bytes(path: Path, max_bytes: int) -> tuple[str, int]:
    size = path.stat().st_size
    with open(path, "rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            data = fh.read()
            data = data.split(b"\n", 1)[1] if b"\n" in data else data
        else:
            data = fh.read()
    text, _ = fs.decode_bytes(data)
    return text, size


def analyze_log(root: Path, rel: str, max_bytes: int = 512 * 1024) -> dict:
    path = fs.safe_path(root, rel)
    if not path.is_file():
        raise FileNotFoundError("Лог-файл не знайдено")
    text, size = _tail_bytes(path, max_bytes)
    lines = text.splitlines()
    errors, warnings = 0, 0
    marked = []
    for i, line in enumerate(lines, 1):
        level = ""
        if _ERROR_RE.search(line):
            level = "error"
            errors += 1
        elif _WARN_RE.search(line):
            level = "warning"
            warnings += 1
        marked.append({"n": i, "text": line[:2000], "level": level})
    return {
        "path": fs.rel_path(root, path),
        "size": size,
        "partial": size > max_bytes,
        "lines": marked[-3000:],
        "errors": errors,
        "warnings": warnings,
        "tracebacks": extract_tracebacks(lines),
    }


def extract_tracebacks(lines: list[str], limit: int = 50) -> list[dict]:
    """Знаходить Python-трейсбеки в лозі."""
    found = []
    i = 0
    while i < len(lines) and len(found) < limit:
        if "Traceback (most recent call last)" in lines[i]:
            start = i
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                j += 1
            # Рядок з типом винятку
            if j < len(lines):
                j += 1
            block = lines[start:j]
            title = block[-1].strip() if block else "Traceback"
            found.append({"line": start + 1, "title": title[:300], "text": "\n".join(block)})
            i = j
        else:
            i += 1
    return found


def fingerprint(title: str, traceback: str = "") -> str:
    """Однакові помилки групуються: заголовок без чисел + останній кадр трейсбеку."""
    norm = re.sub(r"\d+", "N", (title or "").strip().lower())
    frames = [ln.strip() for ln in (traceback or "").splitlines() if ln.strip().startswith("File ")]
    last = re.sub(r"line \d+", "line N", frames[-1]) if frames else ""
    return hashlib.sha1(f"{norm}|{last}".encode("utf-8")).hexdigest()

