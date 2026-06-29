"""Tasks + Sub Tasks: add / update / delete, and sub-task rename cascading into
logged timesheet entries. Self-contained: creates and removes its own fixtures."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db

    h.section("tasks")
    c.post("/tasks/add", data={"task_id": "SMOKE-T", "description": "smoke", "next": "/tasks"})
    h.check("task added", db.execute("SELECT 1 FROM tasks WHERE task_id='SMOKE-T'").fetchone() is not None)
    c.post("/tasks/update/SMOKE-T", data={"description": "smoke2"})
    h.check("task description updated",
            db.execute("SELECT description FROM tasks WHERE task_id='SMOKE-T'").fetchone()["description"] == "smoke2")

    # mark completed (records the date) -> reactivate (clears it)
    c.post("/tasks/complete/SMOKE-T")
    row = db.execute("SELECT status, completed_at FROM tasks WHERE task_id='SMOKE-T'").fetchone()
    h.check("complete sets Completed + a completed date", row["status"] == "Completed" and row["completed_at"])
    c.post("/tasks/reactivate/SMOKE-T")
    row = db.execute("SELECT status, completed_at FROM tasks WHERE task_id='SMOKE-T'").fetchone()
    h.check("reactivate restores Active + clears the date", row["status"] == "Active" and row["completed_at"] is None)
    c.post("/tasks/delete/SMOKE-T")
    h.check("task deleted", db.execute("SELECT 1 FROM tasks WHERE task_id='SMOKE-T'").fetchone() is None)

    # delete keeps past-month hours as history (test_date 2099-01 is not this month)
    c.post("/tasks/add", data={"task_id": "SMOKE-HIST", "description": "h", "next": "/tasks"})
    c.post("/day/add", data={"date": h.test_date, "task_id": "SMOKE-HIST", "sub_task": "",
                             "hours": "3", "charge_method": "Regular", "description": "x"})
    c.post("/tasks/delete/SMOKE-HIST")
    h.check("task with only other-month hours is deletable",
            db.execute("SELECT 1 FROM tasks WHERE task_id='SMOKE-HIST'").fetchone() is None)
    h.check("deleting the task keeps its logged hours as history",
            db.execute("SELECT 1 FROM timesheet_entries WHERE task_id='SMOKE-HIST'").fetchone() is not None)
    for r in db.execute("SELECT id FROM timesheet_entries WHERE task_id='SMOKE-HIST'").fetchall():
        c.post("/day/delete/%d" % r["id"])

    # a task with CURRENT-month hours is locked (delete blocked)
    c.post("/tasks/add", data={"task_id": "SMOKE-LOCK", "description": "l", "next": "/tasks"})
    c.post("/day/add", data={"date": h.today, "task_id": "SMOKE-LOCK", "sub_task": "",
                             "hours": "2", "charge_method": "Regular", "description": "x"})
    c.post("/tasks/delete/SMOKE-LOCK")
    h.check("task with current-month hours is locked (not deleted)",
            db.execute("SELECT 1 FROM tasks WHERE task_id='SMOKE-LOCK'").fetchone() is not None)
    for r in db.execute("SELECT id FROM timesheet_entries WHERE task_id='SMOKE-LOCK'").fetchall():
        c.post("/day/delete/%d" % r["id"])
    c.post("/tasks/delete/SMOKE-LOCK")

    # completed-tasks search (wildcard on description) + page-size dropdown
    c.post("/tasks/add", data={"task_id": "CQ-1", "description": "alpha deploy job", "next": "/tasks"})
    c.post("/tasks/add", data={"task_id": "CQ-2", "description": "beta review job", "next": "/tasks"})
    c.post("/tasks/complete/CQ-1")
    c.post("/tasks/complete/CQ-2")
    found = c.get("/tasks?completed_q=deploy").get_data(as_text=True)
    h.check("completed search filters by description (wildcard)",
            "<strong>CQ-1</strong>" in found and "<strong>CQ-2</strong>" not in found)
    page = c.get("/tasks?completed_limit=30").get_data(as_text=True)
    h.check("completed page-size dropdown offers 15/30/45/60/90",
            'name="completed_limit"' in page and 'value="90"' in page
            and 'value="30" selected' in page)
    c.post("/tasks/delete/CQ-1")
    c.post("/tasks/delete/CQ-2")

    h.section("subtasks")
    c.post("/subtasks/add", data={"name": "SmokeSub", "status": "Active"})
    sid = db.execute("SELECT id FROM subtasks WHERE name='SmokeSub'").fetchone()["id"]
    # log an entry that uses it, then rename and confirm the cascade
    c.post("/tasks/add", data={"task_id": "SMOKE-T2", "description": "x", "next": "/tasks"})
    c.post("/day/add", data={"date": h.test_date, "task_id": "SMOKE-T2", "sub_task": "SmokeSub",
                             "hours": "4", "description": "x", "charge_method": "Regular"})
    c.post("/subtasks/update/%d" % sid, data={"name": "SmokeSub2", "status": "Active"})
    h.check("subtask rename cascaded to entries",
            db.execute("SELECT 1 FROM timesheet_entries WHERE work_date=? AND sub_task='SmokeSub2'",
                       (h.test_date,)).fetchone() is not None)

    # cleanup
    for r in db.execute("SELECT id FROM timesheet_entries WHERE work_date=?", (h.test_date,)).fetchall():
        c.post("/day/delete/%d" % r["id"])
    c.post("/tasks/delete/SMOKE-T2")
    c.post("/subtasks/delete/%d" % sid)

    # ---- "Back" button remembers where the page was opened from (Home / a day) ----
    h.section("tasks-back-button")
    day_back = "/day?date=" + h.test_date
    page = c.get("/tasks", query_string={"back": day_back}).get_data(as_text=True)
    h.check("Back button points at the day page you came from",
            ("Back to day " + h.test_date) in page and ('href="%s"' % day_back) in page)
    # the target survives a plain /tasks load — exactly how the in-place actions return
    page = c.get("/tasks").get_data(as_text=True)
    h.check("Back target persists across an in-place reload (no back param)",
            ("Back to day " + h.test_date) in page)
    # entering from Home resets it
    page = c.get("/tasks", query_string={"back": "/"}).get_data(as_text=True)
    h.check("Back button resets to Home when entered from Home", "Back to Home" in page)
    # an off-site back target is ignored (no open redirect)
    page = c.get("/tasks", query_string={"back": "https://evil.example/x"}).get_data(as_text=True)
    h.check("off-site back target is ignored (falls back to Home)",
            "Back to Home" in page and "evil.example" not in page)


if __name__ == "__main__":
    standalone(run)
