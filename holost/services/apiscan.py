"""Пошук API-ендпоінтів у коді: Flask, FastAPI, Django, Express/Koa/Fastify, Go net/http, Spring."""
from __future__ import annotations

import re
from pathlib import Path

from . import fs

_PY_DECORATOR = re.compile(
    r"^\s*@(?P<obj>[\w.]+)\.(?P<verb>route|get|post|put|patch|delete|head|options|websocket|api_route)"
    r"\(\s*(?:path\s*=\s*)?[rf]?(?P<q>['\"])(?P<path>[^'\"]*)(?P=q)(?P<rest>.*)$"
)
_PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
_PY_METHODS = re.compile(r"methods\s*=\s*[\[(]([^\])]*)[\])]")
_DJANGO = re.compile(r"\b(?:re_)?path\(\s*r?(['\"])(?P<path>[^'\"]*)\1\s*,\s*(?P<view>[\w.]+(?:\.as_view\(\))?)")
_JS_ROUTE = re.compile(
    r"\b(?P<obj>app|router|api|server|fastify|routes|r)\.(?P<verb>get|post|put|patch|delete|all|options|head)"
    r"\(\s*(?P<q>['\"`])(?P<path>/[^'\"`]*)(?P=q)"
)
_GO_ROUTE = re.compile(r"\.(?:HandleFunc|Handle|GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete)\(\s*\"(?P<path>/[^\"]*)\"")
_GO_VERB = re.compile(r"\.(GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete)\(")
_SPRING = re.compile(r"@(?P<verb>Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\"(?P<path>[^\"]*)\"")

_JS_EXTS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}


def _methods_from_rest(verb: str, rest: str) -> list[str]:
    if verb in ("route", "api_route"):
        m = _PY_METHODS.search(rest)
        if m:
            return [x.strip(" '\"").upper() for x in m.group(1).split(",") if x.strip(" '\"")]
        return ["GET"]
    if verb == "websocket":
        return ["WS"]
    return [verb.upper()]


def scan(root: Path) -> list[dict]:
    endpoints: list[dict] = []
    for path in fs.walk_files(root):
        suffix = path.suffix.lower()
        if suffix not in {".py", ".go", ".java", ".kt"} | _JS_EXTS:
            continue
        if path.name.endswith((".min.js", ".test.js", ".spec.js", ".test.ts", ".spec.ts")):
            continue
        text = fs.read_text_quick(path, 1024 * 1024)
        if not text:
            continue
        rel = fs.rel_path(root, path)
        lines = text.splitlines()
        if suffix == ".py":
            endpoints.extend(_scan_python(rel, lines))
        elif suffix in _JS_EXTS:
            endpoints.extend(_scan_js(rel, lines))
        elif suffix == ".go":
            for i, line in enumerate(lines, 1):
                m = _GO_ROUTE.search(line)
                if m:
                    vm = _GO_VERB.search(line)
                    endpoints.append({"methods": [vm.group(1).upper()] if vm else ["ANY"], "path": m.group("path"),
                                      "handler": "", "file": rel, "line": i, "framework": "Go"})
        else:
            for i, line in enumerate(lines, 1):
                m = _SPRING.search(line)
                if m:
                    verb = m.group("verb").upper()
                    endpoints.append({"methods": ["ANY" if verb == "REQUEST" else verb], "path": m.group("path"),
                                      "handler": "", "file": rel, "line": i, "framework": "Spring"})
    endpoints.sort(key=lambda e: (e["path"], e["methods"]))
    return endpoints


def _scan_python(rel: str, lines: list[str]) -> list[dict]:
    found = []
    is_urls = rel.endswith("urls.py")
    for i, line in enumerate(lines):
        m = _PY_DECORATOR.match(line)
        if m:
            verb = m.group("verb")
            # Пропускаємо звичайні dict.get('x') тощо: декоратор має починатися з '@'.
            handler = ""
            for nxt in lines[i + 1:i + 8]:
                dm = _PY_DEF.match(nxt)
                if dm:
                    handler = dm.group(1)
                    break
            if verb == "route":
                framework = "Flask"
            elif verb in ("api_route", "websocket"):
                framework = "FastAPI"
            else:
                framework = "Flask/FastAPI"
            found.append({"methods": _methods_from_rest(verb, m.group("rest")), "path": m.group("path") or "/",
                          "handler": handler, "file": rel, "line": i + 1, "framework": framework})
            continue
        if is_urls:
            dm = _DJANGO.search(line)
            if dm:
                found.append({"methods": ["ANY"], "path": "/" + dm.group("path"), "handler": dm.group("view"),
                              "file": rel, "line": i + 1, "framework": "Django"})
    return found


def _scan_js(rel: str, lines: list[str]) -> list[dict]:
    found = []
    for i, line in enumerate(lines, 1):
        for m in _JS_ROUTE.finditer(line):
            verb = m.group("verb").upper()
            found.append({"methods": ["ANY" if verb == "ALL" else verb], "path": m.group("path"), "handler": "",
                          "file": rel, "line": i, "framework": "Express"})
    return found
