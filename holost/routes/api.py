"""JSON API, яким користується інтерфейс (і зовнішні проекти — для звітів про помилки)."""
from __future__ import annotations

import difflib
import json
import os
import re
import time
from pathlib import Path

from flask import Blueprint, Flask, abort, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from .. import db
from ..services import (apiscan, dbschema, fs, git_ops, httpclient, logs, runner, scanner, search, usage)

bp = Blueprint("api", __name__, url_prefix="/api")

DEFAULT_ROOT_CANDIDATES = (
    "~/projects", "~/Projects", "~/PycharmProjects", "~/WebstormProjects", "~/code", "~/Code", "~/dev",
    "~/src", "~/repos", "~/git", "~/GitHub", "~/Documents/GitHub", "~/Desktop/projects",
)


# =================================================================== helpers


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_project(project_id: int) -> dict:
    proj = db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not proj:
        abort(404, description="Проект не знайдено")
    return proj


def project_and_root(project_id: int) -> tuple[dict, Path]:
    proj = get_project(project_id)
    return proj, fs.project_root(proj["path"])


def make_diff(old: str, new: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def timeout() -> int:
    return int(current_app.config.get("COMMAND_TIMEOUT", 600))


def get_roots() -> list[str]:
    raw = db.get_setting("roots", "")
    if raw:
        try:
            return [r for r in json.loads(raw) if r]
        except ValueError:
            pass
    env_roots = current_app.config.get("PROJECT_ROOTS") or ""
    return [r for r in env_roots.split(os.pathsep) if r.strip()]


def register_error_handlers(app: Flask) -> None:
    def as_json(status: int):
        def handler(exc):
            return jsonify(error=str(exc)), status
        return handler

    app.register_error_handler(fs.PathError, as_json(400))
    app.register_error_handler(fs.NotTextError, as_json(415))
    app.register_error_handler(fs.ConflictError, as_json(409))
    app.register_error_handler(git_ops.GitError, as_json(400))
    app.register_error_handler(dbschema.DBError, as_json(400))
    app.register_error_handler(search.SearchError, as_json(400))
    app.register_error_handler(httpclient.HttpError, as_json(400))

    @app.errorhandler(FileNotFoundError)
    def _not_found(exc):
        return jsonify(error=str(exc) or "Не знайдено"), 404


@bp.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    return jsonify(error=exc.description or exc.name), exc.code


# =================================================================== налаштування


@bp.get("/settings")
def settings_get():
    suggestions = [c for c in DEFAULT_ROOT_CANDIDATES if Path(c).expanduser().is_dir()]
    return jsonify(roots=get_roots(), suggestions=suggestions, home=str(Path.home()))


@bp.put("/settings")
def settings_put():
    roots = body().get("roots") or []
    if isinstance(roots, str):
        roots = roots.splitlines()
    roots = [str(r).strip() for r in roots if str(r).strip()]
    missing = [r for r in roots if not Path(r).expanduser().is_dir()]
    db.set_setting("roots", json.dumps(roots, ensure_ascii=False))
    return jsonify(roots=roots, missing=missing)


# =================================================================== проекти


def _project_card(p: dict) -> dict:
    path = Path(p["path"])
    exists = path.is_dir()
    open_incidents = db.query_one(
        "SELECT COUNT(*) AS n FROM incidents WHERE project_id = ? AND status = 'open'", (p["id"],)
    )["n"]
    return {
        "id": p["id"],
        "name": p["name"],
        "path": p["path"],
        "short_desc": p["short_desc"],
        "tags": [t.strip() for t in p["tags"].split(",") if t.strip()],
        "favorite": bool(p["favorite"]),
        "exists": exists,
        "stack": scanner.detect_stack(path) if exists else [],
        "open_incidents": open_incidents,
        "last_opened_at": p["last_opened_at"],
        "updated_at": p["updated_at"],
    }


@bp.get("/projects")
def projects_list():
    rows = db.query_all("SELECT * FROM projects ORDER BY favorite DESC, COALESCE(last_opened_at, '') DESC, name")
    return jsonify(projects=[_project_card(p) for p in rows], roots=get_roots())


@bp.post("/projects")
def projects_add():
    data = body()
    raw = (data.get("path") or "").strip()
    if not raw:
        abort(400, description="Вкажіть шлях до папки проекту")
    path = Path(raw).expanduser()
    if not path.is_dir():
        abort(400, description=f"Папка не існує: {path}")
    path = path.resolve()
    existing = db.query_one("SELECT id FROM projects WHERE path = ?", (str(path),))
    if existing:
        return jsonify(error="Цей проект уже є в списку", id=existing["id"]), 409
    name = (data.get("name") or "").strip() or path.name
    pid = db.add_project(name, str(path), scanner.readme_summary(path))
    return jsonify(id=pid), 201


@bp.post("/scan")
def projects_scan():
    roots = get_roots()
    if not roots:
        abort(400, description="Спочатку вкажіть папки з проектами в налаштуваннях")
    found = scanner.discover(roots)
    added = []
    for path in found:
        if db.query_one("SELECT id FROM projects WHERE path = ?", (str(path),)):
            continue
        pid = db.add_project(path.name, str(path), scanner.readme_summary(path))
        added.append({"id": pid, "name": path.name, "path": str(path)})
    return jsonify(found=len(found), added=added)


@bp.get("/projects/<int:pid>")
def project_get(pid: int):
    proj = get_project(pid)
    root = Path(proj["path"])
    info = dict(proj)
    info["exists"] = root.is_dir()
    info["stack"] = scanner.detect_stack(root) if info["exists"] else []
    info["detected"] = {}
    info["readme"] = None
    if info["exists"]:
        info["detected"] = {
            "test_cmd": runner.detect_test_command(root),
            "run_cmd": runner.detect_run_command(root),
            "install_cmd": runner.detect_install_command(root),
        }
        readme = scanner.find_readme(root)
        if readme:
            info["readme"] = {"path": fs.rel_path(root, readme), "content": fs.read_text_quick(readme, 512 * 1024) or ""}
    info["ingest_url"] = request.host_url.rstrip("/") + f"/api/ingest/{proj['ingest_key']}"
    return jsonify(info)


@bp.put("/projects/<int:pid>")
def project_update(pid: int):
    proj = get_project(pid)
    data = body()
    updates = {}
    for field in db.EDITABLE_PROJECT_FIELDS:
        if field in data:
            value = data[field]
            if field == "favorite":
                value = 1 if value else 0
            elif field == "prod_mode":
                value = value if value in ("git", "command") else "git"
            else:
                value = "" if value is None else str(value)
            updates[field] = value
    if "name" in updates and not updates["name"].strip():
        abort(400, description="Назва не може бути порожньою")
    if not updates:
        return jsonify(get_project(pid))
    updates["updated_at"] = db.now()
    sets = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE projects SET {sets} WHERE id = ?", (*updates.values(), pid))

    labels = {"short_desc": "Короткий опис", "full_desc": "Повний опис", "usage_notes": "Нотатки використання"}
    for field, label in labels.items():
        if field in updates and updates[field] != proj[field]:
            db.record_change(pid, "description", "", f"{label} змінено",
                             make_diff(proj[field], updates[field], field))
    changed_settings = [k for k in updates if k not in labels and k not in ("updated_at", "favorite")
                        and updates[k] != proj[k]]
    if changed_settings:
        db.record_change(pid, "settings", "", "Налаштування: " + ", ".join(changed_settings))
    return jsonify(get_project(pid))


@bp.delete("/projects/<int:pid>")
def project_delete(pid: int):
    get_project(pid)
    db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    return jsonify(ok=True)


@bp.post("/projects/<int:pid>/ingest-key")
def project_regenerate_key(pid: int):
    get_project(pid)
    db.execute("UPDATE projects SET ingest_key = ? WHERE id = ?", (db.new_ingest_key(), pid))
    return project_get(pid)


@bp.get("/projects/<int:pid>/summary")
def project_summary(pid: int):
    proj = get_project(pid)
    root = Path(proj["path"])
    if not root.is_dir():
        return jsonify(exists=False)
    try:
        git = git_ops.brief(root)
    except git_ops.GitError as exc:
        git = {"is_repo": False, "error": str(exc)}
    return jsonify(exists=True, git=git)


@bp.post("/projects/<int:pid>/open-folder")
def project_open_folder(pid: int):
    _proj, root = project_and_root(pid)
    target = fs.safe_path(root, body().get("path", ""))
    if target.is_file():
        target = target.parent
    try:
        fs.open_in_file_manager(target)
    except OSError as exc:
        abort(400, description=f"Не вдалося відкрити провідник: {exc}")
    return jsonify(ok=True, path=str(target))


# =================================================================== файли / код


@bp.get("/projects/<int:pid>/files")
def files_list(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(fs.list_dir(root, request.args.get("path", "")))


@bp.get("/projects/<int:pid>/file")
def file_read(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(fs.read_file(root, request.args.get("path", "")))


@bp.put("/projects/<int:pid>/file")
def file_write(pid: int):
    _proj, root = project_and_root(pid)
    data = body()
    rel = data.get("path", "")
    content = data.get("content")
    if not isinstance(content, str):
        abort(400, description="Немає вмісту файлу")
    existed = fs.safe_path(root, rel).exists()
    result = fs.write_file(root, rel, content, data.get("mtime"), data.get("encoding"))
    norm = fs.rel_path(root, fs.safe_path(root, rel))
    diff = make_diff(result["old_content"], content.replace("\r\n", "\n"), norm)
    if diff or not existed:
        added = sum(1 for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
        db.record_change(pid, "edit" if existed else "create", norm, f"+{added} −{removed}", diff)
    return jsonify(ok=True, path=norm, mtime=result["mtime"], encoding=result["encoding"])


@bp.post("/projects/<int:pid>/file")
def file_create(pid: int):
    _proj, root = project_and_root(pid)
    data = body()
    kind = "dir" if data.get("type") == "dir" else "file"
    path = fs.create(root, data.get("path", ""), kind, data.get("content") or "")
    rel = fs.rel_path(root, path)
    db.record_change(pid, "create", rel, "Створено папку" if kind == "dir" else "Створено файл",
                     make_diff("", data.get("content") or "", rel) if kind == "file" else "")
    return jsonify(ok=True, path=rel), 201


@bp.post("/projects/<int:pid>/rename")
def file_rename(pid: int):
    _proj, root = project_and_root(pid)
    data = body()
    src = data.get("path", "")
    dst = fs.rename(root, src, data.get("new_path", ""))
    rel = fs.rel_path(root, dst)
    db.record_change(pid, "rename", rel, f"{src} → {rel}")
    return jsonify(ok=True, path=rel)


@bp.delete("/projects/<int:pid>/file")
def file_delete(pid: int):
    _proj, root = project_and_root(pid)
    rel = request.args.get("path", "")
    norm = fs.rel_path(root, fs.safe_path(root, rel))
    old = fs.delete(root, rel)
    db.record_change(pid, "delete", norm, "Видалено", make_diff(old, "", norm) if old else "")
    return jsonify(ok=True)


@bp.get("/projects/<int:pid>/tree")
def project_tree(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(fs.tree(root))


@bp.get("/projects/<int:pid>/stats")
def project_stats(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(scanner.stats(root))


# =================================================================== БД


@bp.get("/projects/<int:pid>/db")
def db_overview(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(dbschema.overview(root))


@bp.post("/projects/<int:pid>/db/query")
def db_query(pid: int):
    _proj, root = project_and_root(pid)
    data = body()
    path = fs.safe_path(root, data.get("path", ""))
    if not path.is_file():
        abort(404, description="Файл БД не знайдено")
    return jsonify(dbschema.run_readonly_query(path, data.get("sql", "")))


# =================================================================== використання


@bp.get("/projects/<int:pid>/usage")
def usage_info(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(usage.analyze(root))


# =================================================================== API


@bp.get("/projects/<int:pid>/endpoints")
def endpoints(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(endpoints=apiscan.scan(root))


@bp.get("/projects/<int:pid>/requests")
def requests_list(pid: int):
    get_project(pid)
    return jsonify(requests=db.query_all(
        "SELECT * FROM api_requests WHERE project_id = ? ORDER BY name COLLATE NOCASE", (pid,)))


def _request_fields(data: dict) -> tuple:
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, description="Вкажіть назву запиту")
    method = (data.get("method") or "GET").upper()
    if method not in httpclient.METHODS:
        abort(400, description="Некоректний метод")
    headers = data.get("headers") or ""
    if isinstance(headers, dict):
        headers = json.dumps(headers, ensure_ascii=False)
    return name, method, data.get("url") or "", headers, data.get("body") or "", data.get("notes") or ""


@bp.post("/projects/<int:pid>/requests")
def requests_create(pid: int):
    get_project(pid)
    fields = _request_fields(body())
    ts = db.now()
    rid = db.execute(
        "INSERT INTO api_requests(project_id, name, method, url, headers, body, notes, created_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)", (pid, *fields, ts, ts))
    return jsonify(db.query_one("SELECT * FROM api_requests WHERE id = ?", (rid,))), 201


@bp.put("/projects/<int:pid>/requests/<int:rid>")
def requests_update(pid: int, rid: int):
    get_project(pid)
    if not db.query_one("SELECT id FROM api_requests WHERE id = ? AND project_id = ?", (rid, pid)):
        abort(404)
    fields = _request_fields(body())
    db.execute("UPDATE api_requests SET name=?, method=?, url=?, headers=?, body=?, notes=?, updated_at=? "
               "WHERE id = ? AND project_id = ?", (*fields, db.now(), rid, pid))
    return jsonify(db.query_one("SELECT * FROM api_requests WHERE id = ?", (rid,)))


@bp.delete("/projects/<int:pid>/requests/<int:rid>")
def requests_delete(pid: int, rid: int):
    get_project(pid)
    db.execute("DELETE FROM api_requests WHERE id = ? AND project_id = ?", (rid, pid))
    return jsonify(ok=True)


@bp.post("/projects/<int:pid>/http")
def http_send(pid: int):
    proj = get_project(pid)
    data = body()
    url = httpclient.build_url(data.get("base_url") or proj["api_base_url"], data.get("url", ""))
    headers = httpclient.parse_headers(data.get("headers"))
    return jsonify(httpclient.send(data.get("method", "GET"), url, headers, data.get("body") or ""))


# =================================================================== пошук та візуал


@bp.get("/projects/<int:pid>/search")
def search_files(pid: int):
    _proj, root = project_and_root(pid)
    args = request.args
    return jsonify(search.search(root, args.get("q", ""), regex=args.get("regex") == "1",
                                 case=args.get("case") == "1", glob=args.get("glob", "")))


@bp.get("/projects/<int:pid>/images")
def images_list(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(images=search.list_images(root))


_UNSAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)


@bp.post("/projects/<int:pid>/images")
def images_upload(pid: int):
    _proj, root = project_and_root(pid)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        abort(400, description="Оберіть файл")
    name = _UNSAFE_NAME.sub("_", Path(upload.filename).name).lstrip(".") or "image"
    if Path(name).suffix.lower() not in fs.IMAGE_EXTS:
        abort(400, description="Можна завантажувати лише картинки: " + ", ".join(sorted(fs.IMAGE_EXTS)))
    folder = fs.safe_path(root, request.form.get("folder") or "docs/images")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    n = 1
    while target.exists():
        target = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    fs.safe_path(root, fs.rel_path(root, target))  # повторна перевірка
    upload.save(target)
    rel = fs.rel_path(root, target)
    db.record_change(pid, "create", rel, "Завантажено картинку")
    return jsonify(ok=True, path=rel), 201


# =================================================================== прод


@bp.post("/projects/<int:pid>/prod/update")
def prod_update(pid: int):
    proj, root = project_and_root(pid)
    if proj["prod_mode"] == "command":
        cmd = proj["prod_cmd"].strip()
        if not cmd:
            abort(400, description="Вкажіть команду оновлення з проду в налаштуваннях вкладки")
        result = runner.run_command(cmd, root, timeout=timeout())
        command = cmd
    else:
        if not git_ops.is_repo(root):
            abort(400, description="Проект не є git-репозиторієм. Оберіть режим «команда» або ініціалізуйте git.")
        remote = proj["prod_remote"].strip() or "origin"
        branch = proj["prod_branch"].strip() or git_ops.branches(root)["current"]
        command = f"git fetch {remote} && git pull --ff-only {remote} {branch}"
        start = time.monotonic()
        started_at = db.now()
        output, code = [], 0
        try:
            output.append("$ git fetch " + remote)
            output.append(git_ops.fetch(root, remote))
            output.append(f"$ git pull --ff-only {remote} {branch}")
            output.append(git_ops.pull(root, remote, branch))
        except git_ops.GitError as exc:
            output.append(str(exc))
            code = 1
        result = {"exit_code": code, "output": "\n".join(output), "timed_out": False,
                  "duration": round(time.monotonic() - start, 2), "started_at": started_at}
    run = db.record_run(pid, "prod", command, result)
    db.record_change(pid, "prod", "", ("✔ " if result["exit_code"] == 0 else "✘ ") + "Оновлення з проду",
                     result["output"][-20000:])
    return jsonify(run)


@bp.get("/projects/<int:pid>/runs")
def runs_list(pid: int):
    get_project(pid)
    kind = request.args.get("kind")
    sql = ("SELECT id, kind, command, exit_code, timed_out, started_at, duration FROM runs "
           "WHERE project_id = ?" + (" AND kind = ?" if kind else "") + " ORDER BY id DESC LIMIT 50")
    return jsonify(runs=db.query_all(sql, (pid, kind) if kind else (pid,)))


@bp.get("/projects/<int:pid>/runs/<int:rid>")
def runs_get(pid: int, rid: int):
    run = db.query_one("SELECT * FROM runs WHERE id = ? AND project_id = ?", (rid, pid))
    if not run:
        abort(404)
    return jsonify(run)


# =================================================================== історія змін


@bp.get("/projects/<int:pid>/changes")
def changes_list(pid: int):
    get_project(pid)
    return jsonify(changes=db.query_all(
        "SELECT id, kind, path, summary, created_at, LENGTH(diff) > 0 AS has_diff FROM changes "
        "WHERE project_id = ? ORDER BY id DESC LIMIT 300", (pid,)))


@bp.get("/projects/<int:pid>/changes/<int:cid>")
def changes_get(pid: int, cid: int):
    change = db.query_one("SELECT * FROM changes WHERE id = ? AND project_id = ?", (cid, pid))
    if not change:
        abort(404)
    return jsonify(change)


# =================================================================== помилки


@bp.get("/projects/<int:pid>/incidents")
def incidents_list(pid: int):
    get_project(pid)
    status = request.args.get("status", "open")
    if status in ("open", "resolved"):
        rows = db.query_all("SELECT * FROM incidents WHERE project_id = ? AND status = ? ORDER BY last_seen_at DESC",
                            (pid, status))
    else:
        rows = db.query_all("SELECT * FROM incidents WHERE project_id = ? ORDER BY last_seen_at DESC", (pid,))
    return jsonify(incidents=rows)


def _save_incident(pid: int, data: dict, source: str) -> dict:
    title = (data.get("title") or data.get("message") or "").strip()
    traceback = str(data.get("traceback") or data.get("stack") or "")
    if not title and traceback:
        title = traceback.strip().splitlines()[-1]
    if not title:
        abort(400, description="Вкажіть заголовок помилки")
    title = title[:500]
    level = str(data.get("level") or "error").lower()[:20]
    message = str(data.get("message") or "")[:20000]
    fp = logs.fingerprint(title, traceback)
    ts = db.now()
    existing = db.query_one("SELECT * FROM incidents WHERE project_id = ? AND fingerprint = ?", (pid, fp))
    if existing:
        db.execute("UPDATE incidents SET occurrences = occurrences + 1, last_seen_at = ?, status = 'open', "
                   "resolved_at = NULL, message = ?, traceback = ? WHERE id = ?",
                   (ts, message or existing["message"], traceback[:100000] or existing["traceback"], existing["id"]))
        return db.query_one("SELECT * FROM incidents WHERE id = ?", (existing["id"],))
    iid = db.execute(
        "INSERT INTO incidents(project_id, title, message, traceback, level, source, fingerprint, created_at, "
        "last_seen_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, title, message, traceback[:100000], level, source, fp, ts, ts))
    return db.query_one("SELECT * FROM incidents WHERE id = ?", (iid,))


@bp.post("/projects/<int:pid>/incidents")
def incidents_create(pid: int):
    get_project(pid)
    data = body()
    source = data.get("source") if data.get("source") in ("manual", "log") else "manual"
    return jsonify(_save_incident(pid, data, source)), 201


@bp.put("/projects/<int:pid>/incidents/<int:iid>")
def incidents_update(pid: int, iid: int):
    inc = db.query_one("SELECT * FROM incidents WHERE id = ? AND project_id = ?", (iid, pid))
    if not inc:
        abort(404)
    data = body()
    status = data.get("status", inc["status"])
    if status not in ("open", "resolved"):
        abort(400, description="Некоректний статус")
    resolved_at = db.now() if status == "resolved" and inc["status"] != "resolved" else (
        inc["resolved_at"] if status == "resolved" else None)
    db.execute("UPDATE incidents SET status = ?, notes = ?, resolved_at = ? WHERE id = ?",
               (status, data.get("notes", inc["notes"]), resolved_at, iid))
    return jsonify(db.query_one("SELECT * FROM incidents WHERE id = ?", (iid,)))


@bp.delete("/projects/<int:pid>/incidents/<int:iid>")
def incidents_delete(pid: int, iid: int):
    db.execute("DELETE FROM incidents WHERE id = ? AND project_id = ?", (iid, pid))
    return jsonify(ok=True)


@bp.post("/ingest/<key>")
def ingest_incident(key: str):
    """Сюди проект може сам надсилати свої падіння (див. вкладку «Падіння, помилки»)."""
    proj = db.query_one("SELECT id FROM projects WHERE ingest_key = ?", (key,))
    if not proj:
        abort(404, description="Невідомий ключ")
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        abort(400, description="Очікується JSON-об'єкт")
    inc = _save_incident(proj["id"], data, "api")
    return jsonify(id=inc["id"], occurrences=inc["occurrences"]), 201


@bp.get("/projects/<int:pid>/logs")
def logs_list(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(files=logs.find_log_files(root))


@bp.get("/projects/<int:pid>/logs/view")
def logs_view(pid: int):
    _proj, root = project_and_root(pid)
    return jsonify(logs.analyze_log(root, request.args.get("path", "")))


# =================================================================== тести


_PYTEST_SUMMARY = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|warnings?)")


def _test_summary(output: str) -> dict:
    summary = {}
    tail = "\n".join(output.splitlines()[-15:])
    for count, word in _PYTEST_SUMMARY.findall(tail):
        summary[word.rstrip("s") if word.startswith(("error", "warning")) else word] = int(count)
    m = re.search(r"Tests:\s+(.*)", tail)  # jest
    if m:
        for count, word in re.findall(r"(\d+) (passed|failed|skipped|total)", m.group(1)):
            summary[word] = int(count)
    return summary


@bp.post("/projects/<int:pid>/tests/run")
def tests_run(pid: int):
    proj, root = project_and_root(pid)
    data = body()
    command = (data.get("command") or proj["test_cmd"] or runner.detect_test_command(root)).strip()
    if not command:
        abort(400, description="Не знайдено команду для тестів — вкажіть її вручну")
    if data.get("save") and command != proj["test_cmd"]:
        db.execute("UPDATE projects SET test_cmd = ?, updated_at = ? WHERE id = ?", (command, db.now(), pid))
    result = runner.run_command(command, root, timeout=timeout())
    run = db.record_run(pid, "test", command, result)
    run["summary"] = _test_summary(result["output"])
    return jsonify(run)


# =================================================================== git


@bp.get("/projects/<int:pid>/git/status")
def git_status(pid: int):
    _proj, root = project_and_root(pid)
    st = git_ops.status(root)
    if st.get("is_repo"):
        st["branches"] = git_ops.branches(root)
    return jsonify(st)


@bp.get("/projects/<int:pid>/git/diff")
def git_diff(pid: int):
    _proj, root = project_and_root(pid)
    path = request.args.get("path") or None
    if path:
        fs.safe_path(root, path)
    return jsonify(diff=git_ops.diff(root, path, staged=request.args.get("staged") == "1"))


@bp.get("/projects/<int:pid>/git/log")
def git_log(pid: int):
    _proj, root = project_and_root(pid)
    if not git_ops.is_repo(root):
        return jsonify(is_repo=False, commits=[])
    path = request.args.get("path") or None
    if path:
        fs.safe_path(root, path)
    return jsonify(is_repo=True, commits=git_ops.log(root, limit=int(request.args.get("limit", 100)), path=path))


@bp.get("/projects/<int:pid>/git/show/<sha>")
def git_show(pid: int, sha: str):
    _proj, root = project_and_root(pid)
    return jsonify(diff=git_ops.show(root, sha))


def _git_action(pid: int, summary: str, func, *args):
    _proj, root = project_and_root(pid)
    output = func(root, *args)
    db.record_change(pid, "git", "", summary, output[-20000:] if output else "")
    return jsonify(ok=True, output=output, status=git_ops.status(root))


@bp.post("/projects/<int:pid>/git/commit")
def git_commit(pid: int):
    data = body()
    message = (data.get("message") or "").strip()
    return _git_action(pid, f"Коміт: {message[:120]}", git_ops.commit, message, data.get("paths") or None)


@bp.post("/projects/<int:pid>/git/pull")
def git_pull(pid: int):
    data = body()
    return _git_action(pid, "git pull", git_ops.pull, data.get("remote") or None, data.get("branch") or None)


@bp.post("/projects/<int:pid>/git/push")
def git_push(pid: int):
    data = body()
    return _git_action(pid, "git push", git_ops.push, data.get("remote") or None, data.get("branch") or None)


@bp.post("/projects/<int:pid>/git/fetch")
def git_fetch(pid: int):
    return _git_action(pid, "git fetch", git_ops.fetch, body().get("remote") or None)


@bp.post("/projects/<int:pid>/git/checkout")
def git_checkout(pid: int):
    data = body()
    branch = (data.get("branch") or "").strip()
    return _git_action(pid, f"Перехід на гілку {branch}", git_ops.checkout, branch,
                       bool(data.get("create")))


@bp.post("/projects/<int:pid>/git/init")
def git_init(pid: int):
    return _git_action(pid, "git init", git_ops.init)
