"""
Database layer: per-request SQLite connection, schema creation, the one-time
migration to multi-client, per-client default seeding, and the startup backup.

Multi-client model
------------------
A single SQLite file holds every client's data. Two kinds of tables:

* **Global** (no ``client_id``) — shared by the whole app:
  ``clients`` (the roster) and ``app_settings`` (the owner's business identity
  and the single SMTP server used for all clients).

* **Per-client** (carry a ``client_id``) — everything else: tasks, subtasks,
  charge types, timesheet, expenses, invoices, entry defaults, per-client
  invoice profile and email recipients. Every view query is scoped to the
  selected client (see ``services.current_client_id``).

``init_db()`` is safe to call repeatedly. On an old single-client database it
runs ``_migrate_to_multi_client`` once, folding the existing data under the
first client (``FIRST_CLIENT_NAME``) and splitting the old ``invoice_profile``
row into the global ``app_settings`` and the per-client ``client_profile``.
"""
import os
import sqlite3
from datetime import datetime

from flask import g

from timezone.config import *  # noqa: F401,F403  (constants + DEFAULT_* seeds)


def get_db():
    """Return the per-request SQLite connection (stored on Flask's ``g``)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    """Teardown handler — closes the request connection (registered in __init__)."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _table_exists(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(db, table):
    """Set of column names on a table."""
    return {row["name"] for row in db.execute("PRAGMA table_info(%s)" % table)}


def _row_get(row, key, default=None):
    """Safe accessor for an sqlite3.Row that may be missing a column."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


# ---------------------------------------------------------------------------
# Schema (current/new shape). All CREATEs are IF NOT EXISTS so this doubles as
# the creator for fresh installs and the "ensure new tables" step on upgrade.
# Per-client tables include client_id directly; uniqueness that must be
# per-client (task ids, subtask/charge names, day rows) uses composite keys.
#
# Indexes are kept OUT of SCHEMA (see INDEXES below) and created only after the
# migration has added client_id everywhere — otherwise the client_id indexes
# would fail against a legacy table that has not gained the column yet.
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    status      TEXT DEFAULT 'active',   -- 'active' | 'archived'
    color_hue   INTEGER,                 -- optional manual colour override (0-359); NULL = auto
    tint_light  INTEGER,                 -- background-shade strength % in light mode; NULL = default
    tint_dark   INTEGER,                 -- background-shade strength % in dark mode;  NULL = default
    created_at  TEXT,
    archived_on TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    biz_name        TEXT,
    biz_address     TEXT,
    biz_email       TEXT,
    biz_gstin       TEXT,
    bank_details    TEXT,
    smtp_host       TEXT,
    smtp_port       INTEGER DEFAULT 587,
    smtp_user       TEXT,
    smtp_password   TEXT,
    smtp_use_tls    INTEGER DEFAULT 1,
    smtp_from_name  TEXT,
    smtp_from_email TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS client_profile (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id         INTEGER,
    client_name       TEXT,
    client_address    TEXT,
    client_gstin      TEXT,
    default_cgst_rate REAL DEFAULT 0.0,
    default_sgst_rate REAL DEFAULT 0.0,
    use_igst          INTEGER DEFAULT 1,    -- single GST (IGST) vs CGST/SGST split
    default_igst_rate REAL DEFAULT 0.0,
    terms             TEXT,
    email_subject     TEXT,
    email_body        TEXT,
    email_auto_send   INTEGER DEFAULT 0,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    client_id    INTEGER,
    task_id      TEXT,
    description  TEXT,
    status       TEXT DEFAULT 'Active',
    completed_at TEXT,
    created_at   TEXT,
    PRIMARY KEY (client_id, task_id)
);

CREATE TABLE IF NOT EXISTS subtasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER,
    name       TEXT,
    status     TEXT DEFAULT 'Active',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS charge_types (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     INTEGER,
    name          TEXT,
    is_base       INTEGER DEFAULT 0,
    percent       REAL DEFAULT 100.0,
    amount_usd    REAL DEFAULT 0.0,
    invoice_label TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS timesheet_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     INTEGER,
    work_date     TEXT,
    task_id       TEXT,
    sub_task      TEXT,
    description   TEXT,
    hours         REAL,
    charge_method TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS timesheet_days (
    client_id  INTEGER,
    work_date  TEXT,
    status     TEXT DEFAULT 'draft',
    day_type   TEXT DEFAULT 'working',
    updated_at TEXT,
    PRIMARY KEY (client_id, work_date)
);

CREATE TABLE IF NOT EXISTS expenses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER,
    date_purchased      TEXT,
    item                TEXT,
    price               REAL,
    currency            TEXT DEFAULT 'INR',
    purchased_at        TEXT,
    warranty_till       TEXT,
    purpose             TEXT DEFAULT 'Official',
    category            TEXT,            -- expense_categories.name (per-client list)
    is_subscription     INTEGER DEFAULT 0,
    subscription_period TEXT,            -- 'Monthly' | 'Yearly'
    subscription_end    TEXT,            -- renewal date (purchase date + period)
    subscription_ended_on TEXT,          -- date the user closed it (status='closed')
    subscription_status TEXT DEFAULT 'active',  -- 'active' | 'completed' | 'closed'
    rolled_from_id      INTEGER,         -- the previous cycle this entry continues
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS expense_categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER,
    name       TEXT,
    status     TEXT DEFAULT 'Active',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS expense_attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER,
    expense_id   INTEGER,
    stored_name  TEXT UNIQUE,
    original_name TEXT,
    content_type TEXT,
    uploaded_at  TEXT
);

CREATE TABLE IF NOT EXISTS invoice_email_recipients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER,
    email      TEXT,
    kind       TEXT DEFAULT 'to',   -- 'to' | 'cc' | 'bcc'
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     INTEGER,
    number        TEXT,
    invoice_date  TEXT,
    period_start  TEXT,
    period_end    TEXT,
    currency      TEXT DEFAULT 'USD',
    fx_rate       REAL DEFAULT 1.0,
    client_name   TEXT,
    client_address TEXT,
    client_gstin  TEXT,
    tax_rate      REAL DEFAULT 0.0,       -- active GST total (drives total maths)
    cgst_rate     REAL DEFAULT 0.0,
    sgst_rate     REAL DEFAULT 0.0,
    use_igst      INTEGER DEFAULT 0,      -- single GST (IGST) vs CGST/SGST split
    igst_rate     REAL DEFAULT 0.0,
    subtotal      REAL DEFAULT 0.0,
    tax_amount    REAL DEFAULT 0.0,
    total         REAL DEFAULT 0.0,
    show_inr      INTEGER DEFAULT 0,
    inr_rate      REAL DEFAULT 0.0,
    inr_rate_date TEXT,
    inr_total     REAL DEFAULT 0.0,
    notes         TEXT,
    status        TEXT DEFAULT 'generated',
    settled_on    TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER,
    invoice_id  INTEGER,
    description TEXT,
    qty         REAL,
    rate        REAL,
    amount      REAL,
    is_discount INTEGER DEFAULT 0,
    sort_order  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS entry_defaults (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER,
    trigger_field   TEXT,      -- 'task' | 'sub_task'
    trigger_value   TEXT,      -- the Task ID / Sub Task that triggers the rule
    set_sub_task    TEXT,
    set_hours       REAL,
    set_description TEXT,
    created_at      TEXT
);
"""

# Indexes (including the per-client uniqueness on subtask / charge-type names).
# Created only after every table is guaranteed to have client_id — i.e. at the
# end of init_db, after any migration. All IF NOT EXISTS so re-running is safe.
INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_subtasks_client_name   ON subtasks(client_id, name);
CREATE UNIQUE INDEX IF NOT EXISTS ux_charge_client_name     ON charge_types(client_id, name);
CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_client_name ON expense_categories(client_id, name);
CREATE INDEX IF NOT EXISTS ix_entries_client_date ON timesheet_entries(client_id, work_date);
CREATE INDEX IF NOT EXISTS ix_expenses_client     ON expenses(client_id);
CREATE INDEX IF NOT EXISTS ix_invoices_client     ON invoices(client_id);
"""


def init_db():
    """Create tables (IF NOT EXISTS), migrate an old single-client DB once, and
    make sure there is always at least one client to work with."""
    os.makedirs(ATTACH_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # A legacy single-client database still has the old ``invoice_profile`` table;
    # the migration drops it, so its presence is the reliable "needs migration"
    # signal. (Detecting via the ``clients`` table is wrong: ``executescript``
    # below creates ``clients`` empty before the migration runs, so a failed/retried
    # migration would never re-trigger.)
    legacy = _table_exists(db, "invoice_profile")

    cur.executescript(SCHEMA)

    # later-added optional columns on an already-migrated clients table
    for col in ("color_hue", "tint_light", "tint_dark"):
        if col not in _columns(db, "clients"):
            cur.execute("ALTER TABLE clients ADD COLUMN %s INTEGER" % col)

    # iGST (single GST) vs CGST/SGST split — added later
    for col, ddl in (("use_igst", "INTEGER DEFAULT 1"), ("default_igst_rate", "REAL DEFAULT 0.0")):
        if col not in _columns(db, "client_profile"):
            cur.execute("ALTER TABLE client_profile ADD COLUMN %s %s" % (col, ddl))
            if col == "use_igst":
                # clients that already configured a CGST/SGST split keep the split
                cur.execute("UPDATE client_profile SET use_igst = 0 "
                            "WHERE COALESCE(default_cgst_rate,0) > 0 OR COALESCE(default_sgst_rate,0) > 0")
    for col, ddl in (("use_igst", "INTEGER DEFAULT 0"), ("igst_rate", "REAL DEFAULT 0.0")):
        if col not in _columns(db, "invoices"):
            cur.execute("ALTER TABLE invoices ADD COLUMN %s %s" % (col, ddl))

    # refresh an un-edited seeded email body to the current default (so the
    # new wording + report note reach clients that never customised it)
    cur.execute("UPDATE client_profile SET email_body = ? WHERE email_body = ?",
                (DEFAULT_EMAIL_BODY, LEGACY_EMAIL_BODY))

    # when a task was marked completed (added later, for the "Completed On" column)
    if "completed_at" not in _columns(db, "tasks"):
        cur.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")

    # owner login password hash (single-owner auth, added later) — NULL until the
    # first-run setup screen sets it; see services.owner_password_* and views_auth.
    if "owner_password_hash" not in _columns(db, "app_settings"):
        cur.execute("ALTER TABLE app_settings ADD COLUMN owner_password_hash TEXT")

    now = datetime.now().isoformat(timespec="seconds")

    # global settings row always exists (id = 1)
    if cur.execute("SELECT COUNT(*) c FROM app_settings").fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO app_settings (id, smtp_port, smtp_use_tls, updated_at) "
            "VALUES (1, 587, 1, ?)",
            (now,),
        )

    clients_empty = cur.execute("SELECT COUNT(*) c FROM clients").fetchone()["c"] == 0
    if legacy and clients_empty:
        _migrate_to_multi_client(db, cur, now)
    elif clients_empty:
        # brand-new install: create the first client and seed its defaults
        cur.execute(
            "INSERT INTO clients (name, status, created_at) VALUES (?, 'active', ?)",
            (FIRST_CLIENT_NAME, now),
        )
        seed_client_defaults(db, cur.lastrowid)

    cur.executescript(INDEXES)   # safe now that every table has client_id
    db.commit()
    db.close()


def _migrate_to_multi_client(db, cur, now):
    """One-time: fold the existing single-client database under the first client.

    Adds client_id everywhere (rebuilding the four tables whose uniqueness must
    become per-client), then splits the single ``invoice_profile`` row into the
    global ``app_settings`` and the per-client ``client_profile`` before dropping
    it. Runs only when an ``invoice_profile`` table exists and ``clients`` did
    not — i.e. exactly once, on the legacy schema.
    """
    cur.execute(
        "INSERT INTO clients (name, status, created_at) VALUES (?, 'active', ?)",
        (FIRST_CLIENT_NAME, now),
    )
    cid = cur.lastrowid

    # ---- 1. simple tables: add client_id, backfill to the first client ----
    simple = [
        "timesheet_entries", "expenses", "expense_attachments",
        "invoices", "invoice_items", "entry_defaults", "invoice_email_recipients",
    ]
    for table in simple:
        if "client_id" not in _columns(db, table):
            cur.execute("ALTER TABLE %s ADD COLUMN client_id INTEGER" % table)
        cur.execute("UPDATE %s SET client_id = ? WHERE client_id IS NULL" % table, (cid,))
    # very old DBs may predate the expense category column
    if "category" not in _columns(db, "expenses"):
        cur.execute("ALTER TABLE expenses ADD COLUMN category TEXT")

    # drop invoice columns the redesign no longer uses (tax is now the CGST+SGST
    # split; there is no separate tax label / legacy discount / adjust flag).
    # DROP COLUMN needs SQLite >= 3.35; ignore if unavailable (harmless leftover).
    for col in ("tax_label", "discount", "adjust_is_discount"):
        if col in _columns(db, "invoices"):
            try:
                cur.execute("ALTER TABLE invoices DROP COLUMN %s" % col)
            except sqlite3.OperationalError:
                pass

    # ---- 2. tables that need a rebuild for per-client uniqueness ----
    # Their old shape had global UNIQUE/PK constraints (task ids, subtask/charge/
    # category names, day rows) that must become per-client. Move each aside,
    # recreate it via SCHEMA in the new shape, then copy its rows in under `cid`.
    # expense_categories is guarded because pre-categories databases lack it.
    rebuilt = ["tasks", "subtasks", "charge_types", "timesheet_days"]
    has_categories = _table_exists(db, "expense_categories")
    if has_categories:
        rebuilt.append("expense_categories")
    for t in rebuilt:
        cur.execute("ALTER TABLE %s RENAME TO %s_old" % (t, t))
    cur.executescript(SCHEMA)  # recreates them with the new per-client shape
    cur.execute(
        "INSERT INTO tasks (client_id, task_id, description, status, created_at) "
        "SELECT ?, task_id, description, status, created_at FROM tasks_old", (cid,))
    cur.execute(
        "INSERT INTO subtasks (id, client_id, name, status, created_at) "
        "SELECT id, ?, name, status, created_at FROM subtasks_old", (cid,))
    cur.execute(
        "INSERT INTO charge_types "
        "(id, client_id, name, is_base, percent, amount_usd, invoice_label, created_at) "
        "SELECT id, ?, name, is_base, percent, amount_usd, invoice_label, created_at "
        "FROM charge_types_old", (cid,))
    cur.execute(
        "INSERT INTO timesheet_days (client_id, work_date, status, day_type, updated_at) "
        "SELECT ?, work_date, status, day_type, updated_at FROM timesheet_days_old", (cid,))
    if has_categories:
        cur.execute(
            "INSERT INTO expense_categories (id, client_id, name, status, created_at) "
            "SELECT id, ?, name, status, created_at FROM expense_categories_old", (cid,))
    for t in rebuilt:
        cur.execute("DROP TABLE %s_old" % t)

    # ---- 3. split invoice_profile -> app_settings (global) + client_profile ----
    prof = cur.execute("SELECT * FROM invoice_profile WHERE id = 1").fetchone()
    if prof is not None:
        cur.execute(
            "UPDATE app_settings SET biz_name=?, biz_address=?, biz_email=?, biz_gstin=?, "
            "bank_details=?, smtp_host=?, smtp_port=?, smtp_user=?, smtp_password=?, "
            "smtp_use_tls=?, smtp_from_name=?, smtp_from_email=?, updated_at=? WHERE id=1",
            (
                _row_get(prof, "biz_name"), _row_get(prof, "biz_address"),
                _row_get(prof, "biz_email"), _row_get(prof, "biz_gstin"),
                _row_get(prof, "bank_details"),
                _row_get(prof, "smtp_host"), _row_get(prof, "smtp_port", 587),
                _row_get(prof, "smtp_user"), _row_get(prof, "smtp_password"),
                _row_get(prof, "smtp_use_tls", 1),
                _row_get(prof, "smtp_from_name"), _row_get(prof, "smtp_from_email"),
                now,
            ),
        )
        cur.execute(
            "INSERT INTO client_profile (client_id, client_name, client_address, client_gstin, "
            "default_cgst_rate, default_sgst_rate, terms, email_subject, email_body, "
            "email_auto_send, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                _row_get(prof, "client_name"), _row_get(prof, "client_address"),
                _row_get(prof, "client_gstin"),
                _row_get(prof, "default_cgst_rate", 0.0) or 0.0,
                _row_get(prof, "default_sgst_rate", 0.0) or 0.0,
                _row_get(prof, "terms"),
                _row_get(prof, "email_subject") or DEFAULT_EMAIL_SUBJECT,
                _row_get(prof, "email_body") or DEFAULT_EMAIL_BODY,
                _row_get(prof, "email_auto_send", 0) or 0,
                now,
            ),
        )
    else:
        # no profile row to copy — give the client an empty default profile
        _insert_default_client_profile(cur, cid, now)

    cur.execute("DROP TABLE invoice_profile")


def _insert_default_client_profile(cur, client_id, now):
    cur.execute(
        "INSERT INTO client_profile (client_id, default_cgst_rate, default_sgst_rate, "
        "email_subject, email_body, email_auto_send, updated_at) VALUES (?,0,0,?,?,0,?)",
        (client_id, DEFAULT_EMAIL_SUBJECT, DEFAULT_EMAIL_BODY, now),
    )


def seed_client_defaults(db, client_id):
    """Populate a freshly-created client with sensible defaults: charge types,
    sub tasks, entry-default rules (and the tasks/subtasks they reference), and a
    blank invoice/email profile. Mirrors the legacy first-run seeding, scoped to
    one client. Used by ``init_db`` (fresh install) and the Add-client route."""
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.cursor()

    for name, is_base, percent, amount in DEFAULT_CHARGE_TYPES:
        cur.execute(
            "INSERT INTO charge_types "
            "(client_id, name, is_base, percent, amount_usd, invoice_label, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (client_id, name, is_base, percent, amount, DEFAULT_INVOICE_LABELS.get(name, ""), now),
        )

    for name in DEFAULT_SUBTASKS:
        cur.execute(
            "INSERT INTO subtasks (client_id, name, status, created_at) VALUES (?,?,?,?)",
            (client_id, name, "Active", now),
        )

    for name in DEFAULT_EXPENSE_CATEGORIES:
        cur.execute(
            "INSERT INTO expense_categories (client_id, name, status, created_at) VALUES (?,?,?,?)",
            (client_id, name, "Active", now),
        )

    for field, value, sub_task, hours, desc in DEFAULT_ENTRY_DEFAULTS:
        cur.execute(
            "INSERT INTO entry_defaults "
            "(client_id, trigger_field, trigger_value, set_sub_task, set_hours, set_description, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (client_id, field, value, sub_task, hours, desc, now),
        )
    # make the seeded rules usable out of the box
    cur.execute(
        "INSERT INTO tasks (client_id, task_id, description, status, created_at) VALUES (?,?,?,?,?)",
        (client_id, "Status Call", "Daily status call", "Active", now),
    )
    cur.execute(
        "INSERT INTO subtasks (client_id, name, status, created_at) VALUES (?,?,?,?)",
        (client_id, "Deploy", "Active", now),
    )

    _insert_default_client_profile(cur, client_id, now)
    db.commit()


def backup_db():
    """Copy the existing DB into backups/ with a timestamp; keep the most recent
    BACKUP_KEEP copies. A safety net so data is never silently lost — the app
    itself never deletes timezone.db."""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    import shutil
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, "timezone_%s.db" % stamp)
    try:
        shutil.copy2(DB_PATH, dest)
    except OSError:
        return None
    # prune old backups
    backups = sorted(
        f for f in os.listdir(BACKUP_DIR)
        if f.startswith("timezone_") and f.endswith(".db")
    )
    for old in backups[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    return dest
