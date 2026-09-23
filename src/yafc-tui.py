#!/usr/bin/env python3
"""
yafc-tui — Textual TUI for Yet Another Fan Control daemon
HP Victus 16 (Ryzen 7 7840HS + RTX 4050)
"""

import argparse
import glob
import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    Tab,
    Tabs,
)

from translations import STRINGS

# ── Locale ───────────────────────────────────────────────────────────────────

def _parse_lang() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--lang", choices=["tr", "en"], default=None)
    args, _ = parser.parse_known_args()
    if args.lang:
        return args.lang
    return "tr" if os.environ.get("LANG", "").lower().startswith("tr") else "en"


_lang: str = _parse_lang()


def _t(key: str, **kwargs: str | int | float) -> str:
    text = STRINGS.get(_lang, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text


# ── Config ──────────────────────────────────────────────────────────────────

CONF_PATH = Path("/etc/yafc/fan-curve.conf")
CONF_FALLBACK = Path(__file__).parent.parent / "config" / "fan-curve.conf"
STATE_PATH = Path("/run/yafc/state.json")
SERVICE_NAME = "yafc"
POLL_SECONDS = 3
STATE_STALE_S = 15

DEFAULT_CURVE = [
    {"temp": 90, "rpm": 5800},
    {"temp": 84, "rpm": 5000},
    {"temp": 78, "rpm": 4200},
    {"temp": 72, "rpm": 3600},
    {"temp": 65, "rpm": 3000},
    {"temp": 58, "rpm": 2500},
    {"temp": 50, "rpm": 2000},
    {"temp": 42, "rpm": 1650},
    {"temp": 35, "rpm": 1450},
    {"temp":  0, "rpm": 1450},
]

GAMING_CURVE = [
    {"temp": 90, "rpm": 5800},
    {"temp": 85, "rpm": 5600},
    {"temp": 80, "rpm": 5200},
    {"temp": 75, "rpm": 4700},
    {"temp": 70, "rpm": 4200},
    {"temp": 65, "rpm": 3700},
    {"temp": 60, "rpm": 3200},
    {"temp": 55, "rpm": 2800},
    {"temp": 45, "rpm": 2100},
    {"temp": 35, "rpm": 1600},
    {"temp":  0, "rpm": 1450},
]

# UI-only display ranges (not fan logic)
TEMP_MIN = 0
TEMP_MAX = 120
RPM_MIN = 0
RPM_MAX = 5800
GAUGE_MAX_TEMP = 100
GAUGE_WIDTH = 10
GAUGE_MIN = 10
GAUGE_MAX = 60
NARROW_WIDTH = 100
THERMALS_WIDTH = 34
CURVE_FIXED_COLS = 25
TEMP_WARN_C = 65
TEMP_HOT_C = 80

# Palette — single source of truth for the theme and Rich renderables
BG = "#0b0f14"
SURFACE = "#111820"
PANEL = "#16202b"
MUTED = "#7b8b9e"
BAR_IDLE = "#2f4356"
ACCENT = "#38bdf8"
OK = "#4ade80"
WARN = "#fbbf24"
HOT = "#f87171"

YAFC_THEME = Theme(
    name="yafc",
    primary=ACCENT,
    secondary="#818cf8",
    accent="#22d3ee",
    success=OK,
    warning=WARN,
    error=HOT,
    foreground="#c8d4e0",
    background=BG,
    surface=SURFACE,
    panel=PANEL,
    dark=True,
)


def get_conf_path() -> Path:
    if CONF_PATH.exists():
        return CONF_PATH
    return CONF_FALLBACK


def load_config() -> dict:
    path = get_conf_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"mode": "auto", "curve": list(DEFAULT_CURVE)}


def save_config(config: dict) -> None:
    """Atomic write — the daemon must never read a partially written file."""
    path = get_conf_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n")
    os.replace(tmp, path)


def reload_daemon() -> bool:
    """Sends SIGHUP to the daemon so it reloads the config."""
    try:
        result = subprocess.run(
            ["systemctl", "kill", "-s", "HUP", SERVICE_NAME],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass
    try:
        pid_result = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", SERVICE_NAME],
            capture_output=True, text=True, timeout=5,
        )
        pid = int(pid_result.stdout.strip())
        if pid > 0:
            os.kill(pid, signal.SIGHUP)
            return True
    except Exception:
        pass
    return False


# ── Sensor reading ───────────────────────────────────────────────────────────

def find_temp_path(sensor_name: str) -> Path | None:
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        name_file = Path(hwmon) / "name"
        if name_file.exists() and name_file.read_text().strip() == sensor_name:
            t = Path(hwmon) / "temp1_input"
            if t.exists():
                return t
    return None


def read_temp(path: Path) -> float:
    return int(path.read_text().strip()) / 1000.0


def read_nvidia_temp() -> float | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            timeout=3, stderr=subprocess.DEVNULL,
        )
        return float(out.strip())
    except Exception:
        return None


def read_fan_rpms() -> tuple[int, int] | None:
    for hwmon in glob.glob("/sys/devices/platform/hp-wmi/hwmon/hwmon*"):
        f1 = Path(hwmon) / "fan1_input"
        f2 = Path(hwmon) / "fan2_input"
        try:
            return int(f1.read_text().strip()), int(f2.read_text().strip())
        except Exception:
            pass
    return None


def get_service_status() -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def read_daemon_state() -> dict | None:
    """Applied fan state published by the daemon (None when missing or stale)."""
    try:
        data = json.loads(STATE_PATH.read_text())
        if time.time() - float(data["ts"]) > STATE_STALE_S:
            return None
        return data
    except Exception:
        return None


def get_target_level(temp: float, curve: list[dict]) -> int:
    """Returns the curve index for a given temperature (0 = highest level)."""
    for i, entry in enumerate(curve):
        if temp >= entry["temp"]:
            return i
    return len(curve) - 1


# ── Rendering helpers ────────────────────────────────────────────────────────

_BAR_PARTIAL = (" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉")


def bar_text(
    value: float, max_value: float, width: int, color: str, show_track: bool = True
) -> Text:
    ratio = 0.0 if max_value <= 0 else min(max(value / max_value, 0.0), 1.0)
    full, rem = divmod(round(ratio * width * 8), 8)
    bar = Text()
    bar.append("█" * full, style=color)
    if full < width:
        bar.append(_BAR_PARTIAL[rem], style=color)
        if show_track:
            bar.append("░" * (width - full - 1), style=MUTED)
    return bar


def temp_color(temp: float) -> str:
    if temp >= TEMP_HOT_C:
        return HOT
    if temp >= TEMP_WARN_C:
        return WARN
    return OK


def temp_str(temp: float | None) -> str:
    return "—".rjust(7) if temp is None else f"{temp:5.1f}°C"


def temp_plain(temp: float | None) -> str:
    return "—" if temp is None else f"{temp:.1f}"


_JOURNAL_RE = re.compile(r"^\w{3} +\d{1,2} (\d{2}:\d{2}:\d{2}) \S+ \S+: (.*)$")
_LOGGER_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ")
_LEVEL_RE = re.compile(r"\[(INFO|WARNING|ERROR)\]\s*")


def log_text(line: str) -> Text:
    """Formats a journalctl line: short timestamp + level-based colour."""
    match = _JOURNAL_RE.match(line)
    stamp, body = (match.group(1), match.group(2)) if match else ("", line)
    body = _LOGGER_RE.sub("", body)
    text = Text()
    if stamp:
        text.append(f"{stamp} ", style=MUTED)
    level = _LEVEL_RE.search(body)
    if not level:
        text.append(body, style=MUTED)
        return text
    color = {"INFO": "", "WARNING": WARN, "ERROR": HOT}[level.group(1)]
    text.append(body[: level.start()], style=MUTED)
    text.append(level.group(0).strip(), style=f"bold {color}".strip())
    text.append(f" {body[level.end():]}", style=color)
    return text


# ── Modals ───────────────────────────────────────────────────────────────────

class CurveModal(ModalScreen):
    """Adds or edits a single fan curve level."""

    BINDINGS = [Binding("escape", "cancel", _t("cancel"))]

    CSS = """
    CurveModal {
        align: center middle;
    }
    #modal-box {
        width: 46;
        height: auto;
        background: $surface;
        border: round $primary;
        border-title-color: $primary;
        border-title-style: bold;
        padding: 1 2;
    }
    .modal-row {
        height: 3;
        align: left middle;
    }
    .modal-label {
        width: 16;
        content-align: left middle;
        color: $foreground 70%;
    }
    .modal-input {
        width: 1fr;
    }
    #modal-hint {
        height: 1;
        color: $foreground 50%;
    }
    #modal-error {
        height: 1;
        color: $error;
    }
    #modal-buttons {
        height: 3;
        margin-top: 1;
        align: right middle;
    }
    #modal-buttons Button {
        margin-left: 1;
        min-width: 10;
        height: 1;
        border: none;
        padding: 0 2;
    }
    """

    def __init__(self, index: int, temp: int, rpm: int, taken_temps: set[int]):
        super().__init__()
        self.index = index
        self.orig_temp = temp
        self.orig_rpm = rpm
        self.taken_temps = taken_temps

    def compose(self) -> ComposeResult:
        title = (
            _t("modal_add_title") if self.index < 0
            else _t("modal_edit_title", n=self.index + 1)
        )
        with Vertical(id="modal-box") as box:
            box.border_title = title
            with Horizontal(classes="modal-row"):
                yield Label(_t("modal_temp_label"), classes="modal-label")
                yield Input(
                    value=str(self.orig_temp),
                    id="input-temp",
                    classes="modal-input",
                    type="integer",
                )
            with Horizontal(classes="modal-row"):
                yield Label(_t("modal_rpm_label"), classes="modal-label")
                yield Input(
                    value=str(self.orig_rpm),
                    id="input-rpm",
                    classes="modal-input",
                    type="integer",
                )
            yield Label(
                _t("modal_hint", tmin=TEMP_MIN, tmax=TEMP_MAX, rmin=RPM_MIN, rmax=RPM_MAX),
                id="modal-hint",
            )
            yield Label("", id="modal-error")
            with Horizontal(id="modal-buttons"):
                yield Button(_t("save"), variant="primary", id="btn-save")
                yield Button(_t("cancel"), id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#input-temp", Input).focus()

    def _error(self, key: str, input_id: str) -> None:
        self.query_one("#modal-error", Label).update(
            _t(key, tmin=TEMP_MIN, tmax=TEMP_MAX, rmin=RPM_MIN, rmax=RPM_MAX)
        )
        self.query_one(input_id, Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        temp_raw = self.query_one("#input-temp", Input).value.strip()
        rpm_raw = self.query_one("#input-rpm", Input).value.strip()
        if not temp_raw.lstrip("-").isdigit() or not TEMP_MIN <= int(temp_raw) <= TEMP_MAX:
            self._error("invalid_temp", "#input-temp")
            return
        if int(temp_raw) in self.taken_temps:
            self._error("invalid_dup_temp", "#input-temp")
            return
        if not rpm_raw.lstrip("-").isdigit() or not RPM_MIN <= int(rpm_raw) <= RPM_MAX:
            self._error("invalid_rpm", "#input-rpm")
            return
        self.dismiss({"temp": int(temp_raw), "rpm": int(rpm_raw)})

    @on(Input.Submitted)
    def _on_submitted(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-save")
    def _on_save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-cancel")
    def _on_cancel(self) -> None:
        self.action_cancel()


class ConfirmModal(ModalScreen):
    """Confirmation dialog for destructive actions."""

    BINDINGS = [Binding("escape", "cancel", _t("cancel"))]

    CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-box {
        width: 48;
        height: auto;
        background: $surface;
        border: round $error;
        border-title-color: $error;
        border-title-style: bold;
        padding: 1 2;
    }
    #confirm-msg {
        margin-bottom: 1;
    }
    #confirm-buttons {
        height: 3;
        align: right middle;
    }
    #confirm-buttons Button {
        margin-left: 1;
        min-width: 10;
        height: 1;
        border: none;
        padding: 0 2;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box") as box:
            box.border_title = _t("confirm_title")
            yield Label(self._message, id="confirm-msg")
            with Horizontal(id="confirm-buttons"):
                yield Button(_t("confirm_delete_btn"), variant="error", id="btn-confirm-delete")
                yield Button(_t("cancel"), id="btn-confirm-cancel")

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#btn-confirm-delete")
    def _on_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-confirm-cancel")
    def _on_cancel(self) -> None:
        self.dismiss(False)


# ── Main application ─────────────────────────────────────────────────────────

class FanTUI(App):

    TITLE = "YAFC"
    SUB_TITLE = "Victus 16 · Ryzen 7 7840HS + RTX 4050"

    BINDINGS = [
        Binding("q", "quit", _t("quit")),
        Binding("r", "refresh", _t("refresh")),
        Binding("c", "copy_status", _t("copy")),
        Binding("l", "toggle_log", _t("toggle_log")),
        Binding("n", "add_level", _t("add")),
        Binding("d", "delete_level", _t("delete")),
        Binding("?", "show_help_panel", _t("help")),
        Binding("1", "set_mode('max')", _t("mode_max"), show=False),
        Binding("2", "set_mode('auto')", _t("mode_auto"), show=False),
        Binding("3", "set_mode('manual')", _t("mode_manual"), show=False),
        Binding("4", "set_mode('gaming')", _t("mode_gaming"), show=False),
    ]

    CSS = """
    Screen {
        background: $background;
    }

    /* ── Header ── */
    Header {
        background: $surface;
    }

    /* ── Mode bar ── */
    #mode-bar {
        height: 3;
        padding: 0 1;
        background: $surface;
        align: left middle;
    }
    #mode-tabs {
        width: 1fr;
        background: transparent;
    }
    /* keep the active-tab underline, hide the full-width track */
    #mode-tabs .underline--bar {
        background: transparent;
    }
    Tab {
        color: $foreground 60%;
    }
    Tab.-active {
        color: $primary;
        text-style: bold;
    }
    #svc-buttons {
        width: auto;
        height: 3;
        align: right middle;
    }
    .svc {
        min-width: 0;
        width: auto;
        height: 1;
        border: none;
        padding: 0 1;
        margin-left: 1;
        text-style: none;
        color: $background;
    }
    .svc:hover {
        text-style: bold;
    }
    #btn-start:hover {
        background: $success-lighten-2;
    }
    #btn-stop:hover {
        background: $error-lighten-2;
    }
    #btn-restart:hover {
        background: $warning-lighten-2;
    }
    /* declared after :hover so disabled chips keep their muted look */
    #btn-start:disabled, #btn-stop:disabled, #btn-restart:disabled {
        background: $panel;
        color: $foreground 50%;
    }

    /* ── Panels ── */
    /* #thermals-panel width must match THERMALS_WIDTH in _bar_width() */
    #middle {
        height: 2fr;
    }
    #thermals-panel, #curve-panel {
        height: 1fr;
        border: round $panel;
        border-title-color: $primary;
        border-title-style: bold;
        border-subtitle-color: $foreground 50%;
        padding: 0 1;
    }
    #thermals-panel {
        width: 34;
    }
    #curve-panel {
        width: 1fr;
    }
    #thermals {
        height: auto;
        padding: 1 0;
    }
    #curve-note {
        height: 1fr;
        padding: 1 1;
        color: $foreground 60%;
    }
    #curve-table {
        height: 1fr;
        background: transparent;
    }
    DataTable > .datatable--header {
        background: transparent;
        color: $foreground 70%;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: $panel;
        color: $foreground;
    }

    /* ── Log panel ── */
    #log-panel {
        height: 1fr;
        max-height: 12;
        display: none;
        border: round $panel;
        border-title-color: $primary;
        border-title-style: bold;
        padding: 0 1;
    }
    #log-panel.visible {
        display: block;
    }
    #log-output {
        height: 1fr;
        background: transparent;
    }

    /* ── Status bar ── */
    #status-bar {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    #status-left {
        width: 1fr;
    }
    #status-right {
        width: auto;
    }

    /* ── Footer ── */
    Footer {
        background: $surface;
    }
    /* keep toasts clear of the status bar */
    ToastRack {
        margin-bottom: 2;
    }

    /* ── Narrow terminals ── */
    .narrow #thermals-panel {
        width: 26;
    }
    .narrow .svc {
        padding: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self._config = load_config()
        self._cpu_path = find_temp_path("k10temp") or find_temp_path("acpitz")
        self._igpu_path = find_temp_path("amdgpu")
        self._log_proc: subprocess.Popen | None = None
        self._rendered_curve: list[dict] = []
        self._privileged = os.geteuid() == 0
        self._narrow = False
        self._bar_col_width = GAUGE_WIDTH
        self._svc_busy = False
        self._cpu_temp: float | None = None
        self._igpu_temp: float | None = None
        self._dgpu_temp: float | None = None
        self._fan1_rpm: int | None = None
        self._fan2_rpm: int | None = None
        self._service_status = "unknown"
        self._daemon_state: dict | None = None
        self._active_level = -1
        self._active_source = "target"

    # ── Layout ───────────────────────────────────────────────────────────────

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        for cmd in super().get_system_commands(screen):
            if cmd.title != "Screenshot":
                yield cmd

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="mode-bar"):
            yield Tabs(
                Tab(_t("mode_max"), id="max"),
                Tab(_t("mode_auto"), id="auto"),
                Tab(_t("mode_manual"), id="manual"),
                Tab(_t("mode_gaming"), id="gaming"),
                active=self._config.get("mode", "auto"),
                id="mode-tabs",
            )
            with Horizontal(id="svc-buttons"):
                yield Button(_t("svc_start"), id="btn-start", classes="svc", variant="success")
                yield Button(_t("svc_stop"), id="btn-stop", classes="svc", variant="error")
                yield Button(_t("svc_restart"), id="btn-restart", classes="svc", variant="warning")

        with Horizontal(id="middle"):
            with Vertical(id="thermals-panel") as thermals:
                thermals.border_title = _t("panel_thermals")
                yield Static(id="thermals")
            with Vertical(id="curve-panel") as curve:
                curve.border_title = _t("panel_curve")
                yield Static("", id="curve-note")
                yield DataTable(id="curve-table", cursor_type="row", zebra_stripes=True)

        with Vertical(id="log-panel") as log_panel:
            log_panel.border_title = _t("panel_log")
            yield RichLog(id="log-output", markup=False, wrap=True, min_width=40, max_lines=1000)

        with Horizontal(id="status-bar"):
            yield Static("", id="status-left")
            yield Static("", id="status-right")

        yield Footer(compact=True)

    def on_mount(self) -> None:
        self.register_theme(YAFC_THEME)
        self.theme = "yafc"
        self._build_curve_table()
        self._apply_mode_ui()
        self._start_log_stream()
        self.set_interval(POLL_SECONDS, self._poll)
        self._poll()

    def on_resize(self, event: Resize) -> None:
        narrow = event.size.width < NARROW_WIDTH
        bar_width = self._bar_width(event.size.width)
        if narrow == self._narrow and bar_width == self._bar_col_width:
            return
        self._narrow = narrow
        self.screen.set_class(narrow, "narrow")
        self._build_curve_table()
        self._render_thermals()

    # ── Curve model ──────────────────────────────────────────────────────────

    def _manual_curve(self) -> list[dict]:
        curve = self._config.get("curve")
        if isinstance(curve, list) and curve:
            return [dict(entry) for entry in curve]
        return [dict(entry) for entry in DEFAULT_CURVE]

    def _effective_curve(self) -> list[dict] | None:
        """Curve in use for the active mode (None when MAX ignores the curve)."""
        mode = self._config.get("mode", "auto")
        if mode == "manual":
            return self._manual_curve()
        if mode == "gaming":
            return [dict(entry) for entry in GAMING_CURVE]
        if mode == "max":
            return None
        return [dict(entry) for entry in DEFAULT_CURVE]

    def _recalculate_active_level(self) -> None:
        mode = self._config.get("mode", "auto")
        curve = self._effective_curve()
        if curve is None:
            # MAX mode ignores the curve; the status bar reports it separately.
            self._active_level = -1
            return
        if self._daemon_state and self._daemon_state.get("mode") == mode:
            self._active_level = int(self._daemon_state["level"])
            self._active_source = "daemon"
            return
        dominant = self._dominant()
        if dominant is None:
            self._active_level = -1
        else:
            self._active_level = get_target_level(dominant[1], curve)
        self._active_source = "target"

    def _dominant(self) -> tuple[str, float] | None:
        sensors = [
            ("CPU", self._cpu_temp),
            ("iGPU", self._igpu_temp),
            ("dGPU", self._dgpu_temp),
        ]
        available = [(name, temp) for name, temp in sensors if temp is not None]
        if not available:
            return None
        if self._daemon_state:
            name = str(self._daemon_state.get("dominant", ""))
            for sensor, temp in available:
                if sensor == name:
                    return sensor, temp
        return max(available, key=lambda item: item[1])

    # ── Curve table ──────────────────────────────────────────────────────────

    def _bar_width(self, screen_width: int | None = None) -> int:
        """Bar column width that fills the curve panel (0 when hidden)."""
        width = self.size.width if screen_width is None else screen_width
        if width < NARROW_WIDTH:
            return 0
        available = width - THERMALS_WIDTH - 4 - CURVE_FIXED_COLS
        return max(GAUGE_MIN, min(GAUGE_MAX, available))

    def _build_curve_table(self) -> None:
        table = self.query_one("#curve-table", DataTable)
        table.clear(columns=True)
        table.add_column("", key="ind", width=2)
        table.add_column(_t("col_temp"), key="temp", width=7)
        table.add_column(_t("col_rpm"), key="rpm", width=7)
        if not self._narrow:
            self._bar_col_width = self._bar_width()
            table.add_column("", key="bar", width=self._bar_col_width)
        self._rendered_curve = []
        self._refresh_curve_rows(rebuild=True)

    def _curve_cells(self, index: int, entry: dict) -> list[tuple[str, Text]]:
        active = index == self._active_level
        style = f"bold {ACCENT}" if active else ""
        cells = [
            ("ind", Text("▶" if active else "●", style=style or MUTED)),
            ("temp", Text(f"{entry['temp']:>3}°C", style=style)),
            ("rpm", Text(f"{entry['rpm']:>5}", style=style)),
        ]
        if not self._narrow:
            color = ACCENT if active else BAR_IDLE
            cells.append(
                (
                    "bar",
                    bar_text(
                        entry["rpm"], RPM_MAX, self._bar_width(), color, show_track=False
                    ),
                )
            )
        return cells

    def _refresh_curve_rows(self, rebuild: bool = False) -> None:
        curve = self._effective_curve()
        table = self.query_one("#curve-table", DataTable)
        if curve is None:
            return
        if rebuild or curve != self._rendered_curve or table.row_count != len(curve):
            table.clear()
            for i, entry in enumerate(curve):
                table.add_row(*[cell for _, cell in self._curve_cells(i, entry)], key=str(i))
            self._rendered_curve = [dict(entry) for entry in curve]
        else:
            for i, entry in enumerate(curve):
                for key, cell in self._curve_cells(i, entry):
                    table.update_cell(str(i), key, cell)

    # ── Polling ──────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="poll")
    def _poll(self) -> None:
        """Reads sensors and service state off the UI thread."""
        cpu = igpu = dgpu = None
        try:
            if self._cpu_path:
                cpu = read_temp(self._cpu_path)
            if self._igpu_path:
                igpu = read_temp(self._igpu_path)
        except Exception:
            pass
        dgpu = read_nvidia_temp()
        fans = read_fan_rpms()
        status = get_service_status()
        state = read_daemon_state()
        self.call_from_thread(self._apply_poll, cpu, igpu, dgpu, fans, status, state)

    def _apply_poll(
        self,
        cpu: float | None,
        igpu: float | None,
        dgpu: float | None,
        fans: tuple[int, int] | None,
        status: str,
        state: dict | None,
    ) -> None:
        self._cpu_temp, self._igpu_temp, self._dgpu_temp = cpu, igpu, dgpu
        self._fan1_rpm, self._fan2_rpm = fans if fans else (None, None)
        self._service_status = status
        self._daemon_state = state
        self._recalculate_active_level()
        self._render_thermals()
        self._refresh_curve_rows()
        self._update_status_bar()
        self._update_service_ui()

    # ── Rendering ────────────────────────────────────────────────────────────

    def _sensor_row(self, name: str, temp: float | None) -> list[Text]:
        color = temp_color(temp) if temp is not None else MUTED
        row = [
            Text.assemble(("● ", color), (name, MUTED)),
            Text(temp_str(temp), style=color),
        ]
        if not self._narrow:
            row.append(
                bar_text(temp or 0.0, GAUGE_MAX_TEMP, GAUGE_WIDTH, color)
                if temp is not None else bar_text(0, 1, GAUGE_WIDTH, MUTED)
            )
        return row

    def _fan_row(self, name: str, rpm: int | None) -> list[Text]:
        value = "—".rjust(9) if rpm is None else f"{rpm:>5} RPM"
        row = [
            Text.assemble(("● ", ACCENT), (name, MUTED)),
            Text(value, style=ACCENT if rpm is not None else MUTED),
        ]
        if not self._narrow:
            row.append(
                bar_text(rpm or 0, RPM_MAX, GAUGE_WIDTH, ACCENT)
                if rpm is not None else bar_text(0, 1, GAUGE_WIDTH, MUTED)
            )
        return row

    def _render_thermals(self) -> None:
        columns = 2 if self._narrow else 3
        temps = Table.grid(padding=(0, 1))
        fans = Table.grid(padding=(0, 1))
        for grid in (temps, fans):
            for _ in range(columns):
                grid.add_column(no_wrap=True)
        temps.add_row(*self._sensor_row("CPU", self._cpu_temp))
        temps.add_row(*self._sensor_row("iGPU", self._igpu_temp))
        temps.add_row(*self._sensor_row("dGPU", self._dgpu_temp))
        fans.add_row(*self._fan_row("Fan 1", self._fan1_rpm))
        fans.add_row(*self._fan_row("Fan 2", self._fan2_rpm))
        self.query_one("#thermals", Static).update(
            Group(temps, Rule(style=PANEL), fans)
        )

    def _update_status_bar(self) -> None:
        mode = self._config.get("mode", "auto")
        left = Text()
        left.append(mode.upper(), style=f"bold {ACCENT}")
        if mode == "max":
            left.append(f"  ·  {_t('status_max', rpm=RPM_MAX)}", style=MUTED)
        else:
            dominant = self._dominant()
            curve = self._effective_curve()
            if dominant is None or curve is None:
                left.append(f"  ·  {_t('status_no_data')}", style=MUTED)
            else:
                sensor, temp = dominant
                if self._active_source == "daemon" and self._daemon_state:
                    level = int(self._daemon_state["level"]) + 1
                    rpm = int(self._daemon_state["rpm"])
                else:
                    level = self._active_level + 1
                    rpm = curve[self._active_level]["rpm"] if self._active_level >= 0 else 0
                left.append(
                    "  ·  " + _t(
                        "status_decision",
                        sensor=sensor,
                        temp=f"{temp:.1f}",
                        level=level,
                        rpm=rpm,
                    ),
                    style=MUTED,
                )
                if self._active_source != "daemon":
                    left.append(f" ({_t('status_target')})", style=WARN)

        right = Text()
        active = self._service_status == "active"
        failed = self._service_status in ("failed", "deactivating")
        right.append("● ", style=OK if active else HOT if failed else MUTED)
        right.append(f"{_t('status_service')}: {self._service_status}", style=MUTED)
        if not self._privileged:
            right.append(f"  ·  {_t('status_readonly')}", style=WARN)

        self.query_one("#status-left", Static).update(left)
        self.query_one("#status-right", Static).update(right)

    def _update_service_ui(self) -> None:
        active = self._service_status == "active"
        disabled = not self._privileged or self._svc_busy
        self.query_one("#btn-start", Button).disabled = disabled or active
        self.query_one("#btn-stop", Button).disabled = disabled or not active
        self.query_one("#btn-restart", Button).disabled = disabled

    # ── Mode ─────────────────────────────────────────────────────────────────

    def _apply_mode_ui(self) -> None:
        mode = self._config.get("mode", "auto")
        self.query_one("#mode-tabs", Tabs).active = mode
        curve = self.query_one("#curve-panel", Vertical)
        table = self.query_one("#curve-table", DataTable)
        note = self.query_one("#curve-note", Static)
        source = {
            "auto": "curve_src_auto",
            "gaming": "curve_src_gaming",
            "manual": "curve_src_manual",
        }.get(mode)
        curve.border_title = (
            f"{_t('panel_curve')} · {_t(source)}" if source else _t("panel_curve")
        )

        if mode == "max":
            table.display = False
            note.display = True
            note.update(_t("curve_max_note", rpm=RPM_MAX))
            curve.border_subtitle = ""
        else:
            table.display = True
            note.display = False
            if mode == "manual" and self._privileged:
                curve.border_subtitle = _t("curve_hint_edit")
                table.cursor_type = "row"
            elif mode == "manual":
                curve.border_subtitle = _t("status_readonly")
                table.cursor_type = "none"
            else:
                curve.border_subtitle = _t("curve_hint_readonly")
                table.cursor_type = "none"

    def _sync_tabs(self) -> None:
        tabs = self.query_one("#mode-tabs", Tabs)
        mode = self._config.get("mode", "auto")
        if tabs.active != mode:
            tabs.active = mode

    def action_set_mode(self, mode: str) -> None:
        if mode == self._config.get("mode", "auto"):
            return
        if not self._privileged:
            self.notify(_t("toast_not_writable"), severity="warning", timeout=6)
            self._sync_tabs()
            return
        config = dict(self._config)
        config["mode"] = mode
        try:
            save_config(config)
        except OSError as e:
            self.notify(_t("toast_save_error", e=e.strerror or e), severity="error", timeout=8)
            self._sync_tabs()
            return
        self._config = config
        if not reload_daemon():
            self.notify(_t("toast_reload_error"), severity="warning", timeout=6)
        self._apply_mode_ui()
        self._recalculate_active_level()
        self._refresh_curve_rows()
        self._update_status_bar()
        self.notify(_t("toast_mode", mode=mode.upper()), timeout=3)

    @on(Tabs.TabActivated, "#mode-tabs")
    def _on_tab_activated(self, event: Tabs.TabActivated) -> None:
        if not self.is_running or event.tab is None or not event.tab.id:
            return
        self.action_set_mode(event.tab.id)

    # ── Service control ──────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-start")
    def _on_start(self) -> None:
        self._service_action("start", _t("svc_start"))

    @on(Button.Pressed, "#btn-stop")
    def _on_stop(self) -> None:
        self._service_action("stop", _t("svc_stop"))

    @on(Button.Pressed, "#btn-restart")
    def _on_restart(self) -> None:
        self._service_action("restart", _t("svc_restart"))

    def _service_action(self, action: str, label: str) -> None:
        if not self._privileged:
            self.notify(_t("toast_not_writable"), severity="warning", timeout=6)
            return
        self._svc_busy = True
        self._update_service_ui()
        self._run_service_action(action, label)

    @work(thread=True, exclusive=True, group="service")
    def _run_service_action(self, action: str, label: str) -> None:
        ok = False
        message = ""
        try:
            result = subprocess.run(
                ["systemctl", action, SERVICE_NAME],
                capture_output=True, text=True, timeout=15,
            )
            ok = result.returncode == 0
            message = (result.stderr or result.stdout).strip().splitlines()
            message = message[0] if message else ""
        except Exception as e:
            message = str(e)
        status = get_service_status()
        self.call_from_thread(self._service_done, label, ok, message, status)

    def _service_done(
        self, label: str, ok: bool, message: str, status: str
    ) -> None:
        self._svc_busy = False
        self._service_status = status
        if ok:
            self.notify(_t("toast_svc_ok", action=label), timeout=3)
        else:
            self.notify(
                _t("toast_svc_fail", action=label, msg=message or status),
                severity="error",
                timeout=8,
            )
        self._update_service_ui()
        self._update_status_bar()

    # ── Curve editing ────────────────────────────────────────────────────────

    def _editing_allowed(self) -> bool:
        if self._config.get("mode") != "manual":
            self.notify(_t("toast_only_manual"), severity="warning", timeout=4)
            return False
        if not self._privileged:
            self.notify(_t("toast_not_writable"), severity="warning", timeout=6)
            return False
        return True

    def _commit_curve(self, curve: list[dict], message: str, select_temp: int) -> None:
        config = dict(self._config)
        config["curve"] = curve
        try:
            save_config(config)
        except OSError as e:
            self.notify(_t("toast_save_error", e=e.strerror or e), severity="error", timeout=8)
            return
        self._config = config
        if not reload_daemon():
            self.notify(_t("toast_reload_error"), severity="warning", timeout=6)
        self._rendered_curve = []
        self._refresh_curve_rows(rebuild=True)
        self._select_row_by_temp(select_temp)
        self.notify(message, timeout=3)

    def _select_row_by_temp(self, temp: int) -> None:
        table = self.query_one("#curve-table", DataTable)
        curve = self._effective_curve() or []
        for i, entry in enumerate(curve):
            if entry["temp"] == temp:
                table.move_cursor(row=i)
                return

    @on(DataTable.RowSelected, "#curve-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        if not self._editing_allowed():
            return
        index = int(event.row_key.value or 0)
        curve = self._manual_curve()
        if index >= len(curve):
            return
        entry = curve[index]
        taken = {e["temp"] for i, e in enumerate(curve) if i != index}
        self.push_screen(
            CurveModal(index, entry["temp"], entry["rpm"], taken),
            callback=lambda result: self._on_edit_result(index, result),
        )

    def _on_edit_result(self, index: int, result: dict | None) -> None:
        if result is None:
            return
        curve = self._manual_curve()
        if index >= len(curve):
            return
        curve[index] = result
        curve.sort(key=lambda e: e["temp"], reverse=True)
        self._commit_curve(
            curve,
            _t("toast_level_updated", temp=result["temp"], rpm=result["rpm"]),
            result["temp"],
        )

    def action_add_level(self) -> None:
        if not self._editing_allowed():
            return
        curve = self._manual_curve()
        taken = {e["temp"] for e in curve}
        self.push_screen(
            CurveModal(-1, 0, curve[-1]["rpm"], taken),
            callback=self._on_add_result,
        )

    def _on_add_result(self, result: dict | None) -> None:
        if result is None:
            return
        curve = self._manual_curve()
        curve.append(result)
        curve.sort(key=lambda e: e["temp"], reverse=True)
        self._commit_curve(
            curve,
            _t("toast_level_added", temp=result["temp"], rpm=result["rpm"]),
            result["temp"],
        )

    def action_delete_level(self) -> None:
        if not self._editing_allowed():
            return
        curve = self._manual_curve()
        if len(curve) <= 2:
            self.notify(_t("toast_min_levels"), severity="warning", timeout=4)
            return
        table = self.query_one("#curve-table", DataTable)
        index = max(0, min(table.cursor_row, len(curve) - 1))
        entry = curve[index]
        self.push_screen(
            ConfirmModal(_t("del_confirm_msg", temp=entry["temp"], rpm=entry["rpm"])),
            callback=lambda confirmed: self._on_delete_result(confirmed, index),
        )

    def _on_delete_result(self, confirmed: bool | None, index: int) -> None:
        if not confirmed:
            return
        curve = self._manual_curve()
        if index >= len(curve):
            return
        removed = curve.pop(index)
        self._commit_curve(
            curve,
            _t("toast_level_deleted", temp=removed["temp"], rpm=removed["rpm"]),
            removed["temp"],
        )

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._config = load_config()
        self._apply_mode_ui()
        self._sync_tabs()
        self._build_curve_table()
        self._poll()

    def action_toggle_log(self) -> None:
        panel = self.query_one("#log-panel")
        panel.toggle_class("visible")
        if panel.has_class("visible"):
            self.query_one("#log-output", RichLog).scroll_end()

    def action_copy_status(self) -> None:
        mode = self._config.get("mode", "auto").upper()
        curve = self._effective_curve()
        lines = [
            f"Yet Another Fan Control (YAFC) — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            _t("copy_mode_svc", mode=mode, status=self._service_status),
            _t(
                "copy_temps",
                cpu=temp_plain(self._cpu_temp),
                igpu=temp_plain(self._igpu_temp),
                dgpu=temp_plain(self._dgpu_temp),
            ),
            _t("copy_fans", f1=self._fan1_rpm, f2=self._fan2_rpm),
        ]
        if curve is None:
            lines.append(_t("copy_fan_max", rpm=RPM_MAX))
        else:
            lines.append(_t("copy_curve_title"))
            for i, entry in enumerate(curve):
                marker = ">" if i == self._active_level else " "
                lines.append(f"  {marker} {entry['temp']:>3}°C → {entry['rpm']} RPM")
        self.copy_to_clipboard("\n".join(lines))
        self.notify(_t("toast_copied"), timeout=3)

    # ── Log stream ───────────────────────────────────────────────────────────

    def _start_log_stream(self) -> None:
        self._stream_logs()

    @work(thread=True, exclusive=True, group="log")
    def _stream_logs(self) -> None:
        try:
            proc = subprocess.Popen(
                ["journalctl", "-u", SERVICE_NAME, "-f", "-n", "50", "--no-pager"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as e:
            self.call_from_thread(self._append_log, log_text(_t("toast_log_error", e=str(e))))
            return
        self._log_proc = proc
        try:
            for line in proc.stdout or []:
                line = line.rstrip()
                if line:
                    self.call_from_thread(self._append_log, log_text(line))
        finally:
            self.call_from_thread(self._append_log, log_text(_t("toast_journal_ended")))

    def _append_log(self, line: Text) -> None:
        try:
            self.query_one("#log-output", RichLog).write(line)
        except Exception:
            pass

    def on_unmount(self) -> None:
        if self._log_proc:
            self._log_proc.terminate()


if __name__ == "__main__":
    FanTUI().run()
