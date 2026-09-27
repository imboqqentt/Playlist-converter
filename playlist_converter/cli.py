"""Interfaz de línea de comandos.

Uso:
    python -m playlist_converter                      # ventana (interfaz gráfica)
    python -m playlist_converter menu                 # menú en la terminal
    python -m playlist_converter add-account NOMBRE
    python -m playlist_converter accounts
    python -m playlist_converter convert <playlist de Spotify | liked> [opciones]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import accounts, config, report
from .converter import ConvertOptions, convert
from .models import MatchResult, MatchStatus
from .spotify_source import SpotifySource, parse_playlist_ref
from .ytmusic_target import YTMusicTarget

HEADERS_HELP = (
    "Cómo copiar la sesión de YouTube Music:\n"
    "  1. En Firefox, abre https://music.youtube.com con la cuenta que quieres usar.\n"
    "  2. Presiona F12 > pestaña Red (Network) y escribe 'browse' en el filtro.\n"
    "  3. Haz clic en cualquier sección (por ejemplo, Biblioteca).\n"
    "  4. Clic derecho en una petición POST 'browse' > Copiar > Copiar encabezados de la petición.\n"
    "  5. Pégalos aquí (clic derecho en la ventana) y presiona Enter dos veces.\n"
)
ICONS = {
    MatchStatus.MATCHED: "✔",
    MatchStatus.LOW_CONFIDENCE: "?",
    MatchStatus.NOT_FOUND: "✘",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="playlist-converter",
        description="Convierte playlists de Spotify en playlists de YouTube Music.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser(
        "add-account",
        aliases=["setup-ytmusic"],
        help="Guarda la sesión de una cuenta de YouTube Music.",
    )
    add.add_argument("account", nargs="?", default="principal", help="Nombre para la cuenta.")
    add.add_argument("--auth", help="Guardar en este archivo en vez de la carpeta de cuentas.")

    sub.add_parser("accounts", help="Muestra las cuentas de YouTube Music guardadas.")
    sub.add_parser("menu", help="Menú guiado en la terminal.")
    sub.add_parser("gui", help="Abre la ventana (lo mismo que ejecutar sin argumentos).")
    sub.add_parser("selftest", help=argparse.SUPPRESS)

    remove = sub.add_parser("remove-account", help="Borra una cuenta guardada.")
    remove.add_argument("account")

    convert = sub.add_parser("convert", help="Convierte una playlist.")
    convert.add_argument(
        "playlist",
        help="URL, URI o ID de la playlist de Spotify, o 'liked' para tus canciones guardadas.",
    )
    convert.add_argument("--name", help="Nombre de la playlist nueva (por defecto, el de Spotify).")
    convert.add_argument(
        "--privacy",
        choices=["PRIVATE", "UNLISTED", "PUBLIC"],
        default="PRIVATE",
        help="Privacidad de la playlist nueva (por defecto PRIVATE).",
    )
    convert.add_argument(
        "--append-to",
        metavar="PLAYLIST_ID",
        help="Agregar a una playlist existente de YouTube Music en vez de crear una nueva.",
    )
    convert.add_argument(
        "--strict",
        action="store_true",
        help="No agregar las coincidencias dudosas (solo quedan en el reporte).",
    )
    convert.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo buscar y generar el reporte, sin crear ni modificar playlists.",
    )
    convert.add_argument("--limit", type=int, help="Procesar solo las primeras N canciones.")
    convert.add_argument("--report", type=Path, help="Ruta del reporte CSV.")
    convert.add_argument("--account", help="Cuenta de YouTube Music a usar (ver 'accounts').")
    convert.add_argument("--auth", help="Archivo de sesión de YouTube Music (en vez de --account).")
    convert.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Segundos de espera entre búsquedas (útil si YouTube Music te limita).",
    )
    return parser


def cmd_add_account(args: argparse.Namespace) -> int:
    print(HEADERS_HELP)
    headers = accounts.read_headers()
    if not headers:
        print("No pegaste nada; no se guardó la cuenta.", file=sys.stderr)
        return 2
    try:
        if args.auth:
            from ytmusicapi import setup

            setup(filepath=args.auth, headers_raw=headers)
            path = Path(args.auth)
        else:
            path = accounts.save_account(args.account, headers)
    except Exception as exc:  # ytmusicapi lanza errores genéricos si faltan cookies
        print(f"No pude leer esos encabezados: {exc}", file=sys.stderr)
        return 2
    print(f"\nListo. Cuenta guardada en {path}. ¡No compartas ese archivo!")
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    names = accounts.list_accounts()
    if not names:
        print("No hay cuentas guardadas. Agrega una con: add-account NOMBRE")
    for name in names:
        print(f"- {name}")
    print(f"\n(Carpeta: {accounts.accounts_dir()})")
    return 0


def cmd_remove_account(args: argparse.Namespace) -> int:
    if accounts.remove_account(args.account):
        print(f"Cuenta '{args.account}' eliminada.")
        return 0
    print(f"No existe la cuenta '{args.account}'.", file=sys.stderr)
    return 2


def cmd_convert(args: argparse.Namespace) -> int:
    try:
        playlist_id = parse_playlist_ref(args.playlist)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        auth_path = accounts.resolve_auth(args.account, args.auth)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    config.load_env()
    if config.missing_vars():
        if not sys.stdin.isatty():
            print(
                f"Faltan tus credenciales de Spotify: {', '.join(config.missing_vars())}.\n"
                f"Crea un archivo .env en {accounts.app_dir()} con estas dos líneas:\n"
                "  SPOTIPY_CLIENT_ID=tu_client_id\n"
                "  SPOTIPY_CLIENT_SECRET=tu_client_secret",
                file=sys.stderr,
            )
            return 2
        print(
            "Necesito las credenciales de tu app de Spotify (solo esta vez).\n"
            "Están en https://developer.spotify.com/dashboard > tu app > Settings.\n"
        )
        saved = config.prompt_and_save()
        print(f"Guardadas en {saved.resolve()}\n")

    spotify = SpotifySource.from_env()
    ytmusic = YTMusicTarget.from_auth_file(str(auth_path), delay=args.delay)

    width = 1

    def on_start(name: str, total: int) -> None:
        nonlocal width
        width = len(str(total))

    def on_result(i: int, total: int, result: MatchResult) -> None:
        if result.status is MatchStatus.NOT_FOUND or not result.candidate:
            found = "→ no encontrada"
        else:
            found = f"→ {result.candidate.title} ({result.score:.2f})"
        print(f"[{i:>{width}}/{total}] {ICONS[result.status]} {result.track.display()} {found}")

    options = ConvertOptions(
        name=args.name,
        privacy=args.privacy,
        strict=args.strict,
        dry_run=args.dry_run,
        limit=args.limit,
        append_to=args.append_to,
    )
    outcome = convert(spotify, ytmusic, playlist_id, options, on_start, on_result, on_status=print)
    if not outcome.results:
        print("La playlist no tiene canciones.")
        return 0

    report_path = args.report or Path(f"reporte_{datetime.now():%Y%m%d_%H%M%S}.csv")
    report.write_csv(outcome.results, report_path)

    print()
    print(report.summary(outcome.results))
    print(f"Reporte: {report_path}")

    if args.dry_run:
        print("Modo --dry-run: no se modificó YouTube Music.")
        return 0
    if not outcome.playlist_id:
        print("No hay canciones para agregar.")
        return 1
    print(f"\n{outcome.added} canciones agregadas a {outcome.playlist_url}")
    return 0


COMMANDS = {
    "add-account": cmd_add_account,
    "setup-ytmusic": cmd_add_account,
    "accounts": cmd_accounts,
    "remove-account": cmd_remove_account,
    "convert": cmd_convert,
    "menu": lambda args: run_menu(),
    "gui": lambda args: open_gui(),
    "selftest": lambda args: __import__("playlist_converter.gui", fromlist=["selftest"]).selftest(),
}


def run_menu() -> int:
    from .interactive import run_menu as menu

    return menu()


def open_gui() -> int:
    """Abre la ventana; si no se puede (sin Tkinter o sin pantalla), usa el menú de terminal."""
    try:
        from .gui import main as gui_main
    except ImportError:
        return run_menu()
    try:
        return gui_main()
    except Exception as exc:  # p. ej. TclError: no display
        if sys.stdin is None or not sys.stdin.isatty():
            raise
        print(f"No pude abrir la ventana ({exc}); uso el menú en la terminal.")
        return run_menu()


def enable_utf8_output() -> None:
    # En Windows, si la salida se redirige, ✔/✘ y los acentos pueden causar errores.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    enable_utf8_output()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return open_gui()
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
