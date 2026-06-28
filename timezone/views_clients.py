"""Client roster routes — the Maintain Clients page plus switch / add / archive
(delete) / restore / update.

These power the "Switch Client" dropdown in the top bar and the Maintain Clients
page (``/clients``). They are *management* actions, not client data, so they stay
available even while an archived (read-only) client is selected (see the
archived-POST guard in ``__init__``).

A client is never hard-deleted: "delete" sets status='archived' (kept,
read-only); "restore" sets it back to 'active'. Switching just records the
chosen client id in the Flask session (per browser). ``update`` edits the name
and the optional colour-hue override (blank = automatic colour).
"""
from datetime import datetime, date

from flask import render_template, request, redirect, url_for, flash, session, jsonify

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db, seed_client_defaults
from timezone.services import current_client_id, client_hue, pick_distinct_hue


def _back():
    """Redirect target after a roster action — the page we came from, else home."""
    return request.form.get("next") or request.referrer or url_for("home")


@app.route("/clients")
def clients_manage():
    """Maintain Clients: rename, recolour, activate/deactivate, and pick which
    client to work with — the full page behind the dropdown's "Switch Client"."""
    db = get_db()
    rows = db.execute("SELECT * FROM clients ORDER BY status, name").fetchall()
    clients = [{
        "id": r["id"], "name": r["name"], "status": r["status"],
        "archived_on": r["archived_on"],
        "hue": client_hue(r),
        "custom": r["color_hue"] is not None,
        # effective shade strengths (override, else the default) for the sliders
        "tint_light": r["tint_light"] if r["tint_light"] is not None else DEFAULT_TINT_LIGHT,
        "tint_dark": r["tint_dark"] if r["tint_dark"] is not None else DEFAULT_TINT_DARK,
    } for r in rows]
    return render_template(
        "maintain_clients.html", clients=clients, current_id=current_client_id(db),
        tint_min=TINT_MIN, tint_max=TINT_MAX,
        has_archived=any(c["status"] == "archived" for c in clients),
    )


@app.route("/clients/<int:client_id>/update", methods=["POST"])
def clients_update(client_id):
    """Save a client's name, colour and per-theme shade strengths. A blank colour
    hue clears the override (reverts to the automatic id-derived colour).

    Called via fetch from the Maintain Clients page (header ``X-Requested-With:
    fetch``) so saving never navigates — this keeps repeated colour edits out of
    the browser history. Returns JSON for AJAX, or redirects for a plain submit."""
    db = get_db()
    ajax = request.headers.get("X-Requested-With") == "fetch"

    def fail(msg, code=400):
        if ajax:
            return jsonify(ok=False, error=msg), code
        flash(msg, "error")
        return redirect(url_for("clients_manage"))

    if not db.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone():
        return fail("That client no longer exists.", 404)
    name = (request.form.get("name") or "").strip()
    if not name:
        return fail("Client name is required.")
    if db.execute(
        "SELECT 1 FROM clients WHERE name = ? COLLATE NOCASE AND id != ?", (name, client_id)
    ).fetchone():
        return fail("Another client is already named '%s'." % name)

    hue_raw = (request.form.get("color_hue") or "").strip()
    if request.form.get("auto"):
        # "Auto colour": assign a fresh hue that is distinct from every OTHER
        # client's current colour (and different each press), rather than reverting
        # to the deterministic id-derived hue.
        others = db.execute(
            "SELECT * FROM clients WHERE id != ?", (client_id,)
        ).fetchall()
        color_hue = pick_distinct_hue([client_hue(r) for r in others])
    elif hue_raw == "":
        color_hue = None                      # automatic colour
    else:
        try:
            color_hue = int(float(hue_raw)) % 360
        except ValueError:
            color_hue = None

    def _tint(field):
        """Clamp a shade-strength slider value; blank -> NULL (use the default)."""
        raw = (request.form.get(field) or "").strip()
        if raw == "":
            return None
        try:
            return max(TINT_MIN, min(TINT_MAX, int(float(raw))))
        except ValueError:
            return None

    db.execute(
        "UPDATE clients SET name = ?, color_hue = ?, tint_light = ?, tint_dark = ? WHERE id = ?",
        (name, color_hue, _tint("tint_light"), _tint("tint_dark"), client_id),
    )
    db.commit()

    if ajax:
        u = db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return jsonify(
            ok=True, id=client_id, name=name, hue=client_hue(u),
            custom=(u["color_hue"] is not None),
            tint_light=(u["tint_light"] if u["tint_light"] is not None else DEFAULT_TINT_LIGHT),
            tint_dark=(u["tint_dark"] if u["tint_dark"] is not None else DEFAULT_TINT_DARK),
        )
    flash("Client '%s' saved." % name, "success")
    return redirect(url_for("clients_manage"))


@app.route("/clients/switch", methods=["POST"])
def clients_switch():
    """Select a client as the current one for this browser. The Home client-name
    dropdown calls this via fetch (header ``X-Requested-With: fetch``) and gets the
    new client's colour back as JSON so it can run the ripple recolour without a
    full navigation; a plain submit just redirects to Home."""
    db = get_db()
    ajax = request.headers.get("X-Requested-With") == "fetch"
    try:
        target = int(request.form.get("client_id") or 0)
    except ValueError:
        target = 0
    row = db.execute("SELECT * FROM clients WHERE id = ?", (target,)).fetchone()
    if not row:
        if ajax:
            return jsonify(ok=False, error="That client no longer exists."), 404
        flash("That client no longer exists.", "error")
        return redirect(_back())
    session["client_id"] = row["id"]
    if ajax:
        return jsonify(
            ok=True, id=row["id"], name=row["name"], hue=client_hue(row),
            tint_light=(row["tint_light"] if row["tint_light"] is not None else DEFAULT_TINT_LIGHT),
            tint_dark=(row["tint_dark"] if row["tint_dark"] is not None else DEFAULT_TINT_DARK),
        )
    flash("Switched to %s." % row["name"], "success")
    # land on Home so the new client's dashboard shows immediately
    return redirect(url_for("home"))


@app.route("/clients/add", methods=["POST"])
def clients_add():
    """Create a new client with fully-defaulted (empty) data and switch to it."""
    db = get_db()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Client name is required.", "error")
        return redirect(_back())
    if db.execute("SELECT 1 FROM clients WHERE name = ? COLLATE NOCASE", (name,)).fetchone():
        flash("A client named '%s' already exists." % name, "error")
        return redirect(_back())
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO clients (name, status, created_at) VALUES (?, 'active', ?)", (name, now)
    )
    new_id = cur.lastrowid
    seed_client_defaults(db, new_id)   # commits
    session["client_id"] = new_id      # work on the new client right away
    flash("Client '%s' created." % name, "success")
    return redirect(url_for("home"))


@app.route("/clients/<int:client_id>/delete", methods=["POST"])
def clients_delete(client_id):
    """Archive a client (soft delete): its data is kept but becomes read-only."""
    db = get_db()
    row = db.execute("SELECT name, status FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        flash("That client no longer exists.", "error")
        return redirect(_back())
    db.execute(
        "UPDATE clients SET status = 'archived', archived_on = ? WHERE id = ?",
        (date.today().isoformat(), client_id),
    )
    db.commit()
    flash("Client '%s' archived (read-only). Restore it anytime." % row["name"], "success")
    return redirect(_back())


@app.route("/clients/<int:client_id>/restore", methods=["POST"])
def clients_restore(client_id):
    """Restore an archived client back to active (editable) state."""
    db = get_db()
    row = db.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        flash("That client no longer exists.", "error")
        return redirect(_back())
    db.execute(
        "UPDATE clients SET status = 'active', archived_on = NULL WHERE id = ?", (client_id,)
    )
    db.commit()
    flash("Client '%s' restored." % row["name"], "success")
    return redirect(_back())
