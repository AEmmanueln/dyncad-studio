# -*- coding: utf-8 -*-
"""DynFrame CFD - SimScale-style UI theme (pure, testable).

This module holds the *look* of the CFD panels: a cohesive dark professional
palette in the spirit of a SimScale-class setup (an analysis tree, docked
sectioned panels, colour-coded boundary-condition faces), a Qt stylesheet (QSS)
built from that palette, and the boundary-condition colour legend.

It is deliberately SimScale-*style*, not a 1:1 copy of SimScale's proprietary
web UI and branding: FreeCAD is a Qt desktop app, SimScale is a web app, and the
goal is the same workflow and visual language, themed natively in Qt.

No FreeCAD / PySide imports here, so every generator (palette, stylesheet text,
legend HTML) is unit-tested in validate.py without a GUI. dynframe_commands.py
applies the QSS string and HTML to the actual Qt widgets.
"""


# ---- palette ----------------------------------------------------------------
# A dark, cohesive CFD-setup palette (hex). Tuned for legibility on the FreeCAD
# dark theme; the accent is a professional teal used for primary actions and
# section headers, the way a CFD setup app highlights the active step.
PALETTE = {
    "bg":          "#21262d",   # dialog background (panel)
    "surface":     "#2b313a",   # group/section background
    "field":       "#1b1f24",   # input background
    "text":        "#e6edf3",   # primary text
    "subtext":     "#9aa7b4",   # secondary / helper text
    "accent":      "#17a2b8",   # primary action + section header (teal)
    "accent_hi":   "#1abccf",   # accent hover
    "accent_text": "#ffffff",   # text on the accent
    "border":      "#3a424d",   # field / group borders
    "border_hi":   "#17a2b8",   # focused field border
}

# ---- boundary-condition colours ---------------------------------------------
# The same SimScale-style BC colours the 3D domain preview paints on the box
# faces, as hex, so the dialog legend and the viewport agree. Kept in sync with
# dynframe_cfd_gen.DOMAIN_FACE_COLORS (validated by a cross-check in the tests).
BC_COLORS = {
    "inlet":  "#33b24c",   # green  - air enters (+X)
    "outlet": "#d94033",   # red    - air leaves
    "sides":  "#73a6e0",   # blue   - far-field sides
    "top":    "#8cc7f2",   # light blue - far-field top
    "ground": "#9e8c6b",   # tan    - ground wall
    "body":   "#c8ccd2",   # grey   - the solid (no-slip wall)
}

# Human-readable one-liners for each patch, for the legend tooltip/subtitle.
BC_LABELS = {
    "inlet":  "Inlet - velocity in (+X)",
    "outlet": "Outlet - pressure out",
    "sides":  "Sides - far-field (slip)",
    "top":    "Top - far-field (slip)",
    "ground": "Ground - wall",
    "body":   "Body - no-slip wall",
}

# The order BCs are shown in the legend (flow direction first).
BC_ORDER = ("inlet", "outlet", "sides", "top", "ground", "body")


def rgb_hex(rgb):
    """Convert an (r, g, b) triple of 0..1 floats to '#rrggbb'."""
    def c(x):
        v = int(round(max(0.0, min(1.0, float(x))) * 255))
        return "%02x" % v
    return "#" + c(rgb[0]) + c(rgb[1]) + c(rgb[2])


def stylesheet(palette=None):
    """A Qt stylesheet (QSS) for the CFD dialogs, built from `palette`.

    Themes QDialog, labels, inputs (QLineEdit/QSpinBox/QDoubleSpinBox/QComboBox),
    QGroupBox sections, and the OK/Cancel buttons so every CFD panel reads as one
    SimScale-style setup surface. Returned as a plain string so it is testable
    without Qt; dynframe_commands calls widget.setStyleSheet(stylesheet())."""
    p = dict(PALETTE)
    if palette:
        p.update(palette)
    return (
        "QDialog, QWidget#cfdPanel { background: %(bg)s; color: %(text)s; }\n"
        "QLabel { color: %(text)s; background: transparent; }\n"
        "QLabel#cfdHeader { font-size: 15px; font-weight: 600; color: %(text)s; }\n"
        "QLabel#cfdSub { color: %(subtext)s; }\n"
        "QGroupBox {\n"
        "    background: %(surface)s; border: 1px solid %(border)s;\n"
        "    border-radius: 6px; margin-top: 14px; padding: 10px 10px 6px 10px;\n"
        "}\n"
        "QGroupBox::title {\n"
        "    subcontrol-origin: margin; left: 10px; padding: 2px 8px;\n"
        "    color: %(accent_text)s; background: %(accent)s; border-radius: 4px;\n"
        "    font-weight: 600;\n"
        "}\n"
        "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {\n"
        "    background: %(field)s; color: %(text)s;\n"
        "    border: 1px solid %(border)s; border-radius: 4px; padding: 4px 6px;\n"
        "    selection-background-color: %(accent)s;\n"
        "}\n"
        "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {\n"
        "    border: 1px solid %(border_hi)s;\n"
        "}\n"
        "QComboBox QAbstractItemView {\n"
        "    background: %(field)s; color: %(text)s;\n"
        "    selection-background-color: %(accent)s;\n"
        "}\n"
        "QPushButton {\n"
        "    background: %(surface)s; color: %(text)s;\n"
        "    border: 1px solid %(border)s; border-radius: 4px; padding: 5px 14px;\n"
        "}\n"
        "QPushButton:hover { border: 1px solid %(accent)s; }\n"
        "QPushButton:default, QDialogButtonBox QPushButton:default {\n"
        "    background: %(accent)s; color: %(accent_text)s; border: 1px solid %(accent)s;\n"
        "}\n"
        "QPushButton:default:hover { background: %(accent_hi)s; }\n"
        % p)


def header_html(title, subtitle=""):
    """A styled title + subtitle block (rich text) for the top of a CFD panel."""
    t = ("<div style='font-size:15px;font-weight:600;color:%s'>%s</div>"
         % (PALETTE["text"], _esc(title)))
    if subtitle:
        t += ("<div style='color:%s;margin-top:2px'>%s</div>"
              % (PALETTE["subtext"], _esc(subtitle)))
    return t


def bc_legend_html(order=None, colors=None, labels=None):
    """An HTML legend of the boundary-condition colours - a coloured swatch per
    patch with its name - matching the 3D domain preview, for a dialog info row."""
    order = order or BC_ORDER
    colors = colors or BC_COLORS
    labels = labels or BC_LABELS
    rows = []
    for name in order:
        sw = ("<span style='display:inline-block;width:11px;height:11px;"
              "background:%s;border:1px solid #00000040;'></span>"
              % colors.get(name, "#888888"))
        rows.append("<tr><td>%s&nbsp;</td><td style='color:%s'>%s</td></tr>"
                    % (sw, PALETTE["text"], _esc(labels.get(name, name))))
    return ("<table cellspacing='4' cellpadding='0'>%s</table>" % "".join(rows))


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
