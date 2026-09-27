"""Carga de credenciales desde un archivo .env, para no tener que exportarlas cada vez."""

from __future__ import annotations

import os
from pathlib import Path

# El Bloc de notas de Windows suele guardar ".env" como ".env.txt".
ENV_FILES = (".env", ".env.txt")
REQUIRED_VARS = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET")


def load_env_file(directory: Path = Path(".")) -> Path | None:
    """Carga variables KEY=VALUE del primer archivo .env que exista.

    No pisa variables que ya estén definidas en el entorno.
    """
    for name in ENV_FILES:
        path = directory / name
        if path.is_file():
            # utf-8-sig: el Bloc de notas a veces agrega un BOM al inicio.
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().removeprefix("export ").strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)
            return path
    return None


def missing_vars() -> list[str]:
    return [name for name in REQUIRED_VARS if not os.environ.get(name)]
