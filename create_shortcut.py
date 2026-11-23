"""Створює ярлик «Всі проекти» на робочому столі (Windows / macOS / Linux).

    python create_shortcut.py

Ярлик запускає start.bat (Windows) або start.sh (macOS/Linux): вони піднімають сервер
і відкривають браузер. Якщо сервер уже працює — просто відкривається браузер.
Викликається автоматично при першому запуску start.bat / start.sh.
"""
from __future__ import annotations

import base64
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

APP_NAME = "Всі проекти"
ROOT = Path(__file__).resolve().parent
ICONS = ROOT / "allprojects" / "static" / "icons"


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ------------------------------------------------------------------ Windows


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_windows() -> list[str]:
    target = ROOT / "start.bat"
    icon = ICONS / "app.ico"
    script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$shell = New-Object -ComObject WScript.Shell
$created = @()
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
    if (-not $folder) {{ continue }}
    $path = Join-Path $folder {_ps_quote(APP_NAME + '.lnk')}
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = {_ps_quote(str(target))}
    $lnk.WorkingDirectory = {_ps_quote(str(ROOT))}
    $lnk.IconLocation = {_ps_quote(str(icon) + ',0')}
    $lnk.Description = {_ps_quote('Локальна система: усі проекти з кодом')}
    $lnk.Save()
    $created += $path
}}
$created -join "`n"
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


# ------------------------------------------------------------------ macOS


def create_macos() -> list[str]:
    """Маленький .app, який відкриває Terminal зі start.sh (закрили вікно — сервер зупинився)."""
    start = ROOT / "start.sh"
    _make_executable(start)
    created = []
    for folder in (Path.home() / "Desktop", Path.home() / "Applications"):
        if folder.name == "Applications" and not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
        app = folder / f"{APP_NAME}.app"
        if app.exists():
            shutil.rmtree(app)
        macos_dir = app / "Contents" / "MacOS"
        res_dir = app / "Contents" / "Resources"
        macos_dir.mkdir(parents=True)
        res_dir.mkdir(parents=True)
        launcher = macos_dir / "launcher"
        launcher.write_text(f'#!/bin/bash\nopen -a Terminal "{start}"\n', encoding="utf-8")
        _make_executable(launcher)
        shutil.copy(ICONS / "app.icns", res_dir / "app.icns")
        with open(app / "Contents" / "Info.plist", "wb") as fh:
            plistlib.dump({
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": "local.allprojects.launcher",
                "CFBundleExecutable": "launcher",
                "CFBundleIconFile": "app.icns",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1.0",
            }, fh)
        created.append(str(app))
    return created


# ------------------------------------------------------------------ Linux


def _linux_desktop_dir() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except FileNotFoundError:
        pass
    for name in ("Desktop", "Робочий стіл", "Рабочий стол"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home() / "Desktop"


def create_linux() -> list[str]:
    start = ROOT / "start.sh"
    _make_executable(start)
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Локальна система: усі проекти з кодом\n"
        f'Exec="{start}"\n'
        f"Path={ROOT}\n"
        f"Icon={ICONS / 'app-512.png'}\n"
        "Terminal=true\n"
        "Categories=Development;\n"
    )
    created = []
    apps_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
    for folder in (_linux_desktop_dir(), apps_dir):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "vsi-proekty.desktop"
        path.write_text(entry, encoding="utf-8")
        _make_executable(path)
        if shutil.which("gio"):
            # GNOME: дозволити запуск ярлика з робочого столу без підтвердження
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"], capture_output=True, check=False)
        created.append(str(path))
    return created


def main() -> int:
    try:
        if os.name == "nt":
            created = create_windows()
        elif sys.platform == "darwin":
            created = create_macos()
        else:
            created = create_linux()
    except Exception as exc:  # noqa: BLE001 - показуємо користувачу причину
        print(f"Не вдалося створити ярлик: {exc}")
        return 1
    print("Ярлик «Всі проекти» створено:")
    for path in created:
        print("  ", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
