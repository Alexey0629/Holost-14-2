"""Запуск локальної системи «Всі проекти».

    python run.py                 # http://127.0.0.1:5000
    python run.py --port 8080 --open

Змінні оточення:
    HOLOST_ROOTS            папки з проектами (через ":" на Linux/macOS або ";" на Windows)
    HOLOST_DATA_DIR         де зберігати базу Holost (за замовчуванням ./instance)
    HOLOST_COMMAND_TIMEOUT  ліміт часу для тестів / оновлення з проду, секунд (600)
    HOLOST_ALLOWED_HOSTS    дозволені хости через кому (127.0.0.1,localhost,::1)
"""
from __future__ import annotations

import argparse
import threading
import webbrowser

from holost import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Holost — локальна система «Всі проекти»")
    parser.add_argument("--host", default="127.0.0.1", help="адреса (за замовчуванням лише цей комп'ютер)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--open", action="store_true", help="відкрити браузер після запуску")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"\n  🗂️  Всі проекти: {url}\n")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
