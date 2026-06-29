"""TZ Controls — global, app-wide settings shared by every client.

Holds the owner's business identity (name/address/email/GSTIN, bank/payment
details) and the single SMTP server used to email all clients' invoices, plus a
"Back up now" action. None of this is per-client; it lives in the global
``app_settings`` row (id = 1). Per-client billing/email lives in Settings.
"""
import os
import sqlite3
import tempfile
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, send_file

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db, backup_db, init_db, close_db
from timezone.services import app_settings


def _latest_backup_name():
    """Filename of the newest local backup (for display), or None."""
    try:
        files = sorted(f for f in os.listdir(BACKUP_DIR)
                       if f.startswith("timezone_") and f.endswith(".db"))
        return files[-1] if files else None
    except OSError:
        return None


def _is_valid_timezone_db(path):
    """True only for an intact SQLite file that looks like a TimeZone database
    (passes integrity_check and has the core global tables). Guards restore."""
    try:
        with open(path, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                return False
    except OSError:
        return False
    try:
        con = sqlite3.connect(path)
        ok = con.execute("PRAGMA integrity_check").fetchone()
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        return bool(ok) and ok[0] == "ok" and {"clients", "app_settings"} <= names
    except sqlite3.Error:
        return False


@app.route("/controls")
def controls():
    """The global controls screen (business identity + SMTP + backup)."""
    db = get_db()
    settings = app_settings(db)
    return render_template(
        "controls.html", settings=settings,
        backup_copy_dir=(settings["backup_copy_dir"] or "") if settings else "",
        latest_backup=_latest_backup_name(),
    )


@app.route("/controls/save", methods=["POST"])
def controls_save():
    """Save the global business identity and SMTP server settings."""
    db = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        port = int(request.form.get("smtp_port") or 587)
    except ValueError:
        port = 587
    # a blank password means "keep the existing one" (so it isn't echoed back)
    password = request.form.get("smtp_password")
    if not password:
        password = app_settings(db)["smtp_password"] or ""
    db.execute(
        "UPDATE app_settings SET biz_name=?, biz_address=?, biz_email=?, biz_gstin=?, "
        "bank_details=?, smtp_host=?, smtp_port=?, smtp_user=?, smtp_password=?, "
        "smtp_use_tls=?, smtp_from_name=?, smtp_from_email=?, updated_at=? WHERE id=1",
        (
            (request.form.get("biz_name") or "").strip(),
            request.form.get("biz_address"),
            (request.form.get("biz_email") or "").strip(),
            (request.form.get("biz_gstin") or "").strip(),
            request.form.get("bank_details"),
            (request.form.get("smtp_host") or "").strip(), port,
            (request.form.get("smtp_user") or "").strip(), password,
            1 if request.form.get("smtp_use_tls") == "1" else 0,
            (request.form.get("smtp_from_name") or "").strip(),
            (request.form.get("smtp_from_email") or "").strip(),
            now,
        ),
    )
    db.commit()
    flash("Controls saved.", "success")
    return redirect(url_for("controls"))


@app.route("/controls/backup", methods=["POST"])
def controls_backup():
    """Make an immediate timestamped backup of the database."""
    saved = backup_db()
    if saved:
        flash("Backup created: %s" % os.path.basename(saved), "success")
    else:
        flash("Nothing to back up yet.", "error")
    return redirect(url_for("controls"))


@app.route("/controls/backup/download")
def controls_backup_download():
    """Make a fresh consistent backup and stream it to the browser to save anywhere
    (cloud, USB, another PC). The file also remains in backups/ as a normal backup."""
    path = backup_db()
    if not path:
        flash("Nothing to back up yet.", "error")
        return redirect(url_for("controls"))
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/controls/backup/folder", methods=["POST"])
def controls_backup_folder():
    """Set (or clear) the extra folder each backup is mirrored into — e.g. a
    OneDrive/Drive folder for an off-machine copy. Only existing folders are saved."""
    db = get_db()
    path = (request.form.get("backup_copy_dir") or "").strip()
    if path and not os.path.isdir(path):
        flash("That folder doesn't exist: %s" % path, "error")
        return redirect(url_for("controls"))
    db.execute("UPDATE app_settings SET backup_copy_dir = ? WHERE id = 1", (path or None,))
    db.commit()
    flash("Backup folder " + ("set to %s." % path if path else "cleared."), "success")
    return redirect(url_for("controls"))


@app.route("/controls/backup/restore", methods=["POST"])
def controls_backup_restore():
    """Replace ALL current data with an uploaded backup .db. Validates the file,
    takes a safety backup of the current data first (so it's undoable), then copies
    the upload's contents over the live DB via the online-backup API (no file swap,
    so it works while the server is running on Windows)."""
    f = request.files.get("backup_file")
    if not f or not f.filename:
        flash("Choose a backup file to restore.", "error")
        return redirect(url_for("controls"))
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    f.save(tmp)
    try:
        if not _is_valid_timezone_db(tmp):
            flash("That file isn't a valid TimeZone backup.", "error")
            return redirect(url_for("controls"))
        backup_db()                      # safety net: keep the current data first
        close_db()                       # release this request's connection
        src = sqlite3.connect(tmp)
        dst = sqlite3.connect(DB_PATH)
        try:
            with dst:
                src.backup(dst)          # overwrite live content from the upload
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dst.close()
            src.close()
        init_db()                        # bring an older backup up to the current schema
        flash("Restored from backup. Your previous data was saved as a backup first.", "success")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return redirect(url_for("controls"))
