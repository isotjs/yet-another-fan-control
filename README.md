# Yet Another Fan Control (YAFC)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)]()

Yet Another Fan Control (YAFC) is a systemd daemon and Textual TUI for automatic fan control on the HP Victus 16 (Ryzen 7 7840HS + RTX 4050).

---

## The Problem

On the HP Victus 16, the `hp-wmi` kernel driver resets fan settings on every boot, requiring manual intervention to restore a sensible fan curve.

## The Solution

A lightweight Python daemon running as a systemd service. It monitors CPU, iGPU, and dGPU temperatures simultaneously and adjusts fan speeds automatically according to a configurable curve — with no manual intervention after boot.

---

## Disclaimer

This project was developed and tested **only on a single machine**: HP Victus 16 with Ryzen 7 7840HS + RTX 4050, running CachyOS.

**Use at your own risk.** This software directly writes to kernel sysfs interfaces to control fan hardware. While it has caused no issues on the author's machine, it may behave differently on other hardware configurations, kernel versions, or Linux distributions.

The author provides **no warranty of any kind**. By using this software you accept full responsibility for any consequences, including but not limited to: hardware damage, thermal issues, system instability, or data loss.

Before using on your own machine:

- Verify that your system has the `hp-wmi` kernel module
- Check that your hwmon sysfs paths match what this daemon expects
- Monitor temperatures closely during initial use
- Keep stock fan control available as a fallback

**Trademark Notice:** HP and HP Victus are trademarks of HP Inc. This project is not affiliated with, endorsed by, or sponsored by HP Inc. in any way.

---

## Features

- Monitors CPU (`k10temp`), iGPU (`amdgpu`), and dGPU (`nvidia-smi`) temperatures simultaneously
- Determines fan level based on the dominant (hottest) sensor
- Hysteresis: step-down is delayed by 5°C to prevent rapid fan oscillation
- **MAX / AUTO / GAMING / MANUAL** mode support
- Configurable via `fan-curve.conf`; daemon reloads on SIGHUP — no restart required
- Textual TUI with live sensor monitoring, mode switching, fan curve editing, and log viewer
- TUI reads the level the daemon actually applied from `/run/yafc/state.json` (hysteresis included),
  and falls back to a computed target when the daemon is not running
- English and Turkish UI (`--lang en|tr`)
- KDE/Plasma `.desktop` entry installed automatically when KDE is detected

---

## TUI Preview

```
┌─ YAFC ──────────────────────── Victus 16 · Ryzen 7 7840HS + RTX 4050 ── 19:42:07 ─┐
│  MAX  [AUTO]  MANUAL  GAMING                        [Start] [Stop] [Restart]        │
├────────────────────────────────┬───────────────────────────────────────────────────┤
│ THERMALS                       │ FAN CURVE · AUTO (built-in)                        │
│                                │            Temp    RPM                             │
│  ● CPU    46.0°C  ███▍░░░░░░░  │  ●   90°C   5800  ████████████████████████████     │
│  ● iGPU   42.0°C  ███░░░░░░░░  │  ●   84°C   5000  ████████████████████████         │
│  ● dGPU   42.0°C  ███░░░░░░░░  │  ●   78°C   4200  ████████████████████             │
│  ────────────────────────────  │  ●   72°C   3600  █████████████████                │
│  ● Fan 1  1650 RPM ██▍░░░░░░   │  ▶   65°C   3000  ██████████████   ← active level  │
│  ● Fan 2  1650 RPM ██▍░░░░░░   │  ●   58°C   2500  ████████████                     │
│                                │  ●    0°C   1450  ██████                           │
│                                │                        read-only — press 3 to edit  │
├────────────────────────────────┴───────────────────────────────────────────────────┤
│ AUTO · CPU 46.0°C → L8 · 1650 RPM (target)                ● Service: active        │
│ q Quit  r Refresh  c Copy  l Log panel  n Add  d Delete  ? Help                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Requirements

**Hardware:**

- HP Victus 16 (or another HP laptop with the `hp-wmi` kernel module and sysfs fan control)

**Software:**

- Linux with systemd
- Python 3.10+
- `python-textual` (for the TUI)
- NVIDIA driver + `nvidia-smi` (optional — for dGPU temperature monitoring)

---

## Installation

### 1. Install dependencies

```bash
sudo pacman -S python-textual
```

The daemon (`yafc-daemon.py`) uses stdlib only — no additional dependencies required.

### 2. Run the installer

```bash
sudo bash install.sh
```

The installer will:

- Copy the daemon to `/usr/local/bin/yafc-daemon`
- Copy TUI files to `/opt/yafc/`
- Create the `yafc-tui` command at `/usr/local/bin/yafc-tui`
- Install config to `/etc/yafc/fan-curve.conf`
- Enable and start the systemd service
- Install a `.desktop` entry to `/usr/share/applications/` if KDE/Plasma is detected

### 3. Launch the TUI

```bash
sudo yafc-tui
```

> `sudo` is required — the TUI uses `systemctl` for service start/stop/restart.

To force a specific UI language:

```bash
sudo yafc-tui --lang en
sudo yafc-tui --lang tr
```

If `--lang` is not set, the language is determined by the `$LANG` environment variable (defaults to Turkish when `LANG` starts with `tr`, English otherwise).

---

## Configuration

Config file: `/etc/yafc/fan-curve.conf`

```json
{
  "mode": "auto",
  "curve": [
    { "temp": 90, "rpm": 5800 },
    { "temp": 0, "rpm": 1450 }
  ]
}
```

| Field   | Values                                          | Description                                                                |
| ------- | ----------------------------------------------- | -------------------------------------------------------------------------- |
| `mode`  | `"max"` \| `"auto"` \| `"gaming"` \| `"manual"` | Active fan control mode                                                    |
| `curve` | array of `{temp, rpm}` objects                  | Fan curve levels used in **MANUAL** mode, sorted descending by temperature |

The daemon reloads the config on SIGHUP — no restart required:

```bash
sudo systemctl kill -s HUP yafc
```

---

## Fan Curve

Default quiet curve (AUTO mode):

| Level | Threshold (°C) | Fan RPM |
| ----- | -------------- | ------- |
| 10    | ≥ 90           | 5800    |
| 9     | ≥ 84           | 5000    |
| 8     | ≥ 78           | 4200    |
| 7     | ≥ 72           | 3600    |
| 6     | ≥ 65           | 3000    |
| 5     | ≥ 58           | 2500    |
| 4     | ≥ 50           | 2000    |
| 3     | ≥ 42           | 1650    |
| 2     | ≥ 35           | 1450    |
| 1     | ≥ 0            | 1450    |

Thresholds and RPM values can be edited via `fan-curve.conf` or through the TUI in MANUAL mode.
These user-defined values are applied only in MANUAL mode.

---

## Modes

| Mode       | Behavior                                                             |
| ---------- | -------------------------------------------------------------------- |
| **MAX**    | Fixed maximum RPM (5800) regardless of temperature                   |
| **AUTO**   | Uses the built-in default curve                                      |
| **GAMING** | Uses the built-in aggressive gaming curve                            |
| **MANUAL** | Uses the user-defined curve from `fan-curve.conf` (editable via TUI) |

---

## TUI Key Bindings

| Key                 | Action                                                               |
| ------------------- | -------------------------------------------------------------------- |
| `1`                 | Switch to MAX mode                                                   |
| `2`                 | Switch to AUTO mode                                                  |
| `3`                 | Switch to MANUAL mode                                                |
| `4`                 | Switch to GAMING mode                                                |
| `r`                 | Refresh sensors and config                                           |
| `c`                 | Copy current status to clipboard                                     |
| `n`                 | Add a new fan curve level (MANUAL mode only)                         |
| `d`                 | Delete selected fan curve level (MANUAL mode only, minimum 2 levels) |
| `l`                 | Toggle the log panel                                                 |
| `?`                 | Show all key bindings                                                |
| `Enter` (table row) | Edit selected level (MANUAL mode only)                               |
| `q`                 | Quit                                                                 |

Mode switching is also available with the arrow keys on the mode tabs.
Curve editing and service control require root (`sudo yafc-tui`); without it the TUI runs
in read-only mode and says so in the status bar.

---

## Service Management

```bash
# Status
systemctl status yafc

# Live log
journalctl -u yafc -f

# Restart
sudo systemctl restart yafc

# Reload config without restart
sudo systemctl kill -s HUP yafc
```

---

## Hardware Compatibility

Tested on HP Victus 16 (Ryzen 7 7840HS + RTX 4050) running CachyOS.

Sensors are discovered dynamically by reading the hwmon `name` file — hwmon indices can change between reboots without issue.

| Sensor          | hwmon name                     | Method                             |
| --------------- | ------------------------------ | ---------------------------------- |
| CPU (Tctl)      | `k10temp` (fallback: `acpitz`) | sysfs `temp1_input`                |
| iGPU            | `amdgpu`                       | sysfs `temp1_input`                |
| dGPU (RTX 4050) | —                              | `nvidia-smi`                       |
| Fan control     | `hp` (hp-wmi)                  | sysfs `fan1_target`, `fan2_target` |

Reports and testing from other HP Victus / hp-wmi users are welcome.

---

## Contributing

Issues and pull requests are welcome at [github.com/isotjs/yet-another-fan-control](https://github.com/isotjs/yet-another-fan-control).

If you test this on a different HP model, please report your hwmon paths, kernel version, and whether it works — this helps broaden compatibility.

---

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0).
