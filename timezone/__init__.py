"""
TimeZone application package.

Wires everything together: creates the Flask app, registers the DB teardown,
template globals and the ``money`` filter, runs ``init_db()``, then imports the
view modules so their routes attach to the app.

Modules
-------
config.py            constants
database.py          connections, schema/migrations, seeding, backups
services.py          pure business logic (charges, calendar, invoicing)
pdfs.py              invoice PDF builder (ReportLab)
views_*.py           one module per feature area, holding the @app.route handlers
"""
import os
from datetime import date

from flask import Flask, url_for, request, redirect, flash

from timezone import config
from timezone.database import close_db, init_db, get_db
from timezone import services

app = Flask(
    __name__,
    template_folder=os.path.join(config.BASE_DIR, "templates"),
    static_folder=os.path.join(config.BASE_DIR, "static"),
)
app.secret_key = "timesheet-invoicing-local-secret-key-change-me"
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

# close the request DB connection after each request
app.teardown_appcontext(close_db)


# Management endpoints that must keep working even while an archived (read-only)
# client is selected — switching clients, adding/restoring, and global controls.
_ARCHIVE_EXEMPT = {
    "clients_switch", "clients_add", "clients_delete", "clients_restore",
    "clients_update", "controls_save", "controls_backup",
}


@app.before_request
def _guard_archived_client():
    """Archived clients are view-only: block every state-changing POST except the
    roster/controls management actions, redirecting back with a notice."""
    if request.method != "POST" or request.endpoint in _ARCHIVE_EXEMPT:
        return
    client = services.current_client(get_db())
    if client and client["status"] == "archived":
        flash("This client is archived (read-only). Restore it to make changes.", "error")
        return redirect(request.referrer or url_for("home"))


@app.context_processor
def inject_globals():
    """Values available in every template (incl. the client switcher + read-only flag)."""
    db = get_db()
    rows = db.execute("SELECT * FROM clients ORDER BY status, name").fetchall()
    clients = [{
        "id": r["id"], "name": r["name"], "status": r["status"],
        "hue": services.client_hue(r),
        "tint_light": r["tint_light"] if r["tint_light"] is not None else config.DEFAULT_TINT_LIGHT,
        "tint_dark": r["tint_dark"] if r["tint_dark"] is not None else config.DEFAULT_TINT_DARK,
    } for r in rows]
    current = services.current_client(db)
    return {
        "CURRENCY_SYMBOLS": config.CURRENCY_SYMBOLS,
        "DAY_TYPE_LABELS": config.DAY_TYPE_LABELS,
        "now_year": date.today().year,
        "clients": clients,
        "current_client": current,
        "client_hue": services.client_hue(current),
        # per-client background-shade strength overrides (None -> CSS default)
        "client_tint_light": current["tint_light"] if current else None,
        "client_tint_dark": current["tint_dark"] if current else None,
        "read_only": bool(current and current["status"] == "archived"),
    }


@app.after_request
def _no_store_html(resp):
    """Never let the browser serve a stale dynamic page from its HTTP/back-forward
    cache — e.g. the Home progress bars must reflect hours just logged when you
    navigate back. Only HTML is marked no-store; static assets keep their normal
    caching (they're already cache-busted via ``asset_url``)."""
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"
    return resp


app.jinja_env.filters["money"] = services.fmt_money


def asset_url(filename):
    """Static URL with a cache-busting ``?v=<mtime>`` query. The server hot-reloads
    code, but browsers cache static files (CSS/JS) for hours — without this they
    can keep serving a stale stylesheet/script after an update. The version
    changes only when the file itself changes, so caching still works normally."""
    full = os.path.join(app.static_folder, filename)
    try:
        ver = int(os.path.getmtime(full))
    except OSError:
        ver = 0
    return url_for("static", filename=filename, v=ver)


app.jinja_env.globals["asset_url"] = asset_url

from timezone.icons import ico, alt_ico  # noqa: E402
app.jinja_env.globals["ico"] = ico
app.jinja_env.globals["alt_ico"] = alt_ico

# create tables / seed defaults on import (works under both `python app.py`
# and a WSGI server)
init_db()

# importing the view modules registers their @app.route handlers on `app`
from timezone import (  # noqa: E402,F401
    views_main, views_tasks, views_timesheet, views_reports,
    views_expenses, views_invoices, views_settings,
    views_clients, views_controls,
)
