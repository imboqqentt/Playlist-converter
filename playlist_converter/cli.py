"""Interfaz de línea de comandos.

Uso:
    python -m playlist_converter                      # ventana (interfaz gráfica)
    python -m playlist_converter menu                 # menú en la terminal
    python -m playlist_converter add-account NOMBRE
    python -m playlist_converter accounts
    python -m playlist_converter convert <link de Spotify o YouTube Music | liked> [opciones]
    python -m playlist_converter synced               # playlists sincronizadas
    python -m playlist_converter update [ID ...] [--all] [--remove-missing]
    python -m playlist_converter link <origen> <destino>
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import accounts, config, links, report, services
from .converter import ConvertOptions, convert, link_from_outcome, sync
from .links import SyncLink
from .models import MatchResult, MatchStatus
from .refs import SERVICE_NAMES, SPOTIFY, YTMUSIC, other_service, parse_ref

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
        description="Convierte y sincroniza playlists entre Spotify y YouTube Music.",
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
    sub.add_parser("selftest")  # uso interno: comprueba que la ventana abre

    remove = sub.add_parser("remove-account", help="Borra una cuenta guardada.")
    remove.add_argument("account")

    def add_account_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--account", help="Cuenta de YouTube Music a usar (ver 'accounts').")
        p.add_argument("--auth", help="Archivo de sesión de YouTube Music (en vez de --account).")
        p.add_argument(
            "--delay",
            type=float,
            default=0.0,
            help="Segundos de espera entre búsquedas (útil si YouTube Music te limita).",
        )

    convert_p = sub.add_parser(
        "convert",
        help="Convierte una playlist (la dirección se detecta según el link).",
    )
    convert_p.add_argument(
        "playlist",
        help="Link de una playlist de Spotify o de YouTube Music, o 'liked' para tus canciones guardadas.",
    )
    convert_p.add_argument(
        "--from",
        dest="source",
        choices=[SPOTIFY, YTMUSIC],
        default=SPOTIFY,
        help="Solo para 'liked': de qué servicio tomar tus canciones guardadas (por defecto spotify).",
    )
    convert_p.add_argument("--name", help="Nombre de la playlist nueva (por defecto, el del origen).")
    convert_p.add_argument(
        "--privacy",
        choices=["PRIVATE", "UNLISTED", "PUBLIC"],
        default="PRIVATE",
        help="Privacidad de la playlist nueva (por defecto PRIVATE; Spotify no tiene UNLISTED).",
    )
    convert_p.add_argument(
        "--append-to",
        metavar="PLAYLIST_ID",
        help="Agregar a una playlist existente del destino en vez de crear una nueva.",
    )
    convert_p.add_argument(
        "--strict",
        action="store_true",
        help="No agregar las coincidencias dudosas (solo quedan en el reporte).",
    )
    convert_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo buscar y generar el reporte, sin crear ni modificar playlists.",
    )
    convert_p.add_argument("--limit", type=int, help="Procesar solo las primeras N canciones.")
    convert_p.add_argument("--report", type=Path, help="Ruta del reporte CSV.")
    add_account_args(convert_p)

    sub.add_parser("synced", help="Muestra las playlists sincronizadas.")

    update = sub.add_parser("update", help="Actualiza playlists sincronizadas con las canciones nuevas del origen.")
    update.add_argument("ids", nargs="*", help="IDs de las playlists sincronizadas (ver 'synced').")
    update.add_argument("--all", action="store_true", help="Actualizar todas.")
    update.add_argument(
        "--remove-missing",
        action="store_true",
        help="Quitar del destino las canciones que ya no están en el origen.",
    )
    update.add_argument("--delay", type=float, default=0.0, help=argparse.SUPPRESS)

    link = sub.add_parser("link", help="Vincula dos playlists que ya existen para poder actualizarlas.")
    link.add_argument("origen", help="Link de la playlist de origen.")
    link.add_argument("destino", help="Link de la playlist de destino (del otro servicio).")
    link.add_argument("--strict", action="store_true", help="Al actualizar, no agregar coincidencias dudosas.")
    add_account_args(link)

    unlink = sub.add_parser("unlink", help="Deja de sincronizar una playlist (no borra nada).")
    unlink.add_argument("id")
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


def ensure_spotify_credentials() -> bool:
    config.load_env()
    if not config.missing_vars():
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print(
            f"Faltan tus credenciales de Spotify: {', '.join(config.missing_vars())}.\n"
            f"Crea un archivo .env en {accounts.app_dir()} con estas dos líneas:\n"
            "  SPOTIPY_CLIENT_ID=tu_client_id\n"
            "  SPOTIPY_CLIENT_SECRET=tu_client_secret",
            file=sys.stderr,
        )
        return False
    print(
        "Necesito las credenciales de tu app de Spotify (solo esta vez).\n"
        "Están en https://developer.spotify.com/dashboard > tu app > Settings.\n"
    )
    saved = config.prompt_and_save()
    print(f"Guardadas en {saved.resolve()}\n")
    return True


def ytmusic_factory(delay: float):
    return lambda auth_path: services.default_ytmusic_factory(auth_path, delay=delay)


def print_result(width: int, i: int, total: int, result: MatchResult) -> None:
    if result.status is MatchStatus.NOT_FOUND or not result.candidate:
        found = "→ no encontrada"
    else:
        found = f"→ {result.candidate.title} ({result.score:.2f})"
    print(f"[{i:>{width}}/{total}] {ICONS[result.status]} {result.track.display()} {found}")


def cmd_convert(args: argparse.Namespace) -> int:
    try:
        ref = parse_ref(args.playlist, liked_service=args.source)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    target_service = other_service(ref.service)

    # La cuenta de YouTube Music es obligatoria para escribir en ella o leer tus "Me gusta";
    # para leer una playlist pública de YouTube Music no hace falta.
    needs_account = target_service == YTMUSIC or ref.is_liked
    try:
        auth_path = services.ytmusic_auth(args.account, args.auth, required=needs_account)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not ensure_spotify_credentials():
        return 2

    yt_factory = ytmusic_factory(args.delay)
    source = services.build(ref.service, auth_path, ytmusic_factory=yt_factory)
    target = services.build(target_service, auth_path, ytmusic_factory=yt_factory)
    print(f"{SERVICE_NAMES[ref.service]} → {SERVICE_NAMES[target_service]}")

    width = 1

    def on_start(name: str, total: int) -> None:
        nonlocal width
        width = len(str(total))

    options = ConvertOptions(
        name=args.name,
        privacy=args.privacy,
        strict=args.strict,
        dry_run=args.dry_run,
        limit=args.limit,
        append_to=args.append_to,
    )
    outcome = convert(
        source,
        target,
        ref.id,
        options,
        on_start,
        lambda i, total, result: print_result(width, i, total, result),
        on_status=print,
    )
    if not outcome.results:
        print("La playlist no tiene canciones.")
        return 0

    report_path = args.report or Path(f"reporte_{datetime.now():%Y%m%d_%H%M%S}.csv")
    report.write_csv(outcome.results, report_path)

    print()
    print(report.summary(outcome.results))
    print(f"Reporte: {report_path}")

    if args.dry_run:
        print("Modo --dry-run: no se modificó nada.")
        return 0
    if not outcome.playlist_id:
        print("No hay canciones para agregar.")
        return 1
    print(f"\n{outcome.added} canciones agregadas a {outcome.playlist_url}")

    if not args.limit:  # una conversión parcial no sirve como base para sincronizar
        link = links.upsert(
            link_from_outcome(
                outcome,
                ref.service,
                ref.id,
                source.playlist_name(ref.id),
                services.account_name(auth_path),
                args.strict,
            )
        )
        print(f"Quedó guardada como sincronizada (ID {link.id}). Para actualizarla: update {link.id}")
    return 0


def run_sync(link: SyncLink, remove_missing: bool, delay: float = 0.0) -> int:
    print(f"\n== {link.describe()}")
    needs_account = YTMUSIC == link.target_service or link.source_id == "LM"
    try:
        auth_path = services.ytmusic_auth(link.account, required=needs_account)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    yt_factory = ytmusic_factory(delay)
    source = services.build(link.source_service, auth_path, ytmusic_factory=yt_factory)
    target = services.build(link.target_service, auth_path, ytmusic_factory=yt_factory)

    width = 1

    def on_start(name: str, total: int) -> None:
        nonlocal width
        width = len(str(total))
        print(f"{total} canciones nuevas por buscar." if total else "No hay canciones nuevas.")

    outcome = sync(
        link,
        source,
        target,
        remove_missing=remove_missing,
        on_start=on_start,
        on_result=lambda i, total, result: print_result(width, i, total, result),
        on_status=print,
    )
    links.upsert(link)
    print(f"Agregadas: {outcome.added}. Quitadas: {len(outcome.removed)}.")
    for name in outcome.removed:
        print(f"  − {name}")
    return 0


def cmd_synced(args: argparse.Namespace) -> int:
    saved = links.load()
    if not saved:
        print("No hay playlists sincronizadas. Se agregan solas al convertir una playlist.")
        return 0
    for link in saved:
        account = f" · cuenta {link.account}" if link.account else ""
        print(f"[{link.id}] {link.describe()}")
        print(f"          {link.track_count} canciones · actualizada {link.last_sync or 'nunca'}{account}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    saved = links.load()
    if args.all:
        selected = saved
    else:
        by_id = {l.id: l for l in saved}
        missing = [i for i in args.ids if i not in by_id]
        if missing or not args.ids:
            print(
                f"No encontré: {', '.join(missing)}. " if missing else "Indica los IDs o usa --all. ",
                "Revisa la lista con: synced",
                file=sys.stderr,
            )
            return 2
        selected = [by_id[i] for i in args.ids]
    if not selected:
        print("No hay playlists sincronizadas.")
        return 0
    if not ensure_spotify_credentials():
        return 2
    code = 0
    for link in selected:
        try:
            code = max(code, run_sync(link, args.remove_missing, args.delay))
        except Exception as exc:
            print(f"Error actualizando «{link.target_name}»: {exc}", file=sys.stderr)
            code = 1
    return code


def cmd_link(args: argparse.Namespace) -> int:
    try:
        source_ref = parse_ref(args.origen)
        target_ref = parse_ref(args.destino, liked_service=other_service(source_ref.service))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if source_ref.service == target_ref.service:
        print("El origen y el destino deben ser de servicios distintos.", file=sys.stderr)
        return 2
    if target_ref.is_liked:
        print("El destino debe ser una playlist, no tus canciones guardadas.", file=sys.stderr)
        return 2
    try:
        auth_path = services.ytmusic_auth(args.account, args.auth, required=True)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not ensure_spotify_credentials():
        return 2
    source = services.build(source_ref.service, auth_path)
    target = services.build(target_ref.service, auth_path)
    link = links.upsert(
        SyncLink(
            source_service=source_ref.service,
            source_id=source_ref.id,
            source_name=source.playlist_name(source_ref.id),
            target_service=target_ref.service,
            target_id=target_ref.id,
            target_name=target.playlist_name(target_ref.id),
            account=services.account_name(auth_path),
            strict=args.strict,
        )
    )
    print(f"Vinculadas: {link.describe()} (ID {link.id}).")
    print(f"Para traer las canciones que falten: update {link.id}")
    return 0


def cmd_unlink(args: argparse.Namespace) -> int:
    if links.remove(args.id):
        print("Listo: ya no se sincroniza (no se borró ninguna playlist).")
        return 0
    print(f"No existe la sincronización '{args.id}'.", file=sys.stderr)
    return 2


COMMANDS = {
    "add-account": cmd_add_account,
    "setup-ytmusic": cmd_add_account,
    "accounts": cmd_accounts,
    "remove-account": cmd_remove_account,
    "convert": cmd_convert,
    "synced": cmd_synced,
    "update": cmd_update,
    "link": cmd_link,
    "unlink": cmd_unlink,
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
