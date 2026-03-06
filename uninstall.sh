#!/usr/bin/env bash
# uninstall.sh — HP Fan Curve uninstaller
# Removes daemon, systemd service, and optionally the config

set -e

# ── Colors ────────────────────────────────────────────────────────────────────

if command -v tput &>/dev/null && tput colors &>/dev/null && [[ $(tput colors) -ge 8 ]]; then
    RED=$(tput setaf 1)
    YLW=$(tput setaf 3)
    GRN=$(tput setaf 2)
    CYN=$(tput setaf 6)
    BLD=$(tput bold)
    RST=$(tput sgr0)
else
    RED="" YLW="" GRN="" CYN="" BLD="" RST=""
fi

info()    { echo "${CYN}${BLD}[INFO]${RST}  $*"; }
ok()      { echo "${GRN}${BLD}[ OK ]${RST}  $*"; }
warn()    { echo "${YLW}${BLD}[WARN]${RST}  $*"; }
error()   { echo "${RED}${BLD}[ERR ]${RST}  $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Paths ─────────────────────────────────────────────────────────────────────

DST_DAEMON="/usr/local/bin/hp-fan-curve"
DST_TUI_BIN="/usr/local/bin/hp-fan-tui"
DST_SERVICE="/etc/systemd/system/hp-fan-curve.service"
DST_CONF_DIR="/etc/hp-fan-curve"
DST_CONF="${DST_CONF_DIR}/fan-curve.conf"
OPT_DIR="/opt/hp-fan-curve"
DST_DESKTOP="/usr/share/applications/hp-fan-curve.desktop"

SERVICE_NAME="hp-fan-curve"

# ── Preflight ─────────────────────────────────────────────────────────────────

echo ""
echo "${BLD}HP Fan Curve — Uninstaller${RST}"
echo "──────────────────────────────────────"
echo ""

[[ "${EUID}" -eq 0 ]] || die "This script must be run as root (sudo $0)"

# ── Stop and disable service ──────────────────────────────────────────────────

if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    info "Stopping ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}"
    ok "Service stopped"
else
    info "Service is not running, skipping stop"
fi

if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    info "Disabling ${SERVICE_NAME}..."
    systemctl disable "${SERVICE_NAME}"
    ok "Service disabled"
else
    info "Service is not enabled, skipping disable"
fi

echo ""

# ── Remove files ──────────────────────────────────────────────────────────────

if [[ -f "${DST_DAEMON}" ]]; then
    rm -f "${DST_DAEMON}"
    ok "Removed ${DST_DAEMON}"
else
    warn "Daemon not found at ${DST_DAEMON}, skipping"
fi

if [[ -f "${DST_TUI_BIN}" ]]; then
    rm -f "${DST_TUI_BIN}"
    ok "Removed ${DST_TUI_BIN}"
else
    warn "TUI wrapper not found at ${DST_TUI_BIN}, skipping"
fi

if [[ -d "${OPT_DIR}" ]]; then
    rm -rf "${OPT_DIR}"
    ok "Removed ${OPT_DIR}"
else
    warn "TUI directory not found at ${OPT_DIR}, skipping"
fi

if [[ -f "${DST_DESKTOP}" ]]; then
    rm -f "${DST_DESKTOP}"
    command -v update-desktop-database &>/dev/null \
        && update-desktop-database /usr/share/applications
    ok "Removed ${DST_DESKTOP}"
else
    info ".desktop not found at ${DST_DESKTOP}, skipping"
fi

if [[ -f "${DST_SERVICE}" ]]; then
    rm -f "${DST_SERVICE}"
    ok "Removed ${DST_SERVICE}"
else
    warn "Service unit not found at ${DST_SERVICE}, skipping"
fi

# ── Config ────────────────────────────────────────────────────────────────────

if [[ -f "${DST_CONF}" ]]; then
    echo ""
    read -rp "${YLW}Remove config file (${DST_CONF})? [y/N]${RST} " _ans
    if [[ "${_ans,,}" == "y" ]]; then
        rm -f "${DST_CONF}"
        ok "Removed ${DST_CONF}"
        # Remove dir if empty
        if [[ -d "${DST_CONF_DIR}" ]] && [[ -z "$(ls -A "${DST_CONF_DIR}")" ]]; then
            rmdir "${DST_CONF_DIR}"
            ok "Removed empty directory ${DST_CONF_DIR}"
        fi
    else
        info "Config file kept at ${DST_CONF}"
    fi
else
    info "Config file not found at ${DST_CONF}, skipping"
fi

echo ""

# ── Reload systemd ────────────────────────────────────────────────────────────

info "Reloading systemd daemon..."
systemctl daemon-reload
ok "systemd reloaded"

echo ""
echo "${BLD}Uninstallation complete.${RST}"
echo ""
