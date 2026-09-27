"""Carga de credenciales desde un archivo .env, para no tener que exportarlas cada vez."""

from __future__ import annotations

import os
from pathlib import Path

# El Bloc de notas de Windows suele guardar ".env" como ".env.txt".
ENV_FILES = (".env", ".env.txt")
REQUIRED_VARS = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET")


def load_env() -> Path | None:
    """Busca .env en la carpeta actual y luego en la carpeta de datos del programa."""
    from .accounts import app_dir

    return load_env_file(Path(".")) or load_env_file(app_dir())


def load_env_file(directory: Path = Path(".")) -> Path | None:
    """Carga variables KEY=VALUE del primer archivo .env que exista.

    No pisa variables que ya estén definidas en el entorno.
    """
    for name in ENV_FILES:
        path = directory / name
        if path.is_file():
            for line in _read_text(path).splitlines():
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


def save_credentials(client_id: str, client_secret: str, directory: Path | None = None) -> Path:
    """Guarda las credenciales en .env (carpeta de datos) y las activa ahora mismo."""
    if directory is None:
        from .accounts import app_dir

        directory = app_dir()
    os.environ["SPOTIPY_CLIENT_ID"] = client_id.strip()
    os.environ["SPOTIPY_CLIENT_SECRET"] = client_secret.strip()
    path = directory / ".env"
    path.write_text(
        "".join(f"{name}={os.environ[name]}\n" for name in REQUIRED_VARS), encoding="utf-8"
    )
    return path


def prompt_and_save(directory: Path | None = None, ask=input) -> Path:
    """Pide las credenciales que falten y las guarda en .env para la próxima vez."""
    labels = {"SPOTIPY_CLIENT_ID": "Client ID", "SPOTIPY_CLIENT_SECRET": "Client Secret"}
    for name in missing_vars():
        value = ""
        while not value:
            value = ask(f"Pega tu {labels[name]} de Spotify: ").strip().strip('"').strip("'")
        os.environ[name] = value
    return save_credentials(
        os.environ["SPOTIPY_CLIENT_ID"], os.environ["SPOTIPY_CLIENT_SECRET"], directory
    )


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    # El Bloc de notas puede guardar en UTF-16 ("Unicode") o con BOM UTF-8.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")
