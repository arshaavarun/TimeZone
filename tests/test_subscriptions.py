"""Subscriptions: the deterministic billing-cycle advance (services helper), the
expense-form subscription behaviour (computed end date, warranty blocked), closing
a subscription into the history table, and the page-load auto-advance. Self-contained."""
import os
import sys
from datetime import date as _date, datetime as _dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db
    from timezone.services import advance_subscription_cycles as advance
    cid = h.client_id()   # subscriptions belong to the current client

    def mk_sub(item, start, end, period="Monthly", status="active", price=500):
        db.execute(
            "INSERT INTO expenses (client_id, date_purchased, item, price, currency, purpose, is_subscription, "
            "subscription_period, subscription_end, subscription_status, created_at) "
            "VALUES (?,?,?,?,'INR','Official',1,?,?,?,?)",
            (cid, start, item, price, period, end, status, _dt.now().isoformat(timespec="seconds")))
        db.commit()

    h.section("subscription cycle logic")
    # monthly: a cycle is created on each billing date, the 26th preserved
    mk_sub("HCYC1", "2026-01-26", "2026-02-26", "Monthly")
    advance(db, cid, today=_date(2026, 6, 26))
    hc1 = db.execute("SELECT date_purchased, subscription_status FROM expenses "
                     "WHERE item='HCYC1' ORDER BY date_purchased").fetchall()
    h.check("monthly cycles created on each billing date",
            [r["date_purchased"] for r in hc1] ==
            ["2026-01-26", "2026-02-26", "2026-03-26", "2026-04-26", "2026-05-26", "2026-06-26"])
    h.check("exactly one active cycle (the current one)",
            [r["subscription_status"] for r in hc1].count("active") == 1 and hc1[-1]["subscription_status"] == "active")
    db.execute("DELETE FROM expenses WHERE item='HCYC1'"); db.commit()

    # yearly: billing day preserved across years; the future cycle isn't made early
    mk_sub("HCYC2", "2024-08-15", "2025-08-15", "Yearly")
    advance(db, cid, today=_date(2026, 9, 1))
    h.check("yearly cycles preserve the billing date",
            [r["date_purchased"] for r in db.execute(
                "SELECT date_purchased FROM expenses WHERE item='HCYC2' ORDER BY date_purchased")]
            == ["2024-08-15", "2025-08-15", "2026-08-15"])
    db.execute("DELETE FROM expenses WHERE item='HCYC2'"); db.commit()

    # a not-yet-due cycle is left alone; a closed subscription never advances
    mk_sub("HCYC3", "2026-06-20", "2026-07-20", "Monthly")
    advance(db, cid, today=_date(2026, 6, 26))
    h.check("cycle not advanced before its billing date",
            db.execute("SELECT COUNT(*) c FROM expenses WHERE item='HCYC3'").fetchone()["c"] == 1)
    mk_sub("HCYC4", "2026-01-20", "2026-02-20", "Monthly", status="closed")
    advance(db, cid, today=_date(2026, 6, 26))
    h.check("closed subscription does not advance",
            db.execute("SELECT COUNT(*) c FROM expenses WHERE item='HCYC4'").fetchone()["c"] == 1)
    db.execute("DELETE FROM expenses WHERE item IN ('HCYC3','HCYC4')"); db.commit()

    h.section("expenses/subscription")
    # Monthly subscription bought on the 15th -> end is the 15th of next month;
    # a warranty value is sent but must be ignored for subscriptions.
    c.post("/expenses/new", data={"date_purchased": "2099-01-15", "item": "SmokeSub",
                                  "price": "9.99", "currency": "USD", "purpose": "Official",
                                  "is_subscription": "1", "subscription_period": "Monthly",
                                  "warranty_till": "2099-06-01"})
    srow = db.execute("SELECT * FROM expenses WHERE item='SmokeSub' ORDER BY id DESC LIMIT 1").fetchone()
    h.check("subscription added", srow is not None and srow["is_subscription"] == 1)
    h.check("monthly end date computed", srow is not None and srow["subscription_end"] == "2099-02-15")
    h.check("warranty blocked for subscription", srow is not None and srow["warranty_till"] is None)
    c.post("/expenses/%d/edit" % srow["id"], data={"date_purchased": "2099-01-15", "item": "SmokeSub",
                                                   "price": "99", "currency": "USD", "purpose": "Official",
                                                   "is_subscription": "1", "subscription_period": "Yearly"})
    h.check("yearly end date computed",
            db.execute("SELECT subscription_end FROM expenses WHERE id=?", (srow["id"],)).fetchone()["subscription_end"] == "2100-01-15")
    c.post("/expenses/%d/edit" % srow["id"], data={"date_purchased": "2099-01-15", "item": "SmokeSub",
                                                   "price": "99", "currency": "USD", "purpose": "Official",
                                                   "warranty_till": "2099-06-01"})
    off = db.execute("SELECT * FROM expenses WHERE id=?", (srow["id"],)).fetchone()
    h.check("subscription cleared on uncheck",
            off["is_subscription"] == 0 and off["subscription_period"] is None
            and off["subscription_end"] is None and off["warranty_till"] == "2099-06-01")
    c.post("/expenses/%d/delete" % srow["id"])
    h.check("subscription expense deleted", db.execute("SELECT 1 FROM expenses WHERE id=?", (srow["id"],)).fetchone() is None)

    h.section("expenses/close-subscription")
    c.post("/expenses/new", data={"date_purchased": h.today, "item": "ZZEndSub",
                                  "price": "5", "currency": "USD", "purpose": "Official",
                                  "is_subscription": "1", "subscription_period": "Monthly"})
    esid = db.execute("SELECT id FROM expenses WHERE item='ZZEndSub' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    page = c.get("/expenses").get_data(as_text=True)
    head = page.find("Subscription history")
    h.check("default view loads current year", ('value="%s" selected' % h.today[:4]) in page)
    exp_year_sel = page[page.find('name="year"'):].split('</select>', 1)[0]
    h.check("expenses year filter has no 'All' option", ">All<" not in exp_year_sel)
    h.check("active subscription listed under Items", 0 <= page.find("ZZEndSub") < head)
    c.post("/expenses/%d/end-subscription" % esid, data={"ended_on": h.today})
    cl = db.execute("SELECT subscription_status, subscription_ended_on FROM expenses WHERE id=?", (esid,)).fetchone()
    h.check("subscription closed on date", cl["subscription_status"] == "closed" and cl["subscription_ended_on"] == h.today)
    page2 = c.get("/expenses").get_data(as_text=True)
    head2 = page2.find("Subscription history")
    h.check("closed subscription moved to history table", page2.find("ZZEndSub") > head2)
    c.post("/expenses/%d/delete" % esid)
    h.check("closed subscription deleted", db.execute("SELECT 1 FROM expenses WHERE id=?", (esid,)).fetchone() is None)

    h.section("expenses/cycles")
    c.post("/expenses/new", data={"date_purchased": "2024-01-26", "item": "ZZCyc",
                                  "price": "200", "currency": "INR", "purpose": "Official",
                                  "is_subscription": "1", "subscription_period": "Monthly"})
    c.get("/expenses")   # triggers advance for the real current date
    cyc = db.execute("SELECT subscription_status FROM expenses WHERE item='ZZCyc'").fetchall()
    h.check("page load advanced the subscription into multiple cycles", len(cyc) > 1)
    h.check("only one active cycle remains",
            sum(1 for r in cyc if r["subscription_status"] == "active") == 1)
    for r in db.execute("SELECT id FROM expenses WHERE item='ZZCyc'").fetchall():
        c.post("/expenses/%d/delete" % r["id"])


if __name__ == "__main__":
    standalone(run)
