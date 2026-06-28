"""Per-client Settings: charge types, expense categories, the client's invoice
profile (billing details, GST, terms), entry-default rules, and per-client
invoice email (recipients + subject/body + auto-send).

Everything here is scoped to the current client. The owner's *global* business
identity and the shared SMTP server live in TZ Controls (``views_controls``),
not here. The merged ``services.invoice_profile`` is passed to the template as
``profile`` for the client-billing/GST/email fields.

Note on naming: several routes take a row id as ``cid`` in the URL (a charge
type id / category id). The *client* id is held in ``client_id`` to avoid any
confusion between the two.
"""
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db
from timezone.services import *        # noqa: F401,F403
from timezone.mailer import send_test_email



# ----------------------------- charge types -----------------------------
@app.route("/charge_types/update/<int:cid>", methods=["POST"])
def charge_types_update(cid):
    """Save a single edited charge-type row, then recompute derived rates."""
    db = get_db()
    client_id = current_client_id(db)
    row = db.execute(
        "SELECT name, is_base FROM charge_types WHERE id = ? AND client_id = ?", (cid, client_id)
    ).fetchone()
    if not row:
        flash("Charge type not found.", "error")
        return redirect(url_for("settings", tab="charge"))
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Charge type name is required.", "error")
        return redirect(url_for("settings", tab="charge"))
    clash = db.execute(
        "SELECT 1 FROM charge_types WHERE client_id = ? AND name = ? AND id != ?",
        (client_id, name, cid),
    ).fetchone()
    if clash:
        flash("Another charge type is already named '%s'." % name, "error")
        return redirect(url_for("settings", tab="charge"))
    invoice_label = (request.form.get("invoice_label") or "").strip()
    if row["is_base"]:
        amount = float(request.form.get("amount") or 0.0)
        db.execute(
            "UPDATE charge_types SET name = ?, percent = 100.0, amount_usd = ?, invoice_label = ? "
            "WHERE id = ? AND client_id = ?",
            (name, amount, invoice_label, cid, client_id),
        )
    else:
        percent = float(request.form.get("percent") or 0.0)
        db.execute(
            "UPDATE charge_types SET name = ?, percent = ?, invoice_label = ? "
            "WHERE id = ? AND client_id = ?",
            (name, percent, invoice_label, cid, client_id),
        )
    if name != row["name"]:
        # cascade the rename so this client's timesheet entries keep matching the rate
        db.execute(
            "UPDATE timesheet_entries SET charge_method = ? WHERE client_id = ? AND charge_method = ?",
            (name, client_id, row["name"]),
        )
    db.commit()
    recompute_charge_amounts(db, client_id)
    flash("Charge type '%s' updated." % name, "success")
    return redirect(url_for("settings", tab="charge"))


@app.route("/charge_types/add", methods=["POST"])
def charge_types_add():
    db = get_db()
    client_id = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Charge type name is required.", "error")
        return redirect(url_for("settings", tab="charge"))
    if db.execute(
        "SELECT 1 FROM charge_types WHERE client_id = ? AND name = ?", (client_id, name)
    ).fetchone():
        flash("Charge type '%s' already exists." % name, "error")
    else:
        label = (request.form.get("invoice_label") or "").strip() \
            or "RPG Consulting - %s Charge" % name
        db.execute(
            "INSERT INTO charge_types (client_id, name, is_base, percent, amount_usd, invoice_label, created_at) "
            "VALUES (?,?,0,?,0,?,?)",
            (client_id, name, float(request.form.get("percent") or 100.0), label, now),
        )
        db.commit()
        recompute_charge_amounts(db, client_id)
        flash("Charge type '%s' added." % name, "success")
    return redirect(url_for("settings", tab="charge"))


@app.route("/charge_types/delete/<int:cid>", methods=["POST"])
def charge_types_delete(cid):
    db = get_db()
    client_id = current_client_id(db)
    row = db.execute(
        "SELECT name, is_base FROM charge_types WHERE id = ? AND client_id = ?", (cid, client_id)
    ).fetchone()
    if not row:
        return redirect(url_for("settings", tab="charge"))
    if row["is_base"]:
        flash("Cannot delete the base charge type.", "error")
        return redirect(url_for("settings", tab="charge"))
    used = db.execute(
        "SELECT COUNT(*) c FROM timesheet_entries WHERE client_id = ? AND charge_method = ?",
        (client_id, row["name"]),
    ).fetchone()["c"]
    if used:
        flash("Cannot delete '%s' — it is used by logged entries." % row["name"], "error")
    else:
        db.execute("DELETE FROM charge_types WHERE id = ? AND client_id = ?", (cid, client_id))
        db.commit()
        flash("Charge type '%s' deleted." % row["name"], "success")
    return redirect(url_for("settings", tab="charge"))



@app.route("/settings")
def settings():
    """Per-client configuration: Charge Types, Expense Categories, the client's
    invoice profile, Entry Defaults, and per-client invoice email."""
    db = get_db()
    client_id = current_client_id(db)
    charges = db.execute(
        "SELECT * FROM charge_types WHERE client_id = ? ORDER BY is_base DESC, name", (client_id,)
    ).fetchall()
    defaults = db.execute(
        "SELECT * FROM entry_defaults WHERE client_id = ? ORDER BY trigger_field, trigger_value",
        (client_id,),
    ).fetchall()
    recipients = db.execute(
        "SELECT * FROM invoice_email_recipients WHERE client_id = ? ORDER BY id", (client_id,)
    ).fetchall()
    categories = db.execute(
        "SELECT * FROM expense_categories WHERE client_id = ? ORDER BY status, name", (client_id,)
    ).fetchall()
    return render_template(
        "settings.html", charge_types=charges, profile=invoice_profile(db, client_id),
        entry_defaults=defaults, default_fields=ENTRY_DEFAULT_FIELDS,
        default_field_labels=ENTRY_DEFAULT_LABELS,
        email_recipients=recipients, recipient_kinds=EMAIL_RECIPIENT_KINDS,
        expense_categories=categories, category_statuses=CATEGORY_STATUSES,
    )


# ------------------------- expense categories -------------------------
@app.route("/expense-categories/add", methods=["POST"])
def expense_category_add():
    db = get_db()
    client_id = current_client_id(db)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("settings", tab="categories"))
    if db.execute(
        "SELECT 1 FROM expense_categories WHERE client_id = ? AND name = ?", (client_id, name)
    ).fetchone():
        flash("Category '%s' already exists." % name, "error")
    else:
        db.execute(
            "INSERT INTO expense_categories (client_id, name, status, created_at) VALUES (?,?,?,?)",
            (client_id, name, request.form.get("status") or "Active",
             datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()
        flash("Category '%s' added." % name, "success")
    return redirect(url_for("settings", tab="categories"))


@app.route("/expense-categories/update/<int:cid>", methods=["POST"])
def expense_category_update(cid):
    db = get_db()
    client_id = current_client_id(db)
    row = db.execute(
        "SELECT name FROM expense_categories WHERE id = ? AND client_id = ?", (cid, client_id)
    ).fetchone()
    if not row:
        flash("Category not found.", "error")
        return redirect(url_for("settings", tab="categories"))
    name = (request.form.get("name") or "").strip()
    status = request.form.get("status") or "Active"
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("settings", tab="categories"))
    if db.execute(
        "SELECT 1 FROM expense_categories WHERE client_id = ? AND name = ? AND id != ?",
        (client_id, name, cid),
    ).fetchone():
        flash("Another category is already named '%s'." % name, "error")
        return redirect(url_for("settings", tab="categories"))
    db.execute("UPDATE expense_categories SET name = ?, status = ? WHERE id = ? AND client_id = ?",
               (name, status, cid, client_id))
    if name != row["name"]:
        # cascade the rename to this client's expenses
        db.execute("UPDATE expenses SET category = ? WHERE client_id = ? AND category = ?",
                   (name, client_id, row["name"]))
    db.commit()
    flash("Category updated.", "success")
    return redirect(url_for("settings", tab="categories"))


@app.route("/expense-categories/delete/<int:cid>", methods=["POST"])
def expense_category_delete(cid):
    db = get_db()
    client_id = current_client_id(db)
    row = db.execute(
        "SELECT name FROM expense_categories WHERE id = ? AND client_id = ?", (cid, client_id)
    ).fetchone()
    if row:
        used = db.execute(
            "SELECT COUNT(*) c FROM expenses WHERE client_id = ? AND category = ?",
            (client_id, row["name"]),
        ).fetchone()["c"]
        if used:
            flash("Cannot delete '%s' — it is used by %d expense(s)." % (row["name"], used), "error")
            return redirect(url_for("settings", tab="categories"))
    db.execute("DELETE FROM expense_categories WHERE id = ? AND client_id = ?", (cid, client_id))
    db.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("settings", tab="categories"))


# --------------------------- entry defaults ---------------------------
@app.route("/entry-defaults/add", methods=["POST"])
def entry_defaults_add():
    db = get_db()
    client_id = current_client_id(db)
    field = request.form.get("trigger_field")
    value = (request.form.get("trigger_value") or "").strip()
    if field not in ENTRY_DEFAULT_FIELDS or not value:
        flash("A trigger field and value are required.", "error")
        return redirect(url_for("settings", tab="defaults"))
    hours = request.form.get("set_hours")
    db.execute(
        "INSERT INTO entry_defaults "
        "(client_id, trigger_field, trigger_value, set_sub_task, set_hours, set_description, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (client_id, field, value, (request.form.get("set_sub_task") or "").strip(),
         float(hours) if hours not in (None, "") else None,
         (request.form.get("set_description") or "").strip(),
         datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    flash("Entry default added.", "success")
    return redirect(url_for("settings", tab="defaults"))


@app.route("/entry-defaults/update/<int:rid>", methods=["POST"])
def entry_defaults_update(rid):
    db = get_db()
    client_id = current_client_id(db)
    if not db.execute(
        "SELECT 1 FROM entry_defaults WHERE id = ? AND client_id = ?", (rid, client_id)
    ).fetchone():
        flash("Rule not found.", "error")
        return redirect(url_for("settings", tab="defaults"))
    field = request.form.get("trigger_field")
    value = (request.form.get("trigger_value") or "").strip()
    if field not in ENTRY_DEFAULT_FIELDS or not value:
        flash("A trigger field and value are required.", "error")
        return redirect(url_for("settings", tab="defaults"))
    hours = request.form.get("set_hours")
    db.execute(
        "UPDATE entry_defaults SET trigger_field=?, trigger_value=?, set_sub_task=?, "
        "set_hours=?, set_description=? WHERE id=? AND client_id=?",
        (field, value, (request.form.get("set_sub_task") or "").strip(),
         float(hours) if hours not in (None, "") else None,
         (request.form.get("set_description") or "").strip(), rid, client_id),
    )
    db.commit()
    flash("Entry default updated.", "success")
    return redirect(url_for("settings", tab="defaults"))


@app.route("/entry-defaults/delete/<int:rid>", methods=["POST"])
def entry_defaults_delete(rid):
    db = get_db()
    client_id = current_client_id(db)
    db.execute("DELETE FROM entry_defaults WHERE id = ? AND client_id = ?", (rid, client_id))
    db.commit()
    flash("Entry default deleted.", "success")
    return redirect(url_for("settings", tab="defaults"))


# ------------------- this client's invoice profile -------------------
@app.route("/invoices/settings", methods=["POST"])
def invoice_settings():
    """Save this client's invoice profile: billing details, GST split, terms.
    (The owner's business identity is global — saved in TZ Controls.)"""
    db = get_db()
    client_id = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    def _num(name):
        try:
            return float(request.form.get(name) or 0.0)
        except ValueError:
            return 0.0
    cgst = _num("default_cgst_rate")
    sgst = _num("default_sgst_rate")
    igst = _num("default_igst_rate")
    use_igst = 1 if request.form.get("use_igst") == "1" else 0
    db.execute(
        "UPDATE client_profile SET client_name=?, client_address=?, client_gstin=?, "
        "use_igst=?, default_igst_rate=?, default_cgst_rate=?, default_sgst_rate=?, "
        "terms=?, updated_at=? WHERE client_id=?",
        (
            request.form.get("client_name"), request.form.get("client_address"),
            request.form.get("client_gstin"),
            use_igst, igst, cgst, sgst, request.form.get("terms"), now, client_id,
        ),
    )
    db.commit()
    flash("Invoice settings saved.", "success")
    return redirect(url_for("settings", tab="invoice"))


# ------------- this client's invoice email (uses global SMTP) -------------
@app.route("/email-settings", methods=["POST"])
def email_settings():
    """Save this client's invoice-email options: the auto-send toggle and the
    subject/body templates. The SMTP server itself is global (TZ Controls)."""
    db = get_db()
    client_id = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE client_profile SET email_auto_send=?, email_subject=?, email_body=?, "
        "updated_at=? WHERE client_id=?",
        (
            1 if request.form.get("email_auto_send") == "1" else 0,
            request.form.get("email_subject") or "",
            request.form.get("email_body") or "",
            now, client_id,
        ),
    )
    db.commit()
    flash("Email settings saved.", "success")
    return redirect(url_for("settings", tab="email"))


@app.route("/email-settings/reset", methods=["POST"])
def email_settings_reset():
    """Restore this client's email subject + body to the application defaults
    (leaves the auto-send toggle and recipients untouched)."""
    db = get_db()
    client_id = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE client_profile SET email_subject=?, email_body=?, updated_at=? WHERE client_id=?",
        (DEFAULT_EMAIL_SUBJECT, DEFAULT_EMAIL_BODY, now, client_id),
    )
    db.commit()
    flash("Email subject and body reset to the application default.", "success")
    return redirect(url_for("settings", tab="email"))


@app.route("/email-test", methods=["POST"])
def email_test():
    """Send a one-off test email using the global SMTP settings + this client's recipients."""
    db = get_db()
    client_id = current_client_id(db)
    recipients = db.execute(
        "SELECT email, kind FROM invoice_email_recipients WHERE client_id = ? ORDER BY id",
        (client_id,),
    ).fetchall()
    ok, msg = send_test_email(invoice_profile(db, client_id), recipients)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("settings", tab="email"))


@app.route("/email-recipients/add", methods=["POST"])
def email_recipient_add():
    db = get_db()
    client_id = current_client_id(db)
    email = (request.form.get("email") or "").strip()
    kind = request.form.get("kind")
    if kind not in EMAIL_RECIPIENT_KINDS:
        kind = "to"
    if not email:
        flash("Email address is required.", "error")
        return redirect(url_for("settings", tab="email"))
    db.execute(
        "INSERT INTO invoice_email_recipients (client_id, email, kind, created_at) VALUES (?,?,?,?)",
        (client_id, email, kind, datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    flash("Recipient added.", "success")
    return redirect(url_for("settings", tab="email"))


@app.route("/email-recipients/delete/<int:rid>", methods=["POST"])
def email_recipient_delete(rid):
    db = get_db()
    client_id = current_client_id(db)
    db.execute("DELETE FROM invoice_email_recipients WHERE id = ? AND client_id = ?", (rid, client_id))
    db.commit()
    flash("Recipient removed.", "success")
    return redirect(url_for("settings", tab="email"))
