#!/usr/bin/env bash
# Запуск «Всі проекти» на macOS / Linux: створює venv, ставить залежності, відкриває браузер.
set -e
cd "$(dirname "$0")"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Не знайдено Python 3. Встановіть його: https://www.python.org/downloads/" >&2
  exit 1
fi

if [ ! -x venv/bin/python ]; then
  echo "Створюю віртуальне оточення…"
  "$PY" -m venv venv
fi
venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
exec venv/bin/python run.py --open "$@"
