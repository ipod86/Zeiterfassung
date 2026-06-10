import sqlite3
from pathlib import Path
from flask import g, current_app

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "zeiterfassung.db"

DEFAULT_SETTINGS = {
    "company_name": "Meine Firma",
    "company_address": "",
    "company_email": "",
    "company_phone": "",
    "company_vat": "",
    "currency": "€",
    "tax_rate": "19",
    "rounding_minutes": "0",
    "invoice_prefix": "RE-",
    "invoice_counter": "1",
    "budget_warn_pct": "80",
    "backup_keep_days": "14",
    "backup_time": "",
    "theme_primary": "#4f46e5",
    "theme_mode": "light",
    "logo_path": "",
    "logo_file": "",
    "logo_w": "",
    "logo_h": "",
}


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "invoices").mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    # migrate: add projects.default_rate_id on older databases
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
    if "default_rate_id" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN default_rate_id INTEGER")
    ccols = [r["name"] for r in conn.execute("PRAGMA table_info(customers)").fetchall()]
    if "customer_no" not in ccols:
        conn.execute("ALTER TABLE customers ADD COLUMN customer_no TEXT")
    ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "theme_mode" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN theme_mode TEXT")
    icols = [r["name"] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()]
    if "project_id" not in icols:
        conn.execute("ALTER TABLE invoices ADD COLUMN project_id INTEGER")
    # migrate: denormalize user_name onto time_entries + make user_id nullable
    # (ON DELETE SET NULL) so users can be hard-deleted without losing bookings
    tcols = [r["name"] for r in conn.execute("PRAGMA table_info(time_entries)").fetchall()]
    if "user_name" not in tcols:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript("""
          CREATE TABLE time_entries_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_name  TEXT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            task       TEXT,
            rate       REAL NOT NULL DEFAULT 0,
            start_ts   TEXT NOT NULL,
            end_ts     TEXT,
            manual     INTEGER NOT NULL DEFAULT 0,
            billed     INTEGER NOT NULL DEFAULT 0,
            invoice_id INTEGER REFERENCES invoices(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
          );
          INSERT INTO time_entries_new
            (id,user_id,user_name,project_id,task,rate,start_ts,end_ts,manual,billed,invoice_id,created_at,updated_at)
            SELECT t.id, t.user_id, u.name, t.project_id, t.task, t.rate, t.start_ts,
                   t.end_ts, t.manual, t.billed, t.invoice_id, t.created_at, t.updated_at
            FROM time_entries t LEFT JOIN users u ON u.id=t.user_id;
          DROP TABLE time_entries;
          ALTER TABLE time_entries_new RENAME TO time_entries;
          CREATE INDEX IF NOT EXISTS idx_entries_user    ON time_entries(user_id);
          CREATE INDEX IF NOT EXISTS idx_entries_project ON time_entries(project_id);
          CREATE INDEX IF NOT EXISTS idx_entries_running ON time_entries(end_ts);
        """)
        conn.execute("PRAGMA foreign_keys=ON")
    # migrate: pause support on time_entries (net worked time excludes pauses)
    pcols = [r["name"] for r in conn.execute("PRAGMA table_info(time_entries)").fetchall()]
    if "paused_seconds" not in pcols:
        conn.execute("ALTER TABLE time_entries ADD COLUMN paused_seconds INTEGER NOT NULL DEFAULT 0")
    if "pause_started_at" not in pcols:
        conn.execute("ALTER TABLE time_entries ADD COLUMN pause_started_at TEXT")
    # seed example rates
    if conn.execute("SELECT COUNT(*) AS c FROM rates").fetchone()["c"] == 0:
        conn.executemany(
            "INSERT INTO rates(label, amount, sort) VALUES(?,?,?)",
            [("Standard", 90.0, 1), ("Beratung", 120.0, 2)],
        )
    # seed default settings
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            (k, v),
        )
    # seed one user so the app is usable immediately
    cur = conn.execute("SELECT COUNT(*) AS c FROM users")
    if cur.fetchone()["c"] == 0:
        conn.execute("INSERT INTO users(name, color) VALUES(?, ?)", ("Admin", "#4f46e5"))
    # backfill logo dimensions for a logo uploaded before this feature existed
    sset = {r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM settings").fetchall()}
    if sset.get("logo_path") and not sset.get("logo_w") and Path(sset["logo_path"]).exists():
        from .util import image_size
        size = image_size(sset["logo_path"])
        if size:
            conn.execute("INSERT INTO settings(key,value) VALUES('logo_w',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(size[0]),))
            conn.execute("INSERT INTO settings(key,value) VALUES('logo_h',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(size[1]),))
    conn.commit()
    conn.close()


def get_settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return s


def get_rates(active_only=True):
    sql = "SELECT * FROM rates"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY sort, label"
    return get_db().execute(sql).fetchall()


def get_recurring_tasks(active_only=True):
    sql = "SELECT * FROM recurring_tasks"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY sort, text"
    return get_db().execute(sql).fetchall()


def set_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    db.commit()


def log_activity(action, entity=None, entity_id=None, details=None):
    from flask import session
    db = get_db()
    db.execute(
        "INSERT INTO activity_log(user_id, user_name, action, entity, entity_id, details) "
        "VALUES(?,?,?,?,?,?)",
        (
            session.get("user_id"),
            session.get("user_name"),
            action,
            entity,
            entity_id,
            details,
        ),
    )
    db.commit()
