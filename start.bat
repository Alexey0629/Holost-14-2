@echo off
chcp 65001 >nul
rem Запуск «Всі проекти» на Windows: створює venv, ставить залежності, відкриває браузер.
rem При першому запуску створює ярлик на робочому столі та в меню «Пуск».
set PYTHONIOENCODING=utf-8
title Всі проекти
cd /d "%~dp0"

set FIRST_RUN=0
if not exist venv\Scripts\python.exe (
  echo Перший запуск: створюю віртуальне оточення...
  py -3 -m venv venv 2>nul || python -m venv venv
  set FIRST_RUN=1
)
if not exist venv\Scripts\python.exe (
  echo Не знайдено Python 3. Встановіть його: https://www.python.org/downloads/ ^(галочка "Add python.exe to PATH"^)
  pause
  exit /b 1
)

venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt
if "%FIRST_RUN%"=="1" venv\Scripts\python.exe create_shortcut.py

venv\Scripts\python.exe run.py --open %*
if errorlevel 1 pause
