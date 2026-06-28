"""Charge types: add (with the non-base USD rate derived from the base), rename,
and delete. Self-contained."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db
    cur_cid = h.client_id()  # current client these charge types belong to

    h.section("charge types")
    c.post("/charge_types/add", data={"name": "SmokeCharge", "percent": "200", "invoice_label": "L"})
    base = db.execute("SELECT amount_usd FROM charge_types WHERE is_base=1 AND client_id=?",
                      (cur_cid,)).fetchone()["amount_usd"] or 0
    added = db.execute("SELECT amount_usd FROM charge_types WHERE name='SmokeCharge' AND client_id=?",
                       (cur_cid,)).fetchone()["amount_usd"] or 0
    h.check("charge type added (200% derived)", abs(added - 2 * base) < 0.01)

    cid = db.execute("SELECT id FROM charge_types WHERE name='SmokeCharge' AND client_id=?",
                     (cur_cid,)).fetchone()["id"]
    c.post("/charge_types/update/%d" % cid, data={"name": "SmokeCharge2", "percent": "150", "invoice_label": "L"})
    h.check("charge type renamed",
            db.execute("SELECT 1 FROM charge_types WHERE name='SmokeCharge2'").fetchone() is not None)
    c.post("/charge_types/delete/%d" % cid)
    h.check("charge type deleted", db.execute("SELECT 1 FROM charge_types WHERE id=?", (cid,)).fetchone() is None)


if __name__ == "__main__":
    standalone(run)
