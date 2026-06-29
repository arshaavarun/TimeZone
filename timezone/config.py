"""
Configuration constants for the TimeZone app.

Pure data only — no Flask, no database. Imported by every other module.
Paths are resolved relative to the project root (the folder that contains
this ``timezone/`` package), so the database and uploads live next to
``app.py`` exactly as before.
"""
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))   # .../timezone
BASE_DIR = os.path.dirname(PACKAGE_DIR)                     # project root
# DB location can be overridden via the TIMEZONE_DB env var (used by tests so
# the real timezone.db is never touched). Defaults next to the project.
DB_PATH = os.environ.get("TIMEZONE_DB") or os.path.join(BASE_DIR, "timezone.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BACKUP_KEEP = 20  # how many startup backups to retain

# Flask session-signing key — generated once and kept in this gitignored file
# (next to the DB) instead of hard-coded in source. See _load_secret_key in
# ``timezone/__init__``. Owner-login sessions last this long ("stay logged in").
SECRET_KEY_FILE = os.path.join(BASE_DIR, ".flask_secret")
SESSION_DAYS = 30

DEFAULT_CHARGE_TYPES = [
    # (name, is_base, percent, amount_usd)
    ("Regular", 1, 100.0, 29.00),
    ("OverTime", 0, 125.0, 36.25),
    ("AfterHours", 0, 125.0, 36.25),
    ("Holiday Coverage", 0, 150.0, 43.50),
]

# Default invoice line labels per charge type (configurable on the Settings page).
DEFAULT_INVOICE_LABELS = {
    "Regular": "IBMi RPG Consulting",
    "OverTime": "RPG Consulting - OverTime Charge",
    "AfterHours": "RPG Consulting - AfterHours Charge",
    "Holiday Coverage": "RPG Consulting - Holiday Charge",
}

# Charge-method auto-rules on the day timesheet: once a working day reaches
# HOURS_PER_DAY the base "Regular" rate is dropped and entries default to the
# OverTime charge; weekends never allow the base rate and default to the weekend
# charge. Names are matched against the client's charge types (case-insensitive,
# spaces ignored), falling back to the first non-base charge if the name is absent.
OVERTIME_CHARGE = "OverTime"
WEEKEND_CHARGE = "Holiday Coverage"

ENTRY_DEFAULT_FIELDS = ["task", "sub_task"]
ENTRY_DEFAULT_LABELS = {"task": "Task", "sub_task": "Sub Task"}
# Auto-fill rules seeded on first run (maintainable on the Settings page).
# (trigger_field, trigger_value, set_sub_task, set_hours, set_description)
DEFAULT_ENTRY_DEFAULTS = [
    ("task", "Status Call", "Meeting", 1.0, "Daily call with Kari"),
    ("sub_task", "Deploy", "", 0.25, "Deploy changes done to production"),
]

DEFAULT_SUBTASKS = [
    "Development", "Testing", "Meeting", "Analysis",
    "Documentation", "Code Review", "Support", "Other",
]

TASK_STATUSES = ["Active", "Completed"]
SUBTASK_STATUSES = ["Active", "Inactive"]
# How many completed/inactive rows to show before "Show all".
ARCHIVE_LIST_LIMIT = 15
# Page-size choices for the Completed-tasks list (the dropdown next to its title);
# the first value is the default that loads.
COMPLETED_PAGE_SIZES = [15, 30, 45, 60, 90]

DESC_MAX = 500

DAY_TYPES = ["working", "holiday", "leave"]
DAY_TYPE_LABELS = {"working": "Working", "holiday": "Holiday", "leave": "Leave"}

HOURS_PER_DAY = 8
# Selectable hours in the day-entry dropdown: 0.25 .. 16.0 in 0.25 steps.
HOURS_OPTIONS = [round(0.25 * i, 2) for i in range(1, 65)]

REPORT_SHADE = "F3F6FA"  # subtle alternating date-band tint

CURRENCIES = ["INR", "USD"]
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$"}

EXPENSE_PURPOSES = ["Official", "Personal"]
# Expense categories are maintained on the Settings page; these seed the list.
DEFAULT_EXPENSE_CATEGORIES = ["Software", "Hardware", "Subscription", "Office", "Travel", "Other"]
CATEGORY_STATUSES = ["Active", "Inactive"]
# Subscription billing cycles. The end/renewal date is the purchase date plus
# one of these periods (chosen in a pop-up on the expense form).
SUBSCRIPTION_PERIODS = ["Monthly", "Yearly"]
ATTACH_DIR = os.path.join(BASE_DIR, "attachments")
WARRANTY_WARN_MONTHS = 2

# ----- Clients (multi-client support) -----
# The app is multi-client: every data table carries a client_id and all queries
# are scoped to the currently-selected client (stored in the Flask session).
# A client is never hard-deleted — "delete" archives it (status='archived'),
# after which its data stays visible but read-only.
CLIENT_STATUSES = ["active", "archived"]
# The existing single-client database migrates under this first client name.
FIRST_CLIENT_NAME = "LorenCook"
# Default per-client background-shade strength (% of the client colour mixed in at
# the bottom of the page gradient). Light mode needs more because a light colour
# over a light bg barely shifts. Overridable per client (clients.tint_light/dark).
DEFAULT_TINT_LIGHT = 54
DEFAULT_TINT_DARK = 35
# Allowed range for the shade-strength sliders on the Maintain Clients page.
TINT_MIN, TINT_MAX = 0, 80

INVOICE_STATUSES = ["generated", "paid"]
INVOICE_PREFIX = "INV"  # number format INV-YYYY-NNN

CONSULTING_LINE_LABEL = "IBMi RPG Consulting"

# ----- Invoice email -----
EMAIL_RECIPIENT_KINDS = ["to", "cc", "bcc"]   # primary / cc / bcc
# Subject/body templates support {number} {date} {client} {total} {currency}
# {period} {biz_name} placeholders.
DEFAULT_EMAIL_SUBJECT = "Invoice {number} from {biz_name}"
DEFAULT_EMAIL_BODY = (
    "Dear {client},\n\n"
    "Please find the attached invoice {number} dated {date}, for software services "
    "provided during the period {period}.\n\n"
    "NOTE: The detailed hours report for the billed period is attached alongside "
    "the invoice.\n\n"
    "Thank you,\n{biz_name}"
)
# Previous default — kept so the init migration can recognise an un-edited seeded
# body and refresh it to the current DEFAULT_EMAIL_BODY (custom bodies untouched).
LEGACY_EMAIL_BODY = (
    "Dear {client},\n\n"
    "Please find attached invoice {number} dated {date} for {currency} {total}.\n\n"
    "Thank you,\n{biz_name}"
)

MAX_UPLOAD_MB = 16
