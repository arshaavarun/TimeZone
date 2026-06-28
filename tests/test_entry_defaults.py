"""Entry-default rules: seeded on a fresh client, plus add / update / delete."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    c, db = h.client, h.db

    h.section("entry defaults")
    h.check("entry defaults seeded", db.execute("SELECT COUNT(*) c FROM entry_defaults").fetchone()["c"] >= 2)
    c.post("/entry-defaults/add", data={"trigger_field": "task", "trigger_value": "SmokeStandup", "set_hours": "0.5"})
    rid = db.execute("SELECT id FROM entry_defaults WHERE trigger_value='SmokeStandup'").fetchone()["id"]
    c.post("/entry-defaults/update/%d" % rid,
           data={"trigger_field": "task", "trigger_value": "SmokeStandup", "set_hours": "0.75"})
    h.check("entry default updated",
            db.execute("SELECT set_hours FROM entry_defaults WHERE id=?", (rid,)).fetchone()["set_hours"] == 0.75)
    c.post("/entry-defaults/delete/%d" % rid)
    h.check("entry default deleted", db.execute("SELECT 1 FROM entry_defaults WHERE id=?", (rid,)).fetchone() is None)


if __name__ == "__main__":
    standalone(run)
