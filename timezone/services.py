"""
Business logic — pure helpers that take a DB connection and compute things.

No Flask request/response handling lives here; everything is unit-testable in
isolation. Covers charge rates, the timesheet calendar/progress maths, and all
invoice calculations (line generation, totals, numbering, display rounding).

Multi-client
------------
Every helper that touches a per-client table takes a ``client_id`` and scopes its
queries to it, so two clients never see each other's data. ``current_client_id``
/ ``current_client`` resolve the selected client from the Flask session.
``app_settings`` (global business identity + SMTP) and ``client_profile`` (the
per-client invoice/email profile) replace the old single ``invoice_profile`` row.
"""
import calendar
import random
from datetime import date, datetime

from flask import session
from werkzeug.security import generate_password_hash, check_password_hash

from timezone.config import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# Current client resolution (session-backed, per browser)
# --------------------------------------------------------------------------
def current_client_id(db):
    """The selected client's id. Read from the Flask session and validated; falls
    back to the first active client, or the lowest-id client if none are active.
    Returns None only when there are no clients at all."""
    cid = session.get("client_id")
    if cid is not None:
        row = db.execute("SELECT id FROM clients WHERE id = ?", (cid,)).fetchone()
        if row:
            return row["id"]
    row = db.execute(
        "SELECT id FROM clients ORDER BY (status = 'active') DESC, id LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def current_client(db):
    """The selected client's full row (or None)."""
    cid = current_client_id(db)
    if cid is None:
        return None
    return db.execute("SELECT * FROM clients WHERE id = ?", (cid,)).fetchone()


def client_hue(client):
    """The accent hue (0-359) for a client, used to build the faded page-background
    gradient and to tint the top-bar clock icon. If the client has a manual
    ``color_hue`` override it wins; otherwise the hue is derived deterministically
    from the client id via the golden angle (good spread around the wheel).
    Returns None when there is no client."""
    if not client:
        return None
    try:
        override = client["color_hue"]
    except (IndexError, KeyError):
        override = None
    if override is not None and override != "":
        return int(override) % 360
    return round(client["id"] * 137.508) % 360


def pick_distinct_hue(existing, min_gap=40, tries=64):
    """Choose a hue (0-359) visually distinct from every hue in ``existing`` (a list
    of 0-359 ints; None entries are ignored). Returns a hue at least ``min_gap``
    degrees from all of them when one is found; otherwise the candidate that
    maximises the smallest gap. Randomised, so the "Auto colour" button keeps
    producing a fresh colour on each press instead of the same deterministic one."""
    others = [h % 360 for h in existing if h is not None]
    if not others:
        return random.randint(0, 359)

    def smallest_gap(h):
        return min(min((h - o) % 360, (o - h) % 360) for o in others)

    best, best_gap = random.randint(0, 359), -1
    for _ in range(tries):
        cand = random.randint(0, 359)
        gap = smallest_gap(cand)
        if gap > best_gap:
            best, best_gap = cand, gap
        if gap >= min_gap:          # clearly distinct — accept it (keeps variety)
            return cand
    return best


def app_settings(db):
    """The single global settings row (id = 1): business identity + SMTP server."""
    return db.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()


# --------------------------------------------------------------------------
# Owner login (single shared password, hashed in app_settings)
# --------------------------------------------------------------------------
def owner_password_is_set(db):
    """True once the owner has set a login password (first-run setup done)."""
    row = app_settings(db)
    try:
        return bool(row and (row["owner_password_hash"] or "").strip())
    except (IndexError, KeyError):
        return False


def set_owner_password(db, raw):
    """Store a (salted, hashed) owner password. Commits."""
    db.execute(
        "UPDATE app_settings SET owner_password_hash = ? WHERE id = 1",
        (generate_password_hash(raw),),
    )
    db.commit()


def check_owner_password(db, raw):
    """Verify a candidate password against the stored hash."""
    row = app_settings(db)
    try:
        h = row["owner_password_hash"] if row else None
    except (IndexError, KeyError):
        h = None
    return bool(h) and check_password_hash(h, raw)


def client_profile(db, client_id):
    """The per-client invoice/email profile row for ``client_id``."""
    return db.execute(
        "SELECT * FROM client_profile WHERE client_id = ?", (client_id,)
    ).fetchone()


def invoice_profile(db, client_id):
    """Merged invoice profile: the global business identity + SMTP (``app_settings``)
    combined with this client's billing/GST/email settings (``client_profile``),
    shaped like the old single ``invoice_profile`` row so the invoice templates,
    the PDF builder and the mailer can all consume one object unchanged.

    Replaces the former ``services._profile`` helper.
    """
    a = app_settings(db)
    c = client_profile(db, client_id)

    def g(row, key, default=None):
        if row is None:
            return default
        try:
            val = row[key]
        except (IndexError, KeyError):
            return default
        return default if val is None else val

    cgst = g(c, "default_cgst_rate", 0.0) or 0.0
    sgst = g(c, "default_sgst_rate", 0.0) or 0.0
    use_igst = int(g(c, "use_igst", 1) or 0)
    igst = g(c, "default_igst_rate", 0.0) or 0.0
    return {
        # ---- global business identity + SMTP (shared by all clients) ----
        "biz_name": g(a, "biz_name", ""), "biz_address": g(a, "biz_address", ""),
        "biz_email": g(a, "biz_email", ""), "biz_gstin": g(a, "biz_gstin", ""),
        "bank_details": g(a, "bank_details", ""),
        "smtp_host": g(a, "smtp_host", ""), "smtp_port": g(a, "smtp_port", 587),
        "smtp_user": g(a, "smtp_user", ""), "smtp_password": g(a, "smtp_password", ""),
        "smtp_use_tls": g(a, "smtp_use_tls", 1),
        "smtp_from_name": g(a, "smtp_from_name", ""),
        "smtp_from_email": g(a, "smtp_from_email", ""),
        # ---- per-client billing / GST / email ----
        "client_name": g(c, "client_name", ""), "client_address": g(c, "client_address", ""),
        "client_gstin": g(c, "client_gstin", ""),
        "default_cgst_rate": cgst, "default_sgst_rate": sgst,
        "default_use_igst": use_igst, "default_igst_rate": igst,
        "default_tax_rate": (igst if use_igst else cgst + sgst), "default_tax_label": "GST",
        "terms": g(c, "terms", ""),
        "email_subject": g(c, "email_subject", ""), "email_body": g(c, "email_body", ""),
        "email_auto_send": g(c, "email_auto_send", 0),
    }


# --------------------------------------------------------------------------
# Charge rates
# --------------------------------------------------------------------------
def recompute_charge_amounts(db, client_id):
    """Every non-base type: amount_usd = base * percent/100, 2dp (within client)."""
    base = db.execute(
        "SELECT amount_usd FROM charge_types WHERE is_base = 1 AND client_id = ?",
        (client_id,),
    ).fetchone()
    if not base:
        return
    base_amt = base["amount_usd"] or 0.0
    for row in db.execute(
        "SELECT id, percent FROM charge_types WHERE is_base = 0 AND client_id = ?",
        (client_id,),
    ):
        amt = round(base_amt * (row["percent"] or 0.0) / 100.0, 2)
        db.execute("UPDATE charge_types SET amount_usd = ? WHERE id = ?", (amt, row["id"]))
    db.commit()


def charge_rate_map(db, client_id):
    """{name -> amount_usd} for one client."""
    return {
        r["name"]: r["amount_usd"]
        for r in db.execute(
            "SELECT name, amount_usd FROM charge_types WHERE client_id = ?", (client_id,)
        )
    }


# --------------------------------------------------------------------------
# Timesheet calendar / progress
# --------------------------------------------------------------------------
def day_record(db, client_id, work_date):
    """Return (status, day_type); a missing row = draft + working."""
    row = db.execute(
        "SELECT status, day_type FROM timesheet_days WHERE client_id = ? AND work_date = ?",
        (client_id, work_date),
    ).fetchone()
    if row:
        return row["status"], (row["day_type"] or "working")
    return "draft", "working"


def day_hours(db, client_id, work_date):
    row = db.execute(
        "SELECT COALESCE(SUM(hours),0) h FROM timesheet_entries "
        "WHERE client_id = ? AND work_date = ?",
        (client_id, work_date),
    ).fetchone()
    return row["h"] or 0.0


def month_offdays(db, client_id, year, month):
    """Count of weekdays (Mon-Fri) in the month marked Holiday/Leave."""
    n = 0
    days_in_month = calendar.monthrange(year, month)[1]
    for d in range(1, days_in_month + 1):
        dt = date(year, month, d)
        if dt.weekday() >= 5:  # Sat/Sun
            continue
        _, day_type = day_record(db, client_id, dt.isoformat())
        if day_type in ("holiday", "leave"):
            n += 1
    return n


def month_calendar(db, client_id, year, month):
    """Sunday-first grid of weeks; each cell carries date + colour state."""
    cal = calendar.Calendar(firstweekday=6)  # 6 = Sunday
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        row = []
        for dt in week:
            if dt.month != month:
                row.append({"day": dt.day, "date": dt.isoformat(), "state": "out", "hours": 0})
                continue
            _, day_type = day_record(db, client_id, dt.isoformat())
            hours = day_hours(db, client_id, dt.isoformat())
            if day_type == "holiday":
                state = "holiday"
            elif day_type == "leave":
                state = "leave"
            elif hours <= 0:
                state = "none"
            elif hours < HOURS_PER_DAY:
                state = "partial"
            else:
                state = "complete"
            row.append({"day": dt.day, "date": dt.isoformat(), "state": state, "hours": hours})
        weeks.append(row)
    return weeks


def monthly_progress(db, client_id):
    """Previous-to-last, last, and current month completion summaries."""
    today = date.today()
    months = []
    # build the three (year, month) tuples ending with current
    y, m = today.year, today.month
    seq = []
    for back in (2, 1, 0):
        mm = m - back
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        seq.append((yy, mm))
    for (yy, mm) in seq:
        days_in_month = calendar.monthrange(yy, mm)[1]
        weekdays = sum(
            1 for d in range(1, days_in_month + 1)
            if date(yy, mm, d).weekday() < 5
        )
        off = month_offdays(db, client_id, yy, mm)
        working_days = max(weekdays - off, 0)
        target = working_days * HOURS_PER_DAY
        achieved = db.execute(
            "SELECT COALESCE(SUM(hours),0) h FROM timesheet_entries "
            "WHERE client_id = ? AND work_date >= ? AND work_date <= ?",
            (client_id, date(yy, mm, 1).isoformat(), date(yy, mm, days_in_month).isoformat()),
        ).fetchone()["h"] or 0.0
        pct = (achieved / target * 100.0) if target else 0.0
        tag = ""
        if (yy, mm) == (today.year, today.month):
            tag = "Current"
        elif (yy, mm) == seq[1]:
            tag = "Last month"
        else:
            tag = "Earlier"
        months.append({
            "label": date(yy, mm, 1).strftime("%B %Y"),
            "tag": tag,
            "achieved": round(achieved, 2),
            "target": target,
            "working_days": working_days,
            "offdays": off,
            "pct": pct,
            "pct_bar": min(pct, 100.0),
        })
    return months


# --------------------------------------------------------------------------
# Invoice calculations
# --------------------------------------------------------------------------
def timesheet_invoice_lines(db, client_id, start, end, fx=1.0):
    """One invoice line per charge type that has hours in [start, end].

    The base (Regular) charge becomes the main consulting line; every other
    charge type (OverTime / AfterHours / Holiday Coverage / ...) gets its own
    line at that type's rate. Line labels come from charge_types.invoice_label.
    """
    fx = fx or 1.0
    # charge type metadata, base first then by name (stable line order)
    ctypes = db.execute(
        "SELECT name, amount_usd, invoice_label, is_base FROM charge_types "
        "WHERE client_id = ? ORDER BY is_base DESC, name",
        (client_id,),
    ).fetchall()
    hours_by_method = {
        r["charge_method"]: (r["h"] or 0.0)
        for r in db.execute(
            "SELECT charge_method, COALESCE(SUM(hours),0) h FROM timesheet_entries "
            "WHERE client_id = ? AND work_date >= ? AND work_date <= ? GROUP BY charge_method",
            (client_id, start, end),
        )
    }
    lines = []
    seen = set()
    for ct in ctypes:
        hours = hours_by_method.get(ct["name"], 0.0)
        seen.add(ct["name"])
        if hours <= 0:
            continue
        label = (ct["invoice_label"] or "").strip() or (
            CONSULTING_LINE_LABEL if ct["is_base"]
            else "RPG Consulting - %s Charge" % ct["name"]
        )
        rate = (ct["amount_usd"] or 0.0) * fx
        lines.append({
            "description": label,
            "qty": round(hours, 2),
            "rate": round(rate, 2),
            "amount": round(hours * rate, 2),
            "is_discount": 0,
        })
    # any hours logged against a charge method no longer in the master list
    for method, hours in hours_by_method.items():
        if method in seen or hours <= 0:
            continue
        lines.append({
            "description": "RPG Consulting - %s Charge" % (method or "Other"),
            "qty": round(hours, 2),
            "rate": 0.0,
            "amount": 0.0,
            "is_discount": 0,
        })
    return lines


def compute_invoice_totals(items, tax_rate):
    """net subtotal (discount lines subtracted); tax; total."""
    net = 0.0
    for it in items:
        amt = float(it.get("amount") or 0.0)
        if int(it.get("is_discount") or 0):
            net -= abs(amt)
        else:
            net += amt
    tax = net * (float(tax_rate or 0.0) / 100.0)
    total = net + tax
    return round(net, 2), round(tax, 2), round(total, 2)


def next_invoice_number(db, client_id):
    """Next ``INV-YYYY-NNN`` number for this client (numbering is per-client, so
    each client has its own clean 001, 002, … sequence)."""
    year = date.today().year
    n = db.execute(
        "SELECT COUNT(*) c FROM invoices WHERE client_id = ? AND number LIKE ?",
        (client_id, "%s-%d-%%" % (INVOICE_PREFIX, year)),
    ).fetchone()["c"]
    return "%s-%d-%03d" % (INVOICE_PREFIX, year, n + 1)


def _add_months(year, month, delta):
    m = month + delta
    y = year
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return y, m


def last_unbilled_period(db, client_id):
    """The whole month AFTER this client's latest invoiced period_end; else current month."""
    row = db.execute(
        "SELECT MAX(period_end) m FROM invoices "
        "WHERE client_id = ? AND period_end IS NOT NULL AND period_end != ''",
        (client_id,),
    ).fetchone()
    today = date.today()
    if row and row["m"]:
        try:
            last_end = datetime.strptime(row["m"], "%Y-%m-%d").date()
            y, m = _add_months(last_end.year, last_end.month, 1)
        except ValueError:
            y, m = today.year, today.month
    else:
        y, m = today.year, today.month
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start.isoformat(), end.isoformat()


# --------------------------------------------------------------------------
# Subscriptions (expenses)
# --------------------------------------------------------------------------
def subscription_end_date(start_iso, period):
    """Renewal/end date for a subscription = purchase date + one period.
    Monthly adds a month, Yearly adds a year; the day is clamped to the target
    month's length (e.g. Jan 31 + 1 month -> Feb 28/29). Returns an ISO date
    string, or None if the inputs are unusable."""
    try:
        d = datetime.strptime(start_iso, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    if period == "Yearly":
        y, m = d.year + 1, d.month
    else:  # Monthly (default)
        y, m = _add_months(d.year, d.month, 1)
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day)).isoformat()


def advance_subscription_cycles(db, client_id, today=None):
    """Roll this client's active subscriptions forward one billing cycle at a time.

    When an active cycle's next billing date has arrived (subscription_end <=
    today), that entry is marked 'completed' and a fresh 'active' entry is created
    starting on the billing date (so the billing day is preserved: 26 Jun -> 26
    Jul -> 26 Aug; 15 Aug 2026 -> 15 Aug 2027). A new cycle is only created once
    its billing date has been reached, so a future cycle never shows or counts
    early. Repeats to catch up multiple elapsed cycles; stops at the current,
    not-yet-due cycle. Closed subscriptions are left alone. Idempotent (deduped
    via rolled_from_id). Returns how many cycles were advanced."""
    today = today or date.today()
    today_iso = today.isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    advanced = 0
    for _ in range(5000):  # safety bound (≈400 years of monthly cycles)
        r = db.execute(
            "SELECT * FROM expenses WHERE client_id = ? AND is_subscription = 1 "
            "AND subscription_status = 'active' "
            "AND subscription_end IS NOT NULL AND subscription_end != '' "
            "AND subscription_end <= ? ORDER BY id LIMIT 1",
            (client_id, today_iso),
        ).fetchone()
        if r is None:
            break
        # the current cycle's next billing date has arrived -> complete it
        db.execute("UPDATE expenses SET subscription_status = 'completed' WHERE id = ?", (r["id"],))
        # start the next cycle on that billing date (deduped via rolled_from_id)
        if db.execute("SELECT 1 FROM expenses WHERE rolled_from_id = ?", (r["id"],)).fetchone() is None:
            start = r["subscription_end"]   # next billing date = this cycle's end
            db.execute(
                "INSERT INTO expenses "
                "(client_id, date_purchased, item, price, currency, purchased_at, warranty_till, purpose, "
                "is_subscription, subscription_period, subscription_end, subscription_status, "
                "subscription_ended_on, rolled_from_id, created_at) "
                "VALUES (?,?,?,?,?,?,NULL,?,1,?,?, 'active', NULL, ?, ?)",
                (client_id, start, r["item"], r["price"], r["currency"], r["purchased_at"], r["purpose"],
                 r["subscription_period"], subscription_end_date(start, r["subscription_period"]),
                 r["id"], now),
            )
        advanced += 1
    if advanced:
        db.commit()
    return advanced


# --------------------------------------------------------------------------
# Invoice display + formatting (no DB access)
# --------------------------------------------------------------------------
def invoice_display(inv):
    """Compute display values (round-off line, INR block, GST) for a saved invoice
    row. GST shows either as a single IGST line (use_igst) or a CGST + SGST split,
    each charged on the same taxable base (the INR-converted amount, or the
    INR-native subtotal). `gst_amount` is the total GST in either mode."""
    currency = inv["currency"]
    total = inv["total"] or 0.0
    cgst_rate = inv["cgst_rate"] or 0.0
    sgst_rate = inv["sgst_rate"] or 0.0
    tax_rate = inv["tax_rate"] or 0.0
    use_igst = bool(inv["use_igst"])
    igst_rate = inv["igst_rate"] or 0.0
    out = {
        "currency": currency,
        "symbol": CURRENCY_SYMBOLS.get(currency, ""),
        "total": total,
        "show_round_off": False,
        "round_off": 0.0,
        "rounded_total": total,
        "show_inr": False,
        "inr_rate": inv["inr_rate"] or 0.0,
        "inr_total": inv["inr_total"] or 0.0,
        "inr_rate_date": inv["inr_rate_date"],
        "inr_subtotal": 0.0,
        "inr_tax": 0.0,
        "tax_rate": tax_rate,
        "use_igst": use_igst,
        "igst_rate": igst_rate,
        "cgst_rate": cgst_rate,
        "sgst_rate": sgst_rate,
        "cgst_amount": 0.0,
        "sgst_amount": 0.0,
        "gst_amount": 0.0,
    }

    def split(base):
        out["cgst_amount"] = base * (cgst_rate / 100.0)
        out["sgst_amount"] = base * (sgst_rate / 100.0)
        out["gst_amount"] = base * (tax_rate / 100.0)

    if currency == "USD" and inv["show_inr"] and (inv["inr_rate"] or 0) > 0:
        out["show_inr"] = True
        # GST is applied on the INR-converted amount.
        rate = inv["inr_rate"] or 0.0
        base = (inv["subtotal"] or 0.0) * rate
        out["inr_subtotal"] = base
        split(base)
        out["inr_tax"] = out["gst_amount"]
    elif currency == "USD":
        rounded = round(total)
        diff = rounded - total
        if abs(diff) >= 0.005:
            out["show_round_off"] = True
            out["round_off"] = round(diff, 2)
            out["rounded_total"] = rounded
    else:  # INR-native invoice — GST charged directly on the subtotal
        split(inv["subtotal"] or 0.0)
    return out


def fmt_money(value):
    try:
        return "{:,.2f}".format(float(value or 0.0))
    except (TypeError, ValueError):
        return "0.00"
