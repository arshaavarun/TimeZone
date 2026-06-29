"""Owner authentication — first-run password setup, login, and logout.

This is a single-owner app: there is one shared password, hashed in
``app_settings`` (see ``services.owner_password_*``). The ``_require_login``
guard in ``__init__`` forces ``auth_setup`` until a password exists, then
``auth_login`` until the session is authenticated. Sessions are marked
``permanent`` so the owner stays logged in on a trusted device (the lifetime is
``config.SESSION_DAYS``).
"""
from flask import render_template, request, redirect, url_for, flash, session

from timezone import app
from timezone.database import get_db
from timezone.services import (
    owner_password_is_set, set_owner_password, check_owner_password,
)

MIN_PASSWORD_LEN = 6


def _safe_next(target):
    """Only allow same-site relative paths as a post-login redirect target, so a
    crafted ``?next=`` can't bounce the owner to an external site."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("home")


@app.route("/setup", methods=["GET", "POST"])
def auth_setup():
    """First-run screen: set the owner password. Once one exists, this just
    redirects to the login page."""
    db = get_db()
    if owner_password_is_set(db):
        return redirect(url_for("auth_login"))
    if request.method == "POST":
        pw = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(pw) < MIN_PASSWORD_LEN:
            flash("Password must be at least %d characters." % MIN_PASSWORD_LEN, "error")
        elif pw != confirm:
            flash("The two passwords don't match.", "error")
        else:
            set_owner_password(db, pw)
            session["authed"] = True
            session.permanent = True
            flash("Password set — you're all set.", "success")
            return redirect(url_for("home"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def auth_login():
    """Password login. Sends first-run users to setup; already-logged-in users
    straight through."""
    db = get_db()
    if not owner_password_is_set(db):
        return redirect(url_for("auth_setup"))
    nxt = _safe_next(request.values.get("next"))
    if session.get("authed"):
        return redirect(nxt)
    if request.method == "POST":
        if check_owner_password(db, request.form.get("password") or ""):
            session["authed"] = True
            session.permanent = True
            return redirect(nxt)
        flash("Incorrect password.", "error")
    return render_template("login.html", next=request.values.get("next"))


@app.route("/logout", methods=["POST"])
def auth_logout():
    """Clear the session and return to the login page."""
    session.pop("authed", None)
    flash("Logged out.", "success")
    return redirect(url_for("auth_login"))
