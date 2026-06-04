"""Theme, DPI, fonts and palette for the dosforge GUI.

Windows 11 / Fluent-inspired look built on the Sun Valley ttk theme
(``sv_ttk``). All the platform-specific setup (per-monitor DPI awareness,
light/dark detection, window icon) lives here so the rest of the GUI stays
declarative.

Important ordering constraints (see plan):

* :func:`enable_dpi_awareness` MUST run before any Tk root/widget is created.
* Custom ttk styles MUST be (re)applied AFTER ``sv_ttk.set_theme`` — the theme
  reset clears style state, so :func:`ThemeManager.apply` always reconfigures.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Per-monitor-v2 DPI awareness context handle.
_DPI_PER_MONITOR_V2 = -4


def enable_dpi_awareness() -> None:
    """Make the process per-monitor-DPI aware (crisp text on HiDPI).

    Best-effort and Windows-only. Must be called before the first Tk root is
    created; Windows ignores it once a window exists or a manifest already set
    awareness. All failures are swallowed.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDpiAwarenessContext(_DPI_PER_MONITOR_V2)
            return
        except Exception:
            pass
        # Fallbacks for older Windows.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR
            return
        except Exception:
            pass
        user32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass(frozen=True, slots=True)
class Palette:
    """Resolved colors for the active theme mode."""

    mode: str  # "light" | "dark"
    window_bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    nav_bg: str
    nav_active_bg: str
    danger: str


_LIGHT = Palette(
    mode="light",
    window_bg="#f3f3f3",
    surface="#ffffff",
    surface_alt="#f5f5f5",
    border="#e3e3e3",
    text="#1a1a1a",
    text_muted="#5d5d5d",
    accent="#0067c0",
    accent_text="#ffffff",
    nav_bg="#ededed",
    nav_active_bg="#ffffff",
    danger="#c42b1c",
)

_DARK = Palette(
    mode="dark",
    window_bg="#1c1c1c",
    surface="#2b2b2b",
    surface_alt="#272727",
    border="#3a3a3a",
    text="#ffffff",
    text_muted="#b8b8b8",
    accent="#4cc2ff",
    accent_text="#06243a",
    nav_bg="#1b1b1b",
    nav_active_bg="#2d2d2d",
    danger="#ff99a4",
)


def palette_for(mode: str) -> Palette:
    return _DARK if mode == "dark" else _LIGHT


def detect_windows_theme() -> str:
    """Return ``"dark"`` or ``"light"`` from the Windows apps theme setting."""
    if sys.platform != "win32":
        return "light"
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            key.Close()
        return "light" if value else "dark"
    except Exception:
        return "light"


# Font family preference: Win11's variable UI font, then classic Segoe.
_UI_FAMILY_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI", "Helvetica")


def _pick_font_family() -> str:
    try:
        from tkinter import font as tkfont

        available = set(tkfont.families())
        for candidate in _UI_FAMILY_CANDIDATES:
            if candidate in available:
                return candidate
    except Exception:
        pass
    return "Segoe UI"


def _resource_path(rel: str) -> Path | None:
    """Resolve a bundled resource path (frozen bundle or dev tree)."""
    candidates = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(Path(base) / rel)
    # Dev tree: src/dosforge/_gui/theme.py -> repo root is parents[3].
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / rel)
    for path in candidates:
        if path.is_file():
            return path
    return None


def set_window_icon(root) -> None:
    """Best-effort: set the window icon from the bundled PNG."""
    png = _resource_path("assets/icons/dosforge-256.png")
    if png is None:
        return
    try:
        import tkinter as tk

        image = tk.PhotoImage(file=str(png))
        root.iconphoto(True, image)
        # Keep a reference so it isn't garbage-collected.
        root._dosforge_icon = image  # type: ignore[attr-defined]
    except Exception:
        pass


class ThemeManager:
    """Owns the active theme mode, fonts and custom ttk styles."""

    def __init__(self, root) -> None:
        self.root = root
        self.family = _pick_font_family()
        self.mode = detect_windows_theme()
        self.palette = palette_for(self.mode)
        # Font objects (named so a single configure() restyles globally).
        from tkinter import font as tkfont

        self.font_body = tkfont.Font(family=self.family, size=10)
        self.font_small = tkfont.Font(family=self.family, size=9)
        self.font_heading = tkfont.Font(family=self.family, size=12, weight="bold")
        self.font_title = tkfont.Font(family=self.family, size=20, weight="bold")
        self.font_nav = tkfont.Font(family=self.family, size=11)

    # ── theme application ──────────────────────────────────────────────
    def apply(self, mode: str | None = None) -> None:
        import sv_ttk

        if mode is not None:
            self.mode = mode
        self.palette = palette_for(self.mode)
        sv_ttk.set_theme(self.mode)
        self._configure_styles()
        # Window chrome (title bar) follows the theme on Win11.
        self._apply_titlebar_theme()

    def toggle(self) -> str:
        self.mode = "light" if self.mode == "dark" else "dark"
        self.apply(self.mode)
        return self.mode

    def _configure_styles(self) -> None:
        from tkinter import ttk

        style = ttk.Style(self.root)
        pal = self.palette

        self.root.configure(background=pal.window_bg)

        # Header text styles. These use the default TLabel inheritance so
        # they pick up sv_ttk's correct background; we only override font
        # and (optionally) foreground.
        style.configure("Title.TLabel", font=self.font_title)
        style.configure("Subtitle.TLabel", font=self.font_small, foreground=pal.text_muted)
        style.configure("Heading.TLabel", font=self.font_heading)
        style.configure("FieldLabel.TLabel", font=self.font_small, foreground=pal.text_muted)
        style.configure("Muted.TLabel", font=self.font_small, foreground=pal.text_muted)

        # Combobox dropdown popup colors (the popup is a plain Tk Listbox,
        # not themed by sv_ttk).
        self.root.option_add("*TCombobox*Listbox.background", pal.surface)
        self.root.option_add("*TCombobox*Listbox.foreground", pal.text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", pal.accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", pal.accent_text)
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.font", self.font_body)

        # Nav rail buttons live on a tk.Frame surface (NavRail), so we
        # configure them explicitly.
        style.configure(
            "Nav.TButton",
            font=self.font_nav,
            anchor="w",
            padding=(16, 10),
            relief="flat",
            background=pal.nav_bg,
            foreground=pal.text,
            borderwidth=0,
        )
        style.map(
            "Nav.TButton",
            background=[("active", pal.nav_active_bg), ("pressed", pal.nav_active_bg)],
            foreground=[("active", pal.text)],
        )
        style.configure(
            "NavActive.TButton",
            font=self.font_nav,
            anchor="w",
            padding=(16, 10),
            relief="flat",
            background=pal.nav_active_bg,
            foreground=pal.accent,
            borderwidth=0,
        )
        style.map(
            "NavActive.TButton",
            background=[("active", pal.nav_active_bg), ("pressed", pal.nav_active_bg)],
            foreground=[("active", pal.accent)],
        )

        # Status strip lives on the window bg, not on a card surface.
        style.configure(
            "Status.TLabel",
            font=self.font_small,
            foreground=pal.text_muted,
            background=pal.window_bg,
        )
        style.configure(
            "StatusError.TLabel",
            font=self.font_small,
            foreground=pal.danger,
            background=pal.window_bg,
        )

    def _apply_titlebar_theme(self) -> None:
        """Match the Win11 title bar to the app theme (DWM immersive dark)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1 if self.mode == "dark" else 0)
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (1903+); 19 on older builds.
            for attr in (20, 19):
                try:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                    )
                except Exception:
                    continue
        except Exception:
            pass
