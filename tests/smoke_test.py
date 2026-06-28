"""
TimeZone test runner.

Runs the functional test scripts (``tests/test_*.py``) against a single throwaway
copy of the real ``timezone.db`` — the real data is never touched. Run the whole
suite, or just the functional groups you care about:

    python tests/smoke_test.py                 # all groups (email skipped)
    python tests/smoke_test.py tasks invoices  # only these groups
    python tests/smoke_test.py --email         # include the opt-in email group
    python tests/smoke_test.py --list          # list the group names

Each group is also a standalone script, e.g.  python tests/test_tasks.py

Exit code 0 = all passed, 1 = one or more failures, 2 = bad arguments.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.harness import Harness, report_and_exit  # noqa: E402
from tests import (  # noqa: E402
    test_pages, test_ui, test_tasks, test_charges, test_timesheet,
    test_entry_defaults, test_report, test_expenses, test_subscriptions,
    test_invoices, test_multiclient, test_email, test_autoreload,
)

# Ordered functional groups -> their run(h) functions. Order matters: feature
# groups first, then multi-client, the opt-in email group, and auto-reload last.
GROUPS = {
    "pages": test_pages.run,
    "ui": test_ui.run,
    "tasks": test_tasks.run,
    "charges": test_charges.run,
    "timesheet": test_timesheet.run,
    "entry_defaults": test_entry_defaults.run,
    "report": test_report.run,
    "expenses": test_expenses.run,
    "subscriptions": test_subscriptions.run,
    "invoices": test_invoices.run,
    "multiclient": test_multiclient.run,
    "email": test_email.run,          # opt-in (rarely changes; --email / TIMEZONE_TEST_EMAIL=1)
    "autoreload": test_autoreload.run,
}
DEFAULT_SKIP = {"email"}


def _selected_groups(argv):
    """Resolve which groups to run from argv. Returns a list, or exits on error."""
    if "--list" in argv:
        print("groups: " + ", ".join(GROUPS))
        sys.exit(0)
    named = [a for a in argv if not a.startswith("-")]
    if named:
        unknown = [g for g in named if g not in GROUPS]
        if unknown:
            print("unknown group(s): %s\nknown: %s" % (", ".join(unknown), ", ".join(GROUPS)))
            sys.exit(2)
        return named
    want_email = ("--email" in argv) or os.environ.get("TIMEZONE_TEST_EMAIL") == "1"
    skip = set() if want_email else set(DEFAULT_SKIP)
    return [g for g in GROUPS if g not in skip]


def main(argv):
    groups = _selected_groups(argv)
    h = Harness()
    print("TimeZone tests - source: %s" % h.source)
    print("  DB under test (throwaway copy): %s" % h.tmp.name)
    print("  groups: %s\n" % ", ".join(groups))
    try:
        for g in groups:
            GROUPS[g](h)
    finally:
        h.close()
    report_and_exit(h)


if __name__ == "__main__":
    main(sys.argv[1:])
