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

from . import accounts, config, report
from .converter import ConvertOptions, ConvertOutcome, convert
from .models import MatchResult, MatchStatus
from .spotify_source import DEFAULT_REDIRECT_URI, LIKED, SpotifySource, parse_playlist_ref
from .ytmusic_target import YTMusicTarget

APP_TITLE = "Playlist Converter"
ICON_PATH = Path(__file__).parent / "assets" / "icon_256.png"
SPOTIFY_DASHBOARD = "https://developer.spotify.com/dashboard"
YTMUSIC_URL = "https://music.youtube.com"

STATUS_LABELS = {
    MatchStatus.MATCHED: "✔  Encontrada",
    MatchStatus.LOW_CONFIDENCE: "?  Dudosa",
    MatchStatus.NOT_FOUND: "✘  No encontrada",
}
STATUS_COLORS = {  # (tema claro, tema oscuro)
    MatchStatus.MATCHED: ("#1b7f3b", "#6fdc8c"),
    MatchStatus.LOW_CONFIDENCE: ("#9a6700", "#f1c21b"),
    MatchStatus.NOT_FOUND: ("#c4262e", "#ff8389"),
}
PRIVACY_OPTIONS = (("Privada", "PRIVATE"), ("No listada", "UNLISTED"), ("Pública", "PUBLIC"))

HEADERS_STEPS = (
    "1.  Abre YouTube Music en Firefox con la cuenta que quieres agregar\n"
    "     (para otra persona, usa una ventana privada).\n"
    "2.  Presiona F12 → pestaña «Red» y escribe  browse  en el filtro.\n"
    "3.  Haz clic en cualquier sección de YouTube Music (por ejemplo, Biblioteca).\n"
    "4.  Clic derecho en una petición POST «browse» → Copiar → Copiar encabezados de la petición.\n"
    "5.  Pégalos en el cuadro de abajo y presiona Guardar."
)

SpotifyFactory = Callable[[], object]
YTMusicFactory = Callable[[str], object]


def default_spotify_factory():
    return SpotifySource.from_env()


def default_ytmusic_factory(auth_path: str):
    return YTMusicTarget.from_auth_file(auth_path)


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
        spotify_factory: SpotifyFactory = default_spotify_factory,
        ytmusic_factory: YTMusicFactory = default_ytmusic_factory,
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
        self.result_urls: dict[str, str] = {}

        self.title(APP_TITLE)
        self._set_icon()
        self.geometry("980x760")
        self.minsize(820, 640)
        self._build()
        self.refresh_accounts()
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
        root = ttk.Frame(self, padding=(20, 16))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="Spotify → YouTube Music", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Button(header, text="Ajustes de Spotify…", command=self.open_spotify_settings).pack(side="right")

        # 1. Playlist
        source = ttk.LabelFrame(root, text="  1. Playlist de Spotify  ", padding=12)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(0, weight=1)
        self.link_entry = PlaceholderEntry(source, "Pega aquí el link de la playlist (Compartir → Copiar enlace)")
        self.link_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(source, text="Pegar", command=self.paste_link).grid(row=0, column=1)
        self.liked_var = tk.BooleanVar()
        ttk.Checkbutton(
            source,
            text="Usar mis canciones guardadas («Me gusta») en vez de un link",
            variable=self.liked_var,
            command=self._toggle_liked,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # 2. Cuenta
        target = ttk.LabelFrame(root, text="  2. Cuenta de YouTube Music  ", padding=12)
        target.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        target.columnconfigure(0, weight=1)
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(target, textvariable=self.account_var, state="readonly")
        self.account_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(target, text="Agregar cuenta…", command=self.open_add_account).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(target, text="Eliminar", command=self.remove_account).grid(row=0, column=2)

        # 3. Opciones
        opts = ttk.LabelFrame(root, text="  3. Opciones  ", padding=12)
        opts.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text="Nombre:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.name_entry = PlaceholderEntry(opts, "Igual que en Spotify")
        self.name_entry.grid(row=0, column=1, columnspan=4, sticky="ew")
        ttk.Label(opts, text="Privacidad:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.privacy_var = tk.StringVar(value="PRIVATE")
        privacy_row = ttk.Frame(opts)
        privacy_row.grid(row=1, column=1, columnspan=4, sticky="w", pady=(8, 0))
        for label, value in PRIVACY_OPTIONS:
            ttk.Radiobutton(privacy_row, text=label, value=value, variable=self.privacy_var).pack(
                side="left", padx=(0, 16)
            )
        self.dry_run_var = tk.BooleanVar()
        self.strict_var = tk.BooleanVar()
        checks = ttk.Frame(opts)
        checks.grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Checkbutton(checks, text="Solo probar (no crea la playlist)", variable=self.dry_run_var).pack(
            side="left", padx=(0, 24)
        )
        ttk.Checkbutton(checks, text="No agregar coincidencias dudosas", variable=self.strict_var).pack(side="left")

        # Resultados
        results = ttk.Frame(root)
        results.grid(row=4, column=0, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(2, weight=1)

        actions = ttk.Frame(results)
        actions.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        actions.columnconfigure(2, weight=1)
        self.convert_btn = ttk.Button(actions, text="Convertir", style="Accent.TButton", command=self.start)
        self.convert_btn.grid(row=0, column=0, padx=(0, 8), ipadx=16)
        self.cancel_btn = ttk.Button(actions, text="Cancelar", command=self.cancel, state="disabled")
        self.cancel_btn.grid(row=0, column=1, padx=(0, 12))
        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=2, sticky="w")

        self.progress = ttk.Progressbar(results, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        table = ttk.Frame(results)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("estado", "spotify", "youtube", "puntaje")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for col, title, width, stretch in (
            ("estado", "Estado", 130, False),
            ("spotify", "Canción en Spotify", 320, True),
            ("youtube", "Resultado en YouTube Music", 320, True),
            ("puntaje", "Puntaje", 70, False),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=stretch, anchor="center" if col == "puntaje" else "w")
        for status, (light, dark) in STATUS_COLORS.items():
            self.tree.tag_configure(status.name, foreground=dark if self.dark else light)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._open_selected)

        footer = ttk.Frame(results)
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="Doble clic en una canción para abrirla en YouTube Music.")
        ttk.Label(footer, textvariable=self.summary_var).grid(row=0, column=0, sticky="w")
        self.report_btn = ttk.Button(footer, text="Guardar reporte…", command=self.save_report, state="disabled")
        self.report_btn.grid(row=0, column=1, padx=(8, 0))
        self.open_btn = ttk.Button(
            footer, text="Abrir playlist", style="Accent.TButton", command=self.open_playlist, state="disabled"
        )
        self.open_btn.grid(row=0, column=2, padx=(8, 0))

    # ------------------------------------------------------------ acciones
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
            pass

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

    def validate(self) -> tuple[str, str] | None:
        """Devuelve (playlist_id, archivo de la cuenta) o muestra qué falta."""
        if self.liked_var.get():
            playlist_id = LIKED
        else:
            try:
                playlist_id = parse_playlist_ref(self.link_entry.value())
            except ValueError:
                messagebox.showwarning(
                    APP_TITLE, "Pega el link de una playlist de Spotify.\n(En Spotify: ⋯ → Compartir → Copiar enlace)",
                    parent=self,
                )
                return None
        account = self.account_var.get()
        if not account:
            if messagebox.askyesno(
                APP_TITLE, "Todavía no agregas ninguna cuenta de YouTube Music.\n¿Agregar una ahora?", parent=self
            ):
                self.open_add_account()
            return None
        config.load_env()
        if config.missing_vars() and not self.open_spotify_settings():
            return None
        return playlist_id, str(accounts.account_path(account))

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        checked = self.validate()
        if not checked:
            return
        playlist_id, auth_path = checked
        options = ConvertOptions(
            name=self.name_entry.value() or None,
            privacy=self.privacy_var.get(),
            strict=self.strict_var.get(),
            dry_run=self.dry_run_var.get(),
        )
        self.tree.delete(*self.tree.get_children())
        self.results, self.outcome, self.result_urls = [], None, {}
        self.progress.configure(value=0, maximum=1)
        self.summary_var.set("")
        self._set_running(True)
        self.status_var.set("Conectando con Spotify… (la primera vez se abre el navegador para autorizar)")
        self.cancel_event = threading.Event()
        self.worker = threading.Thread(
            target=self._work, args=(playlist_id, auth_path, options, self.cancel_event), daemon=True
        )
        self.worker.start()

    def cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            self.status_var.set("Cancelando…")

    def _work(self, playlist_id: str, auth_path: str, options: ConvertOptions, cancel: threading.Event) -> None:
        post = self.events.put
        try:
            spotify = self.spotify_factory()
            ytmusic = self.ytmusic_factory(auth_path)
            outcome = convert(
                spotify,
                ytmusic,
                playlist_id,
                options,
                on_start=lambda name, total: post(("start", name, total)),
                on_result=lambda i, total, result: post(("result", i, total, result)),
                on_status=lambda message: post(("status", message)),
                cancel=cancel,
            )
            post(("done", outcome))
        except BaseException as exc:  # noqa: BLE001 - todo error debe llegar a la ventana
            post(("error", exc))

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
            self.status_var.set(f"Buscando {total} canciones de «{name}»…")
        elif kind == "result":
            _, i, total, result = event
            self._add_row(result)
            self.progress.configure(value=i)
            self.status_var.set(f"Buscando canciones… {i} de {total}")
        elif kind == "done":
            self._finish(event[1])
        elif kind == "error":
            self._set_running(False)
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
        if c:
            self.result_urls[item] = c.url
        self.tree.see(item)

    def _finish(self, outcome: ConvertOutcome) -> None:
        self.outcome = outcome
        self._set_running(False)
        self.report_btn.configure(state="normal" if outcome.results else "disabled")
        self.summary_var.set(report.summary(outcome.results) if outcome.results else "")
        if outcome.cancelled:
            self.status_var.set("Cancelado. No se modificó YouTube Music.")
        elif not outcome.results:
            self.status_var.set("La playlist no tiene canciones.")
        elif outcome.playlist_id:
            self.open_btn.configure(state="normal")
            self.status_var.set(f"¡Listo! {outcome.added} canciones agregadas a «{outcome.playlist_name}».")
        elif self.dry_run_var.get():
            self.status_var.set("Prueba terminada: no se creó ninguna playlist.")
        else:
            self.status_var.set("No se encontró ninguna canción para agregar.")

    def _set_running(self, running: bool) -> None:
        self.convert_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        if running:
            self.open_btn.configure(state="disabled")
            self.report_btn.configure(state="disabled")

    def _open_selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection and selection[0] in self.result_urls:
            webbrowser.open(self.result_urls[selection[0]])

    def open_playlist(self) -> None:
        if self.outcome and self.outcome.playlist_url:
            webbrowser.open(self.outcome.playlist_url)

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
