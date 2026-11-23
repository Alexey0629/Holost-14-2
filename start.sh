#!/usr/bin/env bash
# Запуск «Всі проекти» на macOS / Linux: створює venv, ставить залежності, відкриває браузер.
# При першому запуску створює ярлик на робочому столі.
set -e
cd "$(dirname "$0")"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Не знайдено Python 3. Встановіть його: https://www.python.org/downloads/" >&2
  read -r -p "Натисніть Enter…" _ || true
  exit 1
fi

FIRST_RUN=0
if [ ! -x venv/bin/python ]; then
  echo "Перший запуск: створюю віртуальне оточення…"
  "$PY" -m venv venv
  FIRST_RUN=1
fi
venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt

if [ "$FIRST_RUN" = 1 ]; then
  venv/bin/python create_shortcut.py || true
fi

exec venv/bin/python run.py --open "$@"
