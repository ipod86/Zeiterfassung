PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  color      TEXT NOT NULL DEFAULT '#4f46e5',
  active     INTEGER NOT NULL DEFAULT 1,
  theme_mode TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS customers (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  customer_no TEXT,
  contact     TEXT,
  address    TEXT,
  email      TEXT,
  phone      TEXT,
  vat_id     TEXT,
  note       TEXT,
  archived   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS rates (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  label  TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  sort   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id     INTEGER NOT NULL REFERENCES customers(id),
  name            TEXT NOT NULL,
  rate            REAL NOT NULL DEFAULT 0,
  default_rate_id INTEGER REFERENCES rates(id),
  description     TEXT,
  status          TEXT NOT NULL DEFAULT 'offen',
  budget          REAL,
  color           TEXT,
  archived        INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS time_entries (
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
  paused_seconds   INTEGER NOT NULL DEFAULT 0,
  pause_started_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS invoices (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  number      TEXT,
  customer_id INTEGER REFERENCES customers(id),
  project_id  INTEGER REFERENCES projects(id),
  type        TEXT NOT NULL DEFAULT 'zwischen',
  created_by  INTEGER REFERENCES users(id),
  period_from TEXT,
  period_to   TEXT,
  subtotal    REAL NOT NULL DEFAULT 0,
  tax_rate    REAL NOT NULL DEFAULT 0,
  tax_amount  REAL NOT NULL DEFAULT 0,
  total       REAL NOT NULL DEFAULT 0,
  pdf_path    TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS activity_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER,
  user_name  TEXT,
  action     TEXT NOT NULL,
  entity     TEXT,
  entity_id  INTEGER,
  details    TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS recurring_tasks (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  text   TEXT NOT NULL,
  sort   INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_entries_user    ON time_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_entries_project ON time_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_entries_running ON time_entries(end_ts);
CREATE INDEX IF NOT EXISTS idx_projects_cust   ON projects(customer_id);
