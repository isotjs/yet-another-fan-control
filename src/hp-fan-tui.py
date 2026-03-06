#!/usr/bin/env python3
"""
hp-fan-tui — Textual TUI for HP Fan Curve Daemon
HP Victus 16 (Ryzen 7 7840HS + RTX 4050)
"""

import argparse
import glob
import json
import subprocess
import os
import signal
from pathlib import Path

from collections.abc import Iterable
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Log,
    Static,
)
from textual import work, on
from textual.worker import Worker

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

CONF_PATH = Path("/etc/hp-fan-curve/fan-curve.conf")
CONF_FALLBACK = Path(__file__).parent.parent / "config" / "fan-curve.conf"
SERVICE_NAME = "hp-fan-curve"
POLL_SECONDS = 3

DEFAULT_CURVE = [
    {"temp": 90, "rpm": 5800},
    {"temp": 84, "rpm": 4930},
    {"temp": 78, "rpm": 4060},
    {"temp": 70, "rpm": 3500},
    {"temp": 55, "rpm": 2320},
    {"temp": 45, "rpm": 1740},
    {"temp": 35, "rpm": 1450},
    {"temp":  0, "rpm": 1450},
]


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
    path = get_conf_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))


def reload_daemon() -> None:
    """Sends SIGHUP to the daemon to reload config."""
    try:
        result = subprocess.run(
            ["systemctl", "kill", "-s", "HUP", SERVICE_NAME],
            capture_output=True,
        )
        if result.returncode != 0:
            # Fall back to finding PID directly if systemctl failed
            pid_result = subprocess.run(
                ["systemctl", "show", "-p", "MainPID", "--value", SERVICE_NAME],
                capture_output=True, text=True,
            )
            pid = int(pid_result.stdout.strip())
            if pid > 0:
                os.kill(pid, signal.SIGHUP)
    except Exception:
        pass


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


def read_fan_rpms() -> tuple[int, int]:
    for hwmon in glob.glob("/sys/devices/platform/hp-wmi/hwmon/hwmon*"):
        f1 = Path(hwmon) / "fan1_input"
        f2 = Path(hwmon) / "fan2_input"
        try:
            return int(f1.read_text().strip()), int(f2.read_text().strip())
        except Exception:
            pass
    return 0, 0


def get_service_status() -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True, text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def get_active_level(temp: float, curve: list[dict]) -> int:
    """Returns the active level index for the current temperature."""
    for i, entry in enumerate(curve):
        if temp >= entry["temp"]:
            return i
    return len(curve) - 1


# ── Edit Modal ───────────────────────────────────────────────────────────────

class EditCurveModal(ModalScreen):
    """Modal dialog for editing a fan curve row."""

    BINDINGS = [Binding("escape", "dismiss", _t("cancel"))]

    CSS = """
    EditCurveModal {
        align: center middle;
    }
    #modal-container {
        width: 50;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #modal-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        color: $primary;
    }
    .modal-row {
        height: 3;
        margin-bottom: 1;
        align: left middle;
    }
    .modal-label {
        width: 18;
        content-align: left middle;
    }
    .modal-input {
        width: 16;
    }
    #modal-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #btn-save {
        margin-right: 2;
    }
    """

    def __init__(self, index: int, temp: int, rpm: int):
        super().__init__()
        self.index = index
        self.orig_temp = temp
        self.orig_rpm = rpm

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label(_t("modal_edit_title", n=self.index + 1), id="modal-title")
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
            with Horizontal(id="modal-buttons"):
                yield Button(_t("save"), variant="primary", id="btn-save")
                yield Button(_t("cancel"), variant="default", id="btn-cancel")

    @on(Button.Pressed, "#btn-save")
    def save(self) -> None:
        try:
            temp = int(self.query_one("#input-temp", Input).value)
            rpm = int(self.query_one("#input-rpm", Input).value)
            self.dismiss({"temp": temp, "rpm": rpm})
        except ValueError:
            pass

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)


# ── Confirm Modal ────────────────────────────────────────────────────────────

class ConfirmModal(ModalScreen):
    """Confirmation dialog for delete operations."""

    BINDINGS = [Binding("escape", "dismiss", _t("cancel"))]

    CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-container {
        width: 52;
        height: auto;
        background: $surface;
        border: thick $error;
        padding: 1 2;
    }
    #confirm-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        color: $error;
    }
    #confirm-msg {
        text-align: center;
        margin-bottom: 1;
    }
    #confirm-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    #btn-confirm-delete {
        margin-right: 2;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="confirm-container"):
            yield Label(_t("confirm_title"), id="confirm-title")
            yield Label(self._message, id="confirm-msg")
            with Horizontal(id="confirm-buttons"):
                yield Button(_t("confirm_delete_btn"), variant="error", id="btn-confirm-delete")
                yield Button(_t("cancel"), variant="default", id="btn-confirm-cancel")

    @on(Button.Pressed, "#btn-confirm-delete")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-confirm-cancel")
    def cancel(self) -> None:
        self.dismiss(False)


# ── Main Application ─────────────────────────────────────────────────────────

class FanTUI(App):

    TITLE = "HP Fan Control"
    SUB_TITLE = "Victus 16 — Ryzen 7 7840HS + RTX 4050"

    BINDINGS = [
        Binding("q", "quit", _t("quit")),
        Binding("r", "refresh", _t("refresh")),
        Binding("c", "copy_status", _t("copy")),
        Binding("1", "set_mode_max", _t("mode_max")),
        Binding("2", "set_mode_auto", _t("mode_auto")),
        Binding("3", "set_mode_manual", _t("mode_manual")),
        Binding("n", "add_level", _t("add")),
        Binding("d", "delete_level", _t("delete")),
    ]

    CSS = """
    Screen {
        background: $background;
    }

    /* ── Top bar ── */
    #top-bar {
        height: 3;
        align: left middle;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary-darken-2;
    }
    .mode-btn {
        margin-right: 1;
        min-width: 12;
    }
    .mode-btn.active {
        background: $primary;
        color: $background;
    }
    #service-status {
        margin-left: 3;
        content-align: left middle;
    }
    #service-btns {
        margin-left: 2;
        align: left middle;
    }
    .svc-btn {
        margin-right: 1;
        min-width: 10;
        height: 1;
    }

    /* ── Middle panel ── */
    #middle {
        height: 1fr;
    }

    /* ── Left panel: temperatures ── */
    #left-panel {
        width: 32;
        border-right: solid $primary-darken-2;
        padding: 1;
    }
    .panel-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    .sensor-row {
        height: 1;
        margin-bottom: 1;
    }
    .sensor-label {
        width: 10;
    }
    .sensor-value {
        text-style: bold;
    }
    .temp-low    { color: $success; }
    .temp-mid    { color: $warning; }
    .temp-high   { color: $error; }
    .separator {
        height: 1;
        margin: 1 0;
        color: $primary-darken-2;
    }

    /* ── Right panel: fan curve ── */
    #right-panel {
        width: 1fr;
        padding: 1;
    }
    #curve-table {
        height: 1fr;
    }

    /* ── Log panel ── */
    #log-panel {
        height: 10;
        border-top: solid $primary-darken-2;
        padding: 0 1;
    }
    #log-title {
        height: 1;
        text-style: bold;
        color: $primary;
    }
    #log-output {
        height: 1fr;
    }
    """

    # Reactive state
    cpu_temp: reactive[float] = reactive(0.0)
    igpu_temp: reactive[float] = reactive(0.0)
    dgpu_temp: reactive[float] = reactive(0.0)
    fan1_rpm: reactive[int] = reactive(0)
    fan2_rpm: reactive[int] = reactive(0)
    service_status: reactive[str] = reactive("unknown")
    fan_mode: reactive[str] = reactive("auto")
    active_level: reactive[int] = reactive(-1)

    def __init__(self):
        super().__init__()
        self._config = load_config()
        self._cpu_path = find_temp_path("k10temp") or find_temp_path("acpitz")
        self._igpu_path = find_temp_path("amdgpu")
        self._log_proc: subprocess.Popen | None = None

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        for cmd in super().get_system_commands(screen):
            if cmd.title != "Screenshot":
                yield cmd

    def compose(self) -> ComposeResult:
        yield Header()

        # ── Top bar: mode + service ──
        with Horizontal(id="top-bar"):
            yield Button(_t("btn_max"), id="btn-max", classes="mode-btn")
            yield Button(_t("btn_auto"), id="btn-auto", classes="mode-btn")
            yield Button(_t("btn_manual"), id="btn-manual", classes="mode-btn")
            yield Static("", id="service-status")
            with Horizontal(id="service-btns"):
                yield Button(_t("svc_start"), id="btn-start", classes="svc-btn", variant="success")
                yield Button(_t("svc_stop"), id="btn-stop", classes="svc-btn", variant="error")
                yield Button(_t("svc_restart"), id="btn-restart", classes="svc-btn", variant="warning")

        # ── Middle: left + right ──
        with Horizontal(id="middle"):
            # Left: sensors
            with Vertical(id="left-panel"):
                yield Label(_t("panel_temps"), classes="panel-title")
                with Horizontal(classes="sensor-row"):
                    yield Label("CPU:", classes="sensor-label")
                    yield Label("--.-°C", id="val-cpu", classes="sensor-value")
                with Horizontal(classes="sensor-row"):
                    yield Label("iGPU:", classes="sensor-label")
                    yield Label("--.-°C", id="val-igpu", classes="sensor-value")
                with Horizontal(classes="sensor-row"):
                    yield Label("dGPU:", classes="sensor-label")
                    yield Label("--.-°C", id="val-dgpu", classes="sensor-value")
                yield Label("─" * 20, classes="separator")
                yield Label(_t("panel_fans"), classes="panel-title")
                with Horizontal(classes="sensor-row"):
                    yield Label("Fan 1:", classes="sensor-label")
                    yield Label("---- RPM", id="val-fan1", classes="sensor-value")
                with Horizontal(classes="sensor-row"):
                    yield Label("Fan 2:", classes="sensor-label")
                    yield Label("---- RPM", id="val-fan2", classes="sensor-value")

            # Right: fan curve table
            with Vertical(id="right-panel"):
                yield Label(_t("panel_curve"), classes="panel-title")
                yield DataTable(id="curve-table", cursor_type="row")

        # ── Bottom: log ──
        with Vertical(id="log-panel"):
            yield Label(_t("panel_log"), id="log-title")
            yield Log(id="log-output", highlight=True, max_lines=200)

        yield Footer()

    def on_mount(self) -> None:
        self._build_curve_table()
        self._apply_mode_buttons()
        self._start_log_stream()
        self.set_interval(POLL_SECONDS, self._poll)
        self._poll()

    # ── Table ────────────────────────────────────────────────────────────────

    def _build_curve_table(self) -> None:
        table = self.query_one("#curve-table", DataTable)
        table.clear(columns=True)
        table.add_columns("  ", _t("col_threshold"), _t("col_rpm"), _t("col_status"))
        self._refresh_curve_rows()

    def _refresh_curve_rows(self) -> None:
        table = self.query_one("#curve-table", DataTable)
        table.clear()
        curve = self._config.get("curve", DEFAULT_CURVE)
        for i, entry in enumerate(curve):
            active = (i == self.active_level)
            indicator = "●" if active else "○"
            status = _t("active_marker") if active else ""
            table.add_row(indicator, str(entry["temp"]), str(entry["rpm"]), status, key=str(i))

    # ── Polling ──────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        # Temperatures
        if self._cpu_path:
            self.cpu_temp = read_temp(self._cpu_path)
        if self._igpu_path:
            self.igpu_temp = read_temp(self._igpu_path)
        nvidia = read_nvidia_temp()
        self.dgpu_temp = nvidia if nvidia is not None else 0.0

        # Fan RPM
        f1, f2 = read_fan_rpms()
        self.fan1_rpm = f1
        self.fan2_rpm = f2

        # Service status
        self.service_status = get_service_status()

        # Active level
        temp = max(self.cpu_temp, self.igpu_temp, self.dgpu_temp)
        curve = self._config.get("curve", DEFAULT_CURVE)
        self.active_level = get_active_level(temp, curve)

        # Update UI
        self._update_sensor_labels()
        self._update_service_label()
        self._refresh_curve_rows()

    def _temp_class(self, t: float) -> str:
        if t >= 80:
            return "temp-high"
        if t >= 65:
            return "temp-mid"
        return "temp-low"

    def _update_sensor_labels(self) -> None:
        cpu_lbl = self.query_one("#val-cpu", Label)
        cpu_lbl.update(f"{self.cpu_temp:.1f}°C")
        cpu_lbl.set_classes(f"sensor-value {self._temp_class(self.cpu_temp)}")

        igpu_lbl = self.query_one("#val-igpu", Label)
        igpu_lbl.update(f"{self.igpu_temp:.1f}°C")
        igpu_lbl.set_classes(f"sensor-value {self._temp_class(self.igpu_temp)}")

        dgpu_lbl = self.query_one("#val-dgpu", Label)
        dgpu_lbl.update(f"{self.dgpu_temp:.1f}°C")
        dgpu_lbl.set_classes(f"sensor-value {self._temp_class(self.dgpu_temp)}")

        self.query_one("#val-fan1", Label).update(f"{self.fan1_rpm} RPM")
        self.query_one("#val-fan2", Label).update(f"{self.fan2_rpm} RPM")

    def _update_service_label(self) -> None:
        icon = "●" if self.service_status == "active" else "○"
        color = "green" if self.service_status == "active" else "red"
        self.query_one("#service-status", Static).update(
            f"[{color}]{icon}[/{color}] {_t('service_label')}: [{color}]{self.service_status}[/{color}]"
        )

    # ── Mode buttons ──────────────────────────────────────────────────────────

    def _apply_mode_buttons(self) -> None:
        mode = self._config.get("mode", "auto")
        self.fan_mode = mode
        for btn_id, btn_mode in [("btn-max", "max"), ("btn-auto", "auto"), ("btn-manual", "manual")]:
            btn = self.query_one(f"#{btn_id}", Button)
            if btn_mode == mode:
                btn.add_class("active")
            else:
                btn.remove_class("active")

    def _set_mode(self, mode: str) -> None:
        self._config["mode"] = mode
        save_config(self._config)
        reload_daemon()
        self._apply_mode_buttons()
        log_widget = self.query_one("#log-output", Log)
        log_widget.write_line(_t("mode_changed", mode=mode.upper()))

    def action_set_mode_max(self) -> None:
        self._set_mode("max")

    def action_set_mode_auto(self) -> None:
        self._set_mode("auto")

    def action_set_mode_manual(self) -> None:
        self._set_mode("manual")

    # ── Button events ─────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-max")
    def on_max(self) -> None:
        self._set_mode("max")

    @on(Button.Pressed, "#btn-auto")
    def on_auto(self) -> None:
        self._set_mode("auto")

    @on(Button.Pressed, "#btn-manual")
    def on_manual(self) -> None:
        self._set_mode("manual")

    @on(Button.Pressed, "#btn-start")
    def on_start(self) -> None:
        subprocess.run(["systemctl", "start", SERVICE_NAME])
        self.service_status = get_service_status()

    @on(Button.Pressed, "#btn-stop")
    def on_stop(self) -> None:
        subprocess.run(["systemctl", "stop", SERVICE_NAME])
        self.service_status = get_service_status()

    @on(Button.Pressed, "#btn-restart")
    def on_restart(self) -> None:
        subprocess.run(["systemctl", "restart", SERVICE_NAME])
        self.service_status = get_service_status()

    # ── Table row selection / editing ────────────────────────────────────────

    @on(DataTable.RowSelected, "#curve-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._config.get("mode") != "manual":
            log_widget = self.query_one("#log-output", Log)
            log_widget.write_line(_t("edit_only_manual"))
            return
        index = int(event.row_key.value or 0)
        curve = self._config.get("curve", DEFAULT_CURVE)
        entry = curve[index]
        self.app.push_screen(
            EditCurveModal(index, entry["temp"], entry["rpm"]),
            callback=lambda result: self._on_edit_result(index, result),
        )

    def _on_edit_result(self, index: int, result) -> None:
        if result is None:
            return
        curve = self._config.get("curve", DEFAULT_CURVE)
        curve[index] = result
        # Sort table by descending temperature
        curve.sort(key=lambda e: e["temp"], reverse=True)
        self._config["curve"] = curve
        save_config(self._config)
        reload_daemon()
        self._refresh_curve_rows()
        log_widget = self.query_one("#log-output", Log)
        log_widget.write_line(
            _t("level_updated", temp=result['temp'], rpm=result['rpm'])
        )

    # ── Add / delete level ────────────────────────────────────────────────────

    def action_add_level(self) -> None:
        """Adds a new fan curve level in MANUAL mode."""
        if self._config.get("mode") != "manual":
            self.query_one("#log-output", Log).write_line(
                _t("add_only_manual")
            )
            return
        curve = self._config.get("curve", DEFAULT_CURVE)
        # Empty modal — index=-1 means "new entry"
        self.app.push_screen(
            EditCurveModal(-1, 0, 1450),
            callback=self._on_add_result,
        )

    def _on_add_result(self, result) -> None:
        if result is None:
            return
        curve = self._config.get("curve", DEFAULT_CURVE)
        curve.append(result)
        curve.sort(key=lambda e: e["temp"], reverse=True)
        self._config["curve"] = curve
        save_config(self._config)
        reload_daemon()
        self._build_curve_table()
        self.query_one("#log-output", Log).write_line(
            _t("level_added", temp=result['temp'], rpm=result['rpm'])
        )

    def action_delete_level(self) -> None:
        """Deletes the selected fan curve level in MANUAL mode (min 2 levels enforced)."""
        if self._config.get("mode") != "manual":
            self.query_one("#log-output", Log).write_line(
                _t("del_only_manual")
            )
            return
        curve = self._config.get("curve", DEFAULT_CURVE)
        if len(curve) <= 2:
            self.query_one("#log-output", Log).write_line(
                _t("min_levels")
            )
            return
        table = self.query_one("#curve-table", DataTable)
        row_key = table.cursor_row
        # DataTable cursor_row returns a numeric index
        try:
            index = int(row_key)
        except (TypeError, ValueError):
            index = 0
        entry = curve[index]
        msg = _t("del_confirm_msg", temp=entry['temp'], rpm=entry['rpm'])
        self.app.push_screen(
            ConfirmModal(msg),
            callback=lambda confirmed: self._on_delete_result(confirmed, index),
        )

    def _on_delete_result(self, confirmed: bool | None, index: int) -> None:
        if not confirmed:
            return
        curve = self._config.get("curve", DEFAULT_CURVE)
        removed = curve.pop(index)
        self._config["curve"] = curve
        save_config(self._config)
        reload_daemon()
        self._build_curve_table()
        self.query_one("#log-output", Log).write_line(
            _t("level_deleted", temp=removed['temp'], rpm=removed['rpm'])
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._config = load_config()
        self._apply_mode_buttons()
        self._build_curve_table()
        self._poll()

    def action_copy_status(self) -> None:
        """Copies current status as plain text to clipboard."""
        from datetime import datetime
        mode = self._config.get("mode", "auto").upper()
        curve = self._config.get("curve", DEFAULT_CURVE)
        active = self.active_level

        lines = [
            f"HP Fan Control — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            _t("copy_mode_svc", mode=mode, status=self.service_status),
            "",
            _t("panel_temps"),
            f"  CPU:   {self.cpu_temp:.1f}°C",
            f"  iGPU:  {self.igpu_temp:.1f}°C",
            f"  dGPU:  {self.dgpu_temp:.1f}°C",
            "",
            _t("panel_fans"),
            f"  Fan 1: {self.fan1_rpm} RPM",
            f"  Fan 2: {self.fan2_rpm} RPM",
            "",
            _t("copy_curve_title"),
        ]
        for i, entry in enumerate(curve):
            marker = ">" if i == active else " "
            lines.append(f"  {marker} {entry['temp']:>3}°C → {entry['rpm']} RPM")

        text = "\n".join(lines)
        self.copy_to_clipboard(text)
        self.query_one("#log-output", Log).write_line(
            _t("copied")
        )

    # ── Log stream ───────────────────────────────────────────────────────────

    def _start_log_stream(self) -> None:
        self._stream_logs()

    @work(thread=True)
    def _stream_logs(self) -> None:
        try:
            proc = subprocess.Popen(
                ["journalctl", "-u", SERVICE_NAME, "-f", "-n", "30", "--no-pager"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._log_proc = proc
            for line in (proc.stdout or []):
                line = line.rstrip()
                if line:
                    self.call_from_thread(self._append_log, line)
        except Exception as e:
            self.call_from_thread(self._append_log, _t("log_error", e=str(e)))

    def _append_log(self, line: str) -> None:
        self.query_one("#log-output", Log).write_line(line)

    def on_unmount(self) -> None:
        if self._log_proc:
            self._log_proc.terminate()


if __name__ == "__main__":
    FanTUI().run()
