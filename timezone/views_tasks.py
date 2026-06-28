"""Maintain Tasks page: Tasks and Sub Tasks routes (scoped to the current client)."""
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db
from timezone.services import *        # noqa: F401,F403



@app.route("/tasks")
def tasks():
    """Maintain Tasks page: Tasks and Sub Tasks tabbed together.
    Active items on top; completed/inactive items in a separate table below
    (most recent ARCHIVE_LIST_LIMIT, with a 'show all' option)."""
    db = get_db()
    cid = current_client_id(db)
    show_all_inactive = bool(request.args.get("all_inactive"))
    # Completed tasks: a fixed page size (15/30/45/60/90) + a wildcard description
    # search over the whole history. Both come from the query string so a refresh
    # keeps them.
    try:
        completed_limit = int(request.args.get("completed_limit") or COMPLETED_PAGE_SIZES[0])
    except ValueError:
        completed_limit = COMPLETED_PAGE_SIZES[0]
    if completed_limit not in COMPLETED_PAGE_SIZES:
        completed_limit = COMPLETED_PAGE_SIZES[0]
    completed_q = (request.args.get("completed_q") or "").strip()
    # treat the typed text as a literal substring (escape LIKE's % and _)
    like = "%" + completed_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    this_month = date.today().strftime("%Y-%m")
    # tasks older than this (or never used) are flagged stale in "Hours Last Filled"
    stale_cutoff = (date.today() - timedelta(days=30)).isoformat()
    # per active task: the most recent date hours were logged, and whether any
    # hours fall in the current month (the latter drives the lock / delete rules)
    active_sel = (
        "t.*, "
        "(SELECT MAX(e.work_date) FROM timesheet_entries e "
        " WHERE e.client_id = t.client_id AND e.task_id = t.task_id) AS last_filled, "
        "(SELECT COUNT(*) FROM timesheet_entries e "
        " WHERE e.client_id = t.client_id AND e.task_id = t.task_id "
        " AND substr(e.work_date,1,7) = ?) AS used_this_month")

    active_tasks = db.execute(
        "SELECT %s FROM tasks t WHERE t.client_id = ? AND t.status = 'Active' "
        "ORDER BY t.created_at DESC, t.task_id" % active_sel, (this_month, cid)
    ).fetchall()
    completed_count = db.execute(
        "SELECT COUNT(*) c FROM tasks WHERE client_id = ? AND status = 'Completed'", (cid,)
    ).fetchone()["c"]
    completed_matching = db.execute(
        "SELECT COUNT(*) c FROM tasks WHERE client_id = ? AND status = 'Completed' "
        "AND description LIKE ? ESCAPE '\\'", (cid, like)
    ).fetchone()["c"]
    completed_tasks = db.execute(
        "SELECT * FROM tasks WHERE client_id = ? AND status = 'Completed' "
        "AND description LIKE ? ESCAPE '\\' ORDER BY completed_at DESC, task_id LIMIT ?",
        (cid, like, completed_limit),
    ).fetchall()

    active_subtasks = db.execute(
        "SELECT * FROM subtasks WHERE client_id = ? AND status = 'Active' ORDER BY name", (cid,)
    ).fetchall()
    inactive_count = db.execute(
        "SELECT COUNT(*) c FROM subtasks WHERE client_id = ? AND status = 'Inactive'", (cid,)
    ).fetchone()["c"]
    iq = ("SELECT * FROM subtasks WHERE client_id = ? AND status = 'Inactive' "
          "ORDER BY created_at DESC, name")
    if not show_all_inactive:
        iq += " LIMIT %d" % ARCHIVE_LIST_LIMIT
    inactive_subtasks = db.execute(iq, (cid,)).fetchall()

    return render_template(
        "maintain_tasks.html",
        active_tasks=active_tasks,
        completed_tasks=completed_tasks, completed_count=completed_count,
        completed_matching=completed_matching, completed_q=completed_q,
        completed_limit=completed_limit, completed_page_sizes=COMPLETED_PAGE_SIZES,
        active_subtasks=active_subtasks,
        inactive_subtasks=inactive_subtasks, inactive_count=inactive_count,
        show_all_inactive=show_all_inactive,
        task_statuses=TASK_STATUSES, subtask_statuses=SUBTASK_STATUSES,
        archive_limit=ARCHIVE_LIST_LIMIT, stale_cutoff=stale_cutoff,
    )


@app.route("/tasks/update/<task_id>", methods=["POST"])
def tasks_update(task_id):
    """Save an edited task description. Status is changed via the Complete /
    Reactivate buttons (not inline), so it is left untouched here."""
    db = get_db()
    cid = current_client_id(db)
    if not db.execute(
        "SELECT 1 FROM tasks WHERE client_id = ? AND task_id = ?", (cid, task_id)
    ).fetchone():
        flash("Task '%s' not found." % task_id, "error")
        return redirect(url_for("tasks"))
    desc = (request.form.get("description") or "").strip()
    db.execute(
        "UPDATE tasks SET description = ? WHERE client_id = ? AND task_id = ?",
        (desc, cid, task_id),
    )
    db.commit()
    flash("Task '%s' updated." % task_id, "success")
    return redirect(url_for("tasks"))


@app.route("/tasks/complete/<task_id>", methods=["POST"])
def tasks_complete(task_id):
    """Mark a task completed (always allowed) — it moves to the Completed table.
    Records when it was completed for the 'Completed On' column."""
    db = get_db()
    cid = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE tasks SET status = 'Completed', completed_at = ? WHERE client_id = ? AND task_id = ?",
        (now, cid, task_id),
    )
    db.commit()
    flash("Task '%s' marked completed." % task_id, "success")
    return redirect(url_for("tasks"))


@app.route("/tasks/reactivate/<task_id>", methods=["POST"])
def tasks_reactivate(task_id):
    """Move a completed task back to Active (clears the completed date)."""
    db = get_db()
    cid = current_client_id(db)
    db.execute(
        "UPDATE tasks SET status = 'Active', completed_at = NULL WHERE client_id = ? AND task_id = ?",
        (cid, task_id),
    )
    db.commit()
    flash("Task '%s' reactivated." % task_id, "success")
    return redirect(url_for("tasks"))


@app.route("/tasks/add", methods=["POST"])
def tasks_add():
    """Quick-add task (used from the day page)."""
    db = get_db()
    cid = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    tid = (request.form.get("task_id") or "").strip()
    desc = (request.form.get("description") or "").strip()
    nxt = request.form.get("next") or url_for("tasks")
    if not tid:
        flash("Task ID is required.", "error")
        return redirect(nxt)
    if db.execute(
        "SELECT 1 FROM tasks WHERE client_id = ? AND task_id = ?", (cid, tid)
    ).fetchone():
        flash("Task '%s' already exists." % tid, "error")
    else:
        db.execute(
            "INSERT INTO tasks (client_id, task_id, description, status, created_at) VALUES (?,?,?,?,?)",
            (cid, tid, desc, "Active", now),
        )
        db.commit()
        flash("Task '%s' added." % tid, "success")
    return redirect(nxt)


@app.route("/tasks/delete/<task_id>", methods=["POST"])
def tasks_delete(task_id):
    """Delete the task itself. Blocked only while it has hours logged in the
    CURRENT month (it's actively in use / locked); any hours from past months are
    left untouched as history — only the task row is removed."""
    db = get_db()
    cid = current_client_id(db)
    this_month = date.today().strftime("%Y-%m")
    used_this_month = db.execute(
        "SELECT COUNT(*) c FROM timesheet_entries WHERE client_id = ? AND task_id = ? "
        "AND substr(work_date,1,7) = ?",
        (cid, task_id, this_month),
    ).fetchone()["c"]
    if used_this_month:
        flash("Cannot delete '%s' — it has hours logged this month." % task_id, "error")
    else:
        db.execute("DELETE FROM tasks WHERE client_id = ? AND task_id = ?", (cid, task_id))
        db.commit()
        flash("Task '%s' deleted — past logged hours are kept as history." % task_id, "success")
    return redirect(url_for("tasks"))


@app.route("/subtasks/update/<int:sid>", methods=["POST"])
def subtasks_update(sid):
    """Save a single edited row."""
    db = get_db()
    cid = current_client_id(db)
    row = db.execute(
        "SELECT name FROM subtasks WHERE id = ? AND client_id = ?", (sid, cid)
    ).fetchone()
    if not row:
        flash("Sub task not found.", "error")
        return redirect(url_for("tasks", tab="subtasks"))
    name = (request.form.get("name") or "").strip()
    status = request.form.get("status") or "Active"
    if not name:
        flash("Sub task name is required.", "error")
        return redirect(url_for("tasks", tab="subtasks"))
    clash = db.execute(
        "SELECT 1 FROM subtasks WHERE client_id = ? AND name = ? AND id != ?", (cid, name, sid)
    ).fetchone()
    if clash:
        flash("Another sub task is already named '%s'." % name, "error")
        return redirect(url_for("tasks", tab="subtasks"))
    old_name = row["name"]
    db.execute("UPDATE subtasks SET name = ?, status = ? WHERE id = ? AND client_id = ?",
               (name, status, sid, cid))
    if name != old_name:
        # cascade the rename to this client's timesheet entries and entry-default rules
        db.execute(
            "UPDATE timesheet_entries SET sub_task = ? WHERE client_id = ? AND sub_task = ?",
            (name, cid, old_name))
        db.execute(
            "UPDATE entry_defaults SET trigger_value = ? "
            "WHERE client_id = ? AND trigger_field = 'sub_task' AND trigger_value = ?",
            (name, cid, old_name))
        db.execute(
            "UPDATE entry_defaults SET set_sub_task = ? WHERE client_id = ? AND set_sub_task = ?",
            (name, cid, old_name))
    db.commit()
    flash("Sub task updated.", "success")
    return redirect(url_for("tasks", tab="subtasks"))


@app.route("/subtasks/add", methods=["POST"])
def subtasks_add():
    db = get_db()
    cid = current_client_id(db)
    now = datetime.now().isoformat(timespec="seconds")
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Sub task name is required.", "error")
        return redirect(url_for("tasks", tab="subtasks"))
    if db.execute(
        "SELECT 1 FROM subtasks WHERE client_id = ? AND name = ?", (cid, name)
    ).fetchone():
        flash("Sub task '%s' already exists." % name, "error")
    else:
        db.execute(
            "INSERT INTO subtasks (client_id, name, status, created_at) VALUES (?,?,?,?)",
            (cid, name, request.form.get("status") or "Active", now),
        )
        db.commit()
        flash("Sub task '%s' added." % name, "success")
    return redirect(url_for("tasks", tab="subtasks"))


@app.route("/subtasks/delete/<int:sid>", methods=["POST"])
def subtasks_delete(sid):
    db = get_db()
    cid = current_client_id(db)
    row = db.execute(
        "SELECT name FROM subtasks WHERE id = ? AND client_id = ?", (sid, cid)
    ).fetchone()
    if row:
        used = db.execute(
            "SELECT COUNT(*) c FROM timesheet_entries WHERE client_id = ? AND sub_task = ?",
            (cid, row["name"]),
        ).fetchone()["c"]
        if used:
            flash("Cannot delete '%s' — it is used by logged entries." % row["name"], "error")
            return redirect(url_for("tasks", tab="subtasks"))
    db.execute("DELETE FROM subtasks WHERE id = ? AND client_id = ?", (sid, cid))
    db.commit()
    flash("Sub task deleted.", "success")
    return redirect(url_for("tasks", tab="subtasks"))
