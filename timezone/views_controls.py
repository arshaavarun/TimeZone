"""TZ Controls — global, app-wide settings shared by every client.

Holds the owner's business identity (name/address/email/GSTIN, bank/payment
details) and the single SMTP server used to email all clients' invoices, plus a
"Back up now" action. None of this is per-client; it lives in the global
``app_settings`` row (id = 1). Per-client billing/email lives in Settings.
"""
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db, backup_db
from timezone.services import app_settings


@app.route("/controls")
def controls():
    """The global controls screen (business identity + SMTP + backup)."""
    db = get_db()
    return render_template("controls.html", settings=app_settings(db))


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
        import os
        flash("Backup created: %s" % os.path.basename(saved), "success")
    else:
        flash("Nothing to back up yet.", "error")
    return redirect(url_for("controls"))
