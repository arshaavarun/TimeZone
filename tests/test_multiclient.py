"""Multi-client: a new client is seeded with defaults and starts empty, per-client
data is isolated, global settings (app_settings) are shared, and archiving a client
makes it read-only (writes blocked) until restored. Self-contained."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db

    h.section("multi-client")
    loren_id = h.client_id("LorenCook") or h.client_id()
    loren_entries = db.execute(
        "SELECT COUNT(*) c FROM timesheet_entries WHERE client_id=?", (loren_id,)).fetchone()["c"]

    # create a fresh client (the add route switches the session to it)
    c.post("/clients/add", data={"name": "ZZAcme"})
    acme = db.execute("SELECT id FROM clients WHERE name='ZZAcme'").fetchone()
    h.check("new client created", acme is not None)
    acme_id = acme["id"]

    h.check("new client seeded with default charge types",
            db.execute("SELECT COUNT(*) c FROM charge_types WHERE client_id=?", (acme_id,)).fetchone()["c"] >= 4)
    h.check("new client seeded with default expense categories",
            db.execute("SELECT COUNT(*) c FROM expense_categories WHERE client_id=?", (acme_id,)).fetchone()["c"] >= 1)
    h.check("new client has its own invoice profile",
            db.execute("SELECT COUNT(*) c FROM client_profile WHERE client_id=?", (acme_id,)).fetchone()["c"] == 1)
    h.check("new client starts with zero timesheet entries",
            db.execute("SELECT COUNT(*) c FROM timesheet_entries WHERE client_id=?", (acme_id,)).fetchone()["c"] == 0)
    h.check("existing client's data untouched by the new client",
            db.execute("SELECT COUNT(*) c FROM timesheet_entries WHERE client_id=?", (loren_id,)).fetchone()["c"] == loren_entries)

    # session is now ZZAcme — adding a task must not appear under the other client
    c.post("/tasks/add", data={"task_id": "ZZONLY", "description": "acme", "next": "/tasks"})
    h.check("per-client task isolated to its client",
            db.execute("SELECT COUNT(*) c FROM tasks WHERE task_id='ZZONLY' AND client_id=?", (acme_id,)).fetchone()["c"] == 1
            and db.execute("SELECT COUNT(*) c FROM tasks WHERE task_id='ZZONLY' AND client_id=?", (loren_id,)).fetchone()["c"] == 0)

    # global business identity / SMTP is shared (single app_settings row)
    c.post("/controls/save", data={"biz_name": "ZZGlobalBiz", "smtp_host": "smtp.example.com",
                                   "smtp_port": "587", "smtp_use_tls": "1"})
    h.check("app_settings is a single shared (global) row",
            db.execute("SELECT COUNT(*) c FROM app_settings").fetchone()["c"] == 1
            and db.execute("SELECT biz_name FROM app_settings WHERE id=1").fetchone()["biz_name"] == "ZZGlobalBiz")

    # archive ZZAcme -> read-only: a write POST is blocked
    c.post("/clients/%d/delete" % acme_id)
    h.check("client archived (soft delete)",
            db.execute("SELECT status FROM clients WHERE id=?", (acme_id,)).fetchone()["status"] == "archived")
    with c.session_transaction() as s:
        s["client_id"] = acme_id
    c.post("/tasks/add", data={"task_id": "ZZBLOCKED", "description": "no", "next": "/tasks"})
    h.check("write blocked while archived (read-only)",
            db.execute("SELECT COUNT(*) c FROM tasks WHERE task_id='ZZBLOCKED'").fetchone()["c"] == 0)
    h.check("archived client pages still load (view-only)",
            "read-only" in c.get("/").get_data(as_text=True).lower())

    # restore -> writes work again
    c.post("/clients/%d/restore" % acme_id)
    c.post("/tasks/add", data={"task_id": "ZZAFTER", "description": "ok", "next": "/tasks"})
    h.check("write works again after restore",
            db.execute("SELECT COUNT(*) c FROM tasks WHERE task_id='ZZAFTER' AND client_id=?", (acme_id,)).fetchone()["c"] == 1)

    # ---- Maintain Clients page + per-client colour remap ----
    from timezone import services
    h.check("client_hue honours a manual override, else falls back to auto",
            services.client_hue({"id": 1, "color_hue": 300}) == 300
            and services.client_hue({"id": 1, "color_hue": None}) == services.client_hue({"id": 1}))
    h.check("Maintain Clients page renders", c.get("/clients").status_code == 200)
    c.post("/clients/%d/update" % acme_id,
           data={"name": "ZZAcme2", "color_hue": "300", "tint_light": "40", "tint_dark": "25"})
    row = db.execute("SELECT name, color_hue, tint_light, tint_dark FROM clients WHERE id=?",
                     (acme_id,)).fetchone()
    h.check("client update renames + remaps colour", row["name"] == "ZZAcme2" and row["color_hue"] == 300)
    h.check("per-client shade strengths (light/dark) saved",
            row["tint_light"] == 40 and row["tint_dark"] == 25)
    c.post("/clients/%d/update" % acme_id, data={"name": "ZZAcme2", "color_hue": ""})
    h.check("blank colour hue clears the override (reverts to auto)",
            db.execute("SELECT color_hue FROM clients WHERE id=?", (acme_id,)).fetchone()["color_hue"] is None)
    # "Auto colour" assigns a fresh CONCRETE hue (distinct from other clients),
    # not the deterministic id-derived one — sent as auto=1 from the page.
    ja_auto = c.post("/clients/%d/update" % acme_id,
                     data={"name": "ZZAcme2", "auto": "1"},
                     headers={"X-Requested-With": "fetch"}).get_json()
    auto_hue = db.execute("SELECT color_hue FROM clients WHERE id=?", (acme_id,)).fetchone()["color_hue"]
    h.check("'Auto colour' assigns a concrete hue (override set), echoed in the JSON",
            auto_hue is not None and 0 <= auto_hue <= 359
            and bool(ja_auto) and ja_auto.get("hue") == auto_hue and ja_auto.get("custom") is True)
    # pick_distinct_hue stays clear of the hues it is given
    def _gap(a, b): return min((a - b) % 360, (b - a) % 360)
    ph = services.pick_distinct_hue([0, 90, 180, 270])
    h.check("pick_distinct_hue avoids the supplied hues",
            0 <= ph <= 359 and min(_gap(ph, o) for o in (0, 90, 180, 270)) >= 30)
    # restore a known override for the AJAX check below
    c.post("/clients/%d/update" % acme_id, data={"name": "ZZAcme2", "color_hue": ""})
    # the Maintain Clients page saves via AJAX (no navigation -> no Back-button pile-up)
    ja = c.post("/clients/%d/update" % acme_id,
                data={"name": "ZZAcme2", "color_hue": "150", "tint_light": "30", "tint_dark": "20"},
                headers={"X-Requested-With": "fetch"}).get_json()
    h.check("client update via AJAX returns JSON (no page navigation)",
            bool(ja) and ja.get("ok") and ja.get("hue") == 150
            and ja.get("tint_light") == 30 and ja.get("custom") is True)
    # the Home dropdown switches via AJAX, getting back the new client's colour
    js = c.post("/clients/switch", data={"client_id": acme_id},
                headers={"X-Requested-With": "fetch"}).get_json()
    h.check("client switch via AJAX returns the new client's colour",
            bool(js) and js.get("ok") and js.get("id") == acme_id and "hue" in js)

    # client management must keep working while an archived client is selected
    c.post("/clients/%d/delete" % acme_id)
    mc = c.get("/clients").get_data(as_text=True)
    h.check("Maintain Clients splits active + de-activated, with Switch-to only in archived",
            "Active clients" in mc and "De-activated clients" in mc
            and "/clients/switch" in mc and "Switch to" in mc)
    with c.session_transaction() as s:
        s["client_id"] = acme_id
    c.post("/clients/%d/update" % acme_id, data={"name": "ZZAcme3", "color_hue": "120"})
    h.check("client management works even while viewing an archived client",
            db.execute("SELECT name FROM clients WHERE id=?", (acme_id,)).fetchone()["name"] == "ZZAcme3")
    c.post("/clients/%d/restore" % acme_id)

    # leave the session on the original client for any later groups
    with c.session_transaction() as s:
        s["client_id"] = loren_id


if __name__ == "__main__":
    standalone(run)
