"""Smoke: every main page renders (HTTP 200)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone  # noqa: E402


def run(h):
    h.section("pages")
    pages = [
        "/", "/tasks", "/settings", "/controls", "/clients", "/entry", "/entry?month=2025-01",
        "/report", "/expenses", "/expenses/new", "/invoices", "/invoices/new",
        "/day?date=" + h.today,
    ]
    for p in pages:
        h.check("GET %s" % p, h.get_ok(p))

    # Dynamic pages must not be cached by the browser, so returning to a page
    # (e.g. Home after logging hours) always shows fresh server-rendered data.
    # Static assets keep their own caching (they're cache-busted via asset_url).
    h.check("dynamic HTML is no-store (fresh on back-navigation)",
            "no-store" in (h.client.get("/").headers.get("Cache-Control") or ""))
    h.check("static assets are still cacheable (not no-store)",
            "no-store" not in (h.client.get("/static/style.css").headers.get("Cache-Control") or ""))


if __name__ == "__main__":
    standalone(run)
