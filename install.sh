#!/usr/bin/env bash
#
# Zeiterfassung – Installer für Debian/Ubuntu.
#
# Lädt die aktuelle Version von GitHub, installiert sie, richtet eine
# venv ein und legt einen systemd-Dienst an, der den Server beim Booten
# startet und bei Absturz neu startet.
#
# Geführte Installation (fragt Pfad, Port usw. ab):
#   wget -qO install.sh https://raw.githubusercontent.com/ipod86/Zeiterfassung/main/install.sh
#   bash install.sh
#
# Unbeaufsichtigt (keine Rückfragen) – Defaults bzw. Env-Variablen nutzen:
#   NONINTERACTIVE=1 INSTALL_DIR=/opt/zeiterfassung PORT=5050 bash install.sh
#
set -euo pipefail

OWNER="ipod86"
REPO="Zeiterfassung"
BRANCH="${BRANCH:-main}"
ZIP_URL="https://github.com/${OWNER}/${REPO}/archive/refs/heads/${BRANCH}.zip"
SERVICE_NAME="zeiterfassung"

# Vorgaben (per Env überschreibbar, in der geführten Abfrage als Default genutzt)
INSTALL_DIR="${INSTALL_DIR:-/opt/zeiterfassung}"
PORT="${PORT:-5050}"
RUN_USER="${RUN_USER:-${SUDO_USER:-$(whoami)}}"
DO_AUTOSTART="${DO_AUTOSTART:-yes}"
DO_FIREWALL="${DO_FIREWALL:-yes}"
DO_START="${DO_START:-yes}"

# ---------------------------------------------------------------------------
# Geführte Abfrage (nur wenn ein Terminal verfügbar und nicht abgeschaltet)
# ---------------------------------------------------------------------------
INTERACTIVE=1
[ "${NONINTERACTIVE:-0}" = "1" ] && INTERACTIVE=0
[ -r /dev/tty ] || INTERACTIVE=0

ask() {  # $1 = Frage, $2 = Default -> gibt Antwort aus
  local prompt="$1" def="$2" ans=""
  read -r -p "    $prompt [$def]: " ans </dev/tty || ans=""
  echo "${ans:-$def}"
}
ask_yn() {  # $1 = Frage, $2 = Default (yes/no) -> Rückgabewert 0=ja 1=nein
  local prompt="$1" def="$2" hint ans=""
  case "$def" in [Yy]*) hint="J/n";; *) hint="j/N";; esac
  read -r -p "    $prompt [$hint]: " ans </dev/tty || ans=""
  ans="${ans:-$def}"
  case "$ans" in [JjYy]*) return 0;; *) return 1;; esac
}
valid_port() { case "$1" in ''|*[!0-9]*) return 1;; *) [ "$1" -ge 1 ] && [ "$1" -le 65535 ];; esac; }

echo "==> Zeiterfassung-Installation"

if [ "$INTERACTIVE" = "1" ]; then
  echo "    (Enter übernimmt jeweils den Vorschlag in eckigen Klammern)"
  echo ""
  INSTALL_DIR="$(ask "Installationspfad" "$INSTALL_DIR")"
  while true; do
    PORT="$(ask "Port" "$PORT")"
    valid_port "$PORT" && break
    echo "    ! Ungültiger Port (1–65535). Bitte erneut."
  done
  RUN_USER="$(ask "Dienst-Benutzer (läuft unter diesem Konto)" "$RUN_USER")"
  if ask_yn "Autostart beim Booten + Neustart bei Absturz einrichten?" "$DO_AUTOSTART"; then DO_AUTOSTART="yes"; else DO_AUTOSTART="no"; fi
  if ask_yn "Firewall-Port $PORT für Netzwerkzugriff öffnen (falls Firewall aktiv)?" "$DO_FIREWALL"; then DO_FIREWALL="yes"; else DO_FIREWALL="no"; fi
  if ask_yn "Server nach der Installation sofort starten?" "$DO_START"; then DO_START="yes"; else DO_START="no"; fi
  echo ""
else
  valid_port "$PORT" || { echo "Ungültiger Port: $PORT"; exit 1; }
fi

echo "    Ziel:      $INSTALL_DIR"
echo "    Nutzer:    $RUN_USER"
echo "    Port:      $PORT"
echo "    Autostart: $DO_AUTOSTART   Firewall: $DO_FIREWALL   Start: $DO_START"

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
# gewählten Port hinterlegen (run.py liest data/.port; bei Updates geschützt)
echo "$PORT" | $SUDO tee "$INSTALL_DIR/data/.port" >/dev/null
$SUDO chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"

# 4) venv + Abhängigkeiten
echo "==> Richte virtuelle Umgebung ein…"
sudo -u "$RUN_USER" python3 -m venv "$INSTALL_DIR/.venv"
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# 5) systemd-Dienst (Autostart + Neustart bei Absturz)
if [ "$DO_AUTOSTART" = "yes" ]; then
  echo "==> Lege systemd-Dienst '$SERVICE_NAME' an…"
  $SUDO tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<UNIT
[Unit]
Description=Zeiterfassung
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/supervisor.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "$SERVICE_NAME"
else
  echo "==> Autostart übersprungen (manueller Start: $INSTALL_DIR/.venv/bin/python supervisor.py)."
fi

# 6) Firewall-Port öffnen (best effort, nur wenn eine Firewall erkannt wird)
if [ "$DO_FIREWALL" = "yes" ]; then
  if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -qi active; then
    echo "==> Öffne Port $PORT in ufw…"
    $SUDO ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
  elif command -v firewall-cmd >/dev/null 2>&1 && $SUDO firewall-cmd --state >/dev/null 2>&1; then
    echo "==> Öffne Port $PORT in firewalld…"
    $SUDO firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    $SUDO firewall-cmd --reload >/dev/null 2>&1 || true
  else
    echo "==> Keine aktive Firewall erkannt – Port-Freigabe übersprungen."
  fi
fi

# 7) Starten
if [ "$DO_START" = "yes" ]; then
  if [ "$DO_AUTOSTART" = "yes" ]; then
    $SUDO systemctl restart "$SERVICE_NAME"
  else
    echo "==> Starte Server (Hintergrund)…"
    sudo -u "$RUN_USER" sh -c "cd '$INSTALL_DIR' && PORT='$PORT' nohup '.venv/bin/python' supervisor.py >/dev/null 2>&1 &"
  fi
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "==> Fertig!"
echo "    Lokal:       http://localhost:${PORT}"
[ -n "$IP" ] && echo "    Im Netzwerk: http://${IP}:${PORT}"
echo ""
if [ "$DO_AUTOSTART" = "yes" ]; then
  echo "    Status:   sudo systemctl status $SERVICE_NAME"
  echo "    Logs:     journalctl -u $SERVICE_NAME -f"
  echo "    Neustart: sudo systemctl restart $SERVICE_NAME"
fi
echo "    Vorhandene Daten: im Tool unter Einstellungen → Backup einspielen importieren."
