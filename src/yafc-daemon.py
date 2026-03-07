#!/usr/bin/env python3
"""
yafc-daemon — Automatic temperature-based fan control daemon
Optimized for HP Victus 16 (Ryzen 7 7840HS + RTX 4050).

Modes:
  max    — fixed 5800 RPM
  auto   — use built-in default curve
  gaming — use built-in aggressive gaming curve
  manual — use user curve from fan-curve.conf
"""

import glob
import json
import signal
import subprocess
import time
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("yafc")

CONF_PATH = Path("/etc/yafc/fan-curve.conf")
CONF_FALLBACK = Path(__file__).parent.parent / "config" / "fan-curve.conf"

RPM_MAX = 5800

# Default quiet curve — used in AUTO mode and as fallback
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

# Minimum cooldown required before stepping down a level (°C)
HYSTERESIS_C = 5
POLL_INTERVAL = 3
HWMON_BASE = "/sys/devices/platform/hp-wmi/hwmon"

# Runtime state — reloaded on SIGHUP
_config: dict = {}
_reload_flag: bool = False


def _handle_sighup(signum, frame):
    global _reload_flag
    log.info("SIGHUP received — config will be reloaded.")
    _reload_flag = True


def load_config() -> dict:
    """Reads fan-curve.conf. Returns defaults if not found."""
    for path in (CONF_PATH, CONF_FALLBACK):
        if path.exists():
            try:
                data = json.loads(path.read_text())
                log.info(f"Config loaded: {path} (mode: {data.get('mode', 'auto')})")
                return data
            except Exception as e:
                log.warning(f"Failed to read config ({path}): {e}")
    log.warning("Config not found, using default curve.")
    return {"mode": "auto", "curve": DEFAULT_CURVE}


def get_manual_curve(config: dict) -> list[dict]:
    curve = config.get("curve")
    if isinstance(curve, list) and curve:
        return curve
    return list(DEFAULT_CURVE)


def get_effective_curve(mode: str, config: dict) -> list[dict]:
    if mode == "manual":
        return get_manual_curve(config)
    if mode == "gaming":
        return list(GAMING_CURVE)
    return list(DEFAULT_CURVE)


def curve_to_fan_curve(curve: list[dict]) -> list[tuple[int, int, int]]:
    """Converts fan curve entries to (threshold, fan1_rpm, fan2_rpm) tuples."""
    return [(entry["temp"], entry["rpm"], entry["rpm"]) for entry in curve]


def find_hwmon_path() -> Path | None:
    matches = glob.glob(f"{HWMON_BASE}/hwmon*")
    return Path(matches[0]) if matches else None


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
    """Reads discrete GPU temperature via nvidia-smi. Returns None on error."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        return float(out.strip())
    except Exception:
        return None


def write_sysfs(path: Path, value: int) -> bool:
    try:
        path.write_text(str(value))
        return True
    except OSError as e:
        log.error(f"Write error {path}: {e}")
        return False


def set_manual_mode(hwmon: Path) -> bool:
    enable_path = hwmon / "pwm1_enable"
    if not enable_path.exists():
        log.error(f"pwm1_enable not found: {enable_path}")
        return False
    return write_sysfs(enable_path, 0)


def set_fan_speed(hwmon: Path, fan1_rpm: int, fan2_rpm: int) -> None:
    for fname, rpm in [("fan1_target", fan1_rpm), ("fan2_target", fan2_rpm)]:
        path = hwmon / fname
        if path.exists():
            write_sysfs(path, rpm)
        else:
            log.warning(f"{fname} not found, skipping.")


def get_target_level(temp: float, fan_curve: list) -> int:
    """Returns the fan_curve index for a given temperature (0 = highest level)."""
    for i, (threshold, _, _) in enumerate(fan_curve):
        if temp >= threshold:
            return i
    return len(fan_curve) - 1


def get_target_rpm_with_hysteresis(
    temp: float, current_level: int, fan_curve: list
) -> tuple[int, int, int]:
    """
    Target RPM and level with hysteresis applied.
    Stepping up (new_level < current_level): applied immediately.
    Stepping down (new_level > current_level): does not occur until temperature
      drops HYSTERESIS_C below the current threshold.

    Note: fan_curve is sorted in descending order — index 0 is the highest
    threshold/RPM, higher index means lower threshold.

    Returns: (fan1_rpm, fan2_rpm, new_level)
    """
    new_level = get_target_level(temp, fan_curve)

    if new_level < current_level:
        # Heating up — step fan level up, apply immediately
        pass
    elif new_level > current_level:
        # Cooling down — hysteresis check
        current_threshold = fan_curve[current_level][0]
        if temp >= current_threshold - HYSTERESIS_C:
            # Not cool enough yet, stay at current level
            new_level = current_level
    # else: same level, no change

    f1 = fan_curve[new_level][1]
    f2 = fan_curve[new_level][2]
    return f1, f2, new_level


def main():
    global _config, _reload_flag

    signal.signal(signal.SIGHUP, _handle_sighup)

    log.info("yafc daemon starting...")

    hwmon = find_hwmon_path()
    if not hwmon:
        log.error(f"hp-wmi hwmon not found: {HWMON_BASE}/hwmon*")
        sys.exit(1)
    log.info(f"hwmon path: {hwmon}")

    cpu_temp_path = find_temp_path("k10temp") or find_temp_path("acpitz")
    if not cpu_temp_path:
        log.error("CPU temperature sensor not found.")
        sys.exit(1)
    log.info(f"CPU sensor: {cpu_temp_path}")

    gpu_temp_path = find_temp_path("amdgpu")
    has_nvidia = read_nvidia_temp() is not None

    if gpu_temp_path:
        log.info(f"GPU sensor (iGPU/amdgpu): {gpu_temp_path}")
    if has_nvidia:
        log.info("GPU sensor (dGPU/nvidia-smi): active")
    if not gpu_temp_path and not has_nvidia:
        log.warning("GPU sensor not found, using CPU only.")

    if not set_manual_mode(hwmon):
        log.error("Failed to set manual mode.")
        sys.exit(1)
    log.info("Fan mode: Manual (pwm1_enable=0)")

    _config = load_config()
    current_level = -1

    log.info("Fan curve active. Starting loop...")

    while True:
        # Reload config on SIGHUP
        if _reload_flag:
            _reload_flag = False
            _config = load_config()
            current_level = -1  # Reset level, recalculate with new curve
            log.info("Config reloaded, level reset.")

        mode = _config.get("mode", "auto")
        curve = get_effective_curve(mode, _config)
        fan_curve = curve_to_fan_curve(curve)

        try:
            cpu_temp = read_temp(cpu_temp_path)
            igpu_temp = read_temp(gpu_temp_path) if gpu_temp_path else 0.0
            dgpu_temp = read_nvidia_temp() or 0.0
            gpu_temp = max(igpu_temp, dgpu_temp)
            temp = max(cpu_temp, gpu_temp)

            if cpu_temp >= gpu_temp:
                dominant = "CPU"
            elif dgpu_temp >= igpu_temp:
                dominant = "dGPU"
            else:
                dominant = "iGPU"

            if mode == "max":
                # MAX mode: fixed full power
                if current_level != 0:
                    log.info(
                        f"[MAX] CPU: {cpu_temp:.1f}°C | iGPU: {igpu_temp:.1f}°C"
                        f" | dGPU: {dgpu_temp:.1f}°C → Fan: {RPM_MAX} RPM"
                    )
                    set_fan_speed(hwmon, RPM_MAX, RPM_MAX)
                    current_level = 0

            else:
                # AUTO, GAMING, or MANUAL mode: follow the selected curve
                if current_level == -1:
                    current_level = get_target_level(temp, fan_curve)
                    f1, f2 = fan_curve[current_level][1], fan_curve[current_level][2]
                    log.info(
                        f"[{mode.upper()}][{dominant}] CPU: {cpu_temp:.1f}°C"
                        f" | iGPU: {igpu_temp:.1f}°C | dGPU: {dgpu_temp:.1f}°C"
                        f" → Level {current_level + 1}: Fan1: {f1} RPM | Fan2: {f2} RPM"
                    )
                    set_fan_speed(hwmon, f1, f2)
                else:
                    f1, f2, new_level = get_target_rpm_with_hysteresis(
                        temp, current_level, fan_curve
                    )
                    if new_level != current_level:
                        direction = "↑" if new_level < current_level else "↓"
                        log.info(
                            f"[{mode.upper()}][{dominant}] CPU: {cpu_temp:.1f}°C"
                            f" | iGPU: {igpu_temp:.1f}°C | dGPU: {dgpu_temp:.1f}°C"
                            f" → Level {new_level + 1} {direction}:"
                            f" Fan1: {f1} RPM | Fan2: {f2} RPM"
                        )
                        set_fan_speed(hwmon, f1, f2)
                        current_level = new_level

        except Exception as e:
            log.warning(f"Loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
