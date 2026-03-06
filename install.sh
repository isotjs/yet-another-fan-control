#!/usr/bin/env bash
# install.sh — HP Fan Curve installer
# Installs daemon, config, and systemd service for HP Victus 16

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SRC_DAEMON="${SCRIPT_DIR}/src/hp-fan-curve.py"
SRC_SERVICE="${SCRIPT_DIR}/config/hp-fan-curve.service"
SRC_CONF="${SCRIPT_DIR}/config/fan-curve.conf"
SRC_TUI="${SCRIPT_DIR}/src/hp-fan-tui.py"
SRC_TRANSLATIONS="${SCRIPT_DIR}/src/translations.py"
SRC_ICON="${SCRIPT_DIR}/config/icon.png"
SRC_DESKTOP="${SCRIPT_DIR}/config/hp-fan-curve.desktop"

DST_DAEMON="/usr/local/bin/hp-fan-curve"
DST_SERVICE="/etc/systemd/system/hp-fan-curve.service"
DST_CONF_DIR="/etc/hp-fan-curve"
DST_CONF="${DST_CONF_DIR}/fan-curve.conf"
OPT_DIR="/opt/hp-fan-curve"
DST_TUI_PY="${OPT_DIR}/hp-fan-tui.py"
DST_TRANSLATIONS="${OPT_DIR}/translations.py"
DST_ICON="${OPT_DIR}/icon.png"
DST_TUI_BIN="/usr/local/bin/hp-fan-tui"
DST_DESKTOP="/usr/share/applications/hp-fan-curve.desktop"

SERVICE_NAME="hp-fan-curve"

# ── Preflight checks ──────────────────────────────────────────────────────────

echo ""
echo "${BLD}HP Fan Curve — Installer${RST}"
echo "──────────────────────────────────────"
echo ""

# Root
[[ "${EUID}" -eq 0 ]] || die "This script must be run as root (sudo $0)"

# Source files present
[[ -f "${SRC_DAEMON}" ]]       || die "Missing source file: ${SRC_DAEMON}"
[[ -f "${SRC_SERVICE}" ]]      || die "Missing source file: ${SRC_SERVICE}"
[[ -f "${SRC_CONF}" ]]         || die "Missing source file: ${SRC_CONF}"
[[ -f "${SRC_TUI}" ]]          || die "Missing source file: ${SRC_TUI}"
[[ -f "${SRC_TRANSLATIONS}" ]] || die "Missing source file: ${SRC_TRANSLATIONS}"

# python3
command -v python3 &>/dev/null || die "python3 not found. Please install Python 3."
ok "python3 found: $(python3 --version)"

# systemctl
command -v systemctl &>/dev/null || die "systemctl not found. A systemd-based system is required."
ok "systemctl found"

# nvidia-smi (optional)
if command -v nvidia-smi &>/dev/null; then
    ok "nvidia-smi found — dGPU temperature monitoring enabled"
else
    warn "nvidia-smi not found — dGPU temperature monitoring will be disabled"
fi

# hp-wmi module
if [[ -d /sys/devices/platform/hp-wmi ]]; then
    ok "hp-wmi sysfs path found"
else
    warn "hp-wmi sysfs path not found at /sys/devices/platform/hp-wmi"
    warn "The daemon may not work correctly on this machine."
    warn "This project is tested only on HP Victus 16 (Ryzen 7 7840HS + RTX 4050)."
    echo ""
    read -rp "${YLW}Continue anyway? [y/N]${RST} " _ans
    [[ "${_ans,,}" == "y" ]] || { info "Aborted."; exit 0; }
fi

echo ""

# ── python-textual ─────────────────────────────────────────────────────────────

if ! python3 -c "import textual" &>/dev/null; then
    warn "python-textual is not installed. It is required for the TUI (hp-fan-tui.py)."
    read -rp "${YLW}Install python-textual now via pacman? [y/N]${RST} " _ans
    if [[ "${_ans,,}" == "y" ]]; then
        pacman -S --noconfirm python-textual
        ok "python-textual installed"
    else
        warn "Skipping — TUI will not work without python-textual"
    fi
else
    ok "python-textual found"
fi

echo ""

# ── Install files ─────────────────────────────────────────────────────────────

info "Installing daemon → ${DST_DAEMON}"
cp "${SRC_DAEMON}" "${DST_DAEMON}"
chmod +x "${DST_DAEMON}"
ok "Daemon installed"

info "Installing systemd unit → ${DST_SERVICE}"
cp "${SRC_SERVICE}" "${DST_SERVICE}"
ok "Service unit installed"

info "Installing TUI → ${OPT_DIR}"
mkdir -p "${OPT_DIR}"
cp "${SRC_TUI}" "${DST_TUI_PY}"
cp "${SRC_TRANSLATIONS}" "${DST_TRANSLATIONS}"
ok "TUI files installed"

info "Installing icon → ${DST_ICON}"
cp "${SRC_ICON}" "${DST_ICON}"
ok "Icon installed"

info "Installing TUI wrapper → ${DST_TUI_BIN}"
cat > "${DST_TUI_BIN}" <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/hp-fan-curve/hp-fan-tui.py "$@"
EOF
chmod +x "${DST_TUI_BIN}"
ok "TUI wrapper installed"

mkdir -p "${DST_CONF_DIR}"

if [[ -f "${DST_CONF}" ]]; then
    warn "Config file already exists: ${DST_CONF}"
    read -rp "${YLW}Overwrite with default config? [y/N]${RST} " _ans
    if [[ "${_ans,,}" == "y" ]]; then
        cp "${SRC_CONF}" "${DST_CONF}"
        ok "Config overwritten"
    else
        info "Keeping existing config"
    fi
else
    info "Installing config → ${DST_CONF}"
    cp "${SRC_CONF}" "${DST_CONF}"
    ok "Config installed"
fi

echo ""

# ── KDE desktop entry ─────────────────────────────────────────────────────────

_REAL_USER="${SUDO_USER:-}"
_DESKTOP=""
if [[ -n "${_REAL_USER}" ]]; then
    _DESKTOP="$(sudo -u "${_REAL_USER}" \
        env XDG_RUNTIME_DIR="/run/user/$(id -u "${_REAL_USER}")" \
        printenv XDG_CURRENT_DESKTOP 2>/dev/null || true)"
fi

if [[ "${_DESKTOP,,}" == *"kde"* ]] || [[ "${_DESKTOP,,}" == *"plasma"* ]]; then
    info "KDE/Plasma detected — installing .desktop → ${DST_DESKTOP}"
    cp "${SRC_DESKTOP}" "${DST_DESKTOP}"
    command -v update-desktop-database &>/dev/null \
        && update-desktop-database /usr/share/applications
    ok ".desktop installed — app will appear in KDE application menu"
else
    info "KDE not detected (DESKTOP=${_DESKTOP:-unknown}) — skipping .desktop install"
    info "To install manually: cp ${SRC_DESKTOP} ${DST_DESKTOP}"
fi

echo ""

# ── Enable and start service ──────────────────────────────────────────────────

info "Reloading systemd daemon..."
systemctl daemon-reload

info "Enabling and starting ${SERVICE_NAME}..."
systemctl enable --now "${SERVICE_NAME}"

echo ""

# ── Verify ────────────────────────────────────────────────────────────────────

sleep 1
STATUS="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"

if [[ "${STATUS}" == "active" ]]; then
    ok "${BLD}Service is running.${RST}"
else
    warn "Service status: ${STATUS}"
    warn "Check logs with: journalctl -u ${SERVICE_NAME} -n 30"
fi

echo ""
echo "${BLD}Installation complete.${RST}"
echo ""
echo "  Daemon:   ${DST_DAEMON}"
echo "  TUI:      ${DST_TUI_BIN}  (files: ${OPT_DIR})"
echo "  Config:   ${DST_CONF}"
echo "  Service:  ${DST_SERVICE}"
[[ -f "${DST_DESKTOP}" ]] && echo "  Desktop:  ${DST_DESKTOP}"
echo ""
echo "  Launch TUI:   sudo hp-fan-tui"
echo "  Live logs:    journalctl -u ${SERVICE_NAME} -f"
echo "  Reload conf:  sudo systemctl kill -s HUP ${SERVICE_NAME}"
echo ""
