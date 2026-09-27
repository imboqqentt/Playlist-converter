"""Menú guiado: es lo que se ve al abrir el .exe con doble clic."""

from __future__ import annotations

from typing import Callable

from . import accounts
from .cli import HEADERS_HELP, build_parser, cmd_convert
from .refs import parse_ref

Ask = Callable[[str], str]

BANNER = "=== Playlist Converter: Spotify → YouTube Music ==="


def run_menu(ask: Ask = input) -> int:
    print(BANNER)
    while True:
        names = accounts.list_accounts()
        print()
        print("Cuentas de YouTube Music: " + (", ".join(names) if names else "ninguna todavía"))
        print("  1. Convertir una playlist (Spotify ⇄ YouTube Music)")
        print("  2. Agregar una cuenta de YouTube Music")
        print("  3. Eliminar una cuenta")
        print("  4. Actualizar las playlists sincronizadas")
        print("  5. Salir")
        try:
            choice = ask("Elige una opción: ").strip()
            if choice == "1":
                convert_flow(ask)
            elif choice == "2":
                add_account_flow(ask)
            elif choice == "3":
                remove_account_flow(ask)
            elif choice == "4":
                update_flow(ask)
            elif choice in ("5", "q", "salir"):
                return 0
            else:
                print("Opción no válida.")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        except Exception as exc:  # que un error no cierre la ventana del .exe
            print(f"\n⚠ Ocurrió un error: {exc}")
            print("Si se repite, copia este mensaje y pide ayuda.")


def add_account_flow(ask: Ask) -> str | None:
    name = ask("Nombre para esta cuenta (ej. daniel, mama): ").strip()
    if not name:
        print("Cancelado.")
        return None
    try:
        name = accounts.clean_name(name)
    except ValueError as exc:
        print(exc)
        return None
    if name in accounts.list_accounts():
        if not _yes(ask(f"Ya existe '{name}'. ¿Reemplazarla? (s/N): ")):
            return None
    print()
    print(HEADERS_HELP)
    headers = accounts.read_headers(ask)
    if not headers:
        print("No pegaste nada; no se guardó la cuenta.")
        return None
    try:
        accounts.save_account(name, headers)
    except Exception as exc:
        print(f"No pude leer esos encabezados ({exc}). Revisa que copiaste una petición POST 'browse'.")
        return None
    print(f"✔ Cuenta '{name}' guardada.")
    return name


def remove_account_flow(ask: Ask) -> None:
    name = choose_account(ask, allow_add=False)
    if name and _yes(ask(f"¿Eliminar la cuenta '{name}'? (s/N): ")):
        accounts.remove_account(name)
        print(f"Cuenta '{name}' eliminada.")


def choose_account(ask: Ask, allow_add: bool = True) -> str | None:
    names = accounts.list_accounts()
    if not names:
        if allow_add:
            print("Primero agrega una cuenta de YouTube Music.")
            return add_account_flow(ask)
        print("No hay cuentas guardadas.")
        return None
    if len(names) == 1 and allow_add:
        print(f"Usando la cuenta '{names[0]}'.")
        return names[0]
    for i, name in enumerate(names, start=1):
        print(f"  {i}. {name}")
    choice = ask("¿Qué cuenta? (número): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1]
    print("Opción no válida.")
    return None


def convert_flow(ask: Ask) -> None:
    account = choose_account(ask)
    if not account:
        return

    link = ask(
        "\nPega el link de la playlist de Spotify o de YouTube Music\n"
        "(o escribe 'liked' para tus favoritas de Spotify): "
    ).strip()
    try:
        parse_ref(link)
    except ValueError as exc:
        print(exc)
        return

    argv = ["convert", link, "--account", account]
    name = ask("Nombre de la playlist nueva (Enter = el mismo de Spotify): ").strip()
    if name:
        argv += ["--name", name]
    privacy = ask("Privacidad: 1) Privada  2) No listada  3) Pública  [Enter = Privada]: ").strip()
    argv += ["--privacy", {"2": "UNLISTED", "3": "PUBLIC"}.get(privacy, "PRIVATE")]
    if _yes(ask("¿Solo probar, sin crear la playlist todavía? (s/N): ")):
        argv.append("--dry-run")

    print()
    cmd_convert(build_parser().parse_args(argv))
    ask("\nPresiona Enter para volver al menú...")


def update_flow(ask: Ask) -> None:
    import argparse

    from . import links
    from .cli import cmd_update

    if not links.load():
        print("No hay playlists sincronizadas todavía: se agregan solas al convertir una.")
        return
    remove = _yes(ask("¿Quitar del destino las canciones que ya no están en el origen? (s/N): "))
    cmd_update(argparse.Namespace(ids=[], all=True, remove_missing=remove, delay=0.0))
    ask("\nPresiona Enter para volver al menú...")


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("s", "si", "sí", "y", "yes")

