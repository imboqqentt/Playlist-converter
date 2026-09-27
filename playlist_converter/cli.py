"""Interfaz de línea de comandos.

Uso:
    python -m playlist_converter setup-ytmusic
    python -m playlist_converter convert <playlist de Spotify | liked> [opciones]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import report
from .models import MatchResult, MatchStatus
from .spotify_source import SpotifySource, parse_playlist_ref
from .ytmusic_target import YTMusicTarget

DEFAULT_AUTH_FILE = "browser.json"
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

    setup = sub.add_parser(
        "setup-ytmusic",
        help="Guarda las credenciales de YouTube Music (se hace una sola vez).",
    )
    setup.add_argument("--auth", default=DEFAULT_AUTH_FILE, help="Archivo donde guardarlas.")

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
    convert.add_argument("--auth", default=DEFAULT_AUTH_FILE, help="Credenciales de YouTube Music.")
    convert.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Segundos de espera entre búsquedas (útil si YouTube Music te limita).",
    )
    return parser


def cmd_setup(args: argparse.Namespace) -> int:
    from ytmusicapi import setup

    print(
        "1. Abre https://music.youtube.com en tu navegador con tu cuenta iniciada.\n"
        "2. Abre las herramientas de desarrollo (F12) > pestaña Red (Network).\n"
        "3. Filtra por 'browse' y haz clic en alguna sección de YouTube Music.\n"
        "4. Selecciona una petición POST a 'browse' y copia sus Request Headers.\n"
        "   (En Firefox: clic derecho > Copiar > Copiar encabezados de la petición)\n"
        "5. Pégalos abajo y termina con Enter + Ctrl-D (Ctrl-Z + Enter en Windows).\n"
    )
    setup(filepath=args.auth)
    print(f"\nListo. Credenciales guardadas en {args.auth}. ¡No compartas ese archivo!")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    try:
        playlist_id = parse_playlist_ref(args.playlist)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if not Path(args.auth).exists():
        print(
            f"No encuentro {args.auth}. Ejecuta primero:\n"
            "  python -m playlist_converter setup-ytmusic",
            file=sys.stderr,
        )
        return 2

    spotify = SpotifySource.from_env()
    ytmusic = YTMusicTarget.from_auth_file(args.auth, delay=args.delay)

    name = args.name or spotify.playlist_name(playlist_id)
    print(f"Leyendo '{name}' desde Spotify...")
    tracks = list(spotify.tracks(playlist_id))
    if args.limit:
        tracks = tracks[: args.limit]
    if not tracks:
        print("La playlist no tiene canciones.")
        return 0

    results: list[MatchResult] = []
    width = len(str(len(tracks)))
    for i, track in enumerate(tracks, start=1):
        result = ytmusic.find(track)
        results.append(result)
        found = f"→ {result.candidate.title} ({result.score:.2f})" if result.candidate else ""
        if result.status is MatchStatus.NOT_FOUND:
            found = "→ no encontrada"
        print(f"[{i:>{width}}/{len(tracks)}] {ICONS[result.status]} {track.display()} {found}")

    allowed = {MatchStatus.MATCHED} if args.strict else {MatchStatus.MATCHED, MatchStatus.LOW_CONFIDENCE}
    video_ids = [r.candidate.video_id for r in results if r.status in allowed and r.candidate]

    report_path = args.report or Path(f"reporte_{datetime.now():%Y%m%d_%H%M%S}.csv")
    report.write_csv(results, report_path)

    print()
    print(report.summary(results))
    print(f"Reporte: {report_path}")

    if args.dry_run:
        print("Modo --dry-run: no se modificó YouTube Music.")
        return 0
    if not video_ids:
        print("No hay canciones para agregar.")
        return 1

    if args.append_to:
        target_id = args.append_to
    else:
        target_id = ytmusic.create_playlist(
            name, description="Convertida desde Spotify con playlist-converter", privacy=args.privacy
        )
    ytmusic.add_videos(target_id, video_ids)
    print(f"\n{len(set(video_ids))} canciones agregadas a https://music.youtube.com/playlist?list={target_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "setup-ytmusic":
        return cmd_setup(args)
    return cmd_convert(args)


if __name__ == "__main__":
    raise SystemExit(main())
