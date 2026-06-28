"""Timesheet day editing: duplicate Task+Sub Task blocked, entry edit, submit
(locks + redirects to the month calendar) and unsubmit. Self-contained: makes its
own task/sub-task/entry on the far-future TEST_DATE and cleans up after."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db
    d = h.test_date

    h.section("timesheet")
    c.post("/tasks/add", data={"task_id": "TS-T", "description": "x", "next": "/tasks"})
    c.post("/subtasks/add", data={"name": "TSsub", "status": "Active"})
    c.post("/day/add", data={"date": d, "task_id": "TS-T", "sub_task": "TSsub",
                             "hours": "4", "description": "x", "charge_method": "Regular"})

    before = db.execute("SELECT COUNT(*) c FROM timesheet_entries WHERE work_date=?", (d,)).fetchone()["c"]
    c.post("/day/add", data={"date": d, "task_id": "TS-T", "sub_task": "TSsub",
                             "hours": "2", "description": "dup", "charge_method": "Regular"})
    after = db.execute("SELECT COUNT(*) c FROM timesheet_entries WHERE work_date=?", (d,)).fetchone()["c"]
    h.check("duplicate task+subtask combo blocked", before == after)

    eid = db.execute("SELECT id FROM timesheet_entries WHERE work_date=? LIMIT 1", (d,)).fetchone()["id"]
    c.post("/day/entry/update/%d" % eid, data={"task_id": "TS-T", "sub_task": "TSsub",
                                               "hours": "6.5", "description": "edited", "charge_method": "OverTime"})
    h.check("entry edited", db.execute("SELECT hours FROM timesheet_entries WHERE id=?", (eid,)).fetchone()["hours"] == 6.5)

    rsub = c.post("/day/submit", data={"date": d})
    st = db.execute("SELECT status FROM timesheet_days WHERE work_date=?", (d,)).fetchone()
    h.check("day status submitted", st is not None and st["status"] == "submitted")
    h.check("submit day redirects to month calendar",
            rsub.status_code == 302 and "/entry" in rsub.headers.get("Location", ""))
    c.post("/day/unsubmit", data={"date": d})
    h.check("day unsubmitted",
            db.execute("SELECT status FROM timesheet_days WHERE work_date=?", (d,)).fetchone()["status"] == "draft")

    # cleanup
    for r in db.execute("SELECT id FROM timesheet_entries WHERE work_date=?", (d,)).fetchall():
        c.post("/day/delete/%d" % r["id"])
    c.post("/tasks/delete/TS-T")
    sub = db.execute("SELECT id FROM subtasks WHERE name='TSsub'").fetchone()
    if sub:
        c.post("/subtasks/delete/%d" % sub["id"])

    # ---- Charge-method day rules: weekend / full (>=8h) day hides "Regular" ----
    h.section("charge rules")
    from timezone.views_timesheet import _add_charge_options
    cid = h.client_id()
    charges = db.execute(
        "SELECT * FROM charge_types WHERE client_id=? ORDER BY is_base DESC, name", (cid,)
    ).fetchall()
    wkday, wkend = "2099-12-07", "2099-12-05"   # Monday, Saturday

    opts, dft, _ = _add_charge_options(charges, wkday, 4.0)
    h.check("charge rule: weekday <8h keeps Regular default",
            "Regular" in [x["name"] for x in opts] and dft == "Regular")
    opts, dft, _ = _add_charge_options(charges, wkday, 8.0)
    h.check("charge rule: full day hides Regular, defaults OverTime",
            "Regular" not in [x["name"] for x in opts] and dft == "OverTime")
    opts, dft, _ = _add_charge_options(charges, wkend, 0.0)
    h.check("charge rule: weekend hides Regular, defaults Holiday Coverage",
            "Regular" not in [x["name"] for x in opts] and dft == "Holiday Coverage")

    # server-side coercion behind the form
    c.post("/tasks/add", data={"task_id": "CR-T", "description": "x", "next": "/tasks"})
    c.post("/day/add", data={"date": wkend, "task_id": "CR-T", "sub_task": "w",
                             "hours": "3", "charge_method": "Regular", "description": "x"})
    r1 = db.execute("SELECT charge_method FROM timesheet_entries WHERE work_date=? AND task_id='CR-T'", (wkend,)).fetchone()
    h.check("charge rule: Regular on weekend coerced to Holiday Coverage",
            r1 is not None and r1["charge_method"] == "Holiday Coverage")
    c.post("/day/add", data={"date": wkday, "task_id": "CR-T", "sub_task": "am",
                             "hours": "8", "charge_method": "Regular", "description": "x"})
    c.post("/day/add", data={"date": wkday, "task_id": "CR-T", "sub_task": "pm",
                             "hours": "2", "charge_method": "Regular", "description": "x"})
    am = db.execute("SELECT charge_method FROM timesheet_entries WHERE work_date=? AND sub_task='am'", (wkday,)).fetchone()
    pm = db.execute("SELECT charge_method FROM timesheet_entries WHERE work_date=? AND sub_task='pm'", (wkday,)).fetchone()
    h.check("charge rule: first 8h stays Regular", am is not None and am["charge_method"] == "Regular")
    h.check("charge rule: Regular after 8h coerced to OverTime", pm is not None and pm["charge_method"] == "OverTime")

    # cleanup
    for dd in (wkday, wkend):
        for r in db.execute("SELECT id FROM timesheet_entries WHERE work_date=? AND task_id='CR-T'", (dd,)).fetchall():
            c.post("/day/delete/%d" % r["id"])
    c.post("/tasks/delete/CR-T")


if __name__ == "__main__":
    standalone(run)
