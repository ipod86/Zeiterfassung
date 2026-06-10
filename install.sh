#!/usr/bin/env bash
#
# Zeiterfassung – Installer für Debian/Ubuntu.
#
# Lädt die aktuelle Version von GitHub, installiert sie, richtet eine
# venv ein und legt einen systemd-Dienst an, der den Server beim Booten
# startet und bei Absturz neu startet.
#
# Nutzung:
#   wget -qO install.sh https://raw.githubusercontent.com/ipod86/Zeiterfassung/main/install.sh
#   bash install.sh                 # installiert nach /opt/zeiterfassung
#   INSTALL_DIR=$HOME/zeit bash install.sh   # eigenes Zielverzeichnis
#
set -euo pipefail

OWNER="ipod86"
REPO="Zeiterfassung"
BRANCH="main"
ZIP_URL="https://github.com/${OWNER}/${REPO}/archive/refs/heads/${BRANCH}.zip"
INSTALL_DIR="${INSTALL_DIR:-/opt/zeiterfassung}"
SERVICE_NAME="zeiterfassung"
PORT="${PORT:-5050}"
RUN_USER="${SUDO_USER:-$(whoami)}"

echo "==> Zeiterfassung-Installation"
echo "    Ziel:   $INSTALL_DIR"
echo "    Nutzer: $RUN_USER"
echo "    Port:   $PORT"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

# 1) Pakete sicherstellen
echo "==> Pakete prüfen (python3, venv, unzip, wget)…"
if command -v apt-get >/dev/null 2>&1; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq python3 python3-venv python3-pip unzip wget curl
fi

# 2) Download + Entpacken in ein temporäres Verzeichnis
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "==> Lade $ZIP_URL …"
wget -qO "$TMP/app.zip" "$ZIP_URL"
echo "==> Entpacke…"
unzip -q "$TMP/app.zip" -d "$TMP"
SRC="$TMP/${REPO}-${BRANCH}"

# 3) Dateien ins Zielverzeichnis kopieren (data/ niemals überschreiben)
echo "==> Installiere nach $INSTALL_DIR …"
$SUDO mkdir -p "$INSTALL_DIR"
$SUDO cp -a "$SRC/." "$INSTALL_DIR/"
# nicht benötigte Entwicklungsdateien entfernen
$SUDO rm -rf "$INSTALL_DIR/.git" "$INSTALL_DIR/.github" "$INSTALL_DIR/.claude"
$SUDO mkdir -p "$INSTALL_DIR/data"
$SUDO chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"

# 4) venv + Abhängigkeiten
echo "==> Richte virtuelle Umgebung ein…"
sudo -u "$RUN_USER" python3 -m venv "$INSTALL_DIR/.venv"
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# 5) systemd-Dienst (Autostart + Neustart bei Absturz)
echo "==> Lege systemd-Dienst '$SERVICE_NAME' an…"
$SUDO tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<UNIT
[Unit]
Description=Zeiterfassung
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=PORT=${PORT}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/supervisor.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE_NAME"
$SUDO systemctl restart "$SERVICE_NAME"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "==> Fertig! Zeiterfassung läuft als Dienst '$SERVICE_NAME'."
echo "    Lokal:      http://localhost:${PORT}"
[ -n "$IP" ] && echo "    Im Netzwerk: http://${IP}:${PORT}"
echo ""
echo "    Status:   sudo systemctl status $SERVICE_NAME"
echo "    Logs:     journalctl -u $SERVICE_NAME -f"
echo "    Neustart: sudo systemctl restart $SERVICE_NAME"
