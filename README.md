# Zeiterfassung

Lokale, netzwerkfähige Zeiterfassung mit Projekt-/Kundenverwaltung, Pausen,
Budget-Warnungen, PDF-/CSV-Abrechnung und Aktivitätsprotokoll. Reines
Python/Flask + Vanilla-JS, ohne Build-Schritt.

## Stack

- Python 3 · Flask · Waitress (Produktionsserver, 8 Threads)
- SQLite (stdlib `sqlite3`, WAL-Modus)
- `fpdf2` für PDF-Leistungsnachweise
- Jinja2-Templates + Vanilla-JavaScript

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

## Starten

```bash
python run.py
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
