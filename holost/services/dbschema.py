"""Структура БД проекту: SQLite-файли, SQL-схеми та ORM-моделі (SQLAlchemy / Django / SQLModel)."""
from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

from . import fs

SQLITE_EXTS = {".db", ".sqlite", ".sqlite3", ".db3"}
SQLITE_HEADER = b"SQLite format 3\x00"


class DBError(RuntimeError):
    pass


# ------------------------------------------------------------------ SQLite


def find_sqlite_files(root: Path) -> list[str]:
    result = []
    for path in fs.walk_files(root):
        if path.suffix.lower() not in SQLITE_EXTS:
            continue
        try:
            with open(path, "rb") as fh:
                if fh.read(16) == SQLITE_HEADER:
                    result.append(fs.rel_path(root, path))
        except OSError:
            continue
    return result


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqlite_schema(path: Path) -> list[dict]:
    try:
        conn = _connect_ro(path)
    except sqlite3.Error as exc:
        raise DBError(f"Не вдалося відкрити БД: {exc}") from exc
    try:
        objects = conn.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = []
        for name, kind, sql in objects:
            columns = [
                {"name": c[1], "type": c[2] or "", "notnull": bool(c[3]), "default": c[4], "pk": bool(c[5])}
                for c in conn.execute(f"PRAGMA table_info({_qi(name)})")
            ]
            fks = [
                {"from": f[3], "table": f[2], "to": f[4] or ""}
                for f in conn.execute(f"PRAGMA foreign_key_list({_qi(name)})")
            ]
            indexes = []
            for idx in conn.execute(f"PRAGMA index_list({_qi(name)})"):
                cols = [c[2] for c in conn.execute(f"PRAGMA index_info({_qi(idx[1])})")]
                indexes.append({"name": idx[1], "unique": bool(idx[2]), "columns": cols})
            try:
                rows = conn.execute(f"SELECT COUNT(*) FROM {_qi(name)}").fetchone()[0]
            except sqlite3.Error:
                rows = None
            tables.append({"name": name, "kind": kind, "columns": columns, "foreign_keys": fks,
                           "indexes": indexes, "rows": rows, "sql": sql or ""})
        return tables
    finally:
        conn.close()


def run_readonly_query(path: Path, sql: str, limit: int = 200) -> dict:
    sql = (sql or "").strip()
    if not sql:
        raise DBError("Порожній запит")
    try:
        conn = _connect_ro(path)
    except sqlite3.Error as exc:
        raise DBError(str(exc)) from exc
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(limit + 1)
        truncated = len(rows) > limit
        rows = [[_cell(v) for v in r] for r in rows[:limit]]
        return {"columns": columns, "rows": rows, "truncated": truncated}
    except sqlite3.Error as exc:
        raise DBError(f"Помилка SQL: {exc}") from exc
    finally:
        conn.close()


def _cell(value):
    if isinstance(value, bytes):
        return f"<BLOB {len(value)} байт>"
    return value


# ------------------------------------------------------------------ SQL-файли

_CREATE_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?(?:temporary\s+|temp\s+|unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?"
    r"((?:[`\"\[]?[\w$]+[`\"\]]?\.)?[`\"\[]?[\w$]+[`\"\]]?)\s*\(",
    re.IGNORECASE,
)
_CONSTRAINT_START = ("primary key", "foreign key", "unique", "constraint", "check", "key ", "index ",
                     "fulltext", "exclude")
_REF_RE = re.compile(r"references\s+([`\"\[]?[\w$.]+[`\"\]]?)\s*(?:\(\s*([^)]*)\))?", re.IGNORECASE)


def _unquote(name: str) -> str:
    return name.strip().strip('`"[]')


def _split_top_level(body: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _strip_sql_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def parse_sql_schema(text: str) -> list[dict]:
    text = _strip_sql_comments(text)
    tables = []
    for m in _CREATE_RE.finditer(text):
        name = ".".join(_unquote(p) for p in m.group(1).split("."))
        start, depth, i = m.end(), 1, m.end()
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        columns, fks, pk_cols = [], [], set()
        for part in _split_top_level(body):
            low = part.lower()
            if low.startswith(_CONSTRAINT_START):
                if "primary key" in low:
                    inner = re.search(r"primary\s+key\s*\(([^)]*)\)", part, re.I)
                    if inner:
                        pk_cols.update(_unquote(c) for c in inner.group(1).split(","))
                if "foreign key" in low:
                    fm = re.search(r"foreign\s+key\s*\(([^)]*)\)", part, re.I)
                    rm = _REF_RE.search(part)
                    if fm and rm:
                        fks.append({"from": _unquote(fm.group(1)), "table": _unquote(rm.group(1)),
                                    "to": _unquote(rm.group(2) or "")})
                continue
            tokens = part.split(None, 1)
            if not tokens:
                continue
            col = _unquote(tokens[0])
            rest = tokens[1] if len(tokens) > 1 else ""
            col_type = re.split(r"\s+(?:not\s+null|null|primary|default|references|unique|check|"
                                r"auto_increment|autoincrement|generated|collate|constraint)\b",
                                rest, maxsplit=1, flags=re.I)[0].strip()
            rm = _REF_RE.search(rest)
            if rm:
                fks.append({"from": col, "table": _unquote(rm.group(1)), "to": _unquote(rm.group(2) or "")})
            columns.append({
                "name": col,
                "type": col_type,
                "notnull": bool(re.search(r"\bnot\s+null\b", rest, re.I)),
                "default": None,
                "pk": bool(re.search(r"\bprimary\s+key\b", rest, re.I)),
            })
        for c in columns:
            if c["name"] in pk_cols:
                c["pk"] = True
        tables.append({"name": name, "kind": "table", "columns": columns, "foreign_keys": fks,
                       "indexes": [], "rows": None, "sql": text[m.start():i].strip()})
    return tables


def sql_files_schema(root: Path) -> list[dict]:
    result = []
    for path in fs.walk_files(root):
        if path.suffix.lower() != ".sql":
            continue
        text = fs.read_text_quick(path, 2 * 1024 * 1024)
        if not text:
            continue
        tables = parse_sql_schema(text)
        if tables:
            result.append({"path": fs.rel_path(root, path), "tables": tables})
    return result


# ------------------------------------------------------------------ ORM-моделі

_COLUMN_FUNCS = {"Column", "mapped_column"}
_RELATION_FUNCS = {"relationship", "relation", "backref"}
_NON_MODEL_BASES = ("Serializer", "Form", "Schema", "BaseModel", "BaseSettings", "Enum")
_MAPPED_RE = re.compile(r"^(?:\w+\.)*Mapped\[(.*)\]$")


def _type_target(type_text: str) -> str:
    """'Optional[List["User"]]' -> 'User' (назва класу, на який може посилатись зв'язок)."""
    names = re.findall(r"[A-Za-z_][\w.]*", type_text.replace("'", " ").replace('"', " "))
    skip = {"Optional", "List", "list", "Set", "set", "None", "Union", "typing", "WriteOnlyMapped",
            "DynamicMapped"}
    names = [n.rsplit(".", 1)[-1] for n in names if n not in skip]
    return names[-1] if names else ""


def _func_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover
        return ""


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _foreign_key(call: ast.Call) -> str:
    for node in ast.walk(call):
        if isinstance(node, ast.Call) and _short(_func_name(node)) in {"ForeignKey", "OneToOneField",
                                                                      "ManyToManyField"}:
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant):
                    return str(arg.value)
                return ast.unparse(arg)
            for kw in node.keywords:
                if kw.arg in ("to", "column"):
                    return ast.unparse(kw.value).strip("'\"")
    return ""


def _kw(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            if isinstance(kw.value, ast.Constant):
                return kw.value.value
            return ast.unparse(kw.value)
    return None


def _column_from_call(name: str, call: ast.Call, annotation: str = "", allow_plain_field: bool = False) -> dict | None:
    full = _func_name(call)
    func = _short(full)
    if full.startswith(("serializers.", "forms.")) or (func == "Field" and not allow_plain_field):
        return None
    if func in _COLUMN_FUNCS:
        col_type = annotation
        for arg in call.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                continue  # ім'я колонки
            text = ast.unparse(arg)
            if _short(_func_name(arg)) == "ForeignKey":
                continue
            col_type = text
            break
        return {"name": name, "type": col_type, "fk": _foreign_key(call), "pk": bool(_kw(call, "primary_key")),
                "nullable": _kw(call, "nullable")}
    if func.endswith("Field") or func in {"ForeignKey", "OneToOneField", "ManyToManyField"}:
        # Django / SQLModel / Tortoise
        extra = []
        for key in ("max_length", "default", "null", "unique"):
            value = _kw(call, key)
            if value is not None:
                extra.append(f"{key}={value}")
        col_type = func + (f"({', '.join(extra)})" if extra else "")
        if annotation and func == "Field":
            col_type = annotation
        return {"name": name, "type": col_type, "fk": _foreign_key(call),
                "pk": bool(_kw(call, "primary_key")), "nullable": _kw(call, "null") or _kw(call, "nullable")}
    return None


def _model_from_class(cls: ast.ClassDef) -> dict | None:
    bases = [ast.unparse(b) for b in cls.bases]
    table = None
    fields, relations = [], []
    is_sqlmodel_table = any(kw.arg == "table" and isinstance(kw.value, ast.Constant) and kw.value.value
                            for kw in cls.keywords)
    if not is_sqlmodel_table and any(k in b for b in bases for k in _NON_MODEL_BASES):
        return None
    for stmt in cls.body:
        target, value, annotation = None, None, ""
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target, value = stmt.targets[0].id, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target, value = stmt.target.id, stmt.value
            annotation = ast.unparse(stmt.annotation)
        if not target:
            continue
        if target == "__tablename__" and isinstance(value, ast.Constant):
            table = str(value.value)
            continue
        mapped = _MAPPED_RE.match(annotation)
        inner = mapped.group(1) if mapped else annotation
        if isinstance(value, ast.Call):
            func = _short(_func_name(value))
            if func in _RELATION_FUNCS:
                rel_target = ""
                if value.args:
                    a = value.args[0]
                    rel_target = str(a.value) if isinstance(a, ast.Constant) else ast.unparse(a)
                relations.append({"name": target, "target": rel_target or _type_target(inner)})
                continue
            col = _column_from_call(target, value, inner, allow_plain_field=is_sqlmodel_table)
            if col:
                fields.append(col)
                continue
        if mapped and value is None:
            # Mapped[...] без mapped_column: колонка або зв'язок — уточнюємо після збору всіх моделей.
            fields.append({"name": target, "type": inner, "fk": "", "pk": False, "nullable": None,
                           "_maybe_relation": _type_target(inner)})
        elif is_sqlmodel_table and annotation and value is None:
            fields.append({"name": target, "type": annotation, "fk": "", "pk": False, "nullable": None})
    if not fields and not table:
        return None
    return {"class": cls.name, "bases": bases, "table": table or "", "fields": fields, "relationships": relations,
            "line": cls.lineno}


def orm_models(root: Path) -> list[dict]:
    result = []
    for path in fs.walk_files(root):
        if path.suffix != ".py":
            continue
        text = fs.read_text_quick(path, 512 * 1024)
        if not text or not any(k in text for k in ("Column", "mapped_column", "models.", "Field(", "__tablename__")):
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                model = _model_from_class(node)
                if model:
                    model["file"] = fs.rel_path(root, path)
                    result.append(model)
    # Друга фаза: Mapped["User"] без mapped_column — це зв'язок, якщо User є моделлю.
    model_names = {m["class"] for m in result}
    for model in result:
        kept = []
        for field in model["fields"]:
            target = field.pop("_maybe_relation", None)
            if target and target in model_names:
                model["relationships"].append({"name": field["name"], "target": field["type"]})
            else:
                kept.append(field)
        model["fields"] = kept
    return [m for m in result if m["fields"] or m["table"]]


def overview(root: Path) -> dict:
    sqlite_dbs = []
    for rel in find_sqlite_files(root):
        try:
            sqlite_dbs.append({"path": rel, "tables": sqlite_schema(root / rel), "error": ""})
        except DBError as exc:
            sqlite_dbs.append({"path": rel, "tables": [], "error": str(exc)})
    return {
        "sqlite": sqlite_dbs,
        "sql_files": sql_files_schema(root),
        "models": orm_models(root),
        "migrations": _migration_dirs(root),
    }


def _migration_dirs(root: Path) -> list[str]:
    dirs = []
    for name in ("migrations", "alembic", "db/migrations", "prisma/migrations"):
        p = root / name
        if p.is_dir():
            dirs.append(name)
    for p in root.glob("*/migrations"):
        if p.is_dir() and not fs.is_ignored_dir(p.parent.name):
            rel = fs.rel_path(root, p)
            if rel not in dirs:
                dirs.append(rel)
    return dirs
