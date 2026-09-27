"""Interfaz gráfica (ventana) del conversor, hecha con Tkinter."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from . import accounts, config, links, report, services
from .converter import ConvertOptions, ConvertOutcome, SyncOutcome, convert, link_from_outcome, sync
from .links import SyncLink
from .models import MatchResult, MatchStatus
from .refs import (
    SERVICE_NAMES,
    SPOTIFY,
    YTMUSIC,
    PlaylistRef,
    liked_ref,
    other_service,
    parse_ref,
)
from .spotify_service import DEFAULT_REDIRECT_URI

APP_TITLE = "Playlist Converter"
ICON_PATH = Path(__file__).parent / "assets" / "icon_256.png"
SPOTIFY_DASHBOARD = "https://developer.spotify.com/dashboard"
YTMUSIC_URL = "https://music.youtube.com"

STATUS_LABELS = {
    MatchStatus.MATCHED: "✔  Encontrada",
    MatchStatus.LOW_CONFIDENCE: "?  Dudosa",
    MatchStatus.NOT_FOUND: "✘  No encontrada",
}
REMOVED_LABEL = "−  Quitada"
STATUS_COLORS = {  # tag: (tema claro, tema oscuro)
    MatchStatus.MATCHED.name: ("#1b7f3b", "#6fdc8c"),
    MatchStatus.LOW_CONFIDENCE.name: ("#9a6700", "#f1c21b"),
    MatchStatus.NOT_FOUND.name: ("#c4262e", "#ff8389"),
    "REMOVED": ("#6f6f6f", "#a8a8a8"),
}
PRIVACY_OPTIONS = (("Privada", "PRIVATE"), ("No listada", "UNLISTED"), ("Pública", "PUBLIC"))
DIRECTIONS = (
    (SPOTIFY, "Spotify  →  YouTube Music"),
    (YTMUSIC, "YouTube Music  →  Spotify"),
)

HEADERS_STEPS = (
    "1.  Abre YouTube Music en Firefox con la cuenta que quieres agregar\n"
    "     (para otra persona, usa una ventana privada).\n"
    "2.  Presiona F12 → pestaña «Red» y escribe  browse  en el filtro.\n"
    "3.  Haz clic en cualquier sección de YouTube Music (por ejemplo, Biblioteca).\n"
    "4.  Clic derecho en una petición POST «browse» → Copiar → Copiar encabezados de la petición.\n"
    "5.  Pégalos en el cuadro de abajo y presiona Guardar."
)

SpotifyFactory = Callable[[], object]
YTMusicFactory = Callable[[str | None], object]


def friendly_error(exc: BaseException) -> str:
    """Traduce errores típicos a algo entendible."""
    text = str(exc)
    low = text.lower()
    if "invalid_client" in low or "invalid client" in low:
        return (
            "Spotify rechazó tu Client ID o Client Secret.\n"
            "Revísalos en «Ajustes de Spotify»."
        )
    if "invalid redirect" in low or "redirect_uri" in low:
        return (
            "La Redirect URI de tu app de Spotify no coincide.\n"
            f"Debe ser exactamente: {DEFAULT_REDIRECT_URI}"
        )
    if "http status: 404" in low or "http status: 403" in low:
        return (
            "No pude leer esa playlist. Si es una playlist creada por Spotify "
            "(Discover Weekly, Top 50, etc.), cópiala primero a una playlist tuya.\n\n"
            f"Detalle: {text}"
        )
    if "401" in low and ("youtube" in low or "unauthorized" in low):
        return (
            "YouTube Music rechazó la sesión de esta cuenta (puede haber expirado).\n"
            "Vuelve a agregarla con el mismo nombre."
        )
    return text or exc.__class__.__name__


class PlaceholderEntry(ttk.Entry):
    """Entry con texto de ayuda gris cuando está vacío."""

    def __init__(self, master, placeholder: str, **kwargs):
        self.var = kwargs.pop("textvariable", None) or tk.StringVar()
        super().__init__(master, textvariable=self.var, **kwargs)
        self.placeholder = placeholder
        self._showing = False
        self.bind("<FocusIn>", self._clear)
        self.bind("<FocusOut>", self._show)
        self._show()

    def _show(self, _event=None):
        if not self.var.get():
            self._showing = True
            self.var.set(self.placeholder)
            self.configure(foreground="gray")

    def _clear(self, _event=None):
        if self._showing:
            self._showing = False
            self.var.set("")
            self.configure(foreground="")

    def value(self) -> str:
        return "" if self._showing else self.var.get().strip()

    def set_value(self, text: str) -> None:
        self._clear()
        self.var.set(text)
        if not text:
            self._show()


class App(tk.Tk):
    def __init__(
        self,
        spotify_factory: SpotifyFactory | None = None,
        ytmusic_factory: YTMusicFactory | None = None,
    ):
        super().__init__()
        self.spotify_factory = spotify_factory
        self.ytmusic_factory = ytmusic_factory
        self.dark = apply_theme(self)
        self.events: queue.Queue = queue.Queue()
        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.results: list[MatchResult] = []
        self.outcome: ConvertOutcome | None = None
        self.last_url: str | None = None
        self.result_urls: dict[str, str] = {}

        self.title(APP_TITLE)
        self._set_icon()
        self.geometry("1020x880")
        self.minsize(880, 740)
        self._build()
        self.refresh_accounts()
        self.refresh_links()
        self._apply_direction()
        config.load_env()
        self.after(100, self._poll_events)

    # ------------------------------------------------------------------ UI
    def _set_icon(self) -> None:
        try:
            self._icon = tk.PhotoImage(file=str(ICON_PATH))
            self.iconphoto(True, self._icon)
        except (tk.TclError, OSError):
            pass

    def _build(self) -> None:
        root = ttk.Frame(self, padding=(20, 14))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="Spotify ⇄ YouTube Music", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Button(header, text="Ajustes de Spotify…", command=self.open_spotify_settings).pack(side="right")

        self.tabs = ttk.Notebook(root)
        self.tabs.grid(row=1, column=0, sticky="ew")
        convert_tab = ttk.Frame(self.tabs, padding=(12, 10))
        sync_tab = ttk.Frame(self.tabs, padding=(12, 10))
        self.tabs.add(convert_tab, text="  Convertir  ")
        self.tabs.add(sync_tab, text="  Sincronizadas  ")
        self._build_convert_tab(convert_tab)
        self._build_sync_tab(sync_tab)
        self._build_results(root)

    def _build_convert_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=1)

        direction = ttk.Frame(tab)
        direction.grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(direction, text="Dirección:").pack(side="left", padx=(0, 10))
        self.direction_var = tk.StringVar(value=SPOTIFY)
        for value, label in DIRECTIONS:
            ttk.Radiobutton(
                direction, text=label, value=value, variable=self.direction_var, command=self._apply_direction
            ).pack(side="left", padx=(0, 18))

        self.source_frame = ttk.LabelFrame(tab, text="  1. Playlist de origen  ", padding=10)
        self.source_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.source_frame.columnconfigure(0, weight=1)
        self.link_entry = PlaceholderEntry(self.source_frame, "Pega aquí el link de la playlist")
        self.link_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.link_entry.bind("<KeyRelease>", lambda _e: self._detect_direction(), add="+")
        self.link_entry.bind("<FocusOut>", lambda _e: self._detect_direction(), add="+")
        ttk.Button(self.source_frame, text="Pegar", command=self.paste_link).grid(row=0, column=1)
        self.liked_var = tk.BooleanVar()
        self.liked_check = ttk.Checkbutton(
            self.source_frame, variable=self.liked_var, command=self._toggle_liked
        )
        self.liked_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        target = ttk.LabelFrame(tab, text="  2. Cuenta de YouTube Music  ", padding=10)
        target.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        target.columnconfigure(0, weight=1)
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(target, textvariable=self.account_var, state="readonly")
        self.account_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(target, text="Agregar cuenta…", command=self.open_add_account).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(target, text="Eliminar", command=self.remove_account).grid(row=0, column=2)
        self.account_hint = ttk.Label(target, foreground="gray")
        self.account_hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        opts = ttk.LabelFrame(tab, text="  3. Opciones  ", padding=10)
        opts.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text="Nombre:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.name_entry = PlaceholderEntry(opts, "Igual que en el origen")
        self.name_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(opts, text="Privacidad:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.privacy_var = tk.StringVar(value="PRIVATE")
        privacy_row = ttk.Frame(opts)
        privacy_row.grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.privacy_buttons: dict[str, ttk.Radiobutton] = {}
        for label, value in PRIVACY_OPTIONS:
            button = ttk.Radiobutton(privacy_row, text=label, value=value, variable=self.privacy_var)
            button.pack(side="left", padx=(0, 16))
            self.privacy_buttons[value] = button
        self.dry_run_var = tk.BooleanVar()
        self.strict_var = tk.BooleanVar()
        checks = ttk.Frame(opts)
        checks.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(checks, text="Solo probar (no crea la playlist)", variable=self.dry_run_var).pack(
            side="left", padx=(0, 24)
        )
        ttk.Checkbutton(checks, text="No agregar coincidencias dudosas", variable=self.strict_var).pack(side="left")

        self.convert_btn = ttk.Button(tab, text="Convertir", style="Accent.TButton", command=self.start)
        self.convert_btn.grid(row=4, column=0, sticky="w", ipadx=16)

    def _build_sync_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=1)
        ttk.Label(
            tab,
            text=(
                "Las playlists que conviertes quedan aquí. «Actualizar» agrega al destino solo las "
                "canciones nuevas del origen, sin duplicar."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        table = ttk.Frame(tab)
        table.grid(row=1, column=0, sticky="ew")
        table.columnconfigure(0, weight=1)
        columns = ("origen", "destino", "cuenta", "canciones", "actualizada")
        self.links_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended", height=8)
        for col, title, width, stretch in (
            ("origen", "Origen", 300, True),
            ("destino", "Destino", 300, True),
            ("cuenta", "Cuenta YT Music", 130, False),
            ("canciones", "Canciones", 80, False),
            ("actualizada", "Actualizada", 150, False),
        ):
            self.links_tree.heading(col, text=title)
            self.links_tree.column(col, width=width, stretch=stretch, anchor="w" if stretch else "center")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.links_tree.yview)
        self.links_tree.configure(yscrollcommand=scroll.set)
        self.links_tree.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.links_tree.bind("<Double-1>", lambda _e: self.open_link_target())

        buttons = ttk.Frame(tab)
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.update_btn = ttk.Button(
            buttons, text="Actualizar seleccionadas", style="Accent.TButton", command=self.update_selected
        )
        self.update_btn.pack(side="left", padx=(0, 8))
        self.update_all_btn = ttk.Button(buttons, text="Actualizar todas", command=self.update_all)
        self.update_all_btn.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Vincular existente…", command=self.open_link_dialog).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Dejar de sincronizar", command=self.unlink_selected).pack(side="right")
        ttk.Button(buttons, text="Abrir destino", command=self.open_link_target).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Abrir origen", command=self.open_link_source).pack(side="right", padx=(0, 8))

        self.remove_missing_var = tk.BooleanVar()
        ttk.Checkbutton(
            tab,
            text="Quitar también del destino las canciones que borré del origen",
            variable=self.remove_missing_var,
        ).grid(row=3, column=0, sticky="w", pady=(10, 0))

    def _build_results(self, root: ttk.Frame) -> None:
        results = ttk.Frame(root)
        results.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        results.columnconfigure(0, weight=1)
        results.rowconfigure(2, weight=1)

        actions = ttk.Frame(results)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        actions.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.cancel_btn = ttk.Button(actions, text="Cancelar", command=self.cancel, state="disabled")
        self.cancel_btn.grid(row=0, column=1)

        self.progress = ttk.Progressbar(results, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        table = ttk.Frame(results)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("estado", "origen", "destino", "puntaje")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for col, title, width, stretch in (
            ("estado", "Estado", 130, False),
            ("origen", "Canción en el origen", 320, True),
            ("destino", "Resultado en el destino", 320, True),
            ("puntaje", "Puntaje", 70, False),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=stretch, anchor="center" if col == "puntaje" else "w")
        for tag, (light, dark) in STATUS_COLORS.items():
            self.tree.tag_configure(tag, foreground=dark if self.dark else light)
        self.tree.tag_configure("HEADER", font=("Segoe UI", 9, "bold"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._open_selected)

        footer = ttk.Frame(results)
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="Doble clic en una canción para abrirla.")
        ttk.Label(footer, textvariable=self.summary_var).grid(row=0, column=0, sticky="w")
        self.report_btn = ttk.Button(footer, text="Guardar reporte…", command=self.save_report, state="disabled")
        self.report_btn.grid(row=0, column=1, padx=(8, 0))
        self.open_btn = ttk.Button(
            footer, text="Abrir playlist", style="Accent.TButton", command=self.open_playlist, state="disabled"
        )
        self.open_btn.grid(row=0, column=2, padx=(8, 0))

    # ------------------------------------------------------ pestaña Convertir
    @property
    def source_service(self) -> str:
        return self.direction_var.get()

    @property
    def target_service(self) -> str:
        return other_service(self.source_service)

    def _apply_direction(self) -> None:
        src, dst = SERVICE_NAMES[self.source_service], SERVICE_NAMES[self.target_service]
        self.source_frame.configure(text=f"  1. Playlist de {src}  ")
        self.liked_check.configure(text=f"Usar mis canciones guardadas («Me gusta») de {src} en vez de un link")
        if self.target_service == YTMUSIC:
            self.account_hint.configure(text="Aquí se creará la playlist.")
        else:
            self.account_hint.configure(
                text="Se usa para leer la playlist (opcional si es pública). La playlist se creará en tu Spotify."
            )
        # Spotify no tiene playlists "no listadas".
        unlisted = self.privacy_buttons["UNLISTED"]
        if self.target_service == SPOTIFY:
            unlisted.configure(state="disabled")
            if self.privacy_var.get() == "UNLISTED":
                self.privacy_var.set("PRIVATE")
        else:
            unlisted.configure(state="normal")
        self.convert_btn.configure(text=f"Convertir a {dst}")

    def _detect_direction(self) -> None:
        """Si el link es de un servicio, elige la dirección automáticamente."""
        try:
            ref = parse_ref(self.link_entry.value())
        except ValueError:
            return
        if not ref.is_liked and ref.service != self.direction_var.get():
            self.direction_var.set(ref.service)
            self._apply_direction()

    def refresh_accounts(self, select: str | None = None) -> None:
        names = accounts.list_accounts()
        self.account_combo["values"] = names
        if select in names:
            self.account_var.set(select)
        elif self.account_var.get() not in names:
            self.account_var.set(names[0] if names else "")

    def paste_link(self) -> None:
        try:
            self.link_entry.set_value(self.clipboard_get().strip())
        except tk.TclError:
            return
        self._detect_direction()

    def _toggle_liked(self) -> None:
        self.link_entry.configure(state="disabled" if self.liked_var.get() else "normal")

    def remove_account(self) -> None:
        name = self.account_var.get()
        if not name:
            return
        if messagebox.askyesno(APP_TITLE, f"¿Eliminar la cuenta «{name}»?", parent=self):
            accounts.remove_account(name)
            self.refresh_accounts()

    def open_add_account(self) -> None:
        AddAccountDialog(self)

    def open_spotify_settings(self) -> bool:
        dialog = SpotifySettingsDialog(self)
        self.wait_window(dialog)
        return dialog.saved

    def ensure_spotify(self) -> bool:
        config.load_env()
        return not config.missing_vars() or self.open_spotify_settings()

    def _auth_for(self, account: str | None, required: bool) -> str | None | bool:
        """Ruta de la cuenta; None si no hace falta; False si falta y el usuario debe agregarla."""
        if account:
            return str(accounts.account_path(account))
        if not required:
            return None
        if messagebox.askyesno(
            APP_TITLE, "Necesitas una cuenta de YouTube Music para esto.\n¿Agregar una ahora?", parent=self
        ):
            self.open_add_account()
        return False

    def validate(self) -> tuple[PlaylistRef, str | None] | None:
        """Devuelve (playlist de origen, archivo de la cuenta) o muestra qué falta."""
        if self.liked_var.get():
            ref = liked_ref(self.source_service)
        else:
            try:
                ref = parse_ref(self.link_entry.value())
            except ValueError:
                messagebox.showwarning(
                    APP_TITLE,
                    f"Pega el link de una playlist de {SERVICE_NAMES[self.source_service]}.\n"
                    "(En la app: ⋯ → Compartir → Copiar enlace)",
                    parent=self,
                )
                return None
            if ref.service != self.source_service:
                self.direction_var.set(ref.service)
                self._apply_direction()
        needs_account = self.target_service == YTMUSIC or ref.is_liked
        auth = self._auth_for(self.account_var.get() or None, needs_account)
        if auth is False:
            return None
        if not self.ensure_spotify():
            return None
        return ref, auth

    def start(self) -> None:
        if self.busy:
            return
        checked = self.validate()
        if not checked:
            return
        ref, auth_path = checked
        options = ConvertOptions(
            name=self.name_entry.value() or None,
            privacy=self.privacy_var.get(),
            strict=self.strict_var.get(),
            dry_run=self.dry_run_var.get(),
        )
        account = self.account_var.get() or None
        self._begin("Conectando… (la primera vez se abre el navegador para autorizar Spotify)")
        self._run(self._convert_job, ref, auth_path, account, options)

    def _services(self, source_service: str, target_service: str, auth_path: str | None):
        make = lambda service: services.build(  # noqa: E731
            service, auth_path, self.spotify_factory, self.ytmusic_factory
        )
        return make(source_service), make(target_service)

    def _convert_job(self, post, cancel, ref: PlaylistRef, auth_path, account, options: ConvertOptions) -> None:
        source, target = self._services(ref.service, other_service(ref.service), auth_path)
        outcome = convert(
            source,
            target,
            ref.id,
            options,
            on_start=lambda name, total: post(("start", name, total)),
            on_result=lambda i, total, result: post(("result", i, total, result)),
            on_status=lambda message: post(("status", message)),
            cancel=cancel,
        )
        if outcome.playlist_id and not outcome.cancelled:
            links.upsert(
                link_from_outcome(
                    outcome, ref.service, ref.id, source.playlist_name(ref.id), account, options.strict
                )
            )
        post(("done", outcome))

    # -------------------------------------------------- pestaña Sincronizadas
    def refresh_links(self) -> None:
        selected = set(self.links_tree.selection())
        self.links_tree.delete(*self.links_tree.get_children())
        for link in links.load():
            self.links_tree.insert(
                "",
                "end",
                iid=link.id,
                values=(
                    f"{link.source_name}  ·  {SERVICE_NAMES[link.source_service]}",
                    f"{link.target_name}  ·  {SERVICE_NAMES[link.target_service]}",
                    link.account or "—",
                    link.track_count,
                    link.last_sync or "nunca",
                ),
            )
        keep = [i for i in selected if self.links_tree.exists(i)]
        if keep:
            self.links_tree.selection_set(keep)

    def _selected_links(self) -> list[SyncLink]:
        ids = set(self.links_tree.selection())
        return [l for l in links.load() if l.id in ids]

    def update_selected(self) -> None:
        selected = self._selected_links()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Selecciona una o más playlists de la lista.", parent=self)
            return
        self._start_sync(selected)

    def update_all(self) -> None:
        all_links = links.load()
        if not all_links:
            messagebox.showinfo(
                APP_TITLE, "Todavía no hay playlists sincronizadas: se agregan solas al convertir una.", parent=self
            )
            return
        self._start_sync(all_links)

    def _start_sync(self, selected: list[SyncLink]) -> None:
        if self.busy or not self.ensure_spotify():
            return
        self._begin("Actualizando…")
        self._run(self._sync_job, [l.id for l in selected], self.remove_missing_var.get())

    def _sync_job(self, post, cancel, link_ids: list[str], remove_missing: bool) -> None:
        totals = {"added": 0, "removed": 0, "errors": 0, "done": 0}
        for n, link_id in enumerate(link_ids, start=1):
            if cancel.is_set():
                break
            link = links.get(link_id)
            if link is None:
                continue
            post(("sync_header", link, n, len(link_ids)))
            try:
                needs_account = link.target_service == YTMUSIC or link.source_id == "LM"
                auth_path = services.ytmusic_auth(link.account, required=needs_account)
                source, target = self._services(link.source_service, link.target_service, auth_path)
                outcome = sync(
                    link,
                    source,
                    target,
                    remove_missing=remove_missing,
                    on_start=lambda name, total: post(("start", name, total)),
                    on_result=lambda i, total, result: post(("result", i, total, result)),
                    on_status=lambda message: post(("status", message)),
                    cancel=cancel,
                )
                if not outcome.cancelled:
                    links.upsert(link)
                    totals["done"] += 1
                totals["added"] += outcome.added
                totals["removed"] += len(outcome.removed)
                post(("synced", outcome))
            except Exception as exc:  # una playlist con error no detiene las demás
                totals["errors"] += 1
                post(("sync_error", link, exc))
        post(("sync_finished", totals, cancel.is_set()))

    def open_link_dialog(self) -> None:
        LinkDialog(self)

    def link_existing(self, source_ref: PlaylistRef, target_ref: PlaylistRef, account: str | None, strict: bool) -> None:
        """Crea el vínculo (buscando los nombres) y lo actualiza de inmediato."""
        if self.busy or not self.ensure_spotify():
            return
        self._begin("Vinculando…")
        self._run(self._link_job, source_ref, target_ref, account, strict)

    def _link_job(self, post, cancel, source_ref: PlaylistRef, target_ref: PlaylistRef, account, strict) -> None:
        auth_path = services.ytmusic_auth(account, required=True)
        source, target = self._services(source_ref.service, target_ref.service, auth_path)
        link = links.upsert(
            SyncLink(
                source_service=source_ref.service,
                source_id=source_ref.id,
                source_name=source.playlist_name(source_ref.id),
                target_service=target_ref.service,
                target_id=target_ref.id,
                target_name=target.playlist_name(target_ref.id),
                account=account,
                strict=strict,
            )
        )
        post(("links_changed",))
        self._sync_job(post, cancel, [link.id], remove_missing=False)

    def unlink_selected(self) -> None:
        selected = self._selected_links()
        if not selected:
            return
        names = "\n".join(f"• {l.target_name}" for l in selected)
        if messagebox.askyesno(
            APP_TITLE,
            f"¿Dejar de sincronizar estas playlists?\n{names}\n\n(No se borra ninguna playlist.)",
            parent=self,
        ):
            for link in selected:
                links.remove(link.id)
            self.refresh_links()

    def open_link_source(self) -> None:
        for link in self._selected_links()[:1]:
            webbrowser.open(link.source_url)

    def open_link_target(self) -> None:
        for link in self._selected_links()[:1]:
            webbrowser.open(link.target_url)

    # ------------------------------------------------------ trabajo de fondo
    @property
    def busy(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _begin(self, status: str) -> None:
        self.tree.delete(*self.tree.get_children())
        self.results, self.outcome, self.last_url, self.result_urls = [], None, None, {}
        self.progress.configure(value=0, maximum=1)
        self.summary_var.set("")
        self.status_var.set(status)
        self._set_running(True)

    def _run(self, job: Callable, *args) -> None:
        self.cancel_event = threading.Event()
        post = self.events.put
        cancel = self.cancel_event

        def target() -> None:
            try:
                job(post, cancel, *args)
            except BaseException as exc:  # noqa: BLE001 - todo error debe llegar a la ventana
                post(("error", exc))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            self.status_var.set("Cancelando…")

    def _poll_events(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "status":
            self.status_var.set(event[1])
        elif kind == "start":
            _, name, total = event
            self.progress.configure(maximum=max(total, 1), value=0)
            self.status_var.set(f"Buscando {total} canciones de «{name}»…" if total else "No hay canciones nuevas.")
        elif kind == "result":
            _, i, total, result = event
            self._add_row(result)
            self.progress.configure(value=i)
            self.status_var.set(f"Buscando canciones… {i} de {total}")
        elif kind == "done":
            self._finish(event[1])
        elif kind == "links_changed":
            self.refresh_links()
        elif kind == "sync_header":
            _, link, n, total = event
            self.tree.insert("", "end", values=("", f"{n}/{total}  {link.describe()}", "", ""), tags=("HEADER",))
        elif kind == "synced":
            self._synced(event[1])
        elif kind == "sync_error":
            _, link, exc = event
            self.tree.insert(
                "", "end", values=("✘  Error", friendly_error(exc).splitlines()[0], "", ""), tags=("NOT_FOUND",)
            )
        elif kind == "sync_finished":
            _, totals, cancelled = event
            self._set_running(False)
            self.refresh_links()
            self.report_btn.configure(state="normal" if self.results else "disabled")
            text = f"Agregadas: {totals['added']} · Quitadas: {totals['removed']}"
            if totals["errors"]:
                text += f" · Con error: {totals['errors']}"
            self.summary_var.set(text)
            self.status_var.set("Cancelado." if cancelled else f"¡Listo! {totals['done']} playlist(s) actualizadas.")
        elif kind == "error":
            self._set_running(False)
            self.refresh_links()
            self.status_var.set("Ocurrió un error.")
            messagebox.showerror(APP_TITLE, friendly_error(event[1]), parent=self)

    def _add_row(self, result: MatchResult) -> None:
        self.results.append(result)
        c = result.candidate
        found = ""
        if c and result.status is not MatchStatus.NOT_FOUND:
            found = f"{', '.join(c.artists)} - {c.title}" if c.artists else c.title
        item = self.tree.insert(
            "",
            "end",
            values=(STATUS_LABELS[result.status], result.track.display(), found, f"{result.score:.2f}"),
            tags=(result.status.name,),
        )
        if c and c.url:
            self.result_urls[item] = c.url
        self.tree.see(item)

    def _synced(self, outcome: SyncOutcome) -> None:
        for name in outcome.removed:
            self.tree.insert("", "end", values=(REMOVED_LABEL, name, "", ""), tags=("REMOVED",))
        if not outcome.results and not outcome.removed:
            self.tree.insert("", "end", values=("", "Sin cambios: ya estaba al día.", "", ""))
        self.last_url = outcome.link.target_url
        self.open_btn.configure(state="normal")

    def _finish(self, outcome: ConvertOutcome) -> None:
        self.outcome = outcome
        self._set_running(False)
        self.refresh_links()
        self.report_btn.configure(state="normal" if outcome.results else "disabled")
        self.summary_var.set(report.summary(outcome.results) if outcome.results else "")
        if outcome.cancelled:
            self.status_var.set("Cancelado. No se modificó nada.")
        elif not outcome.results:
            self.status_var.set("La playlist no tiene canciones.")
        elif outcome.playlist_id:
            self.last_url = outcome.playlist_url
            self.open_btn.configure(state="normal")
            self.status_var.set(
                f"¡Listo! {outcome.added} canciones agregadas a «{outcome.playlist_name}» "
                f"en {SERVICE_NAMES[outcome.target_service]}. Quedó en «Sincronizadas»."
            )
        elif self.dry_run_var.get():
            self.status_var.set("Prueba terminada: no se creó ninguna playlist.")
        else:
            self.status_var.set("No se encontró ninguna canción para agregar.")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for button in (self.convert_btn, self.update_btn, self.update_all_btn):
            button.configure(state=state)
        self.cancel_btn.configure(state="normal" if running else "disabled")
        if running:
            self.open_btn.configure(state="disabled")
            self.report_btn.configure(state="disabled")

    def _open_selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection and selection[0] in self.result_urls:
            webbrowser.open(self.result_urls[selection[0]])

    def open_playlist(self) -> None:
        if self.last_url:
            webbrowser.open(self.last_url)

    def save_report(self) -> None:
        if not self.results:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar reporte",
            defaultextension=".csv",
            initialfile=f"reporte_{datetime.now():%Y%m%d_%H%M%S}.csv",
            filetypes=[("CSV (Excel)", "*.csv")],
        )
        if path:
            report.write_csv(self.results, Path(path))
            self.status_var.set(f"Reporte guardado en {path}")


class Dialog(tk.Toplevel):
    def __init__(self, master: App, title: str):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(True, False)
        self.body = ttk.Frame(self, padding=20)
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.bind("<Escape>", lambda _e: self.destroy())

    def show(self) -> None:
        self.update_idletasks()
        master = self.master
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            self.grab_set()
        except tk.TclError:  # la ventana aún no es visible en algunos gestores de ventanas
            pass
        self.focus_set()


class SpotifySettingsDialog(Dialog):
    def __init__(self, master: App):
        super().__init__(master, "Ajustes de Spotify")
        self.saved = False
        b = self.body
        ttk.Label(b, text="Conectar con Spotify", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            b,
            justify="left",
            text=(
                "Necesitas una app gratuita de Spotify (solo una vez):\n"
                "1.  Abre el panel de desarrolladores y crea una app.\n"
                "2.  En «Redirect URI» pon la dirección de abajo y marca «Web API».\n"
                "3.  En Settings copia el Client ID y el Client Secret y pégalos aquí."
            ),
        ).grid(row=1, column=0, sticky="w", pady=(6, 10))
        ttk.Button(b, text="Abrir panel de Spotify", command=lambda: webbrowser.open(SPOTIFY_DASHBOARD)).grid(
            row=2, column=0, sticky="w"
        )

        uri_row = ttk.Frame(b)
        uri_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        uri_row.columnconfigure(1, weight=1)
        ttk.Label(uri_row, text="Redirect URI:").grid(row=0, column=0, padx=(0, 8))
        uri = ttk.Entry(uri_row)
        uri.insert(0, DEFAULT_REDIRECT_URI)
        uri.configure(state="readonly")
        uri.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(uri_row, text="Copiar", command=lambda: self._copy(DEFAULT_REDIRECT_URI)).grid(row=0, column=2)

        form = ttk.Frame(b)
        form.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        form.columnconfigure(1, weight=1)
        config.load_env()
        import os

        self.id_var = tk.StringVar(value=os.environ.get("SPOTIPY_CLIENT_ID", ""))
        self.secret_var = tk.StringVar(value=os.environ.get("SPOTIPY_CLIENT_SECRET", ""))
        ttk.Label(form, text="Client ID:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        id_entry = ttk.Entry(form, textvariable=self.id_var, width=48)
        id_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(form, text="Client Secret:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(form, textvariable=self.secret_var, show="•", width=48).grid(
            row=1, column=1, sticky="ew", pady=(8, 0)
        )

        buttons = ttk.Frame(b)
        buttons.grid(row=5, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Guardar", style="Accent.TButton", command=self.save).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self.save())
        id_entry.focus_set()
        self.show()

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def save(self) -> None:
        client_id, secret = self.id_var.get().strip(), self.secret_var.get().strip()
        if not client_id or not secret:
            messagebox.showwarning(APP_TITLE, "Completa el Client ID y el Client Secret.", parent=self)
            return
        config.save_credentials(client_id, secret)
        self.saved = True
        self.destroy()


class AddAccountDialog(Dialog):
    def __init__(self, master: App):
        super().__init__(master, "Agregar cuenta de YouTube Music")
        self.app = master
        b = self.body
        ttk.Label(b, text="Agregar cuenta de YouTube Music", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        name_row = ttk.Frame(b)
        name_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        name_row.columnconfigure(1, weight=1)
        ttk.Label(name_row, text="Nombre para la cuenta:").grid(row=0, column=0, padx=(0, 8))
        self.name_entry = PlaceholderEntry(name_row, "ej. daniel, mamá, trabajo")
        self.name_entry.grid(row=0, column=1, sticky="ew")

        ttk.Label(b, text=HEADERS_STEPS, justify="left").grid(row=2, column=0, sticky="w", pady=(12, 8))
        ttk.Button(b, text="Abrir YouTube Music", command=lambda: webbrowser.open(YTMUSIC_URL)).grid(
            row=3, column=0, sticky="w"
        )

        text_frame = ttk.Frame(b)
        text_frame.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        text_frame.columnconfigure(0, weight=1)
        self.text = tk.Text(text_frame, height=10, width=80, wrap="none", font=("Consolas", 9))
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(b)
        buttons.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="Pegar del portapapeles", command=self.paste).pack(side="left")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Guardar", style="Accent.TButton", command=self.save).pack(side="right", padx=(0, 8))
        self.show()

    def paste(self) -> None:
        try:
            content = self.clipboard_get()
        except tk.TclError:
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)

    def save(self) -> None:
        raw_name = self.name_entry.value()
        headers = self.text.get("1.0", "end").strip()
        try:
            name = accounts.clean_name(raw_name)
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Escribe un nombre para la cuenta.", parent=self)
            return
        if not headers:
            messagebox.showwarning(APP_TITLE, "Pega los encabezados copiados del navegador.", parent=self)
            return
        if name in accounts.list_accounts() and not messagebox.askyesno(
            APP_TITLE, f"Ya existe «{name}». ¿Reemplazarla?", parent=self
        ):
            return
        try:
            accounts.save_account(name, headers)
        except Exception as exc:  # ytmusicapi lanza errores genéricos
            messagebox.showerror(
                APP_TITLE,
                "No pude leer esos encabezados. Revisa que copiaste los de una petición POST «browse» "
                f"con la sesión iniciada.\n\nDetalle: {exc}",
                parent=self,
            )
            return
        self.app.refresh_accounts(select=name)
        self.destroy()
        messagebox.showinfo(APP_TITLE, f"Cuenta «{name}» guardada.", parent=self.app)


class LinkDialog(Dialog):
    """Vincula dos playlists que ya existen (una de cada servicio) para poder actualizarlas."""

    def __init__(self, master: App):
        super().__init__(master, "Vincular playlists existentes")
        self.app = master
        b = self.body
        ttk.Label(b, text="Vincular playlists existentes", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            b,
            justify="left",
            wraplength=560,
            text=(
                "Útil para playlists que convertiste antes o que armaste a mano. Al vincularlas se "
                "agregan al destino las canciones del origen que le falten (sin duplicar)."
            ),
        ).grid(row=1, column=0, sticky="w", pady=(6, 10))

        form = ttk.Frame(b)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Origen:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.source_entry = PlaceholderEntry(form, "Link de la playlist que manda (Spotify o YouTube Music)", width=60)
        self.source_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(form, text="Destino:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.target_entry = PlaceholderEntry(form, "Link de la playlist que se actualiza (del otro servicio)", width=60)
        self.target_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(form, text="Cuenta YT Music:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.account_var = tk.StringVar(value=master.account_var.get())
        ttk.Combobox(
            form, textvariable=self.account_var, values=accounts.list_accounts(), state="readonly"
        ).grid(row=2, column=1, sticky="ew", pady=(8, 0))
        self.strict_var = tk.BooleanVar(value=master.strict_var.get())
        ttk.Checkbutton(form, text="No agregar coincidencias dudosas", variable=self.strict_var).grid(
            row=3, column=1, sticky="w", pady=(8, 0)
        )

        buttons = ttk.Frame(b)
        buttons.grid(row=3, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Vincular y actualizar", style="Accent.TButton", command=self.save).pack(
            side="right", padx=(0, 8)
        )
        self.show()

    def save(self) -> None:
        try:
            source_ref = parse_ref(self.source_entry.value())
            target_ref = parse_ref(self.target_entry.value(), liked_service=other_service(source_ref.service))
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc), parent=self)
            return
        if source_ref.service == target_ref.service:
            messagebox.showwarning(
                APP_TITLE, "El origen y el destino deben ser de servicios distintos.", parent=self
            )
            return
        if target_ref.is_liked:
            messagebox.showwarning(APP_TITLE, "El destino debe ser una playlist.", parent=self)
            return
        account = self.account_var.get() or None
        if not account:
            messagebox.showwarning(APP_TITLE, "Elige la cuenta de YouTube Music.", parent=self)
            return
        self.destroy()
        self.app.link_existing(source_ref, target_ref, account, self.strict_var.get())


def windows_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


def apply_theme(root: tk.Tk) -> bool:
    """Usa el tema estilo Windows 11 (sv-ttk) si está disponible. Devuelve True si es oscuro."""
    dark = windows_prefers_dark()
    try:
        import sv_ttk

        sv_ttk.set_theme("dark" if dark else "light", root)
    except Exception:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        dark = False
    ttk.Style(root).configure("Treeview", rowheight=28)
    return dark


def enable_dpi_awareness() -> None:
    # Sin esto, la ventana se ve borrosa en pantallas con escala > 100 % en Windows.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def selftest() -> int:
    """Abre y cierra la ventana; sirve para comprobar que el .exe incluye todo lo necesario."""
    app = App()
    app.update()
    ok = bool(app.winfo_exists()) and app.convert_btn.winfo_ismapped()
    app.destroy()
    return 0 if ok else 1


def main() -> int:
    enable_dpi_awareness()
    app = App()
    app.mainloop()
    return 0
