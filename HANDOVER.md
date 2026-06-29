# TimeZone — Project Hand-over

A complete picture for anyone taking this project over. For day-to-day coding conventions, also read [`CLAUDE.md`](CLAUDE.md); for the non-coder setup path, read [`README.md`](README.md).

---

## 1. What it is

**TimeZone** is a self-hosted **timesheet + invoicing web app** for a single consultant who bills multiple clients. One person owns it; the browser (laptop, or a phone on the same Wi-Fi) is the entire UI. It tracks daily worked hours per task, expenses, and generates/sends invoices (PDF + email), with per-client isolation inside a single database.

- **Stack:** Python **Flask** + **SQLite**, server-rendered **Jinja** templates. **No build step, no JS framework, no CSS framework** — one stylesheet (`static/style.css`), one script (`static/app.js`).
- **Platform:** Windows (PowerShell / Git Bash). Runs as an always-on background service.
- **Dependencies** (`requirements.txt`, unpinned): `flask`, `waitress` (production WSGI), `hupper` (auto-reload), `reportlab` (invoice PDFs), `openpyxl` (xlsx report export). Install with `python -m pip install -r requirements.txt`.

---

## 2. How to run

| Command | Purpose |
|---|---|
| `python app.py` | Console dev server (Flask) on `0.0.0.0:5000`; prints a phone URL. |
| `pythonw serve.py` | **Headless production path** — waitress + hupper auto-reload, no console window. |
| `Start TimeZone.bat` | Double-click launcher; installs `requirements.txt` on first run, then runs `app.py`. |

- **In normal use it already runs as a Windows Task Scheduler job named "TimeZone"** (`pythonw serve.py`), set up by `install_autostart.py`/`install_autostart.bat` and managed via `service_start.bat` / `service_stop.bat` / `service_restart.bat` (`uninstall_autostart.bat` removes it).
- **hupper auto-reloads on any `.py` or template save** — code/template edits go live with no restart. Static CSS/JS changes need only a browser refresh (cache-busted via `asset_url`).
- **Environment knobs:** `TIMEZONE_PORT` (port), `TIMEZONE_RELOAD=0` (disable auto-reload), `TIMEZONE_DB` (DB path — used by tests), `TIMEZONE_BACKUP_DIR` (backup folder — used by tests), `BACKUP_INTERVAL_HOURS`, `BACKUP_MAX_AGE_DAYS`, `SESSION_DAYS`.

---

## 3. Architecture

`app.py` and `serve.py` are **thin launchers** that import the `timezone/` package.

**Wiring — `timezone/__init__.py`:** creates the Flask `app`, then **imports every `views_*` module at the bottom purely for side effects** — each module does `from timezone import app` and attaches routes with `@app.route`. Importing the module *is* the registration (there is no blueprint registry). It also installs, in order:
1. `@app.before_request` **owner-login guard** (`_require_login`) — runs first,
2. `@app.before_request` **archived-client guard**,
3. `@app.context_processor` injecting `clients`, `current_client`, `client_hue`, `read_only` into every template,
4. Jinja globals `ico` / `alt_ico` (icons) and `asset_url` (cache-busting), the `money` filter, and `init_db()`.

**Layers (one-way import direction: views → services → database → config):**

- `config.py` — pure constants + `DEFAULT_*` seed data. No Flask, no DB. Wildcard-imported everywhere (`from timezone.config import *`).
- `database.py` — per-request SQLite connection on Flask `g`, schema (`CREATE … IF NOT EXISTS`), the one-time multi-client migration, per-client seeding, backups, WAL. `init_db()` is **idempotent** (safe to re-run on a populated DB).
- `services.py` — **pure business logic** (client scoping, charge-rate computation, month calendar/progress, invoice line generation & totals, subscription cycles, money formatting). No routes; logic-heavy changes belong here.
- `pdfs.py` (ReportLab invoice PDF), `mailer.py` (SMTP), and `views_*.py` (one module per feature area; they wildcard-import config + services).

**View modules & approximate route counts:** `views_main` (home), `views_timesheet` (8), `views_tasks` (9), `views_clients` (6), `views_expenses` (6), `views_invoices` (10), `views_reports` (2), `views_settings` (16), `views_controls` (6), `views_auth` (3).

---

## 4. Data model

**One SQLite file (`timezone.db`) holds all clients' data.** Tables are either **global** (no `client_id`) or **per-client** (carry `client_id`).

- **Global:** `clients`, `app_settings`.
- **Per-client:** `client_profile`, `tasks`, `subtasks`, `charge_types`, `timesheet_entries`, `timesheet_days`, `expenses`, `expense_categories`, `expense_attachments`, `invoice_email_recipients`, `invoices`, `invoice_items`, `entry_defaults`.

**Central rule:** the selected client lives in the Flask session; **every per-client query must be scoped through `services.current_client_id(db)`**. Per-client tables use composite uniqueness (`(client_id, …)`); their indexes are created after the multi-client migration, not in the schema block.

**Soft-delete clients:** a client is never hard-deleted — "delete" sets `status='archived'`. **Archived clients are read-only**: the archived-client guard blocks every state-changing POST except an allow-list (`_ARCHIVE_EXEMPT` in `__init__.py`). On an old single-client DB, `init_db()` folds existing data under the first client.

**Schema changes must be additive:** add `CREATE … IF NOT EXISTS` plus an additive `ALTER`/migration step in `database.py`. Never write a migration that breaks re-running on a populated DB.

---

## 5. Feature areas (what the app does)

- **Home** (`views_main`, `home.html`) — six feature tiles + client switcher.
- **Timesheet / day entry** (`views_timesheet`, `entry.html` calendar, `day.html`) — month calendar with per-day state (complete / partial / none / holiday / leave); add/edit hour entries per task & sub-task; "Add Task" shortcut into Maintain Tasks.
- **Tasks** (`views_tasks`, `maintain_tasks.html`) — manage Tasks and Sub Tasks.
- **Clients** (`views_clients`, `maintain_clients.html`) — add/edit/archive clients, per-client hue/auto-colour, switch active client.
- **Expenses** (`views_expenses`, `expenses.html`, `expense_form.html`) — categorised expenses with file attachments; Totals expander.
- **Invoices** (`views_invoices`, `invoices.html`, `invoice_form.html`, `invoice_view.html`) — generate invoices from logged hours, USD/INR with hand-typed FX → INR conversion, **status `generated → paid`** (binary, by design), PDF download, email to recipients.
- **Reports** (`views_reports`, `report.html`) — xlsx hours report tied to an invoice period.
- **Settings** (`views_settings`, `settings.html`) — client profile, charge types, invoice/email settings, recipients, entry defaults.
- **TZ Controls** (`views_controls`, `controls.html`) — global app settings, SMTP, **Backup** tab (back up now / download / restore / cloud folder), icon/theme controls.
- **Auth** (`views_auth`, `setup.html`, `login.html`) — first-run setup + login/logout.

---

## 6. Front-end system (no framework)

**Three *orthogonal* looks**, each chosen by an attribute on `<html>`, applied **pre-paint** by inline scripts in `layout.html` and persisted in `localStorage`:

- `data-theme` — light / dark.
- `data-ui-theme` — button/control style (Classic / Flat / Soft / Outline / Pill / Sharp / Neumorphic). Each variant re-declares the `--btn3d-*` background/border/shadow vars + `--ctl-radius` that every `.btn`, `select`, and `.tab-btn` consume.
- `data-icon-style` — icon pack (below). **Always present**; app default is **`fc` (Flat colour)**.

Separately, the selected client's `--client-hue` (on `<body>`) drives a **viewport-fixed** page-gradient tint (`body.tinted::before`) and accent colours.

**Icon system** (`timezone/icons.py`): no emoji, no image files. `ico(name, cls, style, alt=True)` Jinja global emits an inline line-glyph `<svg>` plus one variant per downloadable pack that has the icon (`icons_flatcolor.py` = Icons8, `icons_solar.py`, `icons_material.py`). Which pack shows is a pure-CSS choice driven by `data-icon-style`. Icon SVGs are `aria-hidden`. **Rule:** any new icon design/pack/preview must cover *every* app icon, not just the home tiles.

**Interaction** (`static/app.js`): `.inplace` forms POST via `fetch` then reload with `location.replace`; `data-soft="<selector>"` swaps just that region in place. One-shot `sessionStorage` keys carry state across an in-place reload — `tz_scroll` and `tz_tab_once:<path>`. Tabbed sections open the **first** tab on a fresh visit and only restore the worked tab across an in-place reload.

**Standing rule — Browser Back = app back:** Back must never replay an in-app action or re-enter a backed-out detour. Two mechanisms: in-place actions use `location.replace` (no history entry); any "Back / return to X" link carries **`data-back`** → a delegated handler does `history.back()` (falling back to its `href` via `location.replace`). Never ship a back-out control as a plain pushing `<a href>`.

**Accessibility (standing rule):** Tab/Shift+Tab moves *between* controls; arrow keys move only *within* a widget — tabs (ARIA `tablist` + roving tabindex + Arrow/Home/End), the calendar grid (Left/Right a day, Up/Down a week, Home/End), the custom dropdown menus (`setupMenuKeys`), and combobox lists; native `<select>`s get arrows for free. New controls must be focusable with a visible `:focus-visible` ring, have an accessible name (visible text / `title` / `aria-label`), and expose state (`aria-expanded` / `aria-selected`). Custom toggles use `role="button"` + Enter/Space. Flash toasts live in an `aria-live` region.

---

## 7. Security / Owner auth

Single-owner app, one shared password **hashed** in `app_settings.owner_password_hash` (werkzeug). The `_require_login` guard forces `/setup` until a password exists, then `/login` on every page; exempt endpoints (login/setup/logout/static) are in `_AUTH_EXEMPT`. Sessions are long-lived (`SESSION_DAYS`, ~30 days). The Flask `secret_key` is generated once into a **gitignored `.flask_secret`** file, never hard-coded. **CSRF is deliberately deferred** (a known gap). Helpers: `services.owner_password_is_set / set_owner_password / check_owner_password`; routes in `views_auth.py`.

---

## 8. Data safety / backups

- Both launchers take a **full consistent snapshot** (SQLite online-backup API) into `backups/` on start, and **every few hours** while running (`BACKUP_INTERVAL_HOURS`, default 8 → ~3×/day, via a daemon thread).
- Optionally **mirrored** into a user-chosen cloud-synced folder (TZ Controls → Backup).
- Backups older than `BACKUP_MAX_AGE_DAYS` (default **10**) are auto-deleted from **both** folders (only `timezone_*.db` files).
- **WAL mode** is enabled (`PRAGMA journal_mode=WAL`).
- The UI supports **download** and a **guarded restore** (validates SQLite header + `integrity_check` + presence of core tables, takes a safety-backup first, overwrites via the backup API — Windows-safe, not a file swap).
- ⚠️ **The live SQLite file must stay on local disk** — running it from a cloud-sync folder corrupts it. The cloud folder is for *backups only*.

---

## 9. Testing

**Custom functional scripts — NOT pytest.** `tests/smoke_test.py` is the runner.

```bash
python tests/smoke_test.py                 # all groups (email skipped)
python tests/smoke_test.py tasks invoices  # only the named groups
python tests/smoke_test.py --list          # list group names
python tests/smoke_test.py --email         # include the opt-in email group
python tests/test_tasks.py                 # run one group standalone
```

- The harness (`tests/harness.py`) **snapshots the real `timezone.db` into a throwaway temp copy** (`TIMEZONE_DB` + online-backup API) so real data is never touched, points a Flask test client at the copy, **seeds an owner password + authenticates** (so the login guard passes), and sets **`TIMEZONE_BACKUP_DIR`** to a temp dir (so tests never touch the real `backups/`).
- Each `tests/test_<area>.py` exposes `run(h)` + a `standalone()` `__main__`; `h.check(name, cond)` tallies. Groups: pages, ui, auth, tasks, charges, timesheet, entry_defaults, report, expenses, subscriptions, invoices, multiclient, backup, email, autoreload.
- `test_autoreload.py` launches `serve.py` (port 5099, throwaway DB) and verifies hupper restarts on a file change (Windows-only; timing-sensitive — re-run once before treating a flake as real).
- `test_ui.py` guards rendered HTML/CSS + accessibility contracts. **Current state: 221 checks, all green.** Exit 0 = pass, 1 = fail.
- For true visual/animation checks, use the **browser preview** (port 5057, throwaway DB) — a pure-Python test can't render pixels.

---

## 10. Git & conventions

- **Private** GitHub repo, single-owner workflow. Main branch: `main`.
- **`.gitignore` excludes** `timezone.db` (+`-wal`/`-shm`), `backups/`, `attachments/`, `.flask_secret`, `.claude/`, `__pycache__/`. **Never commit the database, backups, or attachments** — they hold real client data and the SMTP password (plaintext in `app_settings`).
- **Standing rule:** auto-commit + push to `main` after any completed code/rules change — but always run the sensitive-file safety sweep first, and keep tests green.
- View modules intentionally use wildcard imports — match that style.
- **Tab order:** tabs are alphabetical — *except* **Maintain Tasks** (Tasks first, then Sub Tasks; the first tab is the default landing tab).
- **Table layout:** all cell data middle-aligned; per-row action buttons centred, equal size (32×32), equal spacing, coloured by the active icon pack.
- **Cleanup:** clean up dead code / stale comments / tests *with every change*, plus periodic standalone cruft sweeps; update/extend tests whenever behaviour changes.
- `CLAUDE.md` is the living source of truth for all conventions — keep it updated when durable rules emerge.

---

## 11. Known gaps & decisions

**Implemented (audit priorities 1–3):** Security (auth + generated secret key), Data safety (backups / restore / WAL / cloud mirror / 10-day prune), Accessibility (keyboard / ARIA / focus rings).

**Still open / deliberately deferred:**

- **CSRF protection** — not implemented (the remaining security item).
- **SMTP password** stored plaintext in `app_settings` (and therefore in backups) — documented, not encrypted.
- **No foreign keys / cascade** — `PRAGMA foreign_keys=ON` is a no-op since no table declares `REFERENCES`; `timesheet_entries.task_id` is a free string → possible orphans on task delete.
- **No CSV/JSON export-import**, no global search, mobile tables overflow, hard-deletes without undo (except clients), no branded 404/500 pages.
- **Payment tracking: explicitly declined** — the binary `generated → paid` invoice flow is kept on purpose (no partial payments / history / due-dates / INR-received tracking).
- Other optional ideas: timer/quick-entry, live FX rate, recurring invoices, richer reports/dashboards, email send-log, timezone-aware dates.

---

## 12. Gotchas

- **The live app sends real email** — `mailer._transport_send` is the seam tests monkeypatch. The live DB may have real recipients; verify only via the test harness (throwaway DB). The email test group is opt-in.
- **Don't tell the user to restart the server** for `.py`/template edits — hupper reloads automatically. Static CSS/JS just needs a browser refresh.
- A manual `python app.py` while the service runs can race the DB; WAL mitigates but don't run two writers casually.
- DB schema/migrations must stay safe to re-run (`init_db()` is idempotent).

---

## 13. File map (quick reference)

```
app.py / serve.py            launchers (import timezone.app)
Start TimeZone.bat           double-click launcher
install_autostart.py/.bat    Task Scheduler "TimeZone" setup
service_{start,stop,restart}.bat / uninstall_autostart.bat
timezone/
  __init__.py                app + wiring + guards + context + jinja globals
  config.py                  constants + DEFAULT_* seeds
  database.py                schema, migration, seeding, backups, WAL
  services.py                business logic (scope new logic here)
  pdfs.py / mailer.py        invoice PDF / SMTP
  views_*.py                 routes per area (main, timesheet, tasks, clients,
                             expenses, invoices, reports, settings, controls, auth)
  icons.py + icons_*.py      icon system + downloadable packs
templates/                   Jinja (layout.html is the shell; _logo/_tabs/_icon_trash partials)
static/style.css             the one stylesheet
static/app.js                the one script (interaction, a11y, theming)
tests/                       harness.py + smoke_test.py + test_<area>.py
CLAUDE.md                    living conventions/rules — read this first
README.md                    non-coder setup guide
```

---

**First steps for a new maintainer:** read `CLAUDE.md`, run `python tests/smoke_test.py` (expect 221/221), then browse the app in the preview (port 5057, throwaway DB) to see each feature area.
