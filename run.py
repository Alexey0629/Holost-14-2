"""Запуск локальної системи «Всі проекти».

    python run.py                 # http://127.0.0.1:5000
    python run.py --port 8080 --open

Змінні оточення:
    ALLPROJECTS_ROOTS             папки з проектами (через ":" на Linux/macOS або ";" на Windows)
    ALLPROJECTS_DATA_DIR          де зберігати базу застосунку (за замовчуванням ./instance)
    ALLPROJECTS_COMMAND_TIMEOUT   ліміт часу для тестів / оновлення з проду, секунд (600)
    ALLPROJECTS_ALLOWED_HOSTS     дозволені хости через кому (127.0.0.1,localhost,::1)
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import urllib.request
import webbrowser

from allprojects import create_app


def already_running(url: str) -> bool:
    """Чи вже запущено «Всі проекти» на цьому порту (повторний клік по ярлику)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "/", timeout=1.5) as resp:
            return "Всі проекти" in resp.read(4096).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001 - будь-яка помилка = не запущено
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Локальна система «Всі проекти»")
    parser.add_argument("--host", default="127.0.0.1", help="адреса (за замовчуванням лише цей комп'ютер)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--open", action="store_true", help="відкрити браузер після запуску")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    if already_running(url):
        print(f"«Всі проекти» вже запущено: {url}")
        if args.open:
            webbrowser.open(url)
        return 0

    app = create_app()
    if not args.debug:
        # Без технічного шуму в консолі: лише адреса і помилки.
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"\n  Всі проекти: {url}")
    print("  Не закривайте це вікно, поки працюєте. Зупинити: Ctrl+C або закрити вікно.\n")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
