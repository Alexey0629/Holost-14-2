"""Holost — локальна система «Всі проекти».

Flask-застосунок, який збирає всі проекти з кодом в одному місці і дає
для кожного проекту набір інструментів: папки, опис, редактор коду,
структуру БД, API, пошук, картинки, оновлення з проду, історію змін,
помилки, структуру проекту, тести та git.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from . import db, security

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)

    data_dir = Path(os.environ.get("HOLOST_DATA_DIR") or BASE_DIR / "instance")
    app.config.update(
        DATA_DIR=str(data_dir),
        DATABASE=str(data_dir / "holost.db"),
        # Папки, у яких шукаються проекти (розділювач — os.pathsep, тобто ":" або ";").
        PROJECT_ROOTS=os.environ.get("HOLOST_ROOTS", ""),
        # Хости, з яких дозволено відкривати застосунок (захист від DNS-rebinding).
        ALLOWED_HOSTS=set(
            filter(None, os.environ.get("HOLOST_ALLOWED_HOSTS", "127.0.0.1,localhost,::1").split(","))
        ),
        COMMAND_TIMEOUT=int(os.environ.get("HOLOST_COMMAND_TIMEOUT", "600")),
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)

    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    security.init_app(app)

    from .routes import api, pages

    app.register_blueprint(pages.bp)
    app.register_blueprint(api.bp)
    api.register_error_handlers(app)

    return app
