#!/usr/bin/env bash
# Install the YoutubeBot Manager for the desktop owner: release binary in ~/.local/bin,
# icon and an application-menu entry. Run as the owner, without sudo.
#
#   bash desktop/scripts/install.sh [--root /path/to/project]
#
# --root is the project folder that holds the private `.local/` records; by default the
# repository that contains this script.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run as the desktop owner, without sudo." >&2
  exit 1
fi

DESKTOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(dirname "${DESKTOP}")"
if [[ "${1:-}" == "--root" && -n "${2:-}" ]]; then
  ROOT="$(cd "$2" && pwd)"
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--root /path/to/project]" >&2
  exit 2
fi
if [[ ! -d "${ROOT}/.local" ]]; then
  echo "${ROOT} has no .local/ folder; pass the project root with --root." >&2
  exit 1
fi

BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor/scalable/apps"
BINARY="${BIN_DIR}/ytbot-manager"

(cd "${DESKTOP}" && cargo build --release -p manager-app)

mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICON_DIR}"
# Replace atomically so a running instance keeps its old file.
install -m 0755 "${DESKTOP}/target/release/manager-app" "${BINARY}.new"
mv -f "${BINARY}.new" "${BINARY}"
install -m 0644 "${DESKTOP}/apps/manager/icon.svg" "${ICON_DIR}/ytbot-manager.svg"

cat > "${APPS_DIR}/ytbot-manager.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=YoutubeBot Manager
Comment=Métricas do mês, canais, Shorts, X, comercial e sessões (somente leitura)
Exec=env YTBOT_ROOT="${ROOT}" "${BINARY}"
Icon=ytbot-manager
Terminal=false
Categories=System;Monitor;
Keywords=YouTube;YoutubeBot;Shorts;WhatsApp;Mercado Livre;
StartupNotify=true
StartupWMClass=ytbot-manager
EOF

update-desktop-database "${APPS_DIR}" 2>/dev/null || true
gtk-update-icon-cache -q "${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor" 2>/dev/null || true

echo "[ok] ${BINARY}"
echo "[ok] ${APPS_DIR}/ytbot-manager.desktop (records: ${ROOT}/.local)"
