"""
Invoice PDF generation (ReportLab). Isolated so the dependency is optional —
``HAVE_REPORTLAB`` is False if reportlab is not installed.

``profile`` is the merged ``services.invoice_profile`` mapping — the global
business identity / bank details (from ``app_settings``) plus the client's terms
(from ``client_profile``) — so the builder reads it like the old profile row.
"""
import io

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    HAVE_REPORTLAB = True
except Exception:  # pragma: no cover
    HAVE_REPORTLAB = False


def build_invoice_pdf(inv, items, profile, disp):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11)
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=9.5, leading=12)
    meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9, leading=12, alignment=2)

    cur = inv["currency"]
    elems = []

    # ---- header: business block (left) + INVOICE meta (right) ----
    biz_lines = ["<b>%s</b>" % (profile["biz_name"] or "Your Business")]
    if profile["biz_address"]:
        biz_lines.append(profile["biz_address"].replace("\n", "<br/>"))
    if profile["biz_email"]:
        biz_lines.append(profile["biz_email"])
    if profile["biz_gstin"]:
        biz_lines.append("GSTIN: %s" % profile["biz_gstin"])
    biz_cell = Paragraph("<br/>".join(biz_lines), normal)

    status_txt = inv["status"].title()
    if inv["status"] == "paid" and inv["settled_on"]:
        status_txt += " (%s)" % inv["settled_on"]
    meta_lines = [
        "<b>INVOICE</b>",
        "Number: %s" % (inv["number"] or ""),
        "Date: %s" % (inv["invoice_date"] or ""),
    ]
    if inv["period_start"] and inv["period_end"]:
        meta_lines.append("Period: %s to %s" % (inv["period_start"], inv["period_end"]))
    meta_lines.append("Status: %s" % status_txt)
    meta_cell = Paragraph("<br/>".join(meta_lines), meta)

    header = Table([[biz_cell, meta_cell]], colWidths=[100 * mm, 74 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elems.append(header)
    elems.append(Spacer(1, 10))

    # ---- BILL TO ----
    bill_lines = ["<b>BILL TO</b>"]
    if inv["client_name"]:
        bill_lines.append(inv["client_name"])
    if inv["client_address"]:
        bill_lines.append(inv["client_address"].replace("\n", "<br/>"))
    if inv["client_gstin"]:
        bill_lines.append("GSTIN: %s" % inv["client_gstin"])
    elems.append(Paragraph("<br/>".join(bill_lines), normal))
    elems.append(Spacer(1, 10))

    # ---- items table ----
    data = [["#", "Description", "Qty", "Rate (%s)" % cur, "Amount (%s)" % cur]]
    for idx, it in enumerate(items, start=1):
        amt = it["amount"] or 0.0
        if it["is_discount"]:
            amt = -abs(amt)
        data.append([
            str(idx),
            Paragraph(it["description"] or "", small),
            "%.2f" % (it["qty"] or 0),
            "{:,.2f}".format(it["rate"] or 0),
            "{:,.2f}".format(amt),
        ])
    tbl = Table(data, colWidths=[10 * mm, 92 * mm, 16 * mm, 28 * mm, 28 * mm])
    tstyle = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for ridx in range(1, len(data)):
        if ridx % 2 == 0:
            tstyle.append(("BACKGROUND", (0, ridx), (-1, ridx), colors.HexColor("#f1f5f9")))
    tbl.setStyle(TableStyle(tstyle))
    elems.append(tbl)
    elems.append(Spacer(1, 8))

    # ---- totals block (right) ----
    tot_rows = [
        ["Subtotal", "{:,.2f} {}".format(inv["subtotal"] or 0, cur)],
    ]
    cgst_rate = disp["cgst_rate"] or 0
    sgst_rate = disp["sgst_rate"] or 0
    use_igst = disp["use_igst"]
    igst_rate = disp["igst_rate"] or 0

    def gst_rows(suffix):
        """GST line(s): a single "GST" line for iGST, else CGST + SGST."""
        out = []
        if use_igst:
            if igst_rate > 0:
                out.append(["GST (%.2f%%)" % igst_rate, "{:,.2f}{}".format(disp["gst_amount"], suffix)])
        else:
            if cgst_rate > 0:
                out.append(["CGST (%.2f%%)" % cgst_rate, "{:,.2f}{}".format(disp["cgst_amount"], suffix)])
            if sgst_rate > 0:
                out.append(["SGST (%.2f%%)" % sgst_rate, "{:,.2f}{}".format(disp["sgst_amount"], suffix)])
        return out

    if disp["show_inr"]:
        # GST is charged on the INR-converted amount; USD carries none.
        tot_rows.append(["TOTAL", "{:,.2f} {}".format(inv["subtotal"] or 0, cur)])
        rate_lbl = "Exchange rate"
        if disp["inr_rate_date"]:
            rate_lbl += " (as on %s)" % disp["inr_rate_date"]
        tot_rows.append([rate_lbl, "1 USD = {:,.2f} INR".format(disp["inr_rate"])])
        tot_rows.append(["Subtotal (INR)", "{:,.2f} INR".format(disp["inr_subtotal"])])
        tot_rows.extend(gst_rows(" INR"))
        tot_rows.append(["TOTAL (INR)", "{:,.0f} INR".format(disp["inr_total"])])
    else:
        # GST only shows when it actually applies (INR-native invoices); a USD
        # invoice without INR conversion carries no GST.
        tot_rows.extend(gst_rows(" " + cur))
        if disp["show_round_off"]:
            tot_rows.append(["Round off", "{:,.2f} {}".format(disp["round_off"], cur)])
            tot_rows.append(["TOTAL", "{:,.0f} {}".format(disp["rounded_total"], cur)])
        else:
            tot_rows.append(["TOTAL", "{:,.2f} {}".format(inv["total"] or 0, cur)])

    tot_tbl = Table(tot_rows, colWidths=[40 * mm, 44 * mm], hAlign="RIGHT")
    tstyle2 = [
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
    ]
    # bold the TOTAL row(s)
    for ridx, row in enumerate(tot_rows):
        if row[0].startswith("TOTAL"):
            tstyle2.append(("FONTNAME", (0, ridx), (-1, ridx), "Helvetica-Bold"))
            tstyle2.append(("LINEABOVE", (0, ridx), (-1, ridx), 0.75, colors.HexColor("#334155")))
    tot_tbl.setStyle(TableStyle(tstyle2))
    elems.append(tot_tbl)
    elems.append(Spacer(1, 14))

    # ---- INR native note ----
    if cur == "INR" and (inv["fx_rate"] or 1) != 1:
        elems.append(Paragraph(
            "Amounts converted at USD&rarr;INR rate of %.2f" % inv["fx_rate"], small))
        elems.append(Spacer(1, 6))

    # ---- notes / terms / bank ----
    if inv["notes"]:
        elems.append(Paragraph("<b>Notes</b><br/>%s" % inv["notes"].replace("\n", "<br/>"), small))
        elems.append(Spacer(1, 6))
    if profile["bank_details"]:
        elems.append(Paragraph(
            "<b>Payment details</b><br/>%s" % profile["bank_details"].replace("\n", "<br/>"), small))
        elems.append(Spacer(1, 6))
    if profile["terms"]:
        elems.append(Paragraph(
            "<b>Terms</b><br/>%s" % profile["terms"].replace("\n", "<br/>"), small))

    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()
