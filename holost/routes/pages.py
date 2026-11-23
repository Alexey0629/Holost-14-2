"""HTML-сторінки: список усіх проектів і сторінка окремого проекту."""
from __future__ import annotations

import mimetypes

from flask import Blueprint, abort, render_template, request, send_file

from .. import db
from ..services import fs

bp = Blueprint("pages", __name__)

# Вкладки (кнопки) сторінки проекту — у тому ж порядку, що й у плані.
TABS = [
    ("folders", "📁", "Папки"),
    ("about", "📝", "Опис"),
    ("code", "💻", "Код"),
    ("db", "🗄️", "Структура БД"),
    ("usage", "🧭", "Використання"),
    ("api", "🔌", "API"),
    ("search", "🔍", "Пошук"),
    ("visual", "🖼️", "Візуал"),
    ("prod", "⬇️", "Оновлення з проду"),
    ("history", "🕘", "Історія змін"),
    ("errors", "💥", "Падіння, помилки"),
    ("structure", "🌳", "Структура проекту"),
    ("tests", "✅", "Тести + Git"),
    ("settings", "⚙️", "Налаштування"),
]


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/projects/<int:project_id>")
def project(project_id: int):
    proj = db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not proj:
        abort(404)
    db.execute("UPDATE projects SET last_opened_at = ? WHERE id = ?", (db.now(), project_id))
    return render_template("project.html", project=proj, tabs=TABS)


@bp.get("/projects/<int:project_id>/raw")
def raw_file(project_id: int):
    """Сирий файл проекту (картинки для вкладки «Візуал», завантаження файлів)."""
    proj = db.query_one("SELECT path FROM projects WHERE id = ?", (project_id,))
    if not proj:
        abort(404)
    try:
        path = fs.safe_path(fs.project_root(proj["path"]), request.args.get("path", ""))
    except (fs.PathError, FileNotFoundError):
        abort(404)
    if not path.is_file():
        abort(404)
    is_image = path.suffix.lower() in fs.IMAGE_EXTS
    mimetype = mimetypes.guess_type(path.name)[0] if is_image else None
    response = send_file(
        path,
        mimetype=mimetype or "application/octet-stream",
        as_attachment=not is_image,
        download_name=path.name,
        max_age=0,
    )
    # SVG та інші файли не повинні виконувати скрипти в контексті застосунку.
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return response


@bp.app_errorhandler(404)
def not_found(_exc):
    if request.path.startswith("/api/"):
        return {"error": "Не знайдено"}, 404
    return render_template("404.html"), 404
