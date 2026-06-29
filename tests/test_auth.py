"""Owner authentication: the login gate, login/logout, first-run setup, and the
service-level password helpers. Uses its own fresh test clients (the shared
harness client is pre-authenticated). Restores the harness password at the end so
later groups stay logged in."""
from tests.harness import standalone


def run(h):
    h.section("auth")
    from timezone import services
    from werkzeug.security import generate_password_hash
    app = h.app

    # ---- the guard bounces an unauthenticated visitor to /login ----
    anon = app.test_client()
    r = anon.get("/")
    h.check("unauthenticated request redirects to /login",
            r.status_code == 302 and "/login" in r.headers.get("Location", ""))

    # ---- wrong password is rejected; right password lets protected pages load ----
    bad = anon.post("/login", data={"password": "definitely-wrong"})
    h.check("wrong password does not log in",
            bad.status_code == 200 and anon.get("/").status_code == 302)
    good = anon.post("/login", data={"password": h.password})
    h.check("correct password logs in (redirect to home)",
            good.status_code == 302 and good.headers.get("Location", "").endswith("/"))
    h.check("logged-in client can load a protected page", anon.get("/").status_code == 200)

    # ---- next= only follows same-site relative paths (no open redirect) ----
    ext = app.test_client()
    re = ext.post("/login", data={"password": h.password, "next": "https://evil.example/x"})
    h.check("login ignores an off-site next= target (no open redirect)",
            re.status_code == 302 and "evil.example" not in re.headers.get("Location", ""))
    nx = app.test_client()
    rn = nx.post("/login", data={"password": h.password, "next": "/report"})
    h.check("login honours a same-site next= path",
            rn.status_code == 302 and rn.headers.get("Location", "").endswith("/report"))

    # ---- logout clears the session ----
    anon.post("/logout")
    h.check("logout clears the session (back to redirecting)",
            anon.get("/").status_code == 302)

    # ---- service-level password helpers ----
    h.check("owner_password_is_set is true once a password exists",
            services.owner_password_is_set(h.db) is True)
    h.check("check_owner_password verifies the right and rejects the wrong password",
            services.check_owner_password(h.db, h.password)
            and not services.check_owner_password(h.db, "nope"))

    # ---- first-run setup flow (clear the password, then restore it) ----
    h.db.execute("UPDATE app_settings SET owner_password_hash = NULL WHERE id = 1")
    h.db.commit()
    h.check("with no password set, owner_password_is_set is false",
            services.owner_password_is_set(h.db) is False)
    fresh = app.test_client()
    h.check("with no password, requests redirect to /setup",
            "/setup" in fresh.get("/").headers.get("Location", ""))
    mm = fresh.post("/setup", data={"password": "abc123", "confirm": "zzz999"})
    h.check("setup rejects a mismatched confirmation",
            mm.status_code == 200 and services.owner_password_is_set(h.db) is False)
    ok = fresh.post("/setup", data={"password": "abc123", "confirm": "abc123"})
    h.check("setup sets the password and logs the user in",
            ok.status_code == 302 and services.owner_password_is_set(h.db) is True
            and fresh.get("/").status_code == 200)

    # restore the harness password so the rest of the suite stays authenticated
    h.db.execute("UPDATE app_settings SET owner_password_hash = ? WHERE id = 1",
                 (generate_password_hash(h.password),))
    h.db.commit()


if __name__ == "__main__":
    standalone(run)
