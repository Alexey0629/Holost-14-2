"""Простий HTTP-клієнт для вкладки «API»: надсилає запит від імені сервера (без CORS-обмежень)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

MAX_BODY = 1_000_000
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class HttpError(ValueError):
    pass


def parse_headers(raw) -> dict:
    """Приймає dict, JSON-рядок або рядки формату 'Key: Value'."""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            return {str(k): str(v) for k, v in data.items()}
        except ValueError as exc:
            raise HttpError(f"Заголовки: некоректний JSON ({exc})") from exc
    headers = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                headers[k.strip()] = v.strip()
    return headers


def build_url(base: str, url: str) -> str:
    url = (url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    if not base:
        raise HttpError("Вкажіть повний URL (http://...) або базовий URL API в налаштуваннях проекту")
    return urljoin(base.rstrip("/") + "/", url.lstrip("/"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - показуємо редірект як є
        return None


def send(method: str, url: str, headers: dict, body: str = "", timeout: int = 30) -> dict:
    method = (method or "GET").upper()
    if method not in METHODS:
        raise HttpError(f"Непідтримуваний метод {method}")
    if urlparse(url).scheme not in ("http", "https"):
        raise HttpError("Підтримуються лише http:// та https://")
    data = body.encode("utf-8") if body and method not in ("GET", "HEAD") else None
    if data is not None and not any(k.lower() == "content-type" for k in headers):
        try:
            json.loads(body)
            headers = {**headers, "Content-Type": "application/json"}
        except ValueError:
            pass
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    start = time.monotonic()
    try:
        resp = opener.open(req, timeout=timeout)
        status, reason = resp.status, resp.reason
        resp_headers = dict(resp.headers.items())
        raw = resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        status, reason = exc.code, exc.reason
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        raw = exc.read(MAX_BODY + 1) if exc.fp else b""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpError(f"Не вдалося виконати запит: {reason}") from exc
    elapsed = round((time.monotonic() - start) * 1000)
    truncated = len(raw) > MAX_BODY
    text = raw[:MAX_BODY].decode("utf-8", errors="replace")
    return {
        "status": status,
        "reason": str(reason),
        "headers": resp_headers,
        "body": text,
        "truncated": truncated,
        "time_ms": elapsed,
        "url": url,
    }
