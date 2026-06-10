# Zeiterfassung

Lokale, netzwerkfähige Zeiterfassung mit Projekt-/Kundenverwaltung, Pausen,
Budget-Warnungen, PDF-/CSV-Abrechnung und Aktivitätsprotokoll. Reines
Python/Flask + Vanilla-JS, ohne Build-Schritt.

## Stack

- Python 3 · Flask · Waitress (Produktionsserver, 8 Threads)
- SQLite (stdlib `sqlite3`, WAL-Modus)
- `fpdf2` für PDF-Leistungsnachweise
- Jinja2-Templates + Vanilla-JavaScript

## Schnellinstallation (empfohlen)

Der Installer lädt die aktuelle Version von GitHub, richtet eine venv ein und
legt einen Autostart-Dienst an (startet beim Booten/Login, Neustart bei
Absturz). Beim ersten Start wird automatisch eine leere Datenbank angelegt.

**Debian / Ubuntu:**

```bash
wget -qO install.sh https://raw.githubusercontent.com/ipod86/Zeiterfassung/main/install.sh
bash install.sh                       # installiert nach /opt/zeiterfassung
# eigenes Ziel: INSTALL_DIR=$HOME/zeit bash install.sh
```

**Windows (PowerShell als Administrator):**

```powershell
iwr -useb https://raw.githubusercontent.com/ipod86/Zeiterfassung/main/install.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1   # installiert nach C:\Zeiterfassung
```

Danach erreichbar unter `http://localhost:5050` bzw. `http://<rechner-ip>:5050`.
Vorhandene Daten unter *Einstellungen → Backup einspielen* importieren — ohne
Backup startet das Tool mit einer leeren Datenbank.

## Updates

Im Tool unter **Einstellungen → Software-Update**:

- zeigt die installierte Version und ob auf GitHub eine neuere vorliegt
  (es wird zusätzlich regelmäßig automatisch geprüft),
- **„Jetzt aktualisieren"** lädt die neue Version, legt vorher ein Backup an,
  tauscht die Dateien und startet den Server selbstständig neu.

Das Selbst-Update setzt voraus, dass der Server über den Installer-Dienst
(`supervisor.py`) läuft.

## Manuelle Installation / Entwicklung

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
python run.py                 # oder: python supervisor.py (mit Auto-Restart)
```

- Lokal:      http://localhost:5050
- Im Netzwerk: http://<rechner-ip>:5050

Beim ersten Start wird `data/zeiterfassung.db` automatisch angelegt.
Mit `DEV=1` startet der Flask-Entwicklungsserver mit Reloader.

## Funktionen

- **Erfassen:** Timer pro Kunde/Projekt mit Start/Stop, Pause/Weiter und
  manuellem Nachtragen. Es läuft immer nur ein Timer aktiv; pausierte
  Buchungen bleiben beim Start einer anderen erhalten.
- **Kunden & Projekte:** Anlegen, Budgets, Stundensätze, aufklappbare
  Buchungslisten mit Inline-Bearbeitung.
- **Abrechnen:** Vorschau, Zwischen-/Endrechnung, PDF + CSV, offene Salden.
- **Protokoll:** lückenlose Aktivitätshistorie, filterbar.
- **Einstellungen:** Firma/Logo, Rundung, Budget-Warnschwelle, Sätze,
  wiederkehrende Tätigkeiten, Nutzer, Backup (ZIP).
- **Feedback:** In-App-Meldung von Bugs/Wünschen als abhakbare Checkliste.

## Daten & Datenschutz

Das Verzeichnis `data/` (Datenbank, Uploads, Rechnungen, Backups, Feedback)
ist über `.gitignore` ausgeschlossen und wird **nicht** versioniert — es
enthält echte Kundendaten.

> Hinweis: `SECRET_KEY` in `app/__init__.py` ist ein lokaler Platzhalter.
> Für den Produktivbetrieb durch einen eigenen Wert ersetzen.
