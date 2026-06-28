"""Invoices: pull lines from the timesheet, save (USD with INR-converted GST, and
the no-GST USD case), the CGST/SGST split, HTML soft-view + PAID watermark, PDF,
mark-paid, and delete. Self-contained."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db

    # never let an invoice save attempt a real email from the test suite
    # (auto-send email is exercised separately, with the transport mocked)
    db.execute("UPDATE client_profile SET email_auto_send = 0")
    db.commit()

    h.section("invoices")
    inv_page = c.get("/invoices").get_data(as_text=True)
    h.check("invoices default to current year", ('value="%s" selected' % h.today[:4]) in inv_page)
    inv_year_sel = inv_page[inv_page.find('name="year"'):].split('</select>', 1)[0]
    h.check("invoices year filter has no 'All' option", ">All<" not in inv_year_sel)

    lines = c.get("/invoices/lines?start=2000-01-01&end=2100-01-01&currency=USD&fx=1")
    h.check("pull-from-timesheet returns lines", lines.status_code == 200 and b"description" in lines.data)

    form = {"id": "", "number": "INV-SMOKE", "invoice_date": h.today, "currency": "USD", "fx_rate": "1",
            "client_name": "Smoke Client", "cgst_rate": "9", "sgst_rate": "9",
            "item_desc_0": "Work", "item_qty_0": "10", "item_rate_0": "100", "item_discount_0": "0",
            "show_inr": "1", "inr_rate": "83.50", "inr_rate_date": h.today}
    rsave = c.post("/invoices/save", data=form)
    invn = db.execute("SELECT * FROM invoices WHERE number='INV-SMOKE'").fetchone()
    h.check("invoice saved", invn is not None)
    h.check("save invoice redirects to invoices list",
            rsave.status_code == 302 and rsave.headers.get("Location", "").endswith("/invoices"))
    h.check("CGST/SGST split stored (9 + 9 = 18)",
            invn is not None and invn["cgst_rate"] == 9 and invn["sgst_rate"] == 9 and round(invn["tax_rate"]) == 18)
    h.check("INR GST on converted amount (1000 USD -> 98530 INR)", invn is not None and round(invn["inr_total"]) == 98530)

    # GST rule: a USD invoice WITHOUT INR conversion carries no GST
    noinr = dict(form, number="INV-SMOKE2", show_inr="0")
    c.post("/invoices/save", data=noinr)
    nv = db.execute("SELECT * FROM invoices WHERE number='INV-SMOKE2'").fetchone()
    h.check("USD invoice w/o INR conversion has no GST",
            nv is not None and (nv["tax_amount"] or 0) == 0 and round(nv["total"]) == 1000)
    c.post("/invoices/%d/delete" % nv["id"])

    iid = invn["id"]
    view_unpaid = c.get("/invoices/%d/view" % iid).get_data(as_text=True)
    h.check("invoice view (HTML)", "INVOICE" in view_unpaid)
    h.check("soft view splits GST into CGST + SGST", "CGST (9" in view_unpaid and "SGST (9" in view_unpaid)
    h.check("unpaid invoice has no PAID watermark", "iv-watermark" not in view_unpaid)
    h.check("invoice edit page", h.get_ok("/invoices/%d/edit" % iid))
    h.check("invoice PDF", c.get("/invoices/%d/pdf" % iid).status_code == 200)
    c.post("/invoices/%d/paid" % iid)
    h.check("invoice marked paid", db.execute("SELECT status FROM invoices WHERE id=?", (iid,)).fetchone()["status"] == "paid")
    view_paid = c.get("/invoices/%d/view" % iid).get_data(as_text=True)
    h.check("paid invoice soft view shows PAID watermark", "iv-watermark" in view_paid and ">PAID<" in view_paid)
    c.post("/invoices/%d/delete" % iid)
    h.check("invoice deleted", db.execute("SELECT 1 FROM invoices WHERE id=?", (iid,)).fetchone() is None)

    # ---- iGST (single GST) mode: one "GST" line instead of CGST + SGST ----
    iform = {"id": "", "number": "INV-IGST", "invoice_date": h.today, "currency": "INR", "fx_rate": "1",
             "client_name": "Test Client", "use_igst": "1", "igst_rate": "18",
             "item_desc_0": "Work", "item_qty_0": "10", "item_rate_0": "100", "item_discount_0": "0"}
    c.post("/invoices/save", data=iform)
    iv = db.execute("SELECT * FROM invoices WHERE number='INV-IGST'").fetchone()
    h.check("iGST stored (use_igst=1, igst=18, tax=18, cgst/sgst=0)",
            iv is not None and iv["use_igst"] == 1 and iv["igst_rate"] == 18
            and round(iv["tax_rate"]) == 18 and (iv["cgst_rate"] or 0) == 0 and (iv["sgst_rate"] or 0) == 0)
    h.check("iGST total = subtotal + single GST (1000 + 180)", iv is not None and round(iv["total"]) == 1180)
    iv_view = c.get("/invoices/%d/view" % iv["id"]).get_data(as_text=True)
    h.check("iGST view shows a single GST line, no CGST/SGST",
            "GST (18" in iv_view and "CGST" not in iv_view and "SGST" not in iv_view)
    h.check("iGST invoice PDF builds", c.get("/invoices/%d/pdf" % iv["id"]).status_code == 200)
    c.post("/invoices/%d/delete" % iv["id"])

    # ---- invoice email attaches the period's hours report; default body notes it ----
    from timezone.mailer import build_message
    from timezone.views_reports import build_hours_report_xlsx, HAVE_OPENPYXL
    from timezone.config import DEFAULT_EMAIL_BODY
    h.check("default email body mentions the attached hours report",
            "hours report" in DEFAULT_EMAIL_BODY.lower())
    if HAVE_OPENPYXL:
        xlsx = build_hours_report_xlsx(db, h.client_id(), "2000-01-01", "2100-01-01")
        h.check("hours report builds a valid xlsx", len(xlsx) > 0 and bytes(xlsx[:2]) == b"PK")
        prof = {"smtp_from_email": "me@x.com", "smtp_user": "me@x.com", "smtp_from_name": "Biz",
                "biz_name": "Biz", "email_subject": "Invoice {number}", "email_body": DEFAULT_EMAIL_BODY}
        finv = {"number": "INV-RPT", "invoice_date": h.today, "client_name": "C", "currency": "INR",
                "total": 100.0, "period_start": "2000-01-01", "period_end": "2100-01-01"}
        extra = [(xlsx, "Hours.xlsx", "application",
                  "vnd.openxmlformats-officedocument.spreadsheetml.sheet")]
        msg, _ = build_message(prof, [{"email": "a@b.com", "kind": "to"}], finv, b"%PDF fake", extra)
        h.check("invoice email attaches the Excel hours report",
                any((p.get_filename() or "").endswith(".xlsx") for p in msg.iter_attachments()))
        ebody = msg.get_body(preferencelist=("plain",)).get_content()
        h.check("sent email body mentions the hours report and the period",
                "hours report" in ebody.lower() and "2000-01-01 to 2100-01-01" in ebody)

    # ---- multi-line addresses render across lines in the HTML view ----
    c.post("/invoices/save", data={"id": "", "number": "INV-ADDR", "invoice_date": h.today,
           "currency": "INR", "fx_rate": "1", "client_name": "C",
           "client_address": "Line A\nLine B\nLine C", "use_igst": "1", "igst_rate": "0",
           "item_desc_0": "x", "item_qty_0": "1", "item_rate_0": "1", "item_discount_0": "0"})
    av = db.execute("SELECT id FROM invoices WHERE number='INV-ADDR'").fetchone()
    addr_view = c.get("/invoices/%d/view" % av["id"]).get_data(as_text=True)
    h.check("multi-line client address renders across lines (not one line)",
            "Line A<br>Line B<br>Line C" in addr_view)
    c.post("/invoices/%d/delete" % av["id"])

    # ---- reset email subject + body to the application default ----
    from timezone.config import DEFAULT_EMAIL_BODY, DEFAULT_EMAIL_SUBJECT
    c.post("/email-settings", data={"email_subject": "custom subj", "email_body": "custom body",
                                    "email_auto_send": "0"})
    c.post("/email-settings/reset")
    eprof = db.execute("SELECT email_subject, email_body FROM client_profile WHERE client_id=?",
                       (h.client_id(),)).fetchone()
    h.check("reset restores the default email subject + body",
            eprof["email_subject"] == DEFAULT_EMAIL_SUBJECT and eprof["email_body"] == DEFAULT_EMAIL_BODY)


if __name__ == "__main__":
    standalone(run)
