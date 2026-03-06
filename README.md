# HP Fan Curve

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)]()

Systemd daemon and Textual TUI for automatic fan control on the HP Victus 16 (Ryzen 7 7840HS + RTX 4050).

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
- **MAX / AUTO / MANUAL** mode support
- Configurable via `fan-curve.conf`; daemon reloads on SIGHUP — no restart required
- Textual TUI with live sensor monitoring, mode switching, fan curve editing, and log viewer
- English and Turkish UI (`--lang en|tr`)
- KDE/Plasma `.desktop` entry installed automatically when KDE is detected

---

## TUI Preview

```
┌─ HP Fan Control ─────────────────────────────────────────────┐
│  [1:MAX]  [2:AUTO ●]  [3:MANUAL]   ● Service: active         │
│                               [Start] [Stop] [Restart]       │
├───────────────────────┬──────────────────────────────────────┤
│  TEMPERATURES         │  FAN CURVE                           │
│  CPU:   74.1°C        │  ○  90°C → 5800 RPM                  │
│  iGPU:  61.0°C        │  ○  84°C → 4930 RPM                  │
│  dGPU:  66.0°C        │  ●  70°C → 3500 RPM  ← ACTIVE        │
│                       │  ○  55°C → 2320 RPM                  │
│  FANS                 │  ...                                 │
│  Fan 1: 3500 RPM      │                                      │
│  Fan 2: 3500 RPM      │                                      │
├───────────────────────┴──────────────────────────────────────┤
│  LOG  (journalctl -u hp-fan-curve)                           │
│  16:04:17 [AUTO][CPU] CPU: 74.1°C | iGPU: 61.0°C | ...       │
└──────────────────────────────────────────────────────────────┘
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

The daemon (`hp-fan-curve.py`) uses stdlib only — no additional dependencies required.

### 2. Run the installer

```bash
sudo bash install.sh
```

The installer will:
- Copy the daemon to `/usr/local/bin/hp-fan-curve`
- Copy TUI files to `/opt/hp-fan-curve/`
- Create the `hp-fan-tui` command at `/usr/local/bin/hp-fan-tui`
- Install config to `/etc/hp-fan-curve/fan-curve.conf`
- Enable and start the systemd service
- Install a `.desktop` entry to `/usr/share/applications/` if KDE/Plasma is detected

### 3. Launch the TUI

```bash
sudo hp-fan-tui
```

> `sudo` is required — the TUI uses `systemctl` for service start/stop/restart.

To force a specific UI language:

```bash
sudo hp-fan-tui --lang en
sudo hp-fan-tui --lang tr
```

If `--lang` is not set, the language is determined by the `$LANG` environment variable (defaults to Turkish when `LANG` starts with `tr`, English otherwise).

---

## Configuration

Config file: `/etc/hp-fan-curve/fan-curve.conf`

```json
{
  "mode": "auto",
  "curve": [
    {"temp": 90, "rpm": 5800},
    {"temp":  0, "rpm": 1450}
  ]
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `mode` | `"max"` \| `"auto"` \| `"manual"` | Active fan control mode |
| `curve` | array of `{temp, rpm}` objects | Fan curve levels, sorted descending by temperature |

The daemon reloads the config on SIGHUP — no restart required:

```bash
sudo systemctl kill -s HUP hp-fan-curve
```

---

## Fan Curve

Default curve:

| Level | Threshold (°C) | Fan RPM |
|-------|----------------|---------|
| 8 | ≥ 90 | 5800 |
| 7 | ≥ 84 | 4930 |
| 6 | ≥ 78 | 4060 |
| 5 | ≥ 70 | 3500 |
| 4 | ≥ 55 | 2320 |
| 3 | ≥ 45 | 1740 |
| 2 | ≥ 35 | 1450 |
| 1 | ≥  0 | 1450 |

Thresholds and RPM values can be edited via `fan-curve.conf` or through the TUI in MANUAL mode.

---

## Modes

| Mode | Behavior |
|------|----------|
| **MAX** | Fixed maximum RPM (5800) regardless of temperature |
| **AUTO** | Follows the `fan-curve.conf` curve automatically |
| **MANUAL** | Same as AUTO; fan curve is editable via the TUI |

---

## TUI Key Bindings

| Key | Action |
|-----|--------|
| `1` | Switch to MAX mode |
| `2` | Switch to AUTO mode |
| `3` | Switch to MANUAL mode |
| `r` | Refresh sensors and config |
| `c` | Copy current status to clipboard |
| `n` | Add a new fan curve level (MANUAL mode only) |
| `d` | Delete selected fan curve level (MANUAL mode only, minimum 2 levels) |
| `Enter` (table row) | Edit selected level (MANUAL mode only) |
| `q` | Quit |

---

## Service Management

```bash
# Status
systemctl status hp-fan-curve

# Live log
journalctl -u hp-fan-curve -f

# Restart
sudo systemctl restart hp-fan-curve

# Reload config without restart
sudo systemctl kill -s HUP hp-fan-curve
```

---

## Hardware Compatibility

Tested on HP Victus 16 (Ryzen 7 7840HS + RTX 4050) running CachyOS.

Sensors are discovered dynamically by reading the hwmon `name` file — hwmon indices can change between reboots without issue.

| Sensor | hwmon name | Method |
|--------|------------|--------|
| CPU (Tctl) | `k10temp` (fallback: `acpitz`) | sysfs `temp1_input` |
| iGPU | `amdgpu` | sysfs `temp1_input` |
| dGPU (RTX 4050) | — | `nvidia-smi` |
| Fan control | `hp` (hp-wmi) | sysfs `fan1_target`, `fan2_target` |

Reports and testing from other HP Victus / hp-wmi users are welcome.

---

## Contributing

Issues and pull requests are welcome at [github.com/isotjs/my-fan-control](https://github.com/isotjs/my-fan-control).

If you test this on a different HP model, please report your hwmon paths, kernel version, and whether it works — this helps broaden compatibility.

---

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0).
