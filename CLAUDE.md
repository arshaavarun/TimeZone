# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

TimeZone — a self-hosted **Flask + SQLite** timesheet & invoicing web app. There is no build step and no frontend framework: server-rendered Jinja templates in `templates/`, one stylesheet (`static/style.css`) and one script (`static/app.js`). The browser (laptop, or a phone on the same Wi-Fi) is the UI. Runs on Windows; shell commands here assume PowerShell or Git Bash.

Dependencies are not pinned in a requirements file. Needs: `flask`, `waitress`, `hupper`, `reportlab` (invoice PDFs), `openpyxl` (xlsx report export).

## Running

```bash
python app.py            # console launcher — Flask dev server on 0.0.0.0:5000, prints a phone URL
pythonw serve.py         # headless — waitress + hupper auto-reload, no console window
```

`serve.py` is the production/always-on path: in normal use it is already running as a background **Windows Task Scheduler job named "TimeZone"** (set up by `install_autostart.py`; managed via `service_start.bat` / `service_stop.bat` / `service_restart.bat`). **hupper auto-reloads on any `.py` or template save**, so code/template edits go live without a restart — do not tell the user to restart the server for those. Static CSS/JS changes need only a browser refresh (cache-busted via `asset_url`). Set `TIMEZONE_RELOAD=0` to disable auto-reload; `TIMEZONE_PORT` overrides the port.

Both launchers take a timestamped DB backup into `backups/` on start (keeps the latest 20).

## Tests

These are **custom functional scripts, not pytest** — each `tests/test_<area>.py` exposes `run(h)` and uses a `Harness` with a `check(name, cond)` helper. Do not run `pytest`.

```bash
python tests/smoke_test.py                 # all groups (email group skipped by default)
python tests/smoke_test.py tasks invoices  # only the named groups
python tests/smoke_test.py --list          # list group names
python tests/smoke_test.py --email         # include the opt-in email group
python tests/test_tasks.py                 # run one group standalone
```

The harness **snapshots the real `timezone.db` into a throwaway temp copy** (via `TIMEZONE_DB` env var + SQLite's online-backup API) so the real data is never touched, then points a Flask test client at the copy. Run the suite after changing code. Exit 0 = all passed, 1 = failures.

`tests/test_autoreload.py` actually launches `serve.py` and verifies hupper restarts on a file change. `tests/test_ui.py` checks rendered HTML/CSS.

## Architecture

The app is the `timezone/` package; `app.py` and `serve.py` are thin launchers that `import timezone.app`.

**Wiring (`timezone/__init__.py`)** — creates the Flask `app`, then **imports every `views_*` module at the bottom purely for its side effects**: each view module does `from timezone import app` and attaches routes with `@app.route`. There is no blueprint registry — importing the module *is* the registration. `__init__` also installs:
- `@app.before_request` archived-client guard (see multi-client below),
- `@app.context_processor` injecting `clients`, `current_client`, `client_hue`, and `read_only` into every template,
- Jinja globals `ico` / `alt_ico` (icons) and `asset_url` (cache-busting static URLs), the `money` filter, and `init_db()`.

**Layers** (import direction is one-way: views → services → database → config):
- `config.py` — pure constants and `DEFAULT_*` seed data. No Flask, no DB. Imported everywhere via `from timezone.config import *`.
- `database.py` — per-request SQLite connection on Flask's `g`, schema (all `CREATE … IF NOT EXISTS`), the one-time migration to multi-client, per-client seeding, startup backup. `init_db()` is idempotent.
- `services.py` — **pure business logic** (client scoping, charge-rate computation, month calendar/progress, invoice line generation & totals, subscription cycles, money formatting). No routes; this is where logic-heavy changes belong.
- `pdfs.py` (ReportLab invoice PDF) and `mailer.py` (SMTP). `views_*.py` — one module per feature area, holding the route handlers (they wildcard-import config + services).

**Multi-client model (central concept).** One SQLite file holds all clients' data. Tables are either **global** (`clients`, `app_settings` — no `client_id`) or **per-client** (everything else carries `client_id`). The selected client lives in the Flask session; **every per-client query must be scoped through `services.current_client_id(db)`**. A client is never hard-deleted — "delete" sets `status='archived'`, and archived clients are **read-only**: the `before_request` guard blocks every state-changing POST except a small allow-list of management endpoints (`_ARCHIVE_EXEMPT` in `__init__.py`). On an old single-client DB, `init_db()` folds the existing data under the first client (`FIRST_CLIENT_NAME`).

**Icon system.** No emoji and no image files for UI icons. `ico(name, cls, style, alt=True)` (Jinja global, defined in `timezone/icons.py`) emits an inline `<svg>` line glyph plus one variant SVG per downloadable pack that has the icon (`icons_flatcolor.py` = Icons8, `icons_solar.py`, `icons_material.py`). Which pack shows is a pure-CSS choice driven by `data-icon-style` on `<html>` (persisted in `localStorage`, applied pre-paint by an inline script in `layout.html`). The attribute is **always present** — every pack (`semantic`/`tile`/`fc`/`solar`/`ms`) is an explicit CSS state, and the app default is **`fc` (Flat colour)**, set pre-paint when nothing is saved. See `static/style.css` for the pack rules. When adding an icon, add it to `_ICONS` (and optionally the pack dicts).

## Project rules (explicit conventions — follow these)

Standing rules for this codebase. Keep this list **living**: when a new durable rule, non-obvious convention, or gotcha emerges, add it here without being asked.

- **Icon coverage** — any new icon design, pack, or preview must cover *every* app icon (edit, view, PDF/download, email, print, settings, …), not just the six Home-page tiles. A preview that shows only a handful is incomplete.
- **Table layout** — in every table: all cell data is vertically middle-aligned; the per-row action buttons are centred, equally sized (32×32) and equally spaced, and coloured by the active icon pack.
- **Clean up with every change** — when you modify a function, immediately do the related cleanup in the same pass (remove now-dead code, stale params, obsolete imports/helpers, outdated comments) rather than deferring it.
- **Keep tests in step** — when you change a function's behaviour, promptly update its test cases and add any that are missing; run `tests/smoke_test.py` to confirm.
- **Regular code cleanup** — beyond the per-change cleanup above, periodically sweep the whole codebase for accumulated cruft and remove it: dead code (unused CSS vars/selectors/classes, unused JS, icons no longer referenced in any template, unreachable branches), stale or contradictory comments, leftover legacy/`(legacy)`-tagged definitions, and obsolete helpers/params. Verify each removal is truly unreferenced (grep templates + static + `timezone/`) before deleting, then run `tests/smoke_test.py`. Do this as a deliberate standalone pass, not only when a feature happens to touch the area.

## Conventions & gotchas

- View modules intentionally use wildcard imports (`from timezone.config import *`, `from timezone.services import *`) — match that style.
- Email: `mailer._transport_send` isolates the actual SMTP send so tests monkeypatch it. The live `timezone.db` may have real recipients configured — running the real app (not the test harness) can send real email. Use the test harness (throwaway DB) for verification; the email test group is opt-in.
- DB schema changes: add `CREATE … IF NOT EXISTS` to `database.py` and, for columns on existing tables, an additive `ALTER`/migration step there — `init_db()` must stay safe to re-run on a populated DB.
- Per-client tables use composite uniqueness (e.g. `(client_id, …)`); indexes are created after the multi-client migration, not inside the schema block.
