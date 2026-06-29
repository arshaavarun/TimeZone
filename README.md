# TimeZone

A self-hosted **timesheet & invoicing** app for an independent consultant. It tracks daily hours per client, manages tasks and charge rates, records expenses, and creates GST-aware invoices you can download as PDFs or email — with a detailed hours report attached.

It runs on your own Windows PC. You use it in a web browser, on the same computer or on your phone over your home/office Wi-Fi. Your data stays on your machine.

---

## Set it up — no coding needed

You don't need to know any programming. There are three one-time steps, then you just double-click an icon whenever you want to use it.

### Step 1 — Download the app

1. On this GitHub page, click the green **`Code`** button near the top right.
2. Click **Download ZIP**.
3. Find the downloaded `TimeZone-main.zip` (usually in your Downloads folder), **right-click it → Extract All…**, and put the folder somewhere easy like your **Desktop**.

*(This is a private repo, so you have to be signed in to GitHub as the owner — or someone you've invited — to download it.)*

### Step 2 — Install Python (one time)

The app needs a free program called Python to run.

1. Go to **https://www.python.org/downloads/** and click the big **Download Python** button.
2. Open the installer. **On the very first screen, tick the box at the bottom that says "Add Python to PATH"** — this is the most important step. Then click **Install Now**.
3. When it finishes, close the installer.

> If you skip the "Add Python to PATH" tick, the app will say *"Python was not found"* later. Just re-run the Python installer, tick that box, and you're set.

### Step 3 — Start it

1. Open the `TimeZone` folder you extracted.
2. Double-click **`Start TimeZone.bat`**.
3. A black window opens. The **first time only**, it spends a minute installing what it needs. When it's ready it shows:
   `Open this address in your web browser:  http://127.0.0.1:5000`
4. Open your web browser (Chrome, Edge, …), type **`127.0.0.1:5000`** in the address bar, and press Enter.

That's it — TimeZone is running.

> Windows may show a blue **"Windows protected your PC"** box the first time. Click **More info → Run anyway** — this is just because the file came from the internet.

---

## Using it

- **On your phone or another device:** keep the black window open. It also prints a second address like `http://192.168.x.x:5000` — open that on any phone or laptop on the **same Wi-Fi**.
- **To stop it:** close the black window (or click it and press `Ctrl + C`). The app is only available while that window is open.
- **Next time:** just double-click **`Start TimeZone.bat`** again — it starts in a couple of seconds (no waiting after the first run).

### If something doesn't work

| What you see | What to do |
|---|---|
| "Python was not found" | Re-run the Python installer and **tick "Add Python to PATH"**, then try again. |
| The browser says "can't reach this page" | Make sure the black window is still open and finished starting. Use exactly `127.0.0.1:5000`. |
| "That port is already in use" | TimeZone is probably already running in another window — use that one, or close it and restart. |
| It feels stuck on first run | The one-time install can take a minute on slow connections. Give it a moment. |

---

## For developers

Server-rendered **Flask + SQLite** — no build step, no frontend framework. Jinja templates in `templates/`, one stylesheet (`static/style.css`), one script (`static/app.js`).

**Requirements:** Python 3.11+, plus the packages in `requirements.txt` (`flask`, `waitress`, `hupper`, `reportlab`, `openpyxl`).

```bash
python -m pip install -r requirements.txt

python app.py        # console dev server on 0.0.0.0:5000 (prints a phone URL)
pythonw serve.py     # headless waitress + hupper auto-reload, no console window
```

`serve.py` is the always-on path (installable as a Windows Task Scheduler job via `install_autostart.py`). Both launchers take a timestamped DB backup into `backups/` on start. `hupper` hot-reloads on any `.py`/template save; static CSS/JS changes just need a browser refresh (they're cache-busted). `TIMEZONE_PORT` overrides the port; `TIMEZONE_RELOAD=0` disables auto-reload.

**Tests** — custom functional scripts (not pytest). Each run snapshots the real DB into a throwaway copy, so live data is never touched.

```bash
python tests/smoke_test.py            # all groups (email group is opt-in)
python tests/smoke_test.py --list     # list group names
python tests/smoke_test.py tasks invoices   # run only named groups
```

### Multi-client & data

One SQLite file holds every client's data, scoped by `client_id`; switch clients from the top bar. Deleting a client archives it (read-only) rather than destroying data.

The repository intentionally **excludes** the live database (`timezone.db`), its `backups/`, and uploaded `attachments/` — they hold real client data and the SMTP password. A fresh `timezone.db` is created automatically on first run.
