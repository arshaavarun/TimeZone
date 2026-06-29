"""Data safety: WAL mode, consistent backups + cloud-folder mirror, the backup
download, and restore (with validation). Self-contained — creates and cleans up its
own temp folder/files."""
import io
import os
import shutil
import sqlite3
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    h.section("backup")
    c, db = h.client, h.db
    from timezone import config
    from timezone.database import backup_db

    # WAL is enabled on the live DB
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    h.check("WAL journal mode is enabled", str(mode).lower() == "wal")

    # one-click download returns a real, intact SQLite file as an attachment
    r = c.get("/controls/backup/download")
    h.check("backup download streams a SQLite file as an attachment",
            r.status_code == 200
            and "attachment" in r.headers.get("Content-Disposition", "")
            and r.get_data()[:16] == b"SQLite format 3\x00")

    # cloud/extra folder: a real dir is accepted, a non-existent one is rejected
    tmpdir = tempfile.mkdtemp(prefix="tz_cloud_")
    c.post("/controls/backup/folder", data={"backup_copy_dir": tmpdir})
    saved = db.execute("SELECT backup_copy_dir FROM app_settings WHERE id=1").fetchone()[0]
    h.check("backup folder saved", saved == tmpdir)
    c.post("/controls/backup/folder", data={"backup_copy_dir": os.path.join(tmpdir, "does-not-exist")})
    still = db.execute("SELECT backup_copy_dir FROM app_settings WHERE id=1").fetchone()[0]
    h.check("a non-existent backup folder is rejected (unchanged)", still == tmpdir)

    # a backup now mirrors into the configured folder
    before = set(os.listdir(tmpdir))
    backup_db()
    mirrored = [f for f in (set(os.listdir(tmpdir)) - before)
                if f.startswith("timezone_") and f.endswith(".db")]
    h.check("backups are mirrored into the configured folder", len(mirrored) >= 1)

    # backups older than the retention window are auto-deleted (local + cloud);
    # non-backup files in those folders are left untouched
    old = "timezone_20000101_000000.db"      # year 2000 -> far older than 10 days
    keep = "keepme.txt"
    for folder in (config.BACKUP_DIR, tmpdir):
        open(os.path.join(folder, old), "w").close()
        open(os.path.join(folder, keep), "w").close()
    backup_db()                               # triggers pruning of both folders
    h.check("old backups are auto-deleted from the local folder",
            not os.path.exists(os.path.join(config.BACKUP_DIR, old)))
    h.check("old backups are auto-deleted from the cloud folder",
            not os.path.exists(os.path.join(tmpdir, old)))
    h.check("non-backup files in those folders are left alone",
            os.path.exists(os.path.join(config.BACKUP_DIR, keep))
            and os.path.exists(os.path.join(tmpdir, keep)))
    h.check("recent backups are kept",
            any(f.startswith("timezone_") and f.endswith(".db") and f != old
                for f in os.listdir(config.BACKUP_DIR)))
    os.remove(os.path.join(config.BACKUP_DIR, keep))
    os.remove(os.path.join(tmpdir, keep))

    # restore: build a backup = current DB + a marker client, upload it, see the marker
    marker = "ZZRESTORE-MARKER"
    fd, src_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = sqlite3.connect(config.DB_PATH)
    d = sqlite3.connect(src_path)
    with d:
        s.backup(d)
    d.execute("INSERT INTO clients (name, status, created_at) VALUES (?, 'active', '2099-01-01')", (marker,))
    d.commit()
    d.close()
    s.close()
    with open(src_path, "rb") as fh:
        payload = fh.read()
    c.post("/controls/backup/restore",
           data={"backup_file": (io.BytesIO(payload), "restore.db"), "confirm": "1"},
           content_type="multipart/form-data")
    chk = sqlite3.connect(config.DB_PATH)
    found = chk.execute("SELECT 1 FROM clients WHERE name=?", (marker,)).fetchone()
    chk.close()
    h.check("restore replaces live data from the uploaded backup", found is not None)

    # an invalid (non-SQLite) upload is rejected and leaves the data intact
    c.post("/controls/backup/restore",
           data={"backup_file": (io.BytesIO(b"not a database at all"), "junk.db"), "confirm": "1"},
           content_type="multipart/form-data")
    chk = sqlite3.connect(config.DB_PATH)
    intact = chk.execute("SELECT 1 FROM clients WHERE name=?", (marker,)).fetchone()
    chk.close()
    h.check("an invalid restore file is rejected (data unchanged)", intact is not None)

    # periodic backups: a short-interval timer makes new timestamped files while it
    # runs (then we stop it so it doesn't affect later groups)
    import time
    from timezone.database import start_periodic_backups, stop_periodic_backups

    def _bk_files():
        return {f for f in os.listdir(config.BACKUP_DIR)
                if f.startswith("timezone_") and f.endswith(".db")} \
            if os.path.isdir(config.BACKUP_DIR) else set()

    before_bk = _bk_files()
    start_periodic_backups(1.1)
    time.sleep(2.6)
    stop_periodic_backups()
    time.sleep(0.4)
    h.check("periodic backups create new timestamped files while running",
            len(_bk_files() - before_bk) >= 1)

    # cleanup
    try:
        os.remove(src_path)
    except OSError:
        pass
    shutil.rmtree(tmpdir, ignore_errors=True)
    # turn the mirror folder back off so later groups aren't affected
    c.post("/controls/backup/folder", data={"backup_copy_dir": ""})


if __name__ == "__main__":
    standalone(run)
