"""UI contracts: animations, alignment and interactive behaviours.

A pure-Python test can't *render* pixels (that needs a browser — use the preview
tools for true visual checks), but it CAN guard the contracts those visuals rely
on, which is what regresses in practice:

  * the CSS that drives animations (toast slide, progress-bar/​cal transitions)
    and alignment (centred client heading, right-aligned actions, grids,
    dropdown anchoring, the read-only hide rule, responsive breakpoints) is
    present in style.css;
  * the JS behaviours (theme toggle, tabbed panels, the clock dropdown, toast
    auto-dismiss, sortable tables, Ctrl+Enter submit, combobox) are present in
    app.js; and
  * the rendered HTML actually emits the elements/classes those rules target, so
    the styling/behaviour is wired up (assets linked with a cache-bust, top-bar
    structure, animated progress bars, tab/grid containers, flash toasts).

If any of these break (a deleted keyframe, a renamed class, lost centring), the
matching check fails. Keep adding cases here when you add UI.
"""
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone, PROJECT  # noqa: E402


def _read(*parts):
    with open(os.path.join(PROJECT, *parts), encoding="utf-8") as f:
        return f.read()


def _btn_box(css, selector):
    """Pull the pixel width/height out of a CSS rule block, so size checks compare
    the two buttons rather than pinning a specific value (which we keep tweaking)."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    body = m.group(1) if m else ""
    w = re.search(r"width:\s*(\d+)px", body)
    hh = re.search(r"height:\s*(\d+)px", body)
    return {"width": w.group(1) if w else None, "height": hh.group(1) if hh else None}


def run(h):
    c, db = h.client, h.db
    css = _read("static", "style.css")
    js = _read("static", "app.js")

    # ---- CSS: animations ----
    h.section("ui/animations (style.css)")
    h.check("toast slide-in keyframes defined", "@keyframes toast-in" in css)
    h.check("toast slide-out keyframes defined", "@keyframes toast-out" in css)
    h.check("toast uses the slide-in animation", "animation: toast-in" in css)
    h.check("dismissing toast uses slide-out animation", "animation: toast-out" in css)
    h.check("progress bar fill animates width", "transition: width" in css)
    h.check("calendar day cells have a transition", ".cal-cell" in css and "transition:" in css)

    # ---- CSS: alignment / layout ----
    h.section("ui/alignment (style.css)")
    h.check("top bar is a flexbox row", ".topbar {" in css and "display: flex" in css)
    # regression: the header must stay pinned on scroll — it is position:sticky and
    # nothing may override it back to relative/static (that bug hid it on scroll).
    h.check("header is sticky on scroll (not overridden)",
            "position: sticky" in css and ".topbar { position: relative" not in css
            and ".topbar{position:relative" not in css)
    h.check("client heading is centred", ".client-heading" in css
            and "left: 50%" in css and "translate(-50%" in css)
    h.check("top-bar actions pushed to the right", ".topbar-actions" in css and "margin-left: auto" in css)
    tb, cb = _btn_box(css, ".theme-btn"), _btn_box(css, ".clock-btn")
    h.check("theme toggle + clock button are the same square size",
            tb["width"] is not None and tb["width"] == tb["height"]   # square
            and tb == cb)                                             # and equal to each other
    h.check("clock dropdown is absolutely anchored to its menu",
            ".tz-menu {" in css and "position: relative" in css
            and ".tz-dropdown {" in css and "position: absolute" in css)
    h.check("closed dropdown is hidden", '.tz-dropdown[hidden]' in css)
    h.check("form fields use a responsive grid", ".form-grid" in css and "display: grid" in css)
    h.check("invoice builder uses a 2-column grid", ".invoice-layout" in css and "grid-template-columns" in css)
    h.check("read-only mode hides mutating forms",
            'body.read-only main form[method="post"' in css)
    h.check("read-only banner is centred", ".ro-banner" in css and "text-align: center" in css)
    h.check("layout is responsive (has max-width media queries)", css.count("@media (max-width:") >= 2)
    h.check("client heading has a narrow-screen fallback (flows instead of overlapping brand)",
            "@media (max-width: 900px)" in css and "position: static" in css)

    # ---- JS: interactive behaviours ----
    h.section("ui/behaviours (app.js)")
    h.check("theme toggle wired", 'getElementById("theme-toggle")' in js and 'setAttribute("data-theme"' in js)
    h.check("tabbed panels wired", ".tabset" in js and ".tab-btn" in js)
    h.check("clock dropdown open/close wired",
            'getElementById("tz-menu")' in js and 'getElementById("tz-dropdown")' in js)
    h.check("toasts auto-dismiss", '"toast-out"' in js or "toast-out" in js)
    h.check("sortable tables wired", "function sortBy" in js)
    h.check("Ctrl+Enter submits forms", "requestSubmit" in js)
    h.check("prefix combobox wired", "input.combo" in js)

    # ---- rendered markup: the elements those rules target actually exist ----
    h.section("ui/markup (rendered)")
    home = c.get("/").get_data(as_text=True)
    h.check("stylesheet linked with cache-bust", "style.css?v=" in home)
    h.check("script linked with cache-bust", "app.js?v=" in home)
    h.check("top bar present", 'class="topbar"' in home)
    h.check("theme toggle button present", 'id="theme-toggle"' in home)
    h.check("clock menu button present", 'id="tz-menu-btn"' in home)
    h.check("clock dial uses the client colour over a neutral face",
            'class="clock-icon"' in home and "var(--clock-color)" in home and "var(--logo-facefill)" in home
            and "--clock-color" in css and "hsl(var(--client-hue" in css)
    h.check("client name sits in a themed box",
            ".client-heading" in css and "background: var(--surface-2)" in css)
    # the Home client-name button is a glossy "hardware" 3D push-button: the
    # wrapper goes flat (.is-switch) and .client-switcher carries the domed gloss,
    # the accent glow (--btn-glow from the client hue) and the press state.
    h.check("Home client-name is a glossy 3D push-button (gloss + accent glow + press)",
            ".client-heading.is-switch" in css
            and ".client-switcher:active" in css
            and "--btn-glow: hsl(var(--client-hue" in css
            and "radial-gradient(120% 140% at 50% 0%" in css
            and "inset 0 1px 1px" in css
            and 'is-switch' in home)
    h.check("light-colour legibility: black edges (light only) + fixed clock interior ink",
            "--accent-edge" in css and "var(--accent-edge)" in home   # outer ring + motion-line backings
            and "--clock-ink" in css and "var(--clock-ink)" in home)  # clock hands/dots fixed dark
    h.check("dropdown has matching Switch + TZ Controls options",
            home.count("tz-controls-link") >= 2 and "Switch" in home and "TZ Controls" in home)
    h.check("inactive tab text uses the full (dark) text colour in light mode",
            "background: transparent; color: var(--text);" in css)
    controls = c.get("/controls").get_data(as_text=True)
    h.check("TZ Controls is split into tabs",
            'class="tabset"' in controls and 'data-tab="business"' in controls
            and 'data-tab="mail"' in controls and 'data-tab="backup"' in controls)
    h.check("Home client name is a switcher dropdown of active clients",
            'id="client-switcher-btn"' in home and 'id="client-switch-menu"' in home and "csm-item" in home)
    tasks_html = c.get("/tasks").get_data(as_text=True)
    h.check("non-Home pages keep a static client heading (no switcher)",
            "client-switcher-btn" not in tasks_html and "client-name" in tasks_html)
    h.check("client-switch wave ring + smooth hue recolour are defined",
            ".client-wave" in css and "@property --client-hue" in css and "body.recoloring" in css)
    h.check("logo blue, Zone wordmark + Home button follow the client accent",
            "--client-accent: hsl(var(--client-hue" in css
            and ".brand-word .wz { color: var(--client-accent);" in css
            and ".nav-home {" in css and "color: var(--client-accent)" in css
            and "var(--client-accent)" in home and "#1F6BFF" not in home)
    h.check("client switcher dropdown present", 'id="tz-dropdown"' in home)
    cur = h.db.execute("SELECT name FROM clients WHERE status='active' ORDER BY id LIMIT 1").fetchone()
    h.check("centred client heading shows current client",
            'class="client-heading' in home and (cur is None or cur["name"] in home))
    h.check("animated progress bar rendered", "bar-fill" in home)

    settings = c.get("/settings").get_data(as_text=True)
    h.check("settings uses tabbed layout", 'class="tabset"' in settings and "tab-btn" in settings)
    h.check("settings uses aligned form grid", "form-grid" in settings)

    inv = c.get("/invoices/new").get_data(as_text=True)
    h.check("invoice builder uses the 2-column layout", "invoice-layout" in inv)

    # a flashed action renders an (animated) toast on the next page
    c.post("/tasks/add", data={"task_id": "UITOAST", "description": "x", "next": "/tasks"})
    flashed = c.get("/tasks").get_data(as_text=True)
    h.check("flash message renders as a toast", "toast toast-success" in flashed)
    c.post("/tasks/delete/UITOAST")

    # ---- per-client background tint (background only; cards/top bar untouched) ----
    h.section("ui/client-tint")
    from timezone import services
    h.check("client_hue is deterministic + distinct per client, None when absent",
            services.client_hue({"id": 1}) == services.client_hue({"id": 1})
            and services.client_hue({"id": 1}) != services.client_hue({"id": 2})
            and services.client_hue(None) is None)
    h.check("page tint is a top-down gradient from --bg into one faded client colour",
            "body.tinted" in css and "linear-gradient(to bottom, var(--bg)" in css
            and "color-mix(in srgb, var(--c)" in css and "--page-tint" in css
            and "var(--client-hue)" in css and "--client-tint" in css)
    h.check("tint is page-only — cards/top bar keep their own surfaces",
            "var(--surface)" in css and "var(--topbar-bg)" in css)
    h.check("body carries the current client's tint (hue + tinted class)",
            "--client-hue:" in home and "tinted" in home)


if __name__ == "__main__":
    standalone(run)
