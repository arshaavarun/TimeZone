"""
Shared test harness for the TimeZone functional test scripts.

Each feature is tested by its own ``tests/test_<area>.py`` module that exposes a
``run(h)`` function. ``h`` is a :class:`Harness` wrapping:

* a throwaway copy of the real ``timezone.db`` (the real data is never touched —
  taken via SQLite's online-backup API so it's consistent even while the
  always-on service holds the DB open),
* a Flask test client pointed at that copy,
* a direct SQLite connection for assertions, and
* a ``check()`` helper + pass/fail tally.

The runner (``smoke_test.py``) builds one Harness and feeds it to each group, so
the whole suite shares a single DB copy. Any one module can also be run on its
own (``python tests/test_tasks.py``) via :func:`standalone`, which builds its own
Harness and prints a summary.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
REAL_DB = os.path.join(PROJECT, "timezone.db")


def snapshot_db(src, dst):
    """Consistent copy of the live SQLite DB into ``dst`` (online-backup API;
    falls back to a plain file copy)."""
    try:
        s = sqlite3.connect(src)
        d = sqlite3.connect(dst)
        with d:
            s.backup(d)
        d.close()
        s.close()
    except Exception:
        shutil.copy2(src, dst)


def has_openpyxl():
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:
        return False


class Harness:
    """A throwaway-DB Flask test client plus assertion/reporting helpers."""

    def __init__(self):
        self.tmp = tempfile.NamedTemporaryFile(prefix="tz_test_", suffix=".db", delete=False)
        self.tmp.close()
        if os.path.exists(REAL_DB):
            snapshot_db(REAL_DB, self.tmp.name)
            self.source = "fresh copy of real timezone.db"
        else:
            self.source = "fresh DB (no timezone.db present)"
        os.environ["TIMEZONE_DB"] = self.tmp.name
        # isolate backups too: tests must never write into / prune the real backups/
        self.backup_dir = tempfile.mkdtemp(prefix="tz_test_backups_")
        os.environ["TIMEZONE_BACKUP_DIR"] = self.backup_dir

        if PROJECT not in sys.path:
            sys.path.insert(0, PROJECT)
        import app as application  # imported AFTER the env vars so it uses the copy
        self.app = application.app
        self.client = self.app.test_client()
        self.db = sqlite3.connect(self.tmp.name)
        self.db.row_factory = sqlite3.Row

        # The app now requires owner login. Give the throwaway DB a known password
        # and mark the shared test client's session authenticated, so every group's
        # requests sail past the _require_login guard. (test_auth exercises the gate
        # itself with its own fresh clients.)
        from werkzeug.security import generate_password_hash
        self.password = "test-pass-123"
        self.db.execute(
            "UPDATE app_settings SET owner_password_hash = ? WHERE id = 1",
            (generate_password_hash(self.password),),
        )
        self.db.commit()
        with self.client.session_transaction() as s:
            s["authed"] = True

        self.today = date.today().isoformat()
        self.test_date = "2099-01-15"   # far future, isolated from real entries
        self.passed, self.failed = [], []

    # ---- output / assertions ----
    def section(self, name):
        print("[%s]" % name)

    def check(self, name, cond):
        (self.passed if cond else self.failed).append(name)
        print(("  ok   " if cond else "  FAIL ") + name)

    def get_ok(self, path):
        return self.client.get(path).status_code == 200

    def client_id(self, name=None):
        """The id of a client by name, or (default) the first active client —
        which is the one the test client operates as when no session is set."""
        if name:
            row = self.db.execute("SELECT id FROM clients WHERE name=?", (name,)).fetchone()
        else:
            row = self.db.execute(
                "SELECT id FROM clients WHERE status='active' ORDER BY id LIMIT 1").fetchone()
        return row["id"] if row else None

    def close(self):
        self.db.close()
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass
        shutil.rmtree(self.backup_dir, ignore_errors=True)


def report_and_exit(h):
    """Print the PASSED/FAILED summary and exit 0 (all green) or 1 (failures)."""
    print("\n" + "=" * 50)
    print("PASSED: %d   FAILED: %d" % (len(h.passed), len(h.failed)))
    if h.failed:
        print("Failures:")
        for n in h.failed:
            print("  - " + n)
    print("=" * 50)
    sys.exit(1 if h.failed else 0)


def standalone(run_fn):
    """Run a single module's ``run(h)`` by itself with a fresh Harness, then
    print the summary and exit. Used by each test_*.py's ``__main__`` block."""
    h = Harness()
    print("TimeZone test - source: %s" % h.source)
    print("  DB under test (throwaway copy): %s\n" % h.tmp.name)
    try:
        run_fn(h)
    finally:
        h.close()
    report_and_exit(h)
