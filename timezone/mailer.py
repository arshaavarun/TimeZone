"""
Invoice email sending (stdlib smtplib + email — no extra dependencies).

The ``profile`` passed in is the merged ``services.invoice_profile`` mapping: the
SMTP server / From identity come from the global ``app_settings``, while the
subject/body templates are the selected client's. Recipients are passed
separately and are per-client.

The actual network send lives in ``_transport_send`` so tests can monkeypatch it
and never open a real SMTP connection. ``send_invoice_email`` returns
``(ok, message)`` and never raises, so callers can flash the result without the
invoice save/page failing because of an email problem.
"""
import smtplib
from email.message import EmailMessage


def _context(inv):
    """Placeholder values available in the subject/body templates."""
    cur = inv["currency"] or ""
    total = inv["total"] or 0.0
    period = ""
    if inv["period_start"] and inv["period_end"]:
        period = "%s to %s" % (inv["period_start"], inv["period_end"])
    return {
        "number": inv["number"] or "",
        "date": inv["invoice_date"] or "",
        "client": inv["client_name"] or "",
        "currency": cur,
        "total": "{:,.2f}".format(total),
        "period": period,
    }


def _fill(template, ctx):
    """Fill {placeholders}; an unknown placeholder is left untouched."""
    out = template or ""
    for key, val in ctx.items():
        out = out.replace("{%s}" % key, str(val))
    return out


def _split_recipients(recipients):
    """Group recipients by kind; returns (to, cc, bcc, all_addresses)."""
    pick = lambda k: [r["email"].strip() for r in recipients
                      if r["kind"] == k and (r["email"] or "").strip()]
    to, cc, bcc = pick("to"), pick("cc"), pick("bcc")
    return to, cc, bcc, to + cc + bcc


def _compose(profile, recipients, subject, body):
    """Build an EmailMessage with From/To/Cc headers (Bcc kept out of headers)
    and the full recipient list. No attachment."""
    from_email = (profile["smtp_from_email"] or profile["smtp_user"] or "").strip()
    from_name = (profile["smtp_from_name"] or profile["biz_name"] or "").strip()
    to, cc, _bcc, rcpts = _split_recipients(recipients)

    msg = EmailMessage()
    msg["From"] = ("%s <%s>" % (from_name, from_email)) if from_name else from_email
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)
    return msg, rcpts


def build_message(profile, recipients, inv, pdf_bytes, extra_attachments=None):
    """Compose the invoice EmailMessage and recipient list. ``extra_attachments``
    is a list of (data_bytes, filename, maintype, subtype) tuples added after the
    PDF. The body (which already mentions the attached hours report — see
    config.DEFAULT_EMAIL_BODY) is used as-is after placeholder filling."""
    ctx = _context(inv)
    ctx["biz_name"] = profile["biz_name"] or ""
    msg, rcpts = _compose(
        profile, recipients,
        _fill(profile["email_subject"] or "Invoice {number}", ctx),
        _fill(profile["email_body"] or "Please find attached invoice {number}.", ctx),
    )
    if pdf_bytes:
        msg.add_attachment(
            pdf_bytes, maintype="application", subtype="pdf",
            filename="%s.pdf" % (inv["number"] or "invoice"),
        )
    for data, filename, maintype, subtype in (extra_attachments or []):
        if data:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg, rcpts


def _transport_send(profile, msg, rcpts):
    """Open the SMTP connection and send. Isolated for testability."""
    host = (profile["smtp_host"] or "").strip()
    port = int(profile["smtp_port"] or 587)
    user = (profile["smtp_user"] or "").strip()
    password = profile["smtp_password"] or ""
    if port == 465:                       # implicit TLS
        server = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
        if profile["smtp_use_tls"]:
            server.starttls()
    try:
        if user:
            server.login(user, password)
        server.send_message(msg, to_addrs=rcpts)
    finally:
        server.quit()


def send_invoice_email(profile, recipients, inv, pdf_bytes, extra_attachments=None):
    """Send the invoice PDF (plus any ``extra_attachments``) to the configured
    recipients. Returns (ok, message)."""
    if not (profile["smtp_host"] or "").strip():
        return False, "Email server not configured (Settings → Email)."
    recipients = [r for r in recipients if (r["email"] or "").strip()]
    if not recipients:
        return False, "No email recipients configured (Settings → Email)."
    msg, rcpts = build_message(profile, recipients, inv, pdf_bytes, extra_attachments)
    if not rcpts:
        return False, "No valid recipient addresses."
    try:
        _transport_send(profile, msg, rcpts)
    except Exception as exc:  # noqa: BLE001 — surface any SMTP/network error to the user
        return False, "Email failed: %s" % exc
    return True, "Invoice emailed to %d recipient(s)." % len(rcpts)


def send_test_email(profile, recipients):
    """Send a small test message to the configured recipients to verify SMTP
    setup without needing an invoice. Returns (ok, message)."""
    if not (profile["smtp_host"] or "").strip():
        return False, "Email server not configured — fill in the SMTP settings first."
    recipients = [r for r in recipients if (r["email"] or "").strip()]
    if not recipients:
        return False, "Add at least one recipient first."
    msg, rcpts = _compose(
        profile, recipients,
        "TimeZone — test email",
        "This is a test email from your TimeZone app.\n\n"
        "If you can read this, invoice emailing is set up correctly.",
    )
    if not rcpts:
        return False, "No valid recipient addresses."
    try:
        _transport_send(profile, msg, rcpts)
    except Exception as exc:  # noqa: BLE001
        return False, "Test email failed: %s" % exc
    return True, "Test email sent to %d recipient(s) — check your inbox." % len(rcpts)
