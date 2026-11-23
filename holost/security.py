"""Захист локального застосунку.

Застосунок вміє запускати команди та змінювати файли, тому:
  * відповідаємо лише на запити до дозволених хостів (захист від DNS-rebinding);
  * усі змінюючі запити вимагають заголовок X-CSRF-Token, який знає лише наша
    власна сторінка (сторонній сайт не зможе «смикнути» localhost);
  * сирі файли проекту віддаються з CSP sandbox, щоб SVG/HTML не виконували скрипти.
"""
from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from flask import Flask, abort, current_app, jsonify, request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Ендпоінти, які приймають запити від самих проектів (звіти про помилки).
CSRF_EXEMPT_ENDPOINTS = {"api.ingest_incident"}


def _load_token(data_dir: str) -> str:
    token_file = Path(data_dir) / "csrf_token"
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    token_file.write_text(token, encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return token


def csrf_token() -> str:
    return current_app.config["CSRF_TOKEN"]


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def init_app(app: Flask) -> None:
    app.config.setdefault("CSRF_TOKEN", _load_token(app.config["DATA_DIR"]))

    @app.context_processor
    def _inject_token():
        return {"csrf_token": csrf_token()}

    @app.before_request
    def _guard():
        endpoint = request.endpoint or ""
        allowed = current_app.config.get("ALLOWED_HOSTS") or set()
        if "*" not in allowed and endpoint not in CSRF_EXEMPT_ENDPOINTS:
            if _hostname(request.host) not in {h.lower() for h in allowed}:
                abort(403, description="Хост не дозволений. Додайте його в HOLOST_ALLOWED_HOSTS.")

        if request.method in SAFE_METHODS or endpoint in CSRF_EXEMPT_ENDPOINTS:
            return None
        sent = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, csrf_token()):
            response = jsonify(error="Невірний CSRF-токен. Оновіть сторінку.")
            response.status_code = 403
            return response
        return None

    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
