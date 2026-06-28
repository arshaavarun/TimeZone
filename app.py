"""
TimeZone — Timesheet & Invoicing App  (launcher)
================================================
A single-user, self-hosted Flask + SQLite web app. The browser (laptop or a
phone on the same Wi-Fi) is the UI.

The application now lives in the ``timezone/`` package — this file is just the
launcher that `python app.py` runs. See ``timezone/__init__.py`` for how the
pieces fit together:

    timezone/config.py        constants
    timezone/database.py      connections, schema/migrations, seeding, backups
    timezone/services.py      pure business logic (charges, calendar, invoicing)
    timezone/pdfs.py          invoice PDF builder
    timezone/views_*.py       one module per feature area (the route handlers)

Run:  python app.py                                   -> serves on 0.0.0.0:5000
      waitress-serve --listen=0.0.0.0:5000 app:app    -> steadier production server
"""
import socket

from timezone import app                  # the configured Flask app (routes attached on import)
from timezone.config import DB_PATH
from timezone.database import backup_db


def lan_ip():
    """Discover the routable LAN interface (no packets sent) to print a phone URL."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:  # noqa: BLE001
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


if __name__ == "__main__":
    saved = backup_db()
    ip = lan_ip()
    print("=" * 60)
    print("TimeZone — Timesheet & Invoicing App")
    print("  DB: %s" % DB_PATH)
    if saved:
        print("  Backup: %s" % saved)
    print("  Laptop : http://127.0.0.1:5000")
    print("  Phone  : http://%s:5000  (same Wi-Fi)" % ip)
    print("  (Windows firewall must allow Python on Private networks.)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000)
