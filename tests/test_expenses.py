"""Expenses: add / edit / delete, and the expense-category master list — assign a
category to an expense, see the per-purpose category breakdown, rename-cascade,
and the in-use delete guard. Self-contained."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db

    h.section("expenses")
    c.post("/expenses/new", data={"date_purchased": h.today, "item": "SmokeItem", "price": "12.5",
                                  "currency": "INR", "purpose": "Official"})
    erow = db.execute("SELECT id FROM expenses WHERE item='SmokeItem' ORDER BY id DESC LIMIT 1").fetchone()
    h.check("expense added", erow is not None)
    c.post("/expenses/%d/edit" % erow["id"], data={"date_purchased": h.today, "item": "SmokeItem2",
                                                    "price": "13", "currency": "INR", "purpose": "Personal"})
    h.check("expense edited",
            db.execute("SELECT item FROM expenses WHERE id=?", (erow["id"],)).fetchone()["item"] == "SmokeItem2")
    c.post("/expenses/%d/delete" % erow["id"])
    h.check("expense deleted", db.execute("SELECT 1 FROM expenses WHERE id=?", (erow["id"],)).fetchone() is None)

    h.section("expenses/categories")
    c.post("/expense-categories/add", data={"name": "ZCat", "status": "Active"})
    zcid = db.execute("SELECT id FROM expense_categories WHERE name='ZCat'").fetchone()["id"]
    h.check("category added", zcid is not None)
    c.post("/expenses/new", data={"date_purchased": h.today, "item": "ZCatItem", "price": "50",
                                  "currency": "INR", "purpose": "Official", "category": "ZCat"})
    cieid = db.execute("SELECT id FROM expenses WHERE item='ZCatItem' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    h.check("expense stores category",
            db.execute("SELECT category FROM expenses WHERE id=?", (cieid,)).fetchone()["category"] == "ZCat")
    cat_page = c.get("/expenses").get_data(as_text=True)
    h.check("expenses page has per-purpose category breakdown",
            "purpose-detail" in cat_page and "ZCat" in cat_page)
    c.post("/expense-categories/update/%d" % zcid, data={"name": "ZCat2", "status": "Active"})
    h.check("category rename cascades to expenses",
            db.execute("SELECT category FROM expenses WHERE id=?", (cieid,)).fetchone()["category"] == "ZCat2")
    c.post("/expense-categories/delete/%d" % zcid)
    h.check("category delete blocked while in use",
            db.execute("SELECT 1 FROM expense_categories WHERE id=?", (zcid,)).fetchone() is not None)
    c.post("/expenses/%d/delete" % cieid)
    c.post("/expense-categories/delete/%d" % zcid)
    h.check("category deleted when unused",
            db.execute("SELECT 1 FROM expense_categories WHERE id=?", (zcid,)).fetchone() is None)


if __name__ == "__main__":
    standalone(run)
