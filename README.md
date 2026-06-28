# TimeZone

A self-hosted, single-owner **timesheet & invoicing** web app for an independent consultant. It tracks daily hours per client, manages tasks/sub-tasks and charge rates, records expenses (with subscriptions and warranties), and generates GST-aware invoices as PDFs that can be emailed with an attached hours report.

Server-rendered **Flask + SQLite** — no build step and no frontend framework. The browser (laptop, or a phone on the same Wi-Fi) is the UI: one stylesheet (`static/style.css`) and one script (`static/app.js`), with Jinja templates in `templates/`.

## Highlights

- **Multi-client** — one SQLite file holds every client's data, scoped by `client_id`; switch clients from the top bar. Deleting a client archives it (read-only) rather than destroying data.
- **Timesheet** — month calendar + per-day entry with charge-method auto-rules and completion progress.
- **Invoicing** — line generation from logged hours, CGST/SGST or single-IGST, USD/INR with an FX rate, PDF export (ReportLab), and optional auto-email (SMTP) with an `.xlsx` hours report.
- **Expenses** — purchases, categories, warranties, and subscription cycles.
- **Theming** — light/dark mode, five icon packs, and several button/control styles, all client-tinted.

## Requirements

Python 3.11+, with: `flask`, `waitress`, `hupper`, `reportlab` (invoice PDFs), `openpyxl` (xlsx report export).

```bash
pip install flask waitress hupper reportlab openpyxl
```

## Running

```bash
python app.py        # console dev server on 0.0.0.0:5000 (prints a phone URL)
pythonw serve.py     # headless waitress + hupper auto-reload, no console window
```

`serve.py` is the always-on path (set up to run as a Windows Task Scheduler job by `install_autostart.py`). Both launchers take a timestamped DB backup into `backups/` on start. `hupper` hot-reloads on any `.py`/template save; static CSS/JS changes just need a browser refresh (they're cache-busted). `TIMEZONE_PORT` overrides the port; `TIMEZONE_RELOAD=0` disables auto-reload.

## Tests

Custom functional scripts (not pytest). Each run snapshots the real DB into a throwaway copy, so live data is never touched.

```bash
python tests/smoke_test.py            # all groups (email group is opt-in)
python tests/smoke_test.py --list     # list group names
python tests/smoke_test.py tasks invoices   # run only named groups
```

## Notes

The repository intentionally excludes the live database (`timezone.db`), its `backups/`, and uploaded `attachments/` — they hold real client data and the SMTP password. A fresh `timezone.db` is created automatically on first run.
