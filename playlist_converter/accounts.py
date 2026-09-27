"""Cuentas de YouTube Music guardadas y carpeta de datos del programa.

Cada cuenta es un archivo JSON con la sesión del navegador, guardado en la
carpeta de datos del usuario (en Windows, %APPDATA%\\PlaylistConverter), así el
.exe funciona sin importar desde qué carpeta se abra.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable

LEGACY_AUTH_FILE = "browser.json"
_NAME_RE = re.compile(r"[^\w-]+", re.UNICODE)


def app_dir() -> Path:
    override = os.environ.get("PLAYLIST_CONVERTER_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home())) / "PlaylistConverter"
    else:
        path = Path.home() / ".config" / "playlist-converter"
    path.mkdir(parents=True, exist_ok=True)
    return path


def accounts_dir() -> Path:
    path = app_dir() / "cuentas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_name(name: str) -> str:
    cleaned = _NAME_RE.sub("_", name.strip()).strip("_")
    if not cleaned:
        raise ValueError("El nombre de la cuenta no puede estar vacío.")
    return cleaned


def account_path(name: str) -> Path:
    return accounts_dir() / f"{clean_name(name)}.json"


def list_accounts() -> list[str]:
    return sorted(p.stem for p in accounts_dir().glob("*.json"))


def remove_account(name: str) -> bool:
    path = account_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def save_account(name: str, headers_raw: str) -> Path:
    """Guarda la sesión a partir de los encabezados copiados del navegador."""
    from ytmusicapi import setup

    path = account_path(name)
    setup(filepath=str(path), headers_raw=headers_raw)
    return path


def read_headers(ask: Callable[[str], str] | None = None) -> str:
    """Lee encabezados pegados en la terminal hasta una línea vacía (o Ctrl-Z/Ctrl-D)."""
    ask = ask or input
    lines: list[str] = []
    while True:
        try:
            line = ask("")
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines)


def resolve_auth(account: str | None, auth: str | None) -> Path:
    """Decide qué archivo de sesión usar. Lanza ValueError con un mensaje claro."""
    if auth:
        path = Path(auth)
        if not path.exists():
            raise ValueError(f"No encuentro el archivo {auth}.")
        return path
    if account:
        path = account_path(account)
        if not path.exists():
            raise ValueError(
                f"No existe la cuenta '{account}'. Cuentas guardadas: "
                f"{', '.join(list_accounts()) or 'ninguna'}."
            )
        return path

    names = list_accounts()
    if len(names) == 1:
        return account_path(names[0])
    if len(names) > 1:
        raise ValueError(
            f"Tienes varias cuentas ({', '.join(names)}). Elige una con --account NOMBRE."
        )
    if Path(LEGACY_AUTH_FILE).exists():  # versiones anteriores guardaban browser.json aquí
        return Path(LEGACY_AUTH_FILE)
    raise ValueError(
        "No hay ninguna cuenta de YouTube Music. Agrega una con:\n"
        "  python -m playlist_converter add-account NOMBRE"
    )
