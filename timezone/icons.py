"""Inline SVG line-icon set, exposed to templates as the global ``ico(name, cls)``.

One consistent stroked style (``currentColor``) so every icon tints with its
button's text colour and adapts to light/dark. Geometry only lives here; the
presentation (fill/stroke/size) comes from the ``.ico`` CSS rule, so the paths
stay terse. Add an icon by dropping a new 24x24 entry in ``_ICONS``.

Icon packs Semantic / Colour tile are CSS-only treatments of these same glyphs
(see ``[data-icon-style]`` in style.css). The "downloadable" packs swap in real
SVG sets instead: Flat colour = Icons8 multicolour (``_FC_ICONS``), Solar =
bold-duotone (``_SOLAR_ICONS``), Material = Material Symbols (``_MS_ICONS``)."""
from markupsafe import Markup

from timezone.icons_flatcolor import _FC_ICONS
from timezone.icons_solar import _SOLAR_ICONS
from timezone.icons_material import _MS_ICONS

_ICONS = {
    # row actions
    "edit": '<path d="M4 20h4L19 9a2 2 0 0 0-3-3L5 17z"/><path d="M14 7l3 3"/>',
    "save": '<path d="M5.5 4.5h10L19 8v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5.5a1 1 0 0 1 .5-1z"/>'
            '<path d="M8 4.5v4.5h6V4.5"/><path d="M8 13h8v6.5H8z"/>',
    "cancel": '<path d="M7 7l10 10M17 7L7 17"/>',
    "delete": '<path d="M3.5 6.5h17"/><path d="M9 6.5V4.3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2.2"/>'
              '<path d="M18.5 6.5l-1 13a1.4 1.4 0 0 1-1.4 1.3H7.9A1.4 1.4 0 0 1 6.5 19.5l-1-13"/>'
              '<path d="M10 10.5v6M14 10.5v6"/>',
    "check": '<circle cx="12" cy="12" r="8.3"/><path d="M8.3 12l2.6 2.6L16 9"/>',
    "reactivate": '<path d="M6 9h6.6a4.6 4.6 0 1 1-4.4 6"/><path d="M8.6 6L6 9l2.6 3"/>',
    "refresh": '<path d="M18.5 5.5V9.5H14.5"/><path d="M18.4 9.5A7 7 0 1 0 19 13.2"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="9.5" rx="1.6"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "view": '<path d="M2.5 12C5 7 9 5 12 5c3 0 7 2 9.5 7-2.5 5-6.5 7-9.5 7-3 0-7-2-9.5-7z"/>'
            '<circle cx="12" cy="12" r="2.7"/>',
    "file": '<path d="M6.5 3.5H14L17.5 7v13.5h-11z"/><path d="M14 3.5V7h3.5"/><path d="M9 12h6M9 15.5h4"/>',
    "email": '<rect x="3.5" y="6" width="17" height="12" rx="1.6"/><path d="M4.5 7.5L12 13l7.5-5.5"/>',
    "print": '<path d="M7 8.5V4h10v4.5"/><rect x="4.5" y="8.5" width="15" height="7" rx="1.4"/>'
             '<path d="M7 13.5h10v5.5H7z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    # disclosure / navigation / chrome
    "chevron": '<path d="M6 9.5l6 6 6-6"/>',
    "home": '<path d="M4 11.5L12 4.5l8 7"/><path d="M6.5 10v9.5h11V10"/>',
    "clients": '<path d="M15.5 19v-1.5a4 4 0 0 0-4-4h-5a4 4 0 0 0-4 4V19"/><circle cx="9" cy="7.5" r="3.3"/>'
               '<path d="M21.5 19v-1.5a4 4 0 0 0-3-3.87"/><path d="M15.5 4.13a3.3 3.3 0 0 1 0 6.74"/>',
    "settings": '<path d="M19.4 13a7.5 7.5 0 0 0 .1-2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-1.7-1L14 3h-4'
                'l-.4 2.6a7.5 7.5 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.6a7.5 7.5 0 0 0 0 2l-2 1.6 2 3.4 2.4-1'
                'a7.5 7.5 0 0 0 1.7 1L10 21h4l.4-2.6a7.5 7.5 0 0 0 1.7-1l2.4 1 2-3.4-2-1.6z"/>'
                '<circle cx="12" cy="12" r="2.6"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7.5v4.7l3 1.8"/>',
    "moon": '<path d="M19.5 13.2A7.2 7.2 0 1 1 10.8 4.5a5.6 5.6 0 0 0 8.7 8.7z"/>',
    "sun": '<circle cx="12" cy="12" r="3.8"/><path d="M12 3.5V5.7M12 18.3v2.2M3.5 12H5.7M18.3 12h2.2'
           'M6 6l1.6 1.6M16.4 16.4l1.6 1.6M18 6l-1.6 1.6M7.6 16.4l-1.6 1.6"/>',
    # home action tiles
    "calendar": '<rect x="4" y="5.5" width="16" height="14.5" rx="1.6"/><path d="M4 10h16M8 3.5V7M16 3.5V7"/>',
    "tasks": '<rect x="3.5" y="5" width="5" height="5" rx="1"/><rect x="3.5" y="14" width="5" height="5" rx="1"/>'
             '<path d="M11 7.5h9M11 16.5h9"/><path d="M4.6 7.3l1 1 1.8-2"/>',
    "report": '<path d="M4 4v16h16"/><path d="M8 20v-7M12 20V8M16 20v-5"/>',
    "expenses": '<path d="M6 3.5h12v17l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3-2 1.3z"/><path d="M9 8h6M9 11.5h6"/>',
}


# Downloadable packs that swap in their own SVGs: (css-prefix, dict, tintable).
# Tintable sets (Solar/Material) are ``currentColor`` so they take the per-icon
# ``--ic`` meaning colour (they also get the ``ico-<name>`` class); Icons8 is
# full-colour so it doesn't. Dict values: a body string (Icons8, viewBox 48) or
# a ``(w, h, body)`` tuple (Solar/Material, their own viewBox).
_ALT_SETS = [
    ("fc", _FC_ICONS, False),
    ("solar", _SOLAR_ICONS, True),
    ("ms", _MS_ICONS, True),
]


def _alt_svg(prefix, name, cls, tintable, entry):
    if isinstance(entry, tuple):
        w, h, body = entry
    else:
        w, h, body = 48, 48, entry
    classes = [prefix + "-ico", prefix + "-" + name]
    if tintable:
        classes.append("ico-" + name)
    if cls:
        classes.append(cls)
    return ('<svg class="%s" viewBox="0 0 %d %d" aria-hidden="true">%s</svg>'
            % (" ".join(classes), w, h, body))


def ico(name, cls="", style="", alt=True):
    """Return the named icon as an inline ``<svg class="ico ico-<name> …">``
    (HTML-safe). The per-name class lets a colour pack target individual icons;
    an optional inline ``style`` keeps the picker previews isolated.

    When ``alt`` is set, each downloadable pack that has this icon emits a second
    ``<svg class="<pack>-ico …">`` right after the line glyph; the active pack
    (``data-icon-style``) shows its own variant and hides the rest (icons with no
    variant fall back to the line glyph). Picker previews of the line-based packs
    pass ``alt=False`` to stay isolated."""
    classes = " ".join(filter(None, ["ico", "ico-" + name, cls]))
    st = (' style="%s"' % style) if style else ""
    out = ('<svg class="%s"%s viewBox="0 0 24 24" aria-hidden="true">%s</svg>'
           % (classes, st, _ICONS.get(name, "")))
    if alt:
        for prefix, d, tint in _ALT_SETS:
            if name in d:
                out += _alt_svg(prefix, name, cls, tint, d[name])
    return Markup(out)


def alt_ico(pack, name, cls=""):
    """Standalone icon from one downloadable pack (used by the picker cards)."""
    for prefix, d, tint in _ALT_SETS:
        if prefix == pack and name in d:
            return Markup(_alt_svg(prefix, name, cls, tint, d[name]))
    return Markup("")
