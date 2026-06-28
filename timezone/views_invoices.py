"""Invoice routes: builder, save, PDF, soft view, list (scoped to the current client).

The invoice "profile" handed to templates / the PDF / the mailer is the merged
``services.invoice_profile`` (global business identity + SMTP from app_settings,
plus this client's billing/GST/email settings from client_profile).
"""
import io
from datetime import date, datetime

from flask import (
    render_template, request, redirect, url_for, flash, send_file, abort, jsonify,
)

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db
from timezone.services import *        # noqa: F401,F403
from timezone.pdfs import build_invoice_pdf, HAVE_REPORTLAB
from timezone.mailer import send_invoice_email


def _email_invoice(db, invoice_id):
    """Render the invoice PDF and email it to the client's configured recipients.
    Returns (ok, message); never raises so callers can just flash the result."""
    if not HAVE_REPORTLAB:
        return False, "PDF support (reportlab) is not installed."
    cid = current_client_id(db)
    inv = db.execute(
        "SELECT * FROM invoices WHERE id = ? AND client_id = ?", (invoice_id, cid)
    ).fetchone()
    if not inv:
        return False, "Invoice not found."
    profile = invoice_profile(db, cid)
    recipients = db.execute(
        "SELECT email, kind FROM invoice_email_recipients WHERE client_id = ? ORDER BY id", (cid,)
    ).fetchall()
    items = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY sort_order, id", (invoice_id,)
    ).fetchall()
    pdf = build_invoice_pdf(inv, items, profile, invoice_display(inv))
    # also attach the hours report (Excel) for the invoice's billed period
    extra = []
    from timezone.views_reports import build_hours_report_xlsx, _report_filename, HAVE_OPENPYXL
    if HAVE_OPENPYXL and inv["period_start"] and inv["period_end"]:
        try:
            xlsx = build_hours_report_xlsx(db, cid, inv["period_start"], inv["period_end"])
            client = current_client(db)
            rname = _report_filename(inv["period_start"], inv["period_end"],
                                     client["name"] if client else None) + ".xlsx"
            extra.append((xlsx, rname, "application",
                          "vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        except Exception:  # noqa: BLE001 — never block the invoice email on the report
            pass
    return send_invoice_email(profile, recipients, inv, pdf, extra_attachments=extra)



@app.route("/invoices")
def invoices():
    db = get_db()
    cid = current_client_id(db)
    # The year filter always shows one specific year (current by default) — there
    # is no "all years" option, so an absent/empty year falls back to this year.
    year = request.args.get("year")
    if not year:
        year = str(date.today().year)
    q = "SELECT * FROM invoices WHERE client_id = ?"
    params = [cid]
    if year:
        q += " AND substr(invoice_date,1,4) = ?"
        params.append(year)
    q += " ORDER BY invoice_date DESC, id DESC"
    rows = db.execute(q, params).fetchall()

    enriched = []
    usd_total = 0.0
    inr_total = 0.0
    for r in rows:
        disp = invoice_display(r)
        enriched.append({"row": r, "disp": disp})
        if r["currency"] == "USD":
            usd_total += r["total"] or 0.0
            if r["show_inr"] and (r["inr_rate"] or 0) > 0:
                inr_total += r["inr_total"] or 0.0
        else:  # INR native
            inr_total += r["total"] or 0.0

    years = [r["y"] for r in db.execute(
        "SELECT DISTINCT substr(invoice_date,1,4) y FROM invoices WHERE client_id = ? ORDER BY y DESC",
        (cid,),
    ) if r["y"]]
    # always offer the current year in the filter, even before it has any rows
    cur_year = str(date.today().year)
    if cur_year not in years:
        years = sorted(set(years) | {cur_year}, reverse=True)

    return render_template(
        "invoices.html",
        invoices=enriched,
        usd_total=usd_total, inr_total=inr_total,
        years=years, sel_year=year,
    )




@app.route("/invoices/new")
def invoice_new():
    db = get_db()
    cid = current_client_id(db)
    profile = invoice_profile(db, cid)
    start, end = last_unbilled_period(db, cid)
    currency = "USD"
    items = timesheet_invoice_lines(db, cid, start, end, fx=1.0)
    if not items:
        items = [{"description": CONSULTING_LINE_LABEL, "qty": 0, "rate": 0, "amount": 0, "is_discount": 0}]
    invoice = {
        "id": "",
        "number": next_invoice_number(db, cid),
        "invoice_date": date.today().isoformat(),
        "period_start": start,
        "period_end": end,
        "currency": currency,
        "fx_rate": 1.0,
        "client_name": profile["client_name"] or "",
        "client_address": profile["client_address"] or "",
        "client_gstin": profile["client_gstin"] or "",
        "tax_label": "GST",
        "tax_rate": profile["default_tax_rate"] or 0.0,
        "use_igst": profile["default_use_igst"],
        "igst_rate": profile["default_igst_rate"] or 0.0,
        "cgst_rate": profile["default_cgst_rate"] or 0.0,
        "sgst_rate": profile["default_sgst_rate"] or 0.0,
        "notes": "",
        "show_inr": 0,
        "inr_rate": 0.0,
        "inr_rate_date": date.today().isoformat(),
        "status": "generated",
    }
    return render_template(
        "invoice_form.html",
        invoice=invoice, items=items, profile=profile,
        currencies=["USD", "INR"], is_new=True,
    )


@app.route("/invoices/<int:iid>/edit")
def invoice_edit(iid):
    db = get_db()
    cid = current_client_id(db)
    inv = db.execute("SELECT * FROM invoices WHERE id = ? AND client_id = ?", (iid, cid)).fetchone()
    if not inv:
        abort(404)
    if inv["status"] == "paid":
        flash("Paid invoices are PDF-only and cannot be edited.", "error")
        return redirect(url_for("invoices"))
    rows = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY sort_order, id", (iid,)
    ).fetchall()
    # JSON-serialisable dicts for the live preview's |tojson
    items = [{
        "description": r["description"],
        "qty": r["qty"],
        "rate": r["rate"],
        "amount": r["amount"],
        "is_discount": r["is_discount"],
    } for r in rows]
    profile = invoice_profile(db, cid)
    return render_template(
        "invoice_form.html",
        invoice=inv, items=items, profile=profile,
        currencies=["USD", "INR"], is_new=False,
    )


@app.route("/invoices/lines")
def invoice_lines():
    db = get_db()
    cid = current_client_id(db)
    start = request.args.get("start")
    end = request.args.get("end")
    currency = request.args.get("currency") or "USD"
    try:
        fx = float(request.args.get("fx") or 1.0)
    except ValueError:
        fx = 1.0
    if currency != "INR":
        fx = 1.0
    lines = timesheet_invoice_lines(db, cid, start, end, fx=fx)
    return jsonify({"items": lines})


def _parse_items_from_form():
    """Walk description_i / qty_i / rate_i / is_discount_i."""
    items = []
    i = 0
    while ("item_desc_%d" % i) in request.form:
        desc = (request.form.get("item_desc_%d" % i) or "").strip()
        qty = float(request.form.get("item_qty_%d" % i) or 0)
        rate = float(request.form.get("item_rate_%d" % i) or 0)
        is_discount = 1 if request.form.get("item_discount_%d" % i) == "1" else 0
        if desc or qty or rate:
            amount = round(qty * rate, 2)
            items.append({
                "description": desc, "qty": qty, "rate": rate,
                "amount": amount, "is_discount": is_discount,
            })
        i += 1
    return items


@app.route("/invoices/save", methods=["POST"])
def invoice_save():
    db = get_db()
    cid = current_client_id(db)
    iid = request.form.get("id") or ""
    now = datetime.now().isoformat(timespec="seconds")

    if iid:
        existing = db.execute(
            "SELECT status FROM invoices WHERE id = ? AND client_id = ?", (iid, cid)
        ).fetchone()
        if not existing:
            abort(404)
        if existing["status"] == "paid":
            flash("Cannot edit a paid invoice.", "error")
            return redirect(url_for("invoices"))

    currency = request.form.get("currency") or "USD"
    try:
        fx_rate = float(request.form.get("fx_rate") or 1.0)
    except ValueError:
        fx_rate = 1.0
    if currency != "INR":
        fx_rate = 1.0

    # GST is entered either as a single IGST rate or a CGST + SGST split; tax_rate
    # is the active total so all the existing total maths below keeps working.
    def _num(name):
        try:
            return float(request.form.get(name) or 0.0)
        except ValueError:
            return 0.0
    use_igst = 1 if request.form.get("use_igst") == "1" else 0
    if use_igst:
        igst_rate = _num("igst_rate")
        cgst_rate = sgst_rate = 0.0
        tax_rate = igst_rate
    else:
        igst_rate = 0.0
        cgst_rate = _num("cgst_rate")
        sgst_rate = _num("sgst_rate")
        tax_rate = cgst_rate + sgst_rate

    items = _parse_items_from_form()
    # net subtotal only (discounts subtracted); GST is decided below by rules.
    subtotal, _drop_tax, _drop_total = compute_invoice_totals(items, tax_rate)

    # INR conversion block (USD invoices only)
    show_inr = 1 if (currency == "USD" and request.form.get("show_inr") == "1") else 0
    try:
        inr_rate = float(request.form.get("inr_rate") or 0.0)
    except ValueError:
        inr_rate = 0.0
    inr_rate_date = request.form.get("inr_rate_date") or None
    inr_total = 0.0

    # GST rule: GST is ONLY ever charged on an INR amount.
    #  - USD invoice + INR conversion on : GST on the converted INR amount.
    #  - USD invoice + INR conversion off: no GST at all (USD total = subtotal).
    #  - INR-native invoice              : GST on the INR amount directly.
    if currency == "USD":
        tax_amount = 0.0          # USD side never carries GST
        total = subtotal
        if show_inr and inr_rate > 0:
            inr_subtotal = subtotal * inr_rate
            inr_tax = inr_subtotal * (tax_rate / 100.0)
            inr_total = round(inr_subtotal + inr_tax)
        else:
            show_inr = 0          # not effective unless rate > 0
    else:                         # INR-native invoice — amounts already in INR
        show_inr = 0
        tax_amount = round(subtotal * (tax_rate / 100.0), 2)
        total = round(subtotal + tax_amount, 2)

    fields = dict(
        client_id=cid,
        number=(request.form.get("number") or "").strip(),
        invoice_date=request.form.get("invoice_date"),
        period_start=request.form.get("period_start") or None,
        period_end=request.form.get("period_end") or None,
        currency=currency,
        fx_rate=fx_rate,
        client_name=(request.form.get("client_name") or "").strip(),
        client_address=(request.form.get("client_address") or "").strip(),
        client_gstin=(request.form.get("client_gstin") or "").strip(),
        tax_rate=tax_rate,
        use_igst=use_igst,
        igst_rate=igst_rate,
        cgst_rate=cgst_rate,
        sgst_rate=sgst_rate,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        show_inr=show_inr,
        inr_rate=inr_rate,
        inr_rate_date=inr_rate_date,
        inr_total=inr_total,
        notes=(request.form.get("notes") or "").strip(),
    )

    if iid:
        sets = ", ".join("%s = ?" % k for k in fields)
        db.execute("UPDATE invoices SET %s WHERE id = ? AND client_id = ?" % sets,
                   list(fields.values()) + [iid, cid])
        db.execute("DELETE FROM invoice_items WHERE invoice_id = ? AND client_id = ?", (iid, cid))
        invoice_id = int(iid)
        msg = "Invoice updated."
    else:
        cols = ", ".join(list(fields) + ["status", "created_at"])
        ph = ", ".join("?" * (len(fields) + 2))
        cur = db.execute(
            "INSERT INTO invoices (%s) VALUES (%s)" % (cols, ph),
            list(fields.values()) + ["generated", now],
        )
        invoice_id = cur.lastrowid
        msg = "Invoice created."

    for order, it in enumerate(items):
        db.execute(
            "INSERT INTO invoice_items "
            "(client_id, invoice_id, description, qty, rate, amount, is_discount, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, invoice_id, it["description"], it["qty"], it["rate"],
             it["amount"], it["is_discount"], order),
        )
    db.commit()
    flash(msg, "success")
    # auto-email the invoice on every save when this client's toggle is on
    if invoice_profile(db, cid)["email_auto_send"]:
        ok, em = _email_invoice(db, invoice_id)
        flash(em, "success" if ok else "error")
    # return to the Invoices list (the page the builder was opened from)
    return redirect(url_for("invoices"))


@app.route("/invoices/<int:iid>/paid", methods=["POST"])
def invoice_paid(iid):
    db = get_db()
    cid = current_client_id(db)
    db.execute(
        "UPDATE invoices SET status='paid', settled_on=? WHERE id=? AND client_id=?",
        (date.today().isoformat(), iid, cid),
    )
    db.commit()
    flash("Invoice marked paid.", "success")
    return redirect(url_for("invoices"))


@app.route("/invoices/<int:iid>/delete", methods=["POST"])
def invoice_delete(iid):
    db = get_db()
    cid = current_client_id(db)
    db.execute("DELETE FROM invoice_items WHERE invoice_id = ? AND client_id = ?", (iid, cid))
    db.execute("DELETE FROM invoices WHERE id = ? AND client_id = ?", (iid, cid))
    db.commit()
    flash("Invoice deleted.", "success")
    return redirect(url_for("invoices"))


@app.route("/invoices/<int:iid>/pdf")
def invoice_pdf(iid):
    if not HAVE_REPORTLAB:
        abort(500, "reportlab not installed")
    db = get_db()
    cid = current_client_id(db)
    inv = db.execute("SELECT * FROM invoices WHERE id = ? AND client_id = ?", (iid, cid)).fetchone()
    if not inv:
        abort(404)
    items = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY sort_order, id", (iid,)
    ).fetchall()
    profile = invoice_profile(db, cid)
    disp = invoice_display(inv)
    pdf = build_invoice_pdf(inv, items, profile, disp)
    return send_file(
        io.BytesIO(pdf), as_attachment=True,
        download_name="%s.pdf" % (inv["number"] or "invoice"),
        mimetype="application/pdf",
    )


@app.route("/invoices/<int:iid>/email", methods=["POST"])
def invoice_email(iid):
    """Manually email this invoice's PDF to the client's configured recipients."""
    db = get_db()
    ok, em = _email_invoice(db, iid)
    flash(em, "success" if ok else "error")
    return redirect(url_for("invoices"))


@app.route("/invoices/<int:iid>/view")
def invoice_view(iid):
    """Soft (HTML) view of a saved invoice — no PDF download needed."""
    db = get_db()
    cid = current_client_id(db)
    inv = db.execute("SELECT * FROM invoices WHERE id = ? AND client_id = ?", (iid, cid)).fetchone()
    if not inv:
        abort(404)
    items = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY sort_order, id", (iid,)
    ).fetchall()
    profile = invoice_profile(db, cid)
    disp = invoice_display(inv)
    return render_template(
        "invoice_view.html", inv=inv, items=items, profile=profile, disp=disp,
    )
