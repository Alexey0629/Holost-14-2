@echo off
rem Запуск «Всі проекти» на Windows: створює venv, ставить залежності, відкриває браузер.
chcp 65001 >nul
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
  echo Створюю віртуальне оточення...
  py -3 -m venv venv 2>nul || python -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo Не знайдено Python 3. Встановіть його: https://www.python.org/downloads/ ^(галочка "Add python.exe to PATH"^)
  pause
  exit /b 1
)

venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt
venv\Scripts\python.exe run.py --open %*
pause
