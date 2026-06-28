"""Invoice emailing (opt-in: run with --email or TIMEZONE_TEST_EMAIL=1).

The SMTP transport is monkeypatched so nothing is ever really sent. Note the
global/per-client split: the SMTP server lives in TZ Controls (``/controls/save``)
while the recipients + subject/body + auto-send toggle are per-client
(``/email-settings``, ``/email-recipients/*``)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db

    h.section("invoice email")
    import timezone.mailer as mailer
    SENT = []
    mailer._transport_send = lambda profile, msg, rcpts: SENT.append((msg, list(rcpts)))
    # isolate from any recipients carried over in the DB copy
    db.execute("DELETE FROM invoice_email_recipients")
    db.commit()

    # global SMTP server -> TZ Controls
    c.post("/controls/save", data={
        "smtp_host": "smtp.example.com", "smtp_port": "587", "smtp_user": "me@example.com",
        "smtp_password": "secret", "smtp_use_tls": "1", "smtp_from_email": "me@example.com"})
    # per-client message + auto-send -> Settings/Email
    c.post("/email-settings", data={
        "email_subject": "Invoice {number} for {client}",
        "email_body": "Hi {client}, total {currency} {total}.", "email_auto_send": "1"})
    c.post("/email-recipients/add", data={"email": "client@example.com", "kind": "to"})
    c.post("/email-recipients/add", data={"email": "boss@example.com", "kind": "cc"})
    c.post("/email-recipients/add", data={"email": "audit@example.com", "kind": "bcc"})
    h.check("recipients saved (to/cc/bcc)",
            db.execute("SELECT COUNT(*) c FROM invoice_email_recipients").fetchone()["c"] >= 3)

    SENT.clear()
    eform = {"id": "", "number": "INV-MAIL", "invoice_date": h.today, "currency": "INR", "fx_rate": "1",
             "client_name": "Mail Client", "cgst_rate": "9", "sgst_rate": "9",
             "period_start": "2000-01-01", "period_end": "2100-01-01",
             "item_desc_0": "Work", "item_qty_0": "1", "item_rate_0": "100", "item_discount_0": "0"}
    c.post("/invoices/save", data=eform)
    h.check("auto-send fired once on save", len(SENT) == 1)
    msg, rcpts = SENT[-1] if SENT else (None, [])
    h.check("email addressed to all recipients (to+cc+bcc)",
            set(rcpts) == {"client@example.com", "boss@example.com", "audit@example.com"})
    h.check("subject uses placeholders", msg is not None and "INV-MAIL" in msg["Subject"] and "Mail Client" in msg["Subject"])
    h.check("PDF attached to email",
            msg is not None and any(p.get_content_type() == "application/pdf" for p in msg.iter_attachments()))
    h.check("hours report (Excel) attached for the invoice period",
            msg is not None and any((p.get_filename() or "").endswith(".xlsx") for p in msg.iter_attachments()))
    h.check("bcc kept out of headers",
            msg is not None and "audit@example.com" not in ((msg.get("To") or "") + (msg.get("Cc") or "")))

    mid = db.execute("SELECT id FROM invoices WHERE number='INV-MAIL'").fetchone()["id"]
    SENT.clear()
    c.post("/invoices/%d/email" % mid)
    h.check("manual Email button sends", len(SENT) == 1)

    SENT.clear()
    c.post("/email-test")
    tmsg, _ = SENT[-1] if SENT else (None, [])
    h.check("send-test-email works", len(SENT) == 1 and tmsg is not None and "test" in tmsg["Subject"].lower())
    h.check("test email has no attachment", tmsg is not None and not list(tmsg.iter_attachments()))

    # turn auto-send off (per-client) -> a save no longer emails
    c.post("/email-settings", data={"email_subject": "x", "email_body": "y", "email_auto_send": "0"})
    SENT.clear()
    c.post("/invoices/save", data=dict(eform, id=str(mid), number="INV-MAIL"))
    h.check("no auto-send when toggle off", len(SENT) == 0)
    c.post("/invoices/%d/delete" % mid)


if __name__ == "__main__":
    standalone(run)
