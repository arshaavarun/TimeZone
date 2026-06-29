"""
TimeZone — headless launcher for always-on / background running.

Unlike ``app.py`` (the friendly, console-based launcher you double-click), this
one prints nothing and is meant to be started hidden — e.g. by Windows Task
Scheduler at logon via ``pythonw serve.py`` (``pythonw`` = no console window).

It serves with waitress (a steadier production server than Flask's built-in
one) and, by default, AUTO-RELOADS: saving any ``.py`` file or template restarts
the server so your changes go live without a manual restart. Set the env var
``TIMEZONE_RELOAD=0`` to turn that off (then code changes need service_restart).

If waitress isn't installed it falls back to the Flask server; if hupper isn't
installed it runs without auto-reload. Either way the portal still comes up.

    pythonw serve.py    -> serves on 0.0.0.0:5000 with no window
"""
import glob
import os
import sys

# Under Windows Store Python the ``pythonw`` alias reports ``sys.executable`` as
# the *console* python.exe. hupper re-spawns the server via ``sys.executable``
# on each reload, so without this pin those re-spawns would be console
# processes and could flash a black window on the hidden background service.
# Pinning to pythonw.exe keeps every reload windowless.
_pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if os.name == "nt" and os.path.exists(_pythonw):
    sys.executable = _pythonw

from timezone import app                 # configured Flask app (routes attached on import)
from timezone import config
from timezone.database import backup_db, start_periodic_backups

HOST = "0.0.0.0"
PORT = int(os.environ.get("TIMEZONE_PORT", "5000"))   # override for tests

# Auto-reload on source changes. On by default; set TIMEZONE_RELOAD=0 to disable.
RELOAD = os.environ.get("TIMEZONE_RELOAD", "1") != "0"


def _template_files():
    """Template files to watch alongside the Python modules hupper tracks by
    default. (Static CSS/JS is served straight from disk, so it needs no reload —
    just a browser refresh — and is deliberately not watched.)"""
    pattern = os.path.join(config.BASE_DIR, "templates", "**", "*.html")
    return glob.glob(pattern, recursive=True)


def _run_server():
    # runs in the reload worker (and the no-reload process) — start the intra-day
    # periodic backups here so exactly one thread runs per live server process.
    start_periodic_backups(config.BACKUP_INTERVAL_HOURS * 3600)
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT)
    except ImportError:
        # waitress missing — fall back to Flask's own server so we still run
        app.run(host=HOST, port=PORT)


def main():
    if RELOAD:
        try:
            import hupper
        except ImportError:
            hupper = None
        if hupper is not None:
            # Back up once, in the monitor process, not on every reload. The
            # flag is inherited by the reload workers, so they skip it.
            if not os.environ.get("TIMEZONE_RELOAD_WORKER"):
                backup_db()
                os.environ["TIMEZONE_RELOAD_WORKER"] = "1"
            reloader = hupper.start_reloader("serve.main")  # returns only in the worker
            reloader.watch_files(_template_files())
            _run_server()
            return
    # no-reload path (TIMEZONE_RELOAD=0 or hupper unavailable)
    backup_db()
    _run_server()


if __name__ == "__main__":
    main()
