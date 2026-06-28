"""Timesheet routes: month calendar (entry) and per-day editing.

All queries are scoped to the currently-selected client via
``current_client_id``; the ``timesheet_days`` upserts target the composite
primary key ``(client_id, work_date)``.
"""
import calendar
from datetime import date, datetime

from flask import render_template, request, redirect, url_for, flash

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db
from timezone.services import *        # noqa: F401,F403
from timezone.services import _add_months  # private helper


def _is_weekend(work_date):
    """True for a Saturday/Sunday work_date (YYYY-MM-DD)."""
    try:
        return datetime.strptime(work_date, "%Y-%m-%d").date().weekday() >= 5
    except (TypeError, ValueError):
        return False


def _charge_by_name(charges, name):
    """Return the charge-type name matching `name` (spaces/case ignored), or None."""
    key = (name or "").replace(" ", "").lower()
    for c in charges:
        if (c["name"] or "").replace(" ", "").lower() == key:
            return c["name"]
    return None


def _add_charge_options(charges, work_date, total):
    """Charge options + default for the Add-entry form, applying the day rules:
    a weekend, or a day already at HOURS_PER_DAY, drops the base "Regular" rate;
    weekends default to the weekend charge, full days to the OverTime charge.
    Returns (options, default_name, note)."""
    base = next((c["name"] for c in charges if c["is_base"]), None)
    first_non_base = next((c["name"] for c in charges if not c["is_base"]), base)
    weekend = _is_weekend(work_date)
    day_full = total >= HOURS_PER_DAY
    hide_base = weekend or day_full
    options = [c for c in charges if not (hide_base and c["is_base"])]
    if weekend:
        default = _charge_by_name(charges, WEEKEND_CHARGE) or first_non_base
        note = ("Weekend — the base rate isn't available; defaulting to %s." % default) if default else None
    elif day_full:
        default = _charge_by_name(charges, OVERTIME_CHARGE) or first_non_base
        note = ("%g h already logged — extra time defaults to %s." % (HOURS_PER_DAY, default)) if default else None
    else:
        default, note = base, None
    return options, default, note


def _enforce_charge(db, cid, work_date, charge_method):
    """Coerce a submitted base "Regular" charge to the rule's charge when the day
    is a weekend or already full — a safety net behind the Add-form dropdown."""
    charges = db.execute(
        "SELECT * FROM charge_types WHERE client_id = ? ORDER BY is_base DESC, name", (cid,)
    ).fetchall()
    base = next((c["name"] for c in charges if c["is_base"]), None)
    if not base or charge_method != base:
        return charge_method
    total = db.execute(
        "SELECT COALESCE(SUM(hours),0) h FROM timesheet_entries WHERE client_id = ? AND work_date = ?",
        (cid, work_date),
    ).fetchone()["h"] or 0.0
    weekend = _is_weekend(work_date)
    if not (weekend or total >= HOURS_PER_DAY):
        return charge_method
    target = WEEKEND_CHARGE if weekend else OVERTIME_CHARGE
    return _charge_by_name(charges, target) \
        or next((c["name"] for c in charges if not c["is_base"]), base)


@app.route("/entry")
def entry():
    db = get_db()
    cid = current_client_id(db)
    month_str = request.args.get("month") or date.today().strftime("%Y-%m")
    try:
        year, month = map(int, month_str.split("-"))
    except ValueError:
        year, month = date.today().year, date.today().month
    weeks = month_calendar(db, cid, year, month)
    prev_y, prev_m = _add_months(year, month, -1)
    next_y, next_m = _add_months(year, month, 1)

    # all days that have entries within the selected month
    days_in_month = calendar.monthrange(year, month)[1]
    m_start = date(year, month, 1).isoformat()
    m_end = date(year, month, days_in_month).isoformat()
    recent = db.execute(
        "SELECT e.work_date, COALESCE(SUM(e.hours),0) hours "
        "FROM timesheet_entries e WHERE e.client_id = ? AND e.work_date >= ? AND e.work_date <= ? "
        "GROUP BY e.work_date ORDER BY e.work_date DESC",
        (cid, m_start, m_end),
    ).fetchall()
    recent_days = []
    for r in recent:
        status, day_type = day_record(db, cid, r["work_date"])
        recent_days.append({
            "work_date": r["work_date"],
            "hours": r["hours"],
            "status": status,
            "day_type": day_type,
        })

    # completion for the selected month (working days = Mon-Fri minus off-days)
    weekdays = sum(1 for d in range(1, days_in_month + 1)
                   if date(year, month, d).weekday() < 5)
    offdays = month_offdays(db, cid, year, month)
    working_days = max(weekdays - offdays, 0)
    target = working_days * HOURS_PER_DAY
    achieved = db.execute(
        "SELECT COALESCE(SUM(hours),0) h FROM timesheet_entries "
        "WHERE client_id = ? AND work_date >= ? AND work_date <= ?",
        (cid, date(year, month, 1).isoformat(), date(year, month, days_in_month).isoformat()),
    ).fetchone()["h"] or 0.0
    pct = (achieved / target * 100.0) if target else 0.0
    month_progress = {
        "achieved": round(achieved, 2),
        "target": target,
        "working_days": working_days,
        "offdays": offdays,
        "pct": pct,
        "pct_bar": min(pct, 100.0),
    }

    return render_template(
        "entry.html",
        weeks=weeks,
        year=year, month=month,
        month_label=date(year, month, 1).strftime("%B %Y"),
        prev_month="%04d-%02d" % (prev_y, prev_m),
        next_month="%04d-%02d" % (next_y, next_m),
        recent_days=recent_days,
        month_progress=month_progress,
        HOURS_PER_DAY=HOURS_PER_DAY,
    )


@app.route("/day")
def day():
    db = get_db()
    cid = current_client_id(db)
    work_date = request.args.get("date") or date.today().isoformat()
    status, day_type = day_record(db, cid, work_date)
    entries = db.execute(
        "SELECT * FROM timesheet_entries WHERE client_id = ? AND work_date = ? ORDER BY id",
        (cid, work_date),
    ).fetchall()
    total = sum((e["hours"] or 0) for e in entries)
    active_tasks = db.execute(
        "SELECT * FROM tasks WHERE client_id = ? AND status = 'Active' ORDER BY task_id", (cid,)
    ).fetchall()
    active_subtasks = db.execute(
        "SELECT * FROM subtasks WHERE client_id = ? AND status = 'Active' ORDER BY name", (cid,)
    ).fetchall()
    charges = db.execute(
        "SELECT * FROM charge_types WHERE client_id = ? ORDER BY is_base DESC, name", (cid,)
    ).fetchall()
    entry_rules = [
        {"field": r["trigger_field"], "value": r["trigger_value"],
         "sub_task": r["set_sub_task"], "hours": r["set_hours"],
         "description": r["set_description"]}
        for r in db.execute("SELECT * FROM entry_defaults WHERE client_id = ?", (cid,))
    ]
    # task_id -> [sub_tasks already logged that day] (to block duplicate combos)
    used_combos = {}
    for e in entries:
        used_combos.setdefault(e["task_id"], []).append(e["sub_task"] or "")
    # Add-form charge options/default: weekend or a full (>= 8 h) day drops the
    # base "Regular" rate and defaults to the weekend / OverTime charge.
    add_charges, default_charge, charge_note = _add_charge_options(charges, work_date, total)
    return render_template(
        "day.html",
        work_date=work_date,
        status=status, day_type=day_type,
        entries=entries, total=total,
        active_tasks=active_tasks,
        active_subtasks=active_subtasks,
        charges=charges,
        add_charges=add_charges, default_charge=default_charge, charge_note=charge_note,
        day_types=DAY_TYPES,
        hours_options=HOURS_OPTIONS,
        entry_rules=entry_rules,
        used_combos=used_combos,
        DESC_MAX=DESC_MAX,
    )


@app.route("/day/add", methods=["POST"])
def day_add():
    db = get_db()
    cid = current_client_id(db)
    work_date = request.form.get("date")
    status, day_type = day_record(db, cid, work_date)
    if status == "submitted":
        flash("Day is submitted (locked). Unsubmit to edit.", "error")
        return redirect(url_for("day", date=work_date))
    if day_type != "working":
        flash("Cannot add entries to a %s day." % DAY_TYPE_LABELS.get(day_type, day_type), "error")
        return redirect(url_for("day", date=work_date))

    task_id = request.form.get("task_id") or ""
    sub_task = request.form.get("sub_task") or ""
    description = (request.form.get("description") or "")[:DESC_MAX]
    charge_method = request.form.get("charge_method") or ""
    try:
        hours = float(request.form.get("hours") or 0)
    except ValueError:
        hours = 0
    if hours <= 0:
        flash("Hours must be greater than 0.", "error")
        return redirect(url_for("day", date=work_date))
    # a weekend / full day can't use the base "Regular" rate (matches the form)
    charge_method = _enforce_charge(db, cid, work_date, charge_method)
    dup = db.execute(
        "SELECT 1 FROM timesheet_entries "
        "WHERE client_id = ? AND work_date = ? AND task_id = ? AND IFNULL(sub_task,'') = ?",
        (cid, work_date, task_id, sub_task),
    ).fetchone()
    if dup:
        flash("That Task + Sub Task is already logged for this day.", "error")
        return redirect(url_for("day", date=work_date))
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO timesheet_entries "
        "(client_id, work_date, task_id, sub_task, description, hours, charge_method, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (cid, work_date, task_id, sub_task, description, hours, charge_method, now),
    )
    # ensure a day row exists (draft/working)
    db.execute(
        "INSERT INTO timesheet_days (client_id, work_date, status, day_type, updated_at) "
        "VALUES (?, ?, 'draft', 'working', ?) "
        "ON CONFLICT(client_id, work_date) DO UPDATE SET updated_at = excluded.updated_at",
        (cid, work_date, now),
    )
    db.commit()
    flash("Entry added.", "success")
    return redirect(url_for("day", date=work_date))


@app.route("/day/entry/update/<int:entry_id>", methods=["POST"])
def day_entry_update(entry_id):
    """Edit a single existing entry (blocked while the day is submitted)."""
    db = get_db()
    cid = current_client_id(db)
    row = db.execute(
        "SELECT work_date FROM timesheet_entries WHERE id = ? AND client_id = ?",
        (entry_id, cid),
    ).fetchone()
    if not row:
        return redirect(url_for("entry"))
    work_date = row["work_date"]
    status, _ = day_record(db, cid, work_date)
    if status == "submitted":
        flash("Day is submitted (locked). Unsubmit to edit.", "error")
        return redirect(url_for("day", date=work_date))
    task_id = request.form.get("task_id") or ""
    sub_task = request.form.get("sub_task") or ""
    description = (request.form.get("description") or "")[:DESC_MAX]
    charge_method = request.form.get("charge_method") or ""
    try:
        hours = float(request.form.get("hours") or 0)
    except ValueError:
        hours = 0
    if hours <= 0:
        flash("Hours must be greater than 0.", "error")
        return redirect(url_for("day", date=work_date))
    dup = db.execute(
        "SELECT 1 FROM timesheet_entries "
        "WHERE client_id = ? AND work_date = ? AND task_id = ? AND IFNULL(sub_task,'') = ? AND id <> ?",
        (cid, work_date, task_id, sub_task, entry_id),
    ).fetchone()
    if dup:
        flash("That Task + Sub Task is already logged for this day.", "error")
        return redirect(url_for("day", date=work_date))
    db.execute(
        "UPDATE timesheet_entries SET task_id=?, sub_task=?, description=?, hours=?, "
        "charge_method=? WHERE id=? AND client_id=?",
        (task_id, sub_task, description, hours, charge_method, entry_id, cid),
    )
    db.commit()
    flash("Entry updated.", "success")
    return redirect(url_for("day", date=work_date))


@app.route("/day/delete/<int:entry_id>", methods=["POST"])
def day_delete(entry_id):
    db = get_db()
    cid = current_client_id(db)
    row = db.execute(
        "SELECT work_date FROM timesheet_entries WHERE id = ? AND client_id = ?",
        (entry_id, cid),
    ).fetchone()
    if not row:
        return redirect(url_for("entry"))
    work_date = row["work_date"]
    status, _ = day_record(db, cid, work_date)
    if status == "submitted":
        flash("Day is submitted (locked). Unsubmit to edit.", "error")
        return redirect(url_for("day", date=work_date))
    db.execute("DELETE FROM timesheet_entries WHERE id = ? AND client_id = ?", (entry_id, cid))
    db.commit()
    flash("Entry deleted.", "success")
    return redirect(url_for("day", date=work_date))


@app.route("/day/type", methods=["POST"])
def day_type_set():
    db = get_db()
    cid = current_client_id(db)
    work_date = request.form.get("date")
    new_type = request.form.get("day_type")
    if new_type not in DAY_TYPES:
        flash("Invalid day type.", "error")
        return redirect(url_for("day", date=work_date))
    now = datetime.now().isoformat(timespec="seconds")
    if new_type in ("holiday", "leave"):
        has_entries = db.execute(
            "SELECT COUNT(*) c FROM timesheet_entries WHERE client_id = ? AND work_date = ?",
            (cid, work_date),
        ).fetchone()["c"]
        if has_entries:
            flash("Remove entries before marking this day as %s." %
                  DAY_TYPE_LABELS[new_type], "error")
            return redirect(url_for("day", date=work_date))
        # clears any submitted lock -> back to draft
        db.execute(
            "INSERT INTO timesheet_days (client_id, work_date, status, day_type, updated_at) "
            "VALUES (?, ?, 'draft', ?, ?) "
            "ON CONFLICT(client_id, work_date) DO UPDATE SET status='draft', day_type=excluded.day_type, "
            "updated_at=excluded.updated_at",
            (cid, work_date, new_type, now),
        )
    else:
        db.execute(
            "INSERT INTO timesheet_days (client_id, work_date, status, day_type, updated_at) "
            "VALUES (?, ?, 'draft', 'working', ?) "
            "ON CONFLICT(client_id, work_date) DO UPDATE SET day_type='working', updated_at=excluded.updated_at",
            (cid, work_date, now),
        )
    db.commit()
    flash("Day set to %s." % DAY_TYPE_LABELS[new_type], "success")
    return redirect(url_for("day", date=work_date))


@app.route("/day/submit", methods=["POST"])
def day_submit():
    db = get_db()
    cid = current_client_id(db)
    work_date = request.form.get("date")
    has_entries = db.execute(
        "SELECT COUNT(*) c FROM timesheet_entries WHERE client_id = ? AND work_date = ?",
        (cid, work_date),
    ).fetchone()["c"]
    if not has_entries:
        flash("Add at least one entry before submitting.", "error")
        return redirect(url_for("day", date=work_date))
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO timesheet_days (client_id, work_date, status, day_type, updated_at) "
        "VALUES (?, ?, 'submitted', 'working', ?) "
        "ON CONFLICT(client_id, work_date) DO UPDATE SET status='submitted', updated_at=excluded.updated_at",
        (cid, work_date, now),
    )
    db.commit()
    flash("Day submitted and locked.", "success")
    # return to the month calendar (the page the day was opened from)
    return redirect(url_for("entry", month=(work_date or "")[:7]))


@app.route("/day/unsubmit", methods=["POST"])
def day_unsubmit():
    db = get_db()
    cid = current_client_id(db)
    work_date = request.form.get("date")
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE timesheet_days SET status='draft', updated_at=? WHERE client_id=? AND work_date=?",
        (now, cid, work_date),
    )
    db.commit()
    flash("Day unsubmitted (draft).", "success")
    return redirect(url_for("day", date=work_date))
