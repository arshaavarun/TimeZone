"""Expense tracker routes (scoped to the current client).

Expenses, their attachments and the expense-category master list are all
per-client; every query is filtered by ``current_client_id``.
"""
import calendar
import os
from datetime import date, datetime

from flask import (
    render_template, request, redirect, url_for, flash, send_file, abort,
)
from werkzeug.utils import secure_filename

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db
from timezone.services import *        # noqa: F401,F403
from timezone.services import _add_months  # private helper



@app.route("/expenses")
def expenses():
    db = get_db()
    cid = current_client_id(db)
    # roll active subscriptions forward through any billing cycles that are now due
    advance_subscription_cycles(db, cid)
    # The year filter always shows one specific year (current by default) — there
    # is no "all years" option, so an absent/empty year falls back to this year.
    year = request.args.get("year")
    if not year:
        year = str(date.today().year)
    purpose = request.args.get("purpose") or ""

    q = "SELECT * FROM expenses WHERE client_id = ?"
    params = [cid]
    if year:
        q += " AND substr(date_purchased,1,4) = ?"
        params.append(year)
    if purpose:
        q += " AND purpose = ?"
        params.append(purpose)
    q += " ORDER BY date_purchased DESC, id DESC"
    rows = db.execute(q, params).fetchall()

    # attachments per expense (this client only)
    atts = {}
    for a in db.execute("SELECT * FROM expense_attachments WHERE client_id = ? ORDER BY id", (cid,)):
        atts.setdefault(a["expense_id"], []).append(a)

    # warranty / subscription-renewal highlight
    today = date.today()
    warn_cut_y, warn_cut_m = _add_months(today.year, today.month, WARRANTY_WARN_MONTHS)
    warn_cutoff = date(warn_cut_y, warn_cut_m, calendar.monthrange(warn_cut_y, warn_cut_m)[1])

    def date_state(iso):
        """'expired' if the date has passed, 'warn' if it falls within the
        warning window, else '' — shared by warranty and subscription dates."""
        if not iso:
            return ""
        try:
            d = datetime.strptime(iso, "%Y-%m-%d").date()
        except ValueError:
            return ""
        if d < today:
            return "expired"
        if d <= warn_cutoff:
            return "warn"
        return ""

    # Each row is one billing cycle (or a one-off expense) and counts its price
    # once. Active subscription cycles + ordinary expenses go in "Items";
    # completed/closed subscription cycles drop into the history table below.
    totals = {p: {c: 0.0 for c in CURRENCIES} for p in EXPENSE_PURPOSES}
    grand = {c: 0.0 for c in CURRENCIES}
    cat_by_purpose = {p: {} for p in EXPENSE_PURPOSES}
    items, past_cycles = [], []
    for r in rows:
        atts_r = atts.get(r["id"], [])
        price = r["price"] or 0.0

        # totals: every started cycle / expense adds its price once
        p = r["purpose"] or "Official"
        c = r["currency"] or "INR"
        totals.setdefault(p, {ccy: 0.0 for ccy in CURRENCIES})
        totals[p][c] = totals[p].get(c, 0.0) + price
        grand[c] = grand.get(c, 0.0) + price
        # the same amount also rolls up by category, within its purpose
        cat = r["category"] or "Uncategorized"
        cat_by_purpose.setdefault(p, {})
        cat_by_purpose[p].setdefault(cat, {ccy: 0.0 for ccy in CURRENCIES})
        cat_by_purpose[p][cat][c] = cat_by_purpose[p][cat].get(c, 0.0) + price

        enriched = {"row": r, "atts": atts_r}
        status = (r["subscription_status"] or "active") if r["is_subscription"] else None
        if r["is_subscription"] and status in ("completed", "closed"):
            past_cycles.append(enriched)
            continue
        # active subscriptions are highlighted on their next billing date,
        # everything else on its warranty date (sub-* vs warranty-* -> blue vs amber).
        if r["is_subscription"]:
            state = date_state(r["subscription_end"])
            enriched.update(warranty_state="", sub_state=state,
                            row_class=("sub-" + state) if state else "")
        else:
            state = date_state(r["warranty_till"])
            enriched.update(warranty_state=state, sub_state="",
                            row_class=("warranty-" + state) if state else "")
        items.append(enriched)

    years = [r["y"] for r in db.execute(
        "SELECT DISTINCT substr(date_purchased,1,4) y FROM expenses WHERE client_id = ? ORDER BY y DESC",
        (cid,),
    ) if r["y"]]
    # always offer the current year in the filter, even before it has any rows
    cur_year = str(date.today().year)
    if cur_year not in years:
        years = sorted(set(years) | {cur_year}, reverse=True)

    # per-purpose category sub-totals: by name, with "Uncategorized" last
    cat_by_purpose_rows = {
        p: sorted(cats.items(), key=lambda kv: (kv[0] == "Uncategorized", kv[0].lower()))
        for p, cats in cat_by_purpose.items()
    }

    return render_template(
        "expenses.html",
        items=items, past_cycles=past_cycles,
        totals=totals, grand=grand, cat_by_purpose=cat_by_purpose_rows,
        purposes=EXPENSE_PURPOSES, currencies=CURRENCIES,
        years=years, sel_year=year, sel_purpose=purpose,
        today=date.today().isoformat(),
    )


def _subscription_fields(form):
    """Read the subscription inputs from an expense form. Returns
    (is_subscription, period, end_date); a non-subscription is (0, None, None).
    The end date is computed server-side so it always matches the purchase date
    and chosen period regardless of what the browser sent."""
    if form.get("is_subscription") != "1":
        return 0, None, None
    period = form.get("subscription_period")
    if period not in SUBSCRIPTION_PERIODS:
        period = SUBSCRIPTION_PERIODS[0]   # default to Monthly
    end = subscription_end_date(form.get("date_purchased"), period)
    return 1, period, end


def _active_categories(db, client_id):
    """Active expense category names for the form dropdown (this client)."""
    return [r["name"] for r in db.execute(
        "SELECT name FROM expense_categories WHERE client_id = ? AND status = 'Active' ORDER BY name",
        (client_id,))]


def _save_attachments(db, client_id, expense_id, files):
    now = datetime.now().isoformat(timespec="seconds")
    for f in files:
        if not f or not f.filename:
            continue
        safe = secure_filename(f.filename)
        stored = "%d_%s" % (expense_id, safe)
        path = os.path.join(ATTACH_DIR, stored)
        # avoid clobbering: if a file with that name exists, add a counter
        counter = 1
        while os.path.exists(path):
            stored = "%d_%d_%s" % (expense_id, counter, safe)
            path = os.path.join(ATTACH_DIR, stored)
            counter += 1
        f.save(path)
        db.execute(
            "INSERT INTO expense_attachments "
            "(client_id, expense_id, stored_name, original_name, content_type, uploaded_at) "
            "VALUES (?,?,?,?,?,?)",
            (client_id, expense_id, stored, f.filename, f.content_type, now),
        )


@app.route("/expenses/new", methods=["GET", "POST"])
def expense_new():
    db = get_db()
    cid = current_client_id(db)
    if request.method == "POST":
        now = datetime.now().isoformat(timespec="seconds")
        is_sub, sub_period, sub_end = _subscription_fields(request.form)
        # subscriptions have no warranty — that field is blocked on the form
        warranty = None if is_sub else (request.form.get("warranty_till") or None)
        cur = db.execute(
            "INSERT INTO expenses "
            "(client_id, date_purchased, item, price, currency, purchased_at, warranty_till, purpose, category, "
            "is_subscription, subscription_period, subscription_end, subscription_status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                request.form.get("date_purchased"),
                (request.form.get("item") or "").strip(),
                float(request.form.get("price") or 0),
                request.form.get("currency") or "INR",
                (request.form.get("purchased_at") or "").strip(),
                warranty,
                request.form.get("purpose") or "Official",
                (request.form.get("category") or "").strip() or None,
                is_sub, sub_period, sub_end, ("active" if is_sub else None),
                now,
            ),
        )
        eid = cur.lastrowid
        _save_attachments(db, cid, eid, request.files.getlist("attachments"))
        db.commit()
        flash("Expense added.", "success")
        return redirect(url_for("expenses"))
    return render_template(
        "expense_form.html",
        expense=None, attachments=[],
        purposes=EXPENSE_PURPOSES, currencies=CURRENCIES,
        subscription_periods=SUBSCRIPTION_PERIODS,
        categories=_active_categories(db, cid),
        today=date.today().isoformat(),
    )


@app.route("/expenses/<int:eid>/edit", methods=["GET", "POST"])
def expense_edit(eid):
    db = get_db()
    cid = current_client_id(db)
    expense = db.execute(
        "SELECT * FROM expenses WHERE id = ? AND client_id = ?", (eid, cid)
    ).fetchone()
    if not expense:
        abort(404)
    if request.method == "POST":
        is_sub, sub_period, sub_end = _subscription_fields(request.form)
        warranty = None if is_sub else (request.form.get("warranty_till") or None)
        # preserve the cycle's status/close-date while it stays a subscription;
        # clear both if the row is no longer a subscription at all
        if is_sub:
            status = expense["subscription_status"] or "active"
            ended_on = expense["subscription_ended_on"]
        else:
            status, ended_on = None, None
        db.execute(
            "UPDATE expenses SET date_purchased=?, item=?, price=?, currency=?, "
            "purchased_at=?, warranty_till=?, purpose=?, category=?, "
            "is_subscription=?, subscription_period=?, subscription_end=?, "
            "subscription_status=?, subscription_ended_on=? WHERE id=? AND client_id=?",
            (
                request.form.get("date_purchased"),
                (request.form.get("item") or "").strip(),
                float(request.form.get("price") or 0),
                request.form.get("currency") or "INR",
                (request.form.get("purchased_at") or "").strip(),
                warranty,
                request.form.get("purpose") or "Official",
                (request.form.get("category") or "").strip() or None,
                is_sub, sub_period, sub_end, status, ended_on,
                eid, cid,
            ),
        )
        _save_attachments(db, cid, eid, request.files.getlist("attachments"))
        db.commit()
        flash("Expense updated.", "success")
        return redirect(url_for("expenses"))
    attachments = db.execute(
        "SELECT * FROM expense_attachments WHERE client_id = ? AND expense_id = ? ORDER BY id",
        (cid, eid),
    ).fetchall()
    return render_template(
        "expense_form.html",
        expense=expense, attachments=attachments,
        purposes=EXPENSE_PURPOSES, currencies=CURRENCIES,
        subscription_periods=SUBSCRIPTION_PERIODS,
        categories=_active_categories(db, cid),
        today=date.today().isoformat(),
    )


@app.route("/expenses/<int:eid>/delete", methods=["POST"])
def expense_delete(eid):
    db = get_db()
    cid = current_client_id(db)
    atts = db.execute(
        "SELECT stored_name FROM expense_attachments WHERE client_id = ? AND expense_id = ?",
        (cid, eid),
    ).fetchall()
    for a in atts:
        try:
            os.remove(os.path.join(ATTACH_DIR, a["stored_name"]))
        except OSError:
            pass
    db.execute("DELETE FROM expense_attachments WHERE client_id = ? AND expense_id = ?", (cid, eid))
    db.execute("DELETE FROM expenses WHERE id = ? AND client_id = ?", (eid, cid))
    db.commit()
    flash("Expense deleted.", "success")
    return redirect(url_for("expenses"))


@app.route("/expenses/<int:eid>/end-subscription", methods=["POST"])
def expense_end_subscription(eid):
    """Close a subscription on a given date: the current cycle is kept (it was
    charged) but no further cycles are created. It moves to the history table."""
    db = get_db()
    cid = current_client_id(db)
    row = db.execute(
        "SELECT is_subscription FROM expenses WHERE id = ? AND client_id = ?", (eid, cid)
    ).fetchone()
    if not row:
        abort(404)
    if not row["is_subscription"]:
        flash("That expense is not a subscription.", "error")
        return redirect(url_for("expenses"))
    ended_on = request.form.get("ended_on") or date.today().isoformat()
    db.execute(
        "UPDATE expenses SET subscription_status = 'closed', subscription_ended_on = ? "
        "WHERE id = ? AND client_id = ?",
        (ended_on, eid, cid),
    )
    db.commit()
    flash("Subscription closed.", "success")
    return redirect(url_for("expenses"))


@app.route("/expense/attachment/<int:att_id>")
def expense_attachment(att_id):
    db = get_db()
    cid = current_client_id(db)
    a = db.execute(
        "SELECT * FROM expense_attachments WHERE id = ? AND client_id = ?", (att_id, cid)
    ).fetchone()
    if not a:
        abort(404)
    path = os.path.join(ATTACH_DIR, a["stored_name"])
    if not os.path.exists(path):
        abort(404)
    return send_file(
        path,
        mimetype=a["content_type"] or "application/octet-stream",
        as_attachment=False,
        download_name=a["original_name"] or a["stored_name"],
    )
