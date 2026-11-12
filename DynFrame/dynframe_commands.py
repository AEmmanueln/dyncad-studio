# -*- coding: utf-8 -*-
"""DynFrame commands — an Inventor-style Frame Generator for FreeCAD.

Members store their skeleton (MemberStart/MemberEnd), profile, twist and
alignment, so every edit rebuilds the solid robustly. Members are oriented
with an explicit, stable frame (no arbitrary roll).
"""

import os
import FreeCAD
import FreeCADGui
import Part

import dynframe_profiles as profiles
try:
    import dynframe_cfd as cfd            # OpenFOAM case driver (pure, testable)
except Exception:                         # keep the workbench loading if absent
    cfd = None
try:
    import dynframe_cfd_gen as cfdgen     # mesh-from-CAD generators (pure)
except Exception:
    cfdgen = None
try:
    import dynframe_cfd_ui as cfdui       # SimScale-style CFD theme (pure)
except Exception:
    cfdui = None
try:
    import dynframe_cfd_tree as cfdtree    # SimScale-style simulation-tree model
except Exception:
    cfdtree = None
try:
    import dynframe_cfd_bc as cfdbc        # interactive boundary-condition model
except Exception:
    cfdbc = None
try:
    import dynframe_cfd_materials as cfdmat  # fluid/solid material library
except Exception:
    cfdmat = None
try:
    import dynframe_cfd_examples as cfdex   # curated parameterised example cases
except Exception:
    cfdex = None

from PySide import QtGui
try:
    from PySide import QtWidgets as QW
except Exception:
    QW = QtGui

_ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
TOL = 1e-6
GROUP = "Frame"

# 9-point alignment (which point of the profile sits on the skeleton line)
ALIGN_OPTIONS = ["Center",
                 "Top-Left", "Top-Center", "Top-Right",
                 "Middle-Left", "Middle-Right",
                 "Bottom-Left", "Bottom-Center", "Bottom-Right"]


# ── vector helpers (operator-based: always return NEW vectors) ──
def unit(v):
    L = v.Length
    return FreeCAD.Vector(v.x / L, v.y / L, v.z / L) if L > TOL else FreeCAD.Vector(v)


def vscale(v, k):
    return FreeCAD.Vector(v.x * k, v.y * k, v.z * k)


# ── UI helpers ───────────────────────────────────────────────────
def _icon(name):
    p = os.path.join(_ICON_DIR, name + ".svg")
    return p if os.path.exists(p) else os.path.join(_ICON_DIR, "dynframe.svg")


def _mw():
    try:
        return FreeCADGui.getMainWindow()
    except Exception:
        return None


def info(m):
    QW.QMessageBox.information(_mw(), "DynFrame", m)


def warn(m):
    QW.QMessageBox.warning(_mw(), "DynFrame", m)


def err(m):
    QW.QMessageBox.critical(_mw(), "DynFrame", m)


def get_item(title, label, items, cur=0):
    return QW.QInputDialog.getItem(_mw(), title, label, items, cur, False)


def get_double(title, label, value, lo, hi, dec=2):
    return QW.QInputDialog.getDouble(_mw(), title, label, value, lo, hi, dec)


def get_int(title, label, value, lo, hi):
    return QW.QInputDialog.getInt(_mw(), title, label, value, lo, hi, 1)


def get_text(title, label, default=""):
    try:
        return QW.QInputDialog.getText(_mw(), title, label, text=default)
    except Exception:
        return QW.QInputDialog.getText(_mw(), title, label)


def _dlg_exec(d):
    """exec a QDialog across PySide2/6; return True if accepted."""
    run = getattr(d, "exec", None) or getattr(d, "exec_", None)
    res = run()
    try:
        return int(res) == int(QW.QDialog.Accepted)
    except Exception:
        return bool(res)


def form_dialog(title, fields, stylesheet=None, header=None):
    """One modal form instead of a chain of pop-ups. `fields` is a list of
    dicts: {key, label, kind, default, options, min, max, decimals}. kind is
    one of 'text', 'float', 'int', 'combo', 'section', 'info'. Returns a
    {key: value} dict, or None if cancelled. 'section' is a profile picker
    (family + size combos). 'info' is a read-only label row.

    Optional SimScale-style theming (used by the CFD panels): `stylesheet` is a
    QSS string applied to the dialog; `header` is (title, subtitle) drawn as a
    styled banner at the top. An 'info' field may set 'html': True to render its
    default as rich text (for the BC colour legend)."""
    d = QW.QDialog(_mw())
    d.setObjectName("cfdPanel")
    d.setWindowTitle(title)
    if stylesheet:
        try:
            d.setStyleSheet(stylesheet)
        except Exception:
            pass
    outer = QW.QVBoxLayout(d)
    if header:
        try:
            htitle, hsub = (header if isinstance(header, (tuple, list))
                            else (header, ""))
            hl = QW.QLabel(str(htitle)); hl.setObjectName("cfdHeader")
            outer.addWidget(hl)
            if hsub:
                sl = QW.QLabel(str(hsub)); sl.setObjectName("cfdSub")
                sl.setWordWrap(True); outer.addWidget(sl)
        except Exception:
            pass
    form = QW.QFormLayout()
    widgets = {}
    fam_combo = {}
    for f in fields:
        k = f.get("key"); kind = f.get("kind", "text"); lab = f.get("label", k or "")
        if kind == "info":
            w = QW.QLabel(str(f.get("default", "")))
            w.setWordWrap(True)
            # QLabel auto-detects HTML (AutoText); an 'html' info row (e.g. the
            # BC colour legend) therefore renders as rich text with no extra API.
            form.addRow(w)
            continue
        if kind == "combo":
            w = QW.QComboBox()
            opts = [str(x) for x in f.get("options", [])]
            w.addItems(opts)
            dv = f.get("default")
            if dv is not None and str(dv) in opts:
                w.setCurrentIndex(opts.index(str(dv)))
            form.addRow(lab, w); widgets[k] = ("combo", w)
        elif kind == "section":
            fams = sorted(profiles.families().keys())
            fw = QW.QComboBox(); fw.addItems(fams)
            sw = QW.QComboBox()

            def _fill(idx, fw=fw, sw=sw):
                sw.clear()
                fam = fw.currentText()
                sw.addItems([nm for (nm, _b) in profiles.families().get(fam, [])])
            fw.currentIndexChanged.connect(_fill)
            _fill(0)
            form.addRow(lab + " family", fw)
            form.addRow(lab + " size", sw)
            widgets[k] = ("section", sw)
        elif kind in ("float", "int"):
            w = QW.QDoubleSpinBox() if kind == "float" else QW.QSpinBox()
            w.setMinimum(f.get("min", -1e12)); w.setMaximum(f.get("max", 1e12))
            if kind == "float":
                w.setDecimals(f.get("decimals", 3))
            w.setValue(f.get("default", 0))
            form.addRow(lab, w); widgets[k] = (kind, w)
        else:
            w = QW.QLineEdit(str(f.get("default", "")))
            form.addRow(lab, w); widgets[k] = ("text", w)
    outer.addLayout(form)
    bb = QW.QDialogButtonBox(QW.QDialogButtonBox.Ok | QW.QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept); bb.rejected.connect(d.reject)
    outer.addWidget(bb)
    if not _dlg_exec(d):
        return None
    out = {}
    for k, (kind, w) in widgets.items():
        if kind == "combo" or kind == "section":
            out[k] = w.currentText()
        elif kind in ("float", "int"):
            out[k] = w.value()
        else:
            out[k] = w.text()
    return out


def _cfd_dialog_kwargs(title, subtitle=""):
    """SimScale-style theming kwargs for a CFD form_dialog (QSS + header banner).
    Returns {} when the theme module is unavailable, so the dialog still opens."""
    if cfdui is None:
        return {}
    try:
        return {"stylesheet": cfdui.stylesheet(), "header": (title, subtitle)}
    except Exception:
        return {}


def selected_edge_dir():
    """Return (base_point, unit_direction) of the first straight edge in the
    selection, or (None, None)."""
    for so in FreeCADGui.Selection.getSelectionEx():
        for sub in getattr(so, "SubObjects", []) or []:
            if getattr(sub, "ShapeType", "") == "Edge" and len(sub.Vertexes) >= 2:
                a = FreeCAD.Vector(sub.Vertexes[0].Point)
                b = FreeCAD.Vector(sub.Vertexes[-1].Point)
                if (b - a).Length > TOL:
                    return a, unit(b - a)
    return None, None


def save_name(title, filt):
    r = QW.QFileDialog.getSaveFileName(_mw(), title, "", filt)
    return r[0] if isinstance(r, (tuple, list)) else r


def choose_dir(title):
    return QW.QFileDialog.getExistingDirectory(_mw(), title, "")


def _exec(dlg):
    # PySide2 uses exec_(), PySide6 uses exec(); support both.
    return dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()


# 3x3 anchor grid (row = vertical, col = horizontal), matching apply_align.
ANCHOR_GRID = [["Top-Left", "Top-Center", "Top-Right"],
               ["Middle-Left", "Center", "Middle-Right"],
               ["Bottom-Left", "Bottom-Center", "Bottom-Right"]]


def frame_dialog(title, defaults=None):
    """Single Inventor-style dialog: family + size + 9-point anchor +
    rotation + offsets. Returns a dict or None (cancelled)."""
    defaults = defaults or {}
    fams = profiles.families()
    famnames = list(fams.keys())

    dlg = QW.QDialog(_mw())
    dlg.setWindowTitle(title)
    outer = QW.QVBoxLayout(dlg)

    # ---- Profile ----
    pg = QW.QGroupBox("Profile")
    pf = QW.QFormLayout(pg)
    fam_cb = QW.QComboBox()
    fam_cb.addItems(famnames)
    size_cb = QW.QComboBox()

    def refill():
        size_cb.clear()
        for nm, _b in fams[fam_cb.currentText()]:
            size_cb.addItem(nm)

    fam_cb.currentIndexChanged.connect(lambda *a: refill())
    pf.addRow("Family:", fam_cb)
    pf.addRow("Size:", size_cb)
    outer.addWidget(pg)

    # ---- Orientation ----
    og = QW.QGroupBox("Orientation")
    ov = QW.QVBoxLayout(og)
    ov.addWidget(QW.QLabel("Anchor point (which profile point sits on the line):"))
    grid = QW.QGridLayout()
    grid.setHorizontalSpacing(24)
    bgrp = QW.QButtonGroup(dlg)
    radios = {}
    for r in range(3):
        for c in range(3):
            rb = QW.QRadioButton(ANCHOR_GRID[r][c])
            grid.addWidget(rb, r, c)
            bgrp.addButton(rb)
            radios[ANCHOR_GRID[r][c]] = rb
    gwrap = QW.QWidget()
    gwrap.setLayout(grid)
    ov.addWidget(gwrap)

    frm = QW.QFormLayout()
    rot = QW.QDoubleSpinBox(); rot.setRange(-360.0, 360.0); rot.setSuffix("  deg")
    ox = QW.QDoubleSpinBox(); ox.setRange(-1e5, 1e5); ox.setSuffix("  mm")
    oy = QW.QDoubleSpinBox(); oy.setRange(-1e5, 1e5); oy.setSuffix("  mm")
    frm.addRow("Rotate about axis:", rot)
    frm.addRow("Offset X (horizontal):", ox)
    frm.addRow("Offset Y (vertical):", oy)
    ov.addLayout(frm)
    outer.addWidget(og)

    # ---- Buttons ----
    bb = QW.QDialogButtonBox(QW.QDialogButtonBox.Ok | QW.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    outer.addWidget(bb)

    # ---- defaults ----
    if defaults.get("family") in famnames:
        fam_cb.setCurrentText(defaults["family"])
    refill()
    if defaults.get("size"):
        i = size_cb.findText(defaults["size"])
        if i >= 0:
            size_cb.setCurrentIndex(i)
    (radios.get(defaults.get("align", "Center")) or radios["Center"]).setChecked(True)
    rot.setValue(float(defaults.get("twist", 0.0)))
    ox.setValue(float(defaults.get("offx", 0.0)))
    oy.setValue(float(defaults.get("offy", 0.0)))

    if not _exec(dlg):
        return None
    align = "Center"
    for nm, rb in radios.items():
        if rb.isChecked():
            align = nm
            break
    return {"family": fam_cb.currentText(), "size": size_cb.currentText(),
            "align": align, "twist": rot.value(), "offx": ox.value(), "offy": oy.value()}


def _prompt_fallback(defaults=None):
    """Sequential QInputDialog fallback if the rich dialog can't run."""
    defaults = defaults or {}
    fams = profiles.families()
    fam, ok = get_item("Frame Generator (1/3)", "Profile family:", list(fams.keys()))
    if not ok:
        return None
    sizes = fams[fam]
    name, ok = get_item("Frame Generator (2/3)", "Size:", [s[0] for s in sizes])
    if not ok:
        return None
    align, ok = get_item("Frame Generator (3/3)", "Alignment:", ALIGN_OPTIONS, 0)
    if not ok:
        return None
    twist, _ = get_double("Frame Generator", "Rotate about axis (deg):", 0.0, -360.0, 360.0)
    return {"family": fam, "size": name, "align": align, "twist": twist, "offx": 0.0, "offy": 0.0}


def get_frame_settings(title, defaults=None):
    """Rich dialog with automatic fallback to simple prompts."""
    try:
        return frame_dialog(title, defaults)
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: rich dialog unavailable, using "
                                   "simple prompts (%s)\n" % e)
        return _prompt_fallback(defaults)


# ── geometry helpers ─────────────────────────────────────────────
def global_shape(obj):
    """Return the object's shape in global coords with identity placement.

    IMPORTANT: FreeCAD's obj.Shape already carries obj.Placement, so we must
    strip it and bake the placement into the geometry — not multiply it in
    again (that double-places the shape and makes booleans jump)."""
    g = obj.Shape.copy()
    g.Placement = FreeCAD.Placement()
    g.transformShape(obj.Placement.toMatrix())
    return g


def apply_align(face, align, offx=0.0, offy=0.0):
    """Translate the (bbox-centred) profile so the chosen 9-point anchor sits
    at the origin (on the skeleton line), plus any extra X/Y offset."""
    if not align:
        align = "Center"
    bb = face.BoundBox
    xmap = {"Left": bb.XMin, "Center": (bb.XMin + bb.XMax) / 2.0, "Right": bb.XMax}
    ymap = {"Bottom": bb.YMin, "Middle": (bb.YMin + bb.YMax) / 2.0, "Top": bb.YMax}
    parts = align.split("-")
    if len(parts) == 2:
        yk, xk = parts[0], parts[1]
    else:
        yk, xk = "Middle", "Center"
    ax = xmap.get(xk, (bb.XMin + bb.XMax) / 2.0)
    ay = ymap.get(yk, (bb.YMin + bb.YMax) / 2.0)
    f = face.copy()
    f.translate(FreeCAD.Vector(-ax + offx, -ay + offy, 0))
    return f


def build_face(profname, align, offx=0.0, offy=0.0):
    b = profiles.builder_for(profname)
    if b is None:
        return None
    try:
        return apply_align(b(), align, offx, offy)
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: profile build failed (%s)\n" % e)
        return None


def _edge_pts(edge, out):
    try:
        if len(edge.Vertexes) >= 2:
            a = edge.Vertexes[0].Point
            b = edge.Vertexes[-1].Point
            if a.distanceToPoint(b) > TOL:
                out.append((FreeCAD.Vector(a), FreeCAD.Vector(b)))
    except Exception:
        pass


def _edges_of(shp, out):
    try:
        if shp.ShapeType == "Edge":
            _edge_pts(shp, out)
        else:
            for e in shp.Edges:
                _edge_pts(e, out)
    except Exception:
        pass


def collect_edges():
    """Return (p1, p2, source_name, edge_index) for each selected straight
    edge, so each member can remember the sketch edge it came from and be
    rebuilt if the sketch moves."""
    out = []
    for so in FreeCADGui.Selection.getSelectionEx():
        obj = so.Object
        names = list(getattr(so, "SubElementNames", []) or [])
        subs = list(getattr(so, "SubObjects", []) or [])
        if names:
            for nm, sub in zip(names, subs):
                if nm.startswith("Edge") and getattr(sub, "ShapeType", "") == "Edge" \
                        and len(sub.Vertexes) >= 2:
                    a = FreeCAD.Vector(sub.Vertexes[0].Point)
                    b = FreeCAD.Vector(sub.Vertexes[-1].Point)
                    if a.distanceToPoint(b) > TOL:
                        try:
                            idx = int(nm[4:])
                        except Exception:
                            idx = 0
                        out.append((a, b, obj.Name, idx))
        elif getattr(obj, "Shape", None) is not None:
            try:
                g = global_shape(obj)
            except Exception:
                g = obj.Shape
            for i, e in enumerate(g.Edges, start=1):
                if len(e.Vertexes) >= 2:
                    a = FreeCAD.Vector(e.Vertexes[0].Point)
                    b = FreeCAD.Vector(e.Vertexes[-1].Point)
                    if a.distanceToPoint(b) > TOL:
                        out.append((a, b, obj.Name, i))
    uniq = []
    for a, b, src, idx in out:
        if not any(s == src and ix == idx for _, _, s, ix in uniq):
            uniq.append((a, b, src, idx))
    return uniq


def group(doc):
    for o in doc.Objects:
        if o.Name == GROUP and o.TypeId == "App::DocumentObjectGroup":
            return o
    return doc.addObject("App::DocumentObjectGroup", GROUP)


def is_member(o):
    return hasattr(o, "MemberProfile")


def selected_members():
    out = []
    for s in FreeCADGui.Selection.getSelectionEx():
        o = s.Object
        if o not in out and getattr(o, "Shape", None) is not None:
            out.append(o)
    return out


def skeleton(obj):
    s = getattr(obj, "MemberStart", None)
    e = getattr(obj, "MemberEnd", None)
    if s is not None and e is not None and (FreeCAD.Vector(e) - FreeCAD.Vector(s)).Length > TOL:
        return FreeCAD.Vector(s), FreeCAD.Vector(e)
    L = float(getattr(obj, "MemberLength", 0.0) or 0.0)
    base = FreeCAD.Vector(obj.Placement.Base)
    z = unit(obj.Placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1)))
    if L <= 0:
        bb = obj.Shape.BoundBox
        L = max(bb.XLength, bb.YLength, bb.ZLength)
    return base, base + vscale(z, L)


def _set(obj, typ, name, val):
    try:
        if not hasattr(obj, name):
            obj.addProperty(typ, name, "DynFrame", name)
        setattr(obj, name, val)
    except Exception:
        pass


def orient_placement(p1, direction, twist_deg=0.0):
    z = unit(direction)
    if z.Length < TOL:
        return FreeCAD.Placement(p1, FreeCAD.Rotation())
    wz = FreeCAD.Vector(0, 0, 1)
    ref = wz if abs(z.dot(wz)) < 0.9 else FreeCAD.Vector(1, 0, 0)
    x = unit(ref.cross(z))
    if x.Length < TOL:
        x = unit(FreeCAD.Vector(0, 1, 0).cross(z))
    y = unit(z.cross(x))
    if abs(twist_deg) > 1e-9:
        tw = FreeCAD.Rotation(z, twist_deg)
        x = tw.multVec(x)
        y = tw.multVec(y)
    m = FreeCAD.Matrix(x.x, y.x, z.x, p1.x,
                       x.y, y.y, z.y, p1.y,
                       x.z, y.z, z.z, p1.z,
                       0, 0, 0, 1)
    return FreeCAD.Placement(m)


def _store(obj, profname, p1, p2, twist, align, offx, offy, L):
    _set(obj, "App::PropertyString", "MemberProfile", profname)
    _set(obj, "App::PropertyVector", "MemberStart", p1)
    _set(obj, "App::PropertyVector", "MemberEnd", p2)
    _set(obj, "App::PropertyLength", "MemberLength", L)
    _set(obj, "App::PropertyFloat", "MemberTwist", float(twist))
    _set(obj, "App::PropertyString", "MemberAlign", align)
    _set(obj, "App::PropertyFloat", "MemberOffX", float(offx))
    _set(obj, "App::PropertyFloat", "MemberOffY", float(offy))
    obj.Label = "%s (%.0f mm)" % (profname, L)


def make_member(doc, profname, p1, p2, twist, align, offx=0.0, offy=0.0):
    face = build_face(profname, align, offx, offy)
    if face is None:
        return None
    d = p2 - p1
    L = d.Length
    if L < TOL:
        return None
    try:
        solid = face.extrude(FreeCAD.Vector(0, 0, L))
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: extrude failed (%s)\n" % e)
        return None
    obj = doc.addObject("Part::Feature", "Member")
    obj.Shape = solid
    obj.Placement = orient_placement(p1, d, twist)
    _store(obj, profname, p1, p2, twist, align, offx, offy, L)
    return obj


def rebuild_member(obj, p1, p2, profname, twist, align, offx=0.0, offy=0.0):
    face = build_face(profname, align, offx, offy)
    if face is None:
        return False
    d = p2 - p1
    L = d.Length
    if L < TOL:
        return False
    try:
        solid = face.extrude(FreeCAD.Vector(0, 0, L))
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: rebuild failed (%s)\n" % e)
        return False
    obj.Shape = solid
    obj.Placement = orient_placement(p1, d, twist)
    _store(obj, profname, p1, p2, twist, align, offx, offy, L)
    return True


def member_solid_global(obj, p1, p2):
    """Build a member's solid (from its stored profile settings) along p1->p2,
    returned in global coords with identity placement."""
    face = build_face(getattr(obj, "MemberProfile", ""),
                      getattr(obj, "MemberAlign", "Center"),
                      float(getattr(obj, "MemberOffX", 0.0)),
                      float(getattr(obj, "MemberOffY", 0.0)))
    if face is None:
        return None
    d = p2 - p1
    L = d.Length
    if L < TOL:
        return None
    solid = face.extrude(FreeCAD.Vector(0, 0, L))
    solid.transformShape(orient_placement(p1, d, float(getattr(obj, "MemberTwist", 0.0))).toMatrix())
    return solid


def _prof_diag(obj):
    face = build_face(getattr(obj, "MemberProfile", ""),
                      getattr(obj, "MemberAlign", "Center"),
                      float(getattr(obj, "MemberOffX", 0.0)),
                      float(getattr(obj, "MemberOffY", 0.0)))
    if face is None:
        return 100.0
    bb = face.BoundBox
    return ((bb.XMax - bb.XMin) ** 2 + (bb.YMax - bb.YMin) ** 2) ** 0.5


def _halfspace_box(point, remove_dir, size):
    rd = unit(remove_dir)
    box = Part.makeBox(2 * size, 2 * size, 2 * size, FreeCAD.Vector(-size, -size, 0))
    box.Placement = FreeCAD.Placement(FreeCAD.Vector(point),
                                      FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), rd))
    return box


# ═══════════════════════════ COMMANDS ════════════════════════════
class InsertMembers:
    def GetResources(self):
        return {"Pixmap": _icon("member"), "MenuText": "Insert Frame Members",
                "ToolTip": "Place structural members along selected sketch lines or edges.",
                "Accel": "F, M"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        edges = collect_edges()
        if not edges:
            info("Select one or more straight edges or sketch lines first.\n\n"
                 "Tip: draw the frame centre-lines at real size (e.g. a 1000 mm "
                 "sketch rectangle), select them, then run this.")
            return
        res = get_frame_settings("DynFrame - Insert Frame Members")
        if not res:
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: insert members")
        grp = group(doc)
        n = 0
        for p1, p2, src, idx in edges:
            m = make_member(doc, res["size"], p1, p2, res["twist"], res["align"],
                            res["offx"], res["offy"])
            if m:
                _set(m, "App::PropertyString", "MemberSource", src)
                _set(m, "App::PropertyInteger", "MemberSourceIndex", idx)
                grp.addObject(m)
                n += 1
        doc.commitTransaction()
        doc.recompute()
        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        FreeCAD.Console.PrintMessage("DynFrame: created %d member(s)\n" % n)


class ChangeProfile:
    def GetResources(self):
        return {"Pixmap": _icon("changeprofile"), "MenuText": "Change Profile / Align",
                "ToolTip": "Change the profile, alignment or twist of selected members.",
                "Accel": "F, P"}

    def IsActive(self):
        return bool(selected_members())

    def Activated(self):
        members = [m for m in selected_members() if is_member(m)]
        if not members:
            info("Select one or more frame members first.")
            return
        m0 = members[0]
        prof = getattr(m0, "MemberProfile", "")
        fam = ""
        for fn, sizes in profiles.families().items():
            if any(s[0] == prof for s in sizes):
                fam = fn
                break
        res = get_frame_settings("DynFrame - Change Profile / Align", {
            "family": fam, "size": prof,
            "align": getattr(m0, "MemberAlign", "Center"),
            "twist": float(getattr(m0, "MemberTwist", 0.0)),
            "offx": float(getattr(m0, "MemberOffX", 0.0)),
            "offy": float(getattr(m0, "MemberOffY", 0.0))})
        if not res:
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: change profile")
        for m in members:
            s, e = skeleton(m)
            rebuild_member(m, s, e, res["size"], res["twist"], res["align"],
                           res["offx"], res["offy"])
        doc.commitTransaction()
        doc.recompute()


class LengthenShorten:
    def GetResources(self):
        return {"Pixmap": _icon("lengthen"), "MenuText": "Lengthen / Shorten",
                "ToolTip": "Extend (+) or shorten (-) selected members at each end.",
                "Accel": "F, L"}

    def IsActive(self):
        return bool(selected_members())

    def Activated(self):
        members = [m for m in selected_members() if is_member(m)]
        if not members:
            info("Select one or more frame members first.")
            return
        d_start, ok = get_double("Lengthen / Shorten",
                                 "Change at START end (mm, + extend / - shorten):",
                                 0.0, -1e6, 1e6)
        if not ok:
            return
        d_end, ok = get_double("Lengthen / Shorten",
                               "Change at END end (mm, + extend / - shorten):",
                               0.0, -1e6, 1e6)
        if not ok:
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: lengthen/shorten")
        done = 0
        for m in members:
            s, e = skeleton(m)
            d = unit(e - s)
            ns = s - vscale(d, d_start)
            ne = e + vscale(d, d_end)
            if rebuild_member(m, ns, ne, getattr(m, "MemberProfile", ""),
                              float(getattr(m, "MemberTwist", 0.0)),
                              getattr(m, "MemberAlign", "Center"),
                              float(getattr(m, "MemberOffX", 0.0)),
                              float(getattr(m, "MemberOffY", 0.0))):
                done += 1
        doc.commitTransaction()
        doc.recompute()
        if done == 0:
            warn("Could not resize the selected member(s) — are they DynFrame "
                 "members with a known profile?")


class TrimButt:
    def GetResources(self):
        return {"Pixmap": _icon("trim"), "MenuText": "Trim / Notch (to members)",
                "ToolTip": "Cut the FIRST selected member against the others "
                           "(butt joint / cope).", "Accel": "F, T"}

    def IsActive(self):
        return len(selected_members()) >= 2

    def Activated(self):
        members = selected_members()
        if len(members) < 2:
            info("Select the member to trim FIRST, then the member(s) it meets.")
            return
        target, tools = members[0], members[1:]
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: trim")
        try:
            res = global_shape(target)
            for t in tools:
                res = res.cut(global_shape(t))
            try:
                res = res.removeSplitter()
            except Exception:
                pass
            if res.Volume < TOL:
                doc.abortTransaction()
                warn("Trim would remove the whole member — select the member to "
                     "trim FIRST, then what it butts against.")
                return
            target.Shape = res
            target.Placement = FreeCAD.Placement()
            doc.commitTransaction()
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            err("Trim failed:\n%s" % e)


class Miter:
    def GetResources(self):
        return {"Pixmap": _icon("miter"), "MenuText": "Miter Two Members",
                "ToolTip": "Trim two members that meet at a corner on their "
                           "shared angle bisector.", "Accel": "F, I"}

    def IsActive(self):
        return len(selected_members()) == 2

    def Activated(self):
        members = selected_members()
        if len(members) != 2:
            info("Select exactly two members that meet at a corner.")
            return
        m1, m2 = members
        if not (is_member(m1) and is_member(m2)):
            info("Both selections must be DynFrame members.")
            return
        s1, e1 = skeleton(m1)
        s2, e2 = skeleton(m2)
        cand = [(s1, e1, s2, e2), (s1, e1, e2, s2), (e1, s1, s2, e2), (e1, s1, e2, s2)]
        c1, f1, c2, f2 = min(cand, key=lambda p: p[0].distanceToPoint(p[2]))
        if c1.distanceToPoint(c2) > 50.0:
            warn("Those members don't meet at a corner (ends are %.1f mm apart)."
                 % c1.distanceToPoint(c2))
            return
        C = c1
        d1 = unit(f1 - c1)
        d2 = unit(f2 - c2)
        n = d1 - d2
        if n.Length < 1e-4:
            warn("Members are collinear — nothing to miter.")
            return
        n = unit(n)

        # Extend each member past the corner so the solids overlap across the
        # bisector (otherwise an I-beam miter leaves a gap). CRUCIAL: we fuse a
        # short extension piece onto the member's CURRENT shape rather than
        # regenerating it from the skeleton — so an already-mitered other end
        # is preserved when mitering the second corner.
        ext = max(_prof_diag(m1), _prof_diag(m2)) * 1.5 + 20.0

        def extended_current(m, s, e, corner, far):
            cur = global_shape(m)                     # keep prior cuts/miters
            u = unit(e - s)                           # original member direction
            outward = unit(corner - far)              # past-corner direction
            L = s.distanceToPoint(e)
            overlap = min(_prof_diag(m) + 5.0, max(5.0, L * 0.5))
            pa = corner + vscale(outward, ext)        # past the corner
            pb = corner - vscale(outward, overlap)    # a little inside the member
            p1, p2 = (pa, pb) if (pb - pa).dot(u) > 0 else (pb, pa)
            piece = member_solid_global(m, p1, p2)
            if piece is None:
                return cur
            try:
                return cur.fuse(piece)
            except Exception:
                return cur

        g1 = extended_current(m1, s1, e1, c1, f1)
        g2 = extended_current(m2, s2, e2, c2, f2)
        S = (max(s1.distanceToPoint(e1), s2.distanceToPoint(e2)) + ext) * 2.0 + 200.0
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: miter")
        try:
            r1 = g1.cut(_halfspace_box(C, vscale(n, -1.0), S))   # keep d1 side
            r2 = g2.cut(_halfspace_box(C, n, S))                 # keep d2 side
            # merge the coplanar faces left by the fuse+cut so there are no
            # stray seam edges ("strange cuts") on the member.
            try:
                r1 = r1.removeSplitter()
                r2 = r2.removeSplitter()
            except Exception:
                pass
            if r1.Volume < TOL or r2.Volume < TOL:
                doc.abortTransaction()
                warn("Miter produced an empty result — check the two members "
                     "share a corner.")
                return
            m1.Shape, m1.Placement = r1, FreeCAD.Placement()
            m2.Shape, m2.Placement = r2, FreeCAD.Placement()
            doc.commitTransaction()
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            err("Miter failed:\n%s" % e)


class MirrorMembers:
    def GetResources(self):
        return {"Pixmap": _icon("mirror"), "MenuText": "Mirror Members",
                "ToolTip": "Mirror the selected members across a selected planar "
                           "face, or an XY/XZ/YZ plane.", "Accel": "F, R"}

    def IsActive(self):
        return bool(selected_members())

    def Activated(self):
        face = None
        members = []
        for so in FreeCADGui.Selection.getSelectionEx():
            for sub in getattr(so, "SubObjects", []) or []:
                if getattr(sub, "ShapeType", "") == "Face" and face is None:
                    face = sub
            if is_member(so.Object) and so.Object not in members:
                members.append(so.Object)
        members = [m for m in members if is_member(m)]
        if not members:
            info("Select the member(s) to mirror (and optionally a planar face "
                 "to mirror across).")
            return
        if face is not None:
            try:
                pt = face.CenterOfMass
                nrm = unit(face.normalAt(0, 0))
            except Exception:
                warn("Pick a flat face to mirror across.")
                return
        else:
            pl, ok = get_item("Mirror Members", "Mirror plane:", ["XY", "XZ", "YZ"], 0)
            if not ok:
                return
            pt = FreeCAD.Vector(0, 0, 0)
            nrm = {"XY": FreeCAD.Vector(0, 0, 1), "XZ": FreeCAD.Vector(0, 1, 0),
                   "YZ": FreeCAD.Vector(1, 0, 0)}[pl]

        def mir(P):
            return P - vscale(nrm, 2.0 * (P - pt).dot(nrm))

        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: mirror members")
        grp = group(doc)
        n = 0
        for m in members:
            s, e = skeleton(m)
            nm = make_member(doc, getattr(m, "MemberProfile", ""), mir(s), mir(e),
                             float(getattr(m, "MemberTwist", 0.0)),
                             getattr(m, "MemberAlign", "Center"),
                             float(getattr(m, "MemberOffX", 0.0)),
                             float(getattr(m, "MemberOffY", 0.0)))
            if nm:
                grp.addObject(nm)
                n += 1
        doc.commitTransaction()
        doc.recompute()
        FreeCAD.Console.PrintMessage("DynFrame: mirrored %d member(s)\n" % n)


class TrimToFace:
    def GetResources(self):
        return {"Pixmap": _icon("trimface"), "MenuText": "Trim to Face / Plane",
                "ToolTip": "Trim the selected member(s) at a selected planar face.",
                "Accel": "F, F"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        face = None
        members = []
        for so in FreeCADGui.Selection.getSelectionEx():
            for sub in getattr(so, "SubObjects", []) or []:
                if getattr(sub, "ShapeType", "") == "Face" and face is None:
                    face = sub
            if is_member(so.Object) and so.Object not in members:
                members.append(so.Object)
        if face is None or not members:
            info("Select the member(s) to trim AND one planar face to trim them to.")
            return
        try:
            pt = face.CenterOfMass
            nrm = face.normalAt(0, 0)
        except Exception:
            warn("Pick a flat (planar) face.")
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: trim to face")
        try:
            for m in members:
                s, e = skeleton(m)
                mid = vscale(s + e, 0.5)
                rd = FreeCAD.Vector(nrm) if (mid - pt).dot(nrm) < 0 else vscale(nrm, -1.0)
                S = s.distanceToPoint(e) * 4.0 + 200.0
                r = global_shape(m).cut(_halfspace_box(pt, rd, S))
                if r.Volume > TOL:
                    m.Shape, m.Placement = r, FreeCAD.Placement()
            doc.commitTransaction()
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            err("Trim to face failed:\n%s" % e)


STD_HOLES = [("Custom", 0.0),
             ("M3 clearance (3.4)", 3.4), ("M4 clearance (4.5)", 4.5),
             ("M5 clearance (5.5)", 5.5), ("M6 clearance (6.6)", 6.6),
             ("M8 clearance (9.0)", 9.0), ("M10 clearance (11.0)", 11.0),
             ("M12 clearance (13.5)", 13.5), ("M16 clearance (17.5)", 17.5),
             ("M20 clearance (22.0)", 22.0),
             ("M3 tapping (2.5)", 2.5), ("M4 tapping (3.3)", 3.3),
             ("M5 tapping (4.2)", 4.2), ("M6 tapping (5.0)", 5.0),
             ("M8 tapping (6.8)", 6.8), ("M10 tapping (8.5)", 8.5),
             ("M12 tapping (10.2)", 10.2)]


def hole_dialog():
    dlg = QW.QDialog(_mw())
    dlg.setWindowTitle("DynFrame - Hole")
    lay = QW.QFormLayout(dlg)
    typ = QW.QComboBox(); typ.addItems(["Simple / Clearance", "Counterbore", "Countersink", "Tapped"])
    size = QW.QComboBox(); size.addItems([s[0] for s in STD_HOLES]); size.setCurrentIndex(4)
    dia = QW.QDoubleSpinBox(); dia.setRange(0.1, 1000.0); dia.setValue(6.6); dia.setSuffix("  mm")
    through = QW.QCheckBox("Through all"); through.setChecked(True)
    depth = QW.QDoubleSpinBox(); depth.setRange(0.1, 1e5); depth.setValue(20.0); depth.setSuffix("  mm")
    cb_d = QW.QDoubleSpinBox(); cb_d.setRange(0.1, 1000.0); cb_d.setValue(11.0); cb_d.setSuffix("  mm")
    cb_dep = QW.QDoubleSpinBox(); cb_dep.setRange(0.1, 1000.0); cb_dep.setValue(6.6); cb_dep.setSuffix("  mm")
    cs_d = QW.QDoubleSpinBox(); cs_d.setRange(0.1, 1000.0); cs_d.setValue(12.0); cs_d.setSuffix("  mm")
    cs_ang = QW.QDoubleSpinBox(); cs_ang.setRange(1.0, 179.0); cs_ang.setValue(90.0); cs_ang.setSuffix("  deg")

    def on_size():
        v = dict(STD_HOLES).get(size.currentText(), 0.0)
        if v > 0:
            dia.setValue(v)
    size.currentIndexChanged.connect(lambda *a: on_size())
    on_size()

    lay.addRow("Type:", typ)
    lay.addRow("Standard size:", size)
    lay.addRow("Hole diameter:", dia)
    lay.addRow(through)
    lay.addRow("Blind depth:", depth)
    lay.addRow("Counterbore diameter:", cb_d)
    lay.addRow("Counterbore depth:", cb_dep)
    lay.addRow("Countersink diameter:", cs_d)
    lay.addRow("Countersink angle:", cs_ang)
    bb = QW.QDialogButtonBox(QW.QDialogButtonBox.Ok | QW.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addRow(bb)
    if not _exec(dlg):
        return None
    return {"type": typ.currentText(), "dia": dia.value(), "through": through.isChecked(),
            "depth": depth.value(), "cb_d": cb_d.value(), "cb_dep": cb_dep.value(),
            "cs_d": cs_d.value(), "cs_ang": cs_ang.value()}


def _hole_fallback():
    dia, ok = get_double("Hole", "Hole diameter (mm):", 6.6, 0.1, 1000.0)
    if not ok:
        return None
    thru, ok = get_item("Hole", "Termination:", ["Through all", "Blind"], 0)
    if not ok:
        return None
    depth = 20.0
    if thru == "Blind":
        depth, ok = get_double("Hole", "Blind depth (mm):", 20.0, 0.1, 1e5)
        if not ok:
            return None
    return {"type": "Simple / Clearance", "dia": dia, "through": thru == "Through all",
            "depth": depth, "cb_d": dia * 1.8, "cb_dep": dia, "cs_d": dia * 1.8, "cs_ang": 90.0}


def get_hole_settings():
    try:
        return hole_dialog()
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: hole dialog unavailable (%s)\n" % e)
        return _hole_fallback()


class HoleFeature:
    def GetResources(self):
        return {"Pixmap": _icon("hole"), "MenuText": "Hole",
                "ToolTip": "Cut a hole (simple / counterbore / countersink / tapped) "
                           "into a solid at a selected face or vertices.",
                "Accel": "M, H"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import math
        face = None
        owner = None
        pts = []
        for so in FreeCADGui.Selection.getSelectionEx():
            for sub in getattr(so, "SubObjects", []) or []:
                st = getattr(sub, "ShapeType", "")
                if st == "Face" and face is None:
                    face = sub
                    owner = so.Object
                elif st == "Vertex":
                    pts.append(FreeCAD.Vector(sub.Point))
        if face is None or owner is None:
            info("Select a flat face to drill into (optionally also select "
                 "vertices / sketch points for the hole centres).")
            return
        try:
            nrm = unit(face.normalAt(0, 0))
            fpt = face.CenterOfMass
        except Exception:
            warn("Pick a flat (planar) face.")
            return
        if not pts:
            pts = [fpt]
        # project chosen points onto the face plane
        centres = [c - vscale(nrm, (c - fpt).dot(nrm)) for c in pts]

        res = get_hole_settings()
        if not res:
            return
        into = vscale(nrm, -1.0)
        try:
            base = global_shape(owner)
        except Exception:
            base = owner.Shape
        bb = base.BoundBox
        big = (bb.XLength + bb.YLength + bb.ZLength) + 100.0

        tools = []
        for c in centres:
            start = c + vscale(nrm, 0.5)       # start just above the face
            h = (big if res["through"] else res["depth"] + 0.5) + 0.5
            try:
                tools.append(Part.makeCylinder(res["dia"] / 2.0, h, start, into))
                if res["type"] == "Counterbore":
                    tools.append(Part.makeCylinder(res["cb_d"] / 2.0, res["cb_dep"] + 0.5, start, into))
                elif res["type"] == "Countersink":
                    half = math.radians(res["cs_ang"] / 2.0)
                    cdep = ((res["cs_d"] - res["dia"]) / 2.0) / math.tan(half) if half > 1e-6 else res["cs_d"]
                    tools.append(Part.makeCone(res["cs_d"] / 2.0, res["dia"] / 2.0, cdep + 0.5, start, into))
            except Exception as e:
                FreeCAD.Console.PrintError("DynFrame: hole tool build failed (%s)\n" % e)
        if not tools:
            warn("Could not build the hole geometry.")
            return
        tool = tools[0]
        for t in tools[1:]:
            tool = tool.fuse(t)
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: hole")
        try:
            result = base.cut(tool)
            try:
                result = result.removeSplitter()
            except Exception:
                pass
            if result.Volume < TOL:
                doc.abortTransaction()
                warn("The hole removed the whole part — check the diameter/position.")
                return
            try:
                owner.Shape = result
                owner.Placement = FreeCAD.Placement()
            except Exception:
                o = doc.addObject("Part::Feature", owner.Label + "_Hole")
                o.Shape = result
                try:
                    owner.ViewObject.Visibility = False
                except Exception:
                    pass
            doc.commitTransaction()
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            err("Hole failed:\n%s" % e)


class ExtendToFace:
    def GetResources(self):
        return {"Pixmap": _icon("extend"), "MenuText": "Lengthen / Shorten to Face",
                "ToolTip": "Extend or trim the selected member(s) along their axis "
                           "so the nearest end lands on a selected planar face.",
                "Accel": "F, E"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        face = None
        members = []
        for so in FreeCADGui.Selection.getSelectionEx():
            for sub in getattr(so, "SubObjects", []) or []:
                if getattr(sub, "ShapeType", "") == "Face" and face is None:
                    face = sub
            if is_member(so.Object) and so.Object not in members:
                members.append(so.Object)
        if face is None or not members:
            info("Select the member(s) to resize AND one planar face to reach "
                 "(click a flat face of another body/member).")
            return
        try:
            pt = face.CenterOfMass
            nrm = unit(face.normalAt(0, 0))
        except Exception:
            warn("Pick a flat (planar) face.")
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: to face")
        done = 0
        for m in members:
            if not is_member(m):
                continue
            s, e = skeleton(m)
            axis = unit(e - s)
            denom = axis.dot(nrm)
            if abs(denom) < 1e-6:
                continue  # member runs parallel to the face — can't reach it
            t = (pt - s).dot(nrm) / denom
            isect = s + vscale(axis, t)
            if s.distanceToPoint(isect) <= e.distanceToPoint(isect):
                np1, np2 = isect, e            # move the start end to the face
            else:
                np1, np2 = s, isect            # move the end to the face
            if rebuild_member(m, np1, np2, getattr(m, "MemberProfile", ""),
                              float(getattr(m, "MemberTwist", 0.0)),
                              getattr(m, "MemberAlign", "Center"),
                              float(getattr(m, "MemberOffX", 0.0)),
                              float(getattr(m, "MemberOffY", 0.0))):
                done += 1
        doc.commitTransaction()
        doc.recompute()
        if done == 0:
            warn("No member reached the face (they may be parallel to it).")


class CutList:
    def GetResources(self):
        return {"Pixmap": _icon("cutlist"), "MenuText": "Generate Cut List",
                "ToolTip": "Spreadsheet + CSV of every member (profile, length).",
                "Accel": "F, C"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        members = [o for o in doc.Objects if is_member(o)]
        if not members:
            info("No frame members found yet.")
            return
        rows, summ = [], {}
        for m in members:
            prof = getattr(m, "MemberProfile", "?")
            s, e = skeleton(m)
            length = s.distanceToPoint(e)
            rows.append((m.Label, prof, length))
            agg = summ.setdefault(prof, [0, 0.0])
            agg[0] += 1
            agg[1] += length
        try:
            sheet = doc.getObject("CutList") or doc.addObject("Spreadsheet::Sheet", "CutList")
            sheet.clearAll()
            sheet.set("A1", "DynFrame Cut List")
            sheet.set("A3", "Label"); sheet.set("B3", "Profile"); sheet.set("C3", "Length (mm)")
            r = 4
            for label, prof, length in rows:
                sheet.set("A%d" % r, str(label)); sheet.set("B%d" % r, str(prof))
                sheet.set("C%d" % r, "%.1f" % length); r += 1
            r += 1
            sheet.set("A%d" % r, "SUMMARY"); sheet.set("B%d" % r, "Qty"); sheet.set("C%d" % r, "Total (mm)"); r += 1
            for prof, (qty, total) in sorted(summ.items()):
                sheet.set("A%d" % r, str(prof)); sheet.set("B%d" % r, str(qty))
                sheet.set("C%d" % r, "%.1f" % total); r += 1
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: spreadsheet failed (%s)\n" % e)
        fn = save_name("Export cut list CSV", "CSV files (*.csv)")
        if fn:
            if not fn.lower().endswith(".csv"):
                fn += ".csv"
            try:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("Label,Profile,Length_mm\n")
                    for label, prof, length in rows:
                        f.write('"%s","%s",%.1f\n' % (label, prof, length))
                    f.write("\nProfile,Qty,Total_mm\n")
                    for prof, (qty, total) in sorted(summ.items()):
                        f.write('"%s",%d,%.1f\n' % (prof, qty, total))
                info("Cut list written to:\n%s" % fn)
            except Exception as e:
                err("CSV failed:\n%s" % e)
        else:
            info("Spreadsheet 'CutList' added to the document.")


class QuickFillet:
    def GetResources(self):
        return {"Pixmap": _icon("fillet"), "MenuText": "Quick Fillet (edges)",
                "ToolTip": "Fillet the selected solid edges by a radius.", "Accel": "M, F"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        base, idxs = None, []
        for so in FreeCADGui.Selection.getSelectionEx():
            for name in getattr(so, "SubElementNames", []) or []:
                if name.startswith("Edge"):
                    base = so.Object
                    try:
                        idxs.append(int(name[4:]))
                    except Exception:
                        pass
        if base is None or not idxs:
            info("Select one or more edges of a single solid, then run Quick Fillet.")
            return
        r, ok = get_double("Quick Fillet", "Radius (mm):", 2.0, 0.01, 1e6)
        if not ok:
            return
        try:
            edges = [base.Shape.Edges[i - 1] for i in idxs]
            res = base.Shape.makeFillet(r, edges)
        except Exception as e:
            err("Fillet failed (those edges may be unfilletable):\n%s" % e)
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: fillet")
        o = doc.addObject("Part::Feature", base.Label + "_Fillet")
        o.Shape = res
        o.Placement = base.Placement
        try:
            base.ViewObject.Visibility = False
        except Exception:
            pass
        doc.commitTransaction()
        doc.recompute()


class ExportStep:
    def GetResources(self):
        return {"Pixmap": _icon("export"), "MenuText": "Export to STEP",
                "ToolTip": "Export selected objects (or all) to one STEP file.", "Accel": "E, S"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        objs = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if getattr(s.Object, "Shape", None)]
        if not objs:
            objs = [o for o in doc.Objects if getattr(o, "Shape", None) is not None
                    and o.TypeId != "App::DocumentObjectGroup"]
        if not objs:
            info("Nothing with geometry to export.")
            return
        fn = save_name("Export STEP", "STEP files (*.step *.stp)")
        if not fn:
            return
        if not fn.lower().endswith((".step", ".stp")):
            fn += ".step"
        try:
            Part.export(objs, fn)
            info("Exported %d object(s) to:\n%s" % (len(objs), fn))
        except Exception as e:
            err("STEP export failed:\n%s" % e)


class ExportStl:
    def GetResources(self):
        return {"Pixmap": _icon("exportstl"), "MenuText": "Export each body to STL",
                "ToolTip": "Export selected objects (or all) to individual STL files.",
                "Accel": "E, L"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        objs = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if getattr(s.Object, "Shape", None)]
        if not objs:
            objs = [o for o in doc.Objects if getattr(o, "Shape", None) is not None
                    and o.TypeId != "App::DocumentObjectGroup"]
        if not objs:
            info("Nothing with geometry to export.")
            return
        folder = choose_dir("Choose a folder for the STL files")
        if not folder:
            return
        n = 0
        for o in objs:
            try:
                safe = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in o.Label)
                global_shape(o).exportStl(os.path.join(folder, safe + ".stl"))
                n += 1
            except Exception as e:
                FreeCAD.Console.PrintError("DynFrame: STL of %s failed (%s)\n" % (o.Label, e))
        info("Exported %d STL file(s) to:\n%s" % (n, folder))


class Skeleton3D:
    def GetResources(self):
        return {"Pixmap": _icon("sketch3d"), "MenuText": "3D Skeleton (Draft)",
                "ToolTip": "Switch to Draft to draw a 3D centre-line skeleton "
                           "(Polyline), then insert members along it.", "Accel": "F, 3"}

    def IsActive(self):
        return True

    def Activated(self):
        if FreeCAD.ActiveDocument is None:
            FreeCAD.newDocument()
        # Reliable path: type the 3D points and build a wire skeleton.
        default = "0 0 0\n1000 0 0\n1000 1000 0\n0 1000 0\n0 0 0\n0 0 1000"
        text, ok = None, False
        try:
            text, ok = QW.QInputDialog.getMultiLineText(
                _mw(), "3D Skeleton",
                "Enter skeleton points, one 'X Y Z' per line (mm).\n"
                "Each consecutive pair becomes a member edge.\n"
                "Leave blank and press OK to draw interactively with Draft instead:",
                default)
        except Exception:
            ok = False
        if ok and text and text.strip():
            pts = []
            for line in text.splitlines():
                p = line.replace(",", " ").split()
                if len(p) >= 3:
                    try:
                        pts.append(FreeCAD.Vector(float(p[0]), float(p[1]), float(p[2])))
                    except Exception:
                        pass
            if len(pts) < 2:
                warn("Need at least two valid points.")
                return
            doc = FreeCAD.ActiveDocument
            doc.openTransaction("DynFrame: 3D skeleton")
            o = doc.addObject("Part::Feature", "Skeleton3D")
            o.Shape = Part.makePolygon(pts)
            doc.commitTransaction()
            doc.recompute()
            try:
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(o)
                FreeCADGui.activeDocument().activeView().viewAxonometric()
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
            info("3D skeleton created and selected. Run 'Insert Frame Members' "
                 "to build members along it.")
            return
        # Interactive fallback: Draft Polyline.
        try:
            FreeCADGui.activateWorkbench("DraftWorkbench")
            for cmd in ("Draft_Wire", "Draft_Polyline", "Draft_Line"):
                try:
                    FreeCADGui.runCommand(cmd, 0)
                    break
                except Exception:
                    continue
        except Exception as e:
            err("Could not open the Draft workbench:\n%s" % e)
            return
        info("Draft workbench opened. Use the Polyline tool to draw a 3D "
             "skeleton (type X/Y/Z for each point, Esc to finish), then switch "
             "back to DynFrame, select it, and Insert Frame Members.")


class InventorNav:
    def GetResources(self):
        return {"Pixmap": _icon("nav"), "MenuText": "Navigation: SolidWorks / Inventor",
                "ToolTip": "Set the 3D mouse navigation preset."}

    def IsActive(self):
        return True

    def Activated(self):
        style, ok = get_item("Navigation style", "Mouse navigation preset:",
                             ["SolidWorks", "Inventor (OpenInventor)", "CAD", "Revit",
                              "Blender", "Touchpad"])
        if not ok:
            return
        mapping = {"SolidWorks": "Gui::SolidWorksNavigationStyle",
                   "Inventor (OpenInventor)": "Gui::InventorNavigationStyle",
                   "CAD": "Gui::CADNavigationStyle", "Revit": "Gui::RevitNavigationStyle",
                   "Blender": "Gui::BlenderNavigationStyle", "Touchpad": "Gui::TouchpadNavigationStyle"}
        try:
            FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").SetString(
                "NavigationStyle", mapping[style])
            info("Navigation set to %s.\nIf a 3D view is already open, close and "
                 "reopen it (or restart FreeCAD)." % style)
        except Exception as e:
            err("Could not set navigation style:\n%s" % e)


def _dup_member(doc, grp, m, xf):
    s, e = skeleton(m)
    nm = make_member(doc, getattr(m, "MemberProfile", ""), xf(s), xf(e),
                     float(getattr(m, "MemberTwist", 0.0)),
                     getattr(m, "MemberAlign", "Center"),
                     float(getattr(m, "MemberOffX", 0.0)),
                     float(getattr(m, "MemberOffY", 0.0)))
    if nm and grp:
        grp.addObject(nm)
    return nm


def _dup_generic(doc, o, xf_shape):
    try:
        sh = global_shape(o)
    except Exception:
        sh = o.Shape.copy()
    xf_shape(sh)
    no = doc.addObject("Part::Feature", o.Label + "_copy")
    no.Shape = sh
    return no


class RectPattern:
    def GetResources(self):
        return {"Pixmap": _icon("rectpattern"), "MenuText": "Rectangular Pattern",
                "ToolTip": "Copy the selected members/solids along a direction "
                           "(X/Y/Z, or a selected straight edge).", "Accel": "F, X"}

    def IsActive(self):
        return bool(selected_members())

    def Activated(self):
        items = [o for o in selected_members() if getattr(o, "Shape", None) is not None]
        if not items:
            info("Select member(s) or solid(s) to pattern.")
            return
        _, adir = selected_edge_dir()
        if adir is None:
            ax, ok = get_item("Rectangular Pattern", "Direction:", ["X", "Y", "Z"], 0)
            if not ok:
                return
            adir = {"X": FreeCAD.Vector(1, 0, 0), "Y": FreeCAD.Vector(0, 1, 0),
                    "Z": FreeCAD.Vector(0, 0, 1)}[ax]
        count, ok = get_int("Rectangular Pattern", "Total count (incl. original):", 3, 2, 2000)
        if not ok:
            return
        spacing, ok = get_double("Rectangular Pattern", "Spacing (mm):", 100.0, -1e6, 1e6)
        if not ok:
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: rectangular pattern")
        grp = group(doc)
        n = 0
        for o in items:
            mem = is_member(o)
            for k in range(1, count):
                off = vscale(adir, k * spacing)
                if mem:
                    if _dup_member(doc, grp, o, lambda P, off=off: P + off):
                        n += 1
                else:
                    _dup_generic(doc, o, lambda sh, off=off: sh.translate(off))
                    n += 1
        doc.commitTransaction()
        doc.recompute()
        FreeCAD.Console.PrintMessage("DynFrame: created %d copies\n" % n)


class CircPattern:
    def GetResources(self):
        return {"Pixmap": _icon("circpattern"), "MenuText": "Circular Pattern",
                "ToolTip": "Copy the selected members/solids around an axis "
                           "(Z/X/Y, or a selected straight edge as the axis).",
                "Accel": "F, O"}

    def IsActive(self):
        return bool(selected_members())

    def Activated(self):
        items = [o for o in selected_members() if getattr(o, "Shape", None) is not None]
        if not items:
            info("Select member(s) or solid(s) to pattern.")
            return
        apt, adir = selected_edge_dir()
        if adir is None:
            ax, ok = get_item("Circular Pattern", "Axis:", ["Z", "X", "Y"], 0)
            if not ok:
                return
            adir = {"Z": FreeCAD.Vector(0, 0, 1), "X": FreeCAD.Vector(1, 0, 0),
                    "Y": FreeCAD.Vector(0, 1, 0)}[ax]
            apt = FreeCAD.Vector(0, 0, 0)
        count, ok = get_int("Circular Pattern", "Total count (incl. original):", 4, 2, 2000)
        if not ok:
            return
        total, ok = get_double("Circular Pattern", "Total angle (deg, 360 = full):", 360.0, -3600.0, 3600.0)
        if not ok:
            return
        step = total / count if abs(abs(total) - 360.0) < 1e-6 else total / (count - 1)
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: circular pattern")
        grp = group(doc)
        n = 0
        for o in items:
            mem = is_member(o)
            for k in range(1, count):
                ang = step * k

                def rot_pt(P, ang=ang):
                    return apt + FreeCAD.Rotation(adir, ang).multVec(P - apt)

                if mem:
                    if _dup_member(doc, grp, o, rot_pt):
                        n += 1
                else:
                    _dup_generic(doc, o, lambda sh, ang=ang: sh.rotate(apt, adir, ang))
                    n += 1
        doc.commitTransaction()
        doc.recompute()
        FreeCAD.Console.PrintMessage("DynFrame: created %d copies\n" % n)


class BOM:
    def GetResources(self):
        return {"Pixmap": _icon("bom"), "MenuText": "Bill of Materials",
                "ToolTip": "Parts list of every solid (grouped by type, with "
                           "quantity, volume and estimated steel mass).",
                "Accel": "F, B"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        DENS = 7.85e-6  # kg per mm^3 (structural steel)
        groups = {}
        order = []
        for o in doc.Objects:
            sh = getattr(o, "Shape", None)
            if sh is None or o.TypeId == "App::DocumentObjectGroup":
                continue
            try:
                vol = sh.Volume
            except Exception:
                vol = 0.0
            if vol <= TOL:
                continue
            try:
                vis = o.ViewObject.Visibility
            except Exception:
                vis = True
            if not vis:
                continue
            if is_member(o):
                s, e = skeleton(o)
                L = s.distanceToPoint(e)
                key = ("M", getattr(o, "MemberProfile", "?"), round(L, 1))
                desc = "%s  L=%.1f mm" % (getattr(o, "MemberProfile", "?"), L)
            else:
                bb = sh.BoundBox
                key = ("P", round(vol, 1), round(bb.XLength, 1), round(bb.YLength, 1), round(bb.ZLength, 1))
                desc = "%s  %.0f x %.0f x %.0f mm" % (o.Label.split("_")[0],
                                                      bb.XLength, bb.YLength, bb.ZLength)
            if key not in groups:
                groups[key] = {"desc": desc, "qty": 0, "vol": vol}
                order.append(key)
            groups[key]["qty"] += 1
        if not order:
            info("No solids found to list.")
            return
        rows = []
        tot_mass = 0.0
        for i, key in enumerate(order, 1):
            g = groups[key]
            mass = g["vol"] * DENS
            tot_mass += mass * g["qty"]
            rows.append((i, g["desc"], g["qty"], mass, mass * g["qty"]))
        try:
            sheet = doc.getObject("BOM") or doc.addObject("Spreadsheet::Sheet", "BOM")
            sheet.clearAll()
            sheet.set("A1", "DynFrame Bill of Materials  (steel, %.0f kg/m3)" % (DENS * 1e9))
            sheet.set("A3", "Item"); sheet.set("B3", "Description"); sheet.set("C3", "Qty")
            sheet.set("D3", "Unit mass (kg)"); sheet.set("E3", "Total mass (kg)")
            r = 4
            for item, desc, qty, um, tm in rows:
                sheet.set("A%d" % r, str(item)); sheet.set("B%d" % r, str(desc))
                sheet.set("C%d" % r, str(qty)); sheet.set("D%d" % r, "%.3f" % um)
                sheet.set("E%d" % r, "%.3f" % tm); r += 1
            sheet.set("B%d" % (r + 1), "TOTAL MASS (kg)")
            sheet.set("E%d" % (r + 1), "%.3f" % tot_mass)
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: BOM sheet failed (%s)\n" % e)
        fn = save_name("Export BOM CSV", "CSV files (*.csv)")
        if fn:
            if not fn.lower().endswith(".csv"):
                fn += ".csv"
            try:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("Item,Description,Qty,Unit_mass_kg,Total_mass_kg\n")
                    for item, desc, qty, um, tm in rows:
                        f.write('%d,"%s",%d,%.3f,%.3f\n' % (item, desc, qty, um, tm))
                    f.write(',,,TOTAL,%.3f\n' % tot_mass)
                info("BOM written to:\n%s" % fn)
            except Exception as e:
                err("CSV failed:\n%s" % e)
        else:
            info("Spreadsheet 'BOM' added (total steel mass %.1f kg)." % tot_mass)


_PLANE_AXES = {"XY": (FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 1, 0), FreeCAD.Vector(0, 0, 1)),
               "XZ": (FreeCAD.Vector(1, 0, 0), FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(0, 1, 0)),
               "YZ": (FreeCAD.Vector(0, 1, 0), FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(1, 0, 0))}


def _plane_frame(name, offset=0.0):
    """Return (origin, U, V) for a principal plane, shifted by `offset` along
    its normal — so the sketch can sit anywhere in 3D."""
    U, V, N = _PLANE_AXES[name]
    return vscale(N, offset), FreeCAD.Vector(U), FreeCAD.Vector(V)


def _face_frame(face):
    """Return (origin, U, V) for a selected planar face."""
    N = unit(face.normalAt(0, 0))
    O = face.CenterOfMass
    ref = FreeCAD.Vector(0, 0, 1) if abs(N.dot(FreeCAD.Vector(0, 0, 1))) < 0.9 else FreeCAD.Vector(1, 0, 0)
    U = unit(ref.cross(N))
    V = unit(N.cross(U))
    return FreeCAD.Vector(O), U, V


def solve_profile(pts, close, dims=None, slope=0.36):
    """Square up a rough 2D profile with the constraint solver: segments
    within ~20deg of an axis are constrained horizontal/vertical; optional
    driving dimensions `dims` = [(segment_1based, length), ...] pin exact
    segment lengths. Returns the cleaned [(u, v), ...] or None. Validated
    against python-solvespace."""
    from python_solvespace import SolverSystem, ResultFlag
    ss = SolverSystem()
    wp = ss.create_2d_base()
    P = [ss.add_point_2d(x, y, wp) for (x, y) in pts]
    ss.dragged(P[0], wp)
    n = len(P)
    nseg = n if close else n - 1
    segs = []
    for i in range(nseg):
        a, b = i, (i + 1) % n
        ln = ss.add_line_2d(P[a], P[b], wp)
        segs.append((a, b))
        dx = pts[b][0] - pts[a][0]
        dy = pts[b][1] - pts[a][1]
        if abs(dy) <= slope * abs(dx):
            ss.horizontal(ln, wp)
        elif abs(dx) <= slope * abs(dy):
            ss.vertical(ln, wp)
    for (i, length) in (dims or []):
        if 1 <= i <= nseg and float(length) > 0:
            a, b = segs[i - 1]
            ss.distance(P[a], P[b], float(length), wp)
    if ss.solve() != ResultFlag.OKAY:
        return None
    return [tuple(ss.params(p.params)) for p in P]


class ConstrainedSketch:
    def GetResources(self):
        return {"Pixmap": _icon("csketch"), "MenuText": "Constrained Sketch",
                "ToolTip": "Square up a rough profile (selected wire, or typed "
                           "points) with the constraint solver, on a chosen plane.",
                "Accel": "F, S"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        try:
            import python_solvespace  # noqa: F401
        except Exception:
            err("The constraint solver isn't installed.\n\nIn the Python Console "
                "run:\n  import sys,os,subprocess; subprocess.check_call("
                "[os.path.join(sys.prefix,'python.exe'),'-m','pip','install',"
                "'python-solvespace'])\nthen restart FreeCAD.")
            return

        # gather a rough profile (selected wire's vertices) and a face if picked
        verts3d = []
        sel_face = None
        for so in FreeCADGui.Selection.getSelectionEx():
            for sub in getattr(so, "SubObjects", []) or []:
                if getattr(sub, "ShapeType", "") == "Face" and sel_face is None:
                    sel_face = sub
            obj = so.Object
            if not verts3d and getattr(obj, "Shape", None) is not None:
                try:
                    g = global_shape(obj)
                    if g.Wires:
                        verts3d = [FreeCAD.Vector(v.Point) for v in g.Wires[0].OrderedVertexes]
                    elif g.Vertexes:
                        verts3d = [FreeCAD.Vector(v.Point) for v in g.Vertexes]
                except Exception:
                    verts3d = []

        # choose the sketch plane (anywhere in 3D)
        choices = ["XY", "XZ", "YZ", "XY + offset", "XZ + offset", "YZ + offset"]
        if sel_face is not None:
            choices = ["Selected face"] + choices
        plane, ok = get_item("Constrained Sketch", "Sketch plane:", choices, 0)
        if not ok:
            return
        if plane == "Selected face":
            O, U, V = _face_frame(sel_face)
        elif plane.endswith("offset"):
            base = plane.split()[0]
            off, ok = get_double("Constrained Sketch", "Plane offset along its normal (mm):",
                                 0.0, -1e6, 1e6)
            if not ok:
                return
            O, U, V = _plane_frame(base, off)
        else:
            O, U, V = _plane_frame(plane, 0.0)

        def touv(p):
            d = p - O
            return (d.dot(U), d.dot(V))

        def to3d(u, v):
            return (O + vscale(U, u) + vscale(V, v))

        if verts3d:
            pts = [touv(v) for v in verts3d]
            # drop a duplicate closing vertex if present
            if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                pts = pts[:-1]
        else:
            try:
                text, ok = QW.QInputDialog.getMultiLineText(
                    _mw(), "Constrained Sketch",
                    "No wire selected. Enter rough profile points, one 'U V' per "
                    "line (in the chosen plane, mm):", "0 0\n100 4\n96 60\n-3 58")
            except Exception:
                ok = False
            if not ok or not text.strip():
                return
            pts = []
            for line in text.splitlines():
                p = line.replace(",", " ").split()
                if len(p) >= 2:
                    try:
                        pts.append((float(p[0]), float(p[1])))
                    except Exception:
                        pass
        if len(pts) < 3:
            warn("Need at least three points (a selected wire or typed profile).")
            return
        cl, ok = get_item("Constrained Sketch", "Closed profile?", ["Yes", "No"], 0)
        if not ok:
            return
        close = cl == "Yes"

        # optional driving dimensions: "segment length" per line (1-based segments)
        dims = []
        try:
            dtext, dok = QW.QInputDialog.getMultiLineText(
                _mw(), "Constrained Sketch - Dimensions (optional)",
                "Pin exact segment lengths? One 'segment length' per line "
                "(segment 1 = first point to second), or leave blank:", "")
        except Exception:
            dok, dtext = False, ""
        if dok and dtext.strip():
            for line in dtext.splitlines():
                p = line.replace(",", " ").split()
                if len(p) >= 2:
                    try:
                        dims.append((int(float(p[0])), float(p[1])))
                    except Exception:
                        pass

        solved = solve_profile(pts, close, dims)
        if solved is None:
            warn("The solver could not satisfy the constraints — try a rougher "
                 "profile that is clearly near right angles.")
            return
        pts3d = [to3d(u, v) for (u, v) in solved]
        if close:
            pts3d.append(pts3d[0])
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: constrained sketch")
        o = doc.addObject("Part::Feature", "ConstrainedSketch")
        o.Shape = Part.makePolygon(pts3d)
        doc.commitTransaction()
        doc.recompute()
        try:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(o)
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Constrained sketch created (squared-up profile). Select it and run "
             "Insert Frame Members, or use it as a profile.")


# ═══════════════════════════ FRAME ANALYSIS ═══════════════════════
#  Linear-static 3D frame analysis (direct stiffness / Euler-Bernoulli
#  beam elements). Validated against the textbook cantilever.
E_STEEL = 210000.0     # N/mm^2
G_STEEL = 80769.0      # N/mm^2
FY_STEEL = 250.0       # N/mm^2 (yield, for utilisation colour)
RHO_STEEL = 7.85e-6    # kg/mm^3
GRAV = 9.81            # m/s^2


def _beam_k_local(E, G, A, Iy, Iz, J, L):
    import numpy as np
    k = np.zeros((12, 12))
    a = E * A / L
    t = G * J / L
    z1 = 12 * E * Iz / L**3; z2 = 6 * E * Iz / L**2; z3 = 4 * E * Iz / L; z4 = 2 * E * Iz / L
    y1 = 12 * E * Iy / L**3; y2 = 6 * E * Iy / L**2; y3 = 4 * E * Iy / L; y4 = 2 * E * Iy / L
    k[0, 0] = a; k[0, 6] = -a; k[6, 0] = -a; k[6, 6] = a
    k[3, 3] = t; k[3, 9] = -t; k[9, 3] = -t; k[9, 9] = t
    for i, j, v in [(1, 1, z1), (1, 5, z2), (1, 7, -z1), (1, 11, z2), (5, 5, z3),
                    (5, 7, -z2), (5, 11, z4), (7, 7, z1), (7, 11, -z2), (11, 11, z3)]:
        k[i, j] = v; k[j, i] = v
    for i, j, v in [(2, 2, y1), (2, 4, -y2), (2, 8, -y1), (2, 10, -y2), (4, 4, y3),
                    (4, 8, y2), (4, 10, y4), (8, 8, y1), (8, 10, y2), (10, 10, y3)]:
        k[i, j] = v; k[j, i] = v
    return k


def _beam_mass_local(rho, A, J, L):
    """Consistent 12x12 mass matrix (mass density rho in tonne/mm^3 for N-mm-s,
    giving frequencies in Hz). The two bending planes use the standard
    Hermitian consistent mass; the coupling sign in the local-y plane is
    flipped to match _beam_k_local. Validated: cantilever f1 matches the
    analytical (1.875^2/2pi)*sqrt(EI/rho A L^4) to 4 figures."""
    import numpy as np
    m = np.zeros((12, 12))
    mm = rho * A * L
    m[0, 0] = m[6, 6] = mm / 3.0; m[0, 6] = m[6, 0] = mm / 6.0
    ip = (J / A) if A > 1e-9 else 0.0
    m[3, 3] = m[9, 9] = mm * ip / 3.0; m[3, 9] = m[9, 3] = mm * ip / 6.0
    c = mm / 420.0

    def bend(iv, it, jv, jt, sgn):
        m[iv, iv] += 156 * c; m[jv, jv] += 156 * c
        m[iv, jv] += 54 * c; m[jv, iv] += 54 * c
        m[it, it] += 4 * L * L * c; m[jt, jt] += 4 * L * L * c
        m[it, jt] += -3 * L * L * c; m[jt, it] += -3 * L * L * c
        m[iv, it] += sgn * 22 * L * c; m[it, iv] += sgn * 22 * L * c
        m[iv, jt] += sgn * (-13 * L * c); m[jt, iv] += sgn * (-13 * L * c)
        m[jv, it] += sgn * 13 * L * c; m[it, jv] += sgn * 13 * L * c
        m[jv, jt] += sgn * (-22 * L * c); m[jt, jv] += sgn * (-22 * L * c)
    bend(1, 5, 7, 11, +1)      # local-z bending plane (uy, rz)
    bend(2, 4, 8, 10, -1)      # local-y bending plane (uz, ry) - sign flip
    return m


def _beam_kg_local(N, L):
    """Consistent 12x12 geometric stiffness matrix for a beam element carrying
    axial force N (tension +). Used for linear buckling: (K + lam Kg) phi = 0.
    The local-y plane rotation coupling is sign-flipped to match the stiffness
    convention. Validated: cantilever column Pcr = pi^2 EI/(2L)^2 (ratio 1.000)."""
    import numpy as np
    kg = np.zeros((12, 12)); g = N / L

    def bend(iv, it, jv, jt, sgn):
        kg[iv, iv] += g * 6 / 5; kg[jv, jv] += g * 6 / 5
        kg[iv, jv] += -g * 6 / 5; kg[jv, iv] += -g * 6 / 5
        kg[it, it] += g * 2 * L * L / 15; kg[jt, jt] += g * 2 * L * L / 15
        kg[it, jt] += -g * L * L / 30; kg[jt, it] += -g * L * L / 30
        kg[iv, it] += sgn * g * L / 10; kg[it, iv] += sgn * g * L / 10
        kg[iv, jt] += sgn * g * L / 10; kg[jt, iv] += sgn * g * L / 10
        kg[jv, it] += sgn * (-g * L / 10); kg[it, jv] += sgn * (-g * L / 10)
        kg[jv, jt] += sgn * (-g * L / 10); kg[jt, jv] += sgn * (-g * L / 10)
    bend(1, 5, 7, 11, +1)
    bend(2, 4, 8, 10, -1)
    return kg


def _condense(kl, fef, rel):
    """Static condensation of released local DOFs (member end releases). `rel`
    is a set of local DOF indices (0-11) released at the member ends (e.g.
    My/Mz rotations for a pinned connection). Returns (k_cond, f_cond,
    rec_info) with the released rows/cols zeroed so the released actions are
    zero; rec_info recovers the released displacements afterwards. Validated:
    fixed-fixed UDL with My released at one end -> propped cantilever (My_i =
    wL^2/8, My_j = 0)."""
    import numpy as np
    if not rel:
        return kl, fef, None
    c = sorted(rel); r = [d for d in range(12) if d not in rel]
    kcc = kl[np.ix_(c, c)]
    try:
        kcci = np.linalg.inv(kcc)
    except Exception:
        return kl, fef, None
    krr = kl[np.ix_(r, r)]; krc = kl[np.ix_(r, c)]; kcr = kl[np.ix_(c, r)]
    kstar = krr - krc @ kcci @ kcr
    fstar = fef[r] - krc @ kcci @ fef[c]
    kf = np.zeros((12, 12)); ff = np.zeros(12)
    for i, ri in enumerate(r):
        ff[ri] = fstar[i]
        for j, rj in enumerate(r):
            kf[ri, rj] = kstar[i, j]
    return kf, ff, (r, c, kcci, kcr, fef[c])


def _bar_releases(o):
    """Local DOF indices released at the ends of a bar, from its RelI/RelJ
    6-char flags ('100000'=release ux ... index 0..5). End j maps to 6+k."""
    rel = set()
    ri = getattr(o, "RelI", None) or ""
    rj = getattr(o, "RelJ", None) or ""
    for k, ch in enumerate(str(ri)[:6]):
        if ch == "1":
            rel.add(k)
    for k, ch in enumerate(str(rj)[:6]):
        if ch == "1":
            rel.add(6 + k)
    return rel


def _member_cond(o):
    """Nonlinear axial behaviour of a bar from its MemberBehavior property:
    'tension'  -> tension-only (a cable / slack brace carries no compression),
    'compression' -> compression-only (a strut carries no tension),
    or None for an ordinary member. These members are resolved with an
    active-set iteration in the solver (dropped out when the axial force takes
    the wrong sign)."""
    b = str(getattr(o, "MemberBehavior", "") or "").lower()
    if b.startswith("tension"):
        return "tension"
    if b.startswith("compression"):
        return "compression"
    return None


def _beam_T(n1, n2):
    import numpy as np
    x = np.array([n2.x - n1.x, n2.y - n1.y, n2.z - n1.z])
    L = float(np.linalg.norm(x))
    x = x / L
    ref = np.array([0.0, 0.0, 1.0]) if abs(x @ np.array([0.0, 0.0, 1.0])) < 0.99 else np.array([0.0, 1.0, 0.0])
    y = np.cross(ref, x); y /= np.linalg.norm(y)
    z = np.cross(x, y)
    R = np.array([x, y, z])
    T = np.zeros((12, 12))
    for bk in range(4):
        T[bk * 3:bk * 3 + 3, bk * 3:bk * 3 + 3] = R
    return T, L


# ── flat shell triangle: CST membrane + DKT thin-plate bending ───────
# Validated against the simply-supported square plate (w_c = 0.00406 q a^4/D,
# converging to ~0.998 of exact) and shown to be frame-invariant on a tilted
# plane. 6 DOF/node (ux,uy,uz,rx,ry,rz) to match the beam model.
def _tri_area2d(xy):
    (x1, y1), (x2, y2), (x3, y3) = xy
    return 0.5 * abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))


def _membrane_D(E, nu):
    import numpy as np
    return E / (1 - nu * nu) * np.array([[1, nu, 0], [nu, 1, 0],
                                         [0, 0, (1 - nu) / 2.0]])


def _bending_D(E, nu, t):
    import numpy as np
    return E * t ** 3 / (12 * (1 - nu * nu)) * np.array(
        [[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2.0]])


def _cst_B(xy):
    """Constant strain-displacement matrix (3x6) and area of a CST."""
    import numpy as np
    (x1, y1), (x2, y2), (x3, y3) = xy
    A = _tri_area2d(xy)
    b = [y2 - y3, y3 - y1, y1 - y2]
    c = [x3 - x2, x1 - x3, x2 - x1]
    B = np.zeros((3, 6))
    for i in range(3):
        B[0, 2 * i] = b[i]; B[1, 2 * i + 1] = c[i]
        B[2, 2 * i] = c[i]; B[2, 2 * i + 1] = b[i]
    return B / (2.0 * A), A


def _dkt_B(xy, xi, eta):
    """DKT bending strain (curvature) matrix (3x9) at natural coords (xi,eta).
    DOF order per node: w, rx, ry."""
    import numpy as np
    (x1, y1), (x2, y2), (x3, y3) = [(float(a), float(b)) for (a, b) in xy]
    x23, y23 = x2 - x3, y2 - y3
    x31, y31 = x3 - x1, y3 - y1
    x12, y12 = x1 - x2, y1 - y2
    A = _tri_area2d(xy)
    l23, l31, l12 = x23**2 + y23**2, x31**2 + y31**2, x12**2 + y12**2
    P4, P5, P6 = -6*x23/l23, -6*x31/l31, -6*x12/l12
    t4, t5, t6 = -6*y23/l23, -6*y31/l31, -6*y12/l12
    q4, q5, q6 = 3*x23*y23/l23, 3*x31*y31/l31, 3*x12*y12/l12
    r4, r5, r6 = 3*y23**2/l23, 3*y31**2/l31, 3*y12**2/l12
    Hx_xi = np.array([
        P6*(1-2*xi)+(P5-P6)*eta, q6*(1-2*xi)-(q5+q6)*eta,
        -4+6*(xi+eta)+r6*(1-2*xi)-eta*(r5+r6),
        -P6*(1-2*xi)+eta*(P4+P6), q6*(1-2*xi)+eta*(q4-q6),
        -2+6*xi+r6*(1-2*xi)+eta*(r4-r6),
        -eta*(P5+P4), eta*(q4-q5), -eta*(r5-r4)])
    Hy_xi = np.array([
        t6*(1-2*xi)+(t5-t6)*eta, 1+r6*(1-2*xi)-eta*(r5+r6),
        -q6*(1-2*xi)+eta*(q5+q6),
        -t6*(1-2*xi)+eta*(t4+t6), -1+r6*(1-2*xi)+eta*(r4-r6),
        -q6*(1-2*xi)-eta*(q4-q6),
        -eta*(t5+t4), eta*(r4-r5), -eta*(q4-q5)])
    Hx_eta = np.array([
        -P5*(1-2*eta)-(P6-P5)*xi, q5*(1-2*eta)-(q5+q6)*xi,
        -4+6*(xi+eta)+r5*(1-2*eta)-xi*(r5+r6),
        xi*(P4+P6), xi*(q4-q6), -xi*(r6-r4),
        P5*(1-2*eta)-xi*(P4+P5), q5*(1-2*eta)+xi*(q4-q5),
        -2+6*eta+r5*(1-2*eta)+xi*(r4-r5)])
    Hy_eta = np.array([
        -t5*(1-2*eta)-(t6-t5)*xi, 1+r5*(1-2*eta)-xi*(r5+r6),
        -q5*(1-2*eta)+xi*(q5+q6),
        xi*(t4+t6), xi*(r4-r6), -xi*(q4-q6),
        t5*(1-2*eta)-xi*(t4+t5), -1+r5*(1-2*eta)+xi*(r4-r5),
        -q5*(1-2*eta)-xi*(q4-q5)])
    B = np.zeros((3, 9))
    B[0, :] = (y31*Hx_xi + y12*Hx_eta) / (2*A)
    B[1, :] = (-x31*Hy_xi - x12*Hy_eta) / (2*A)
    B[2, :] = (-x31*Hx_xi - x12*Hx_eta + y31*Hy_xi + y12*Hy_eta) / (2*A)
    return B


def _shell_frame(pts):
    """Local axes R (rows ex,ey,ez), local 2D node coords and the 18x18
    global<-local DOF transform T for a flat shell at 3D points `pts`."""
    import numpy as np
    p1, p2, p3 = [np.array([p.x, p.y, p.z], float) for p in pts]
    ex = p2 - p1; ex = ex / np.linalg.norm(ex)
    ez = np.cross(ex, p3 - p1); ez = ez / np.linalg.norm(ez)
    ey = np.cross(ez, ex)
    R = np.vstack([ex, ey, ez])
    xy = [tuple((R @ (p - p1))[:2]) for p in (p1, p2, p3)]
    T = np.zeros((18, 18))
    for n in range(3):
        T[6*n:6*n+3, 6*n:6*n+3] = R
        T[6*n+3:6*n+6, 6*n+3:6*n+6] = R
    return R, xy, T


def _shell_k_global(pts, E, nu, t):
    """18x18 global stiffness of a flat 3-node shell (CST + DKT + small drilling
    stiffness). DOF order per node: ux,uy,uz,rx,ry,rz."""
    import numpy as np
    R, xy, T = _shell_frame(pts)
    Bm, A = _cst_B(xy)
    Km = (Bm.T @ _membrane_D(E, nu) @ Bm) * t * A
    Db = _bending_D(E, nu, t)
    Kb = np.zeros((9, 9))
    for (xi, eta) in [(0.5, 0.0), (0.5, 0.5), (0.0, 0.5)]:
        Bb = _dkt_B(xy, xi, eta)
        Kb += Bb.T @ Db @ Bb
    Kb *= A / 3.0
    Kl = np.zeros((18, 18))
    mi = [0, 1, 6, 7, 12, 13]
    bi = [2, 3, 4, 8, 9, 10, 14, 15, 16]
    for a in range(6):
        for b in range(6):
            Kl[mi[a], mi[b]] += Km[a, b]
    for a in range(9):
        for b in range(9):
            Kl[bi[a], bi[b]] += Kb[a, b]
    kdr = 1e-3 * abs(min(Kb.diagonal().min(), Km.diagonal().min()))
    for n in range(3):
        Kl[6*n+5, 6*n+5] += kdr
    return T.T @ Kl @ T


def _shell_vm_stress(pts, E, nu, t, u_glob18):
    """Peak von Mises stress (top/bottom surface, at the centroid) of a flat
    shell triangle from its 18 global nodal displacements."""
    import numpy as np
    R, xy, T = _shell_frame(pts)
    ul = T @ np.asarray(u_glob18, float)
    mi = [0, 1, 6, 7, 12, 13]; bi = [2, 3, 4, 8, 9, 10, 14, 15, 16]
    Bm, A = _cst_B(xy)
    sig_m = _membrane_D(E, nu) @ (Bm @ ul[mi])          # membrane stress
    Bb = _dkt_B(xy, 1/3.0, 1/3.0)
    M = _bending_D(E, nu, t) @ (Bb @ ul[bi])            # moments / unit width
    sig_b = 6.0 * M / (t * t)                           # surface bending stress

    def vm(s):
        return (s[0]**2 - s[0]*s[1] + s[1]**2 + 3*s[2]**2) ** 0.5
    top = sig_m + sig_b; bot = sig_m - sig_b
    return max(vm(top), vm(bot))


def _plate_frame(tris):
    """A single in-plane coordinate frame (En normal, Ex, Ey) shared by all the
    triangles of one flat plate, so the per-triangle bending moments can be
    reported in one consistent system (Mx, My, Mxy) for a smooth contour. En is
    the area-weighted mean normal; Ex is global X projected onto the plate
    (global Y if the plate faces X)."""
    import numpy as np
    n = np.zeros(3)
    for pts in tris:
        nrm, Ae = _tri_normal_area(pts)
        n = n + np.array([nrm.x, nrm.y, nrm.z]) * Ae
    L = float(np.linalg.norm(n))
    En = n / L if L > 1e-12 else np.array([0.0, 0.0, 1.0])
    gx = np.array([1.0, 0.0, 0.0]) - En * float(En[0])
    if np.linalg.norm(gx) < 1e-6:
        gx = np.array([0.0, 1.0, 0.0]) - En * float(En[1])
    Ex = gx / np.linalg.norm(gx)
    Ey = np.cross(En, Ex)
    return En, Ex, Ey


def _shell_moments(pts, E, nu, t, u_glob18, En, Ex, Ey):
    """Bending moments per unit width of a flat shell triangle, expressed in the
    shared plate frame (Ex, Ey): returns (Mx, My, Mxy, M1, M2) where M1>=M2 are
    the principal moments. Units N.mm/mm (= N). Sagging about an axis is positive
    relative to En; the element's own normal sign is reconciled with En so every
    triangle of the plate reports a consistent sign."""
    import numpy as np
    R, xy, T = _shell_frame(pts)
    ul = T @ np.asarray(u_glob18, float)
    bi = [2, 3, 4, 8, 9, 10, 14, 15, 16]
    Bb = _dkt_B(xy, 1 / 3.0, 1 / 3.0)
    M = _bending_D(E, nu, t) @ (Bb @ ul[bi])        # [Mxx,Myy,Mxy] element-local
    ex_t, ey_t, ez_t = R[0], R[1], R[2]
    sgn = 1.0 if float(ez_t @ En) >= 0.0 else -1.0  # align element normal with En
    Mxx, Myy, Mxy = sgn * M[0], sgn * M[1], sgn * M[2]
    # build the moment as a 3x3 tensor in global coords, then read its
    # components along the shared plate axes (handles any in-plane rotation)
    M3 = (Mxx * np.outer(ex_t, ex_t) + Myy * np.outer(ey_t, ey_t)
          + Mxy * (np.outer(ex_t, ey_t) + np.outer(ey_t, ex_t)))
    mxx = float(Ex @ M3 @ Ex); myy = float(Ey @ M3 @ Ey); mxy = float(Ex @ M3 @ Ey)
    avg = 0.5 * (mxx + myy)
    rad = ((0.5 * (mxx - myy)) ** 2 + mxy ** 2) ** 0.5
    return mxx, myy, mxy, avg + rad, avg - rad


def _principal_angle(mxx, myy, mxy):
    """Angle (rad) of the major principal moment axis relative to the plate Ex
    axis: theta = 0.5*atan2(2 Mxy, Mxx - Myy). The minor axis is at theta+90."""
    import math
    return 0.5 * math.atan2(2.0 * mxy, mxx - myy)


def _wood_armer(mx, my, mxy):
    """Wood-Armer design moments for orthogonal (x, y) slab reinforcement
    (Wood 1968 / Armer). Returns (mxb, myb, mxt, myt): the bottom-face design
    moments (>=0, sagging, carried by bottom steel in x and y) and the
    top-face design moments (<=0, hogging, top steel). The twisting moment
    |Mxy| augments the demand; the standard corner corrections keep each
    moment on the correct side. Sign convention: a sagging moment (bottom in
    tension) is positive, consistent with _shell_moments."""
    amxy = abs(mxy)
    # bottom (sagging) reinforcement
    mxb = mx + amxy; myb = my + amxy
    if mxb < 0.0:
        mxb = 0.0
        myb = (my + abs(mxy * mxy / mx)) if abs(mx) > 1e-12 else (my + amxy)
        if myb < 0.0:
            myb = 0.0
    elif myb < 0.0:
        myb = 0.0
        mxb = (mx + abs(mxy * mxy / my)) if abs(my) > 1e-12 else (mx + amxy)
        if mxb < 0.0:
            mxb = 0.0
    # top (hogging) reinforcement
    mxt = mx - amxy; myt = my - amxy
    if mxt > 0.0:
        mxt = 0.0
        myt = (my - abs(mxy * mxy / mx)) if abs(mx) > 1e-12 else (my - amxy)
        if myt > 0.0:
            myt = 0.0
    elif myt > 0.0:
        myt = 0.0
        mxt = (mx - abs(mxy * mxy / my)) if abs(my) > 1e-12 else (mx - amxy)
        if mxt > 0.0:
            mxt = 0.0
    return mxb, myb, mxt, myt


# characteristic cylinder strength (MPa) for the common EN 1992 grades
CONCRETE_GRADES = {"C20/25": 20.0, "C25/30": 25.0, "C30/37": 30.0,
                   "C35/45": 35.0, "C40/50": 40.0, "C45/55": 45.0,
                   "C50/60": 50.0}


def _fctm(fck):
    """Mean concrete tensile strength (MPa), EN 1992-1-1 Table 3.1."""
    import math
    if fck <= 50.0:
        return 0.30 * fck ** (2.0 / 3.0)
    return 2.12 * math.log(1.0 + (fck + 8.0) / 10.0)


def _ec2_slab_as(med, h, cover, dia, layer, fck, fyk,
                 gc=1.5, gs=1.15, acc=0.85):
    """Required tension-steel area (mm^2 per metre width) for a 1 m slab strip
    under the design moment `med` (N.mm per mm width, magnitude), by
    EN 1992-1-1 for a singly-reinforced rectangular section.

    layer: 0 = outer bars (effective depth d = h - cover - dia/2),
           1 = inner/second direction (d = h - cover - 1.5*dia).
    Returns (As_mm2_per_m, d_mm, note). `note` flags minimum steel or a
    section that needs compression steel / thickening (K > K')."""
    m = abs(float(med))                          # N.mm per mm width
    d = h - cover - dia / 2.0 - (dia if layer else 0.0)
    if d <= 0.0:
        return 0.0, max(d, 0.0), "section too thin for the cover/bar given"
    fcd = acc * fck / gc; fyd = fyk / gs
    K = m / (1.0 * d * d * fcd) if fcd > 0 else 1.0      # b = 1 mm
    Klim = 0.168                                 # no redistribution
    z = d * min(0.95, 0.5 + (max(0.0, 0.25 - min(K, Klim) / 1.134)) ** 0.5)
    As = (m / (fyd * z)) if (fyd > 0 and z > 0) else 0.0  # mm^2 per mm
    as_m = As * 1000.0                           # mm^2 per m
    as_min = max(0.26 * _fctm(fck) / fyk, 0.0013) * d * 1000.0   # EC2 9.2.1.1
    note = ""
    if K > Klim:
        note = "K=%.3f > 0.168: add compression steel or thicken" % K
    elif as_m < as_min:
        as_m = as_min; note = "governed by minimum steel"
    return as_m, d, note


# punching-shear position factor beta (EN 1992-1-1 6.4.3(6), braced frames)
PUNCH_BETA = {"Internal": 1.15, "Edge": 1.4, "Corner": 1.5}


def _punching(ved, c1, c2, d, fck, rhol, beta, gc=1.5, acc=0.85):
    """EN 1992-1-1 (6.4) punching-shear check at a slab-column junction.
    ved = design column load (N), c1 x c2 = column size (mm), d = slab mean
    effective depth (mm), rhol = tension-reinforcement ratio, beta = position
    eccentricity factor. Returns a dict with the control perimeters, the shear
    resistance without links v_Rd,c, the applied shear v_Ed at the 2d perimeter,
    the column-face check v_Ed,0 vs the crushing limit v_Rd,max, and the
    utilisation (needs punching reinforcement when > 1)."""
    import math
    ved = abs(float(ved))
    u0 = 2.0 * (c1 + c2)                      # column-face perimeter
    u1 = 2.0 * (c1 + c2) + 4.0 * math.pi * d  # basic control perimeter at 2d
    k = min(2.0, 1.0 + math.sqrt(200.0 / d)) if d > 0 else 1.0
    rl = min(0.02, max(0.0, rhol))
    crdc = 0.18 / gc
    vrdc = crdc * k * (100.0 * rl * fck) ** (1.0 / 3.0)
    vmin = 0.035 * (k ** 1.5) * math.sqrt(fck)
    vrdc = max(vrdc, vmin)
    ved1 = beta * ved / (u1 * d) if (u1 * d) > 0 else 0.0
    ved0 = beta * ved / (u0 * d) if (u0 * d) > 0 else 0.0
    nu = 0.6 * (1.0 - fck / 250.0)
    fcd = acc * fck / gc
    vrdmax = 0.5 * nu * fcd
    return {"u0": u0, "u1": u1, "k": k, "vRdc": vrdc, "vmin": vmin, "vEd": ved1,
            "vEd0": ved0, "vRdmax": vrdmax,
            "util": (ved1 / vrdc if vrdc > 0 else 0.0),
            "crush": (ved0 / vrdmax if vrdmax > 0 else 0.0)}


def _tri_normal_area(pts):
    """Unit normal (FreeCAD.Vector) and area of a 3D triangle."""
    import numpy as np
    p1, p2, p3 = [np.array([p.x, p.y, p.z], float) for p in pts]
    n = np.cross(p2 - p1, p3 - p1)
    L = float(np.linalg.norm(n))
    nrm = (n / L) if L > 1e-12 else np.array([0.0, 0.0, 1.0])
    return FreeCAD.Vector(float(nrm[0]), float(nrm[1]), float(nrm[2])), 0.5 * L


def _shell_tris(o):
    """Triangle mesh of a plate/shell object as [[v1,v2,v3], ...] (Vectors)."""
    import json
    try:
        return [[FreeCAD.Vector(*p) for p in tri]
                for tri in json.loads(getattr(o, "ShellTris", "[]"))]
    except Exception:
        return []


def _shell_material(o):
    return getattr(o, "Material", DEFAULT_MAT)


def _poisson(E, G):
    """Poisson's ratio from E and G (nu = E/2G - 1), clamped to a sane range."""
    return max(0.0, min(0.49, E / (2.0 * G) - 1.0)) if G > 1e-9 else 0.3


def _mesh_quad(p1, p2, p3, p4, nx, ny):
    """Mesh a (possibly warped) quad p1->p2->p3->p4 into nx*ny*2 triangles by
    bilinear interpolation. Returns a list of [v1,v2,v3] triangles."""
    def bil(u, v):
        a = p1 + vscale(p2 - p1, u)
        b = p4 + vscale(p3 - p4, u)
        return a + vscale(b - a, v)
    tris = []
    for j in range(ny):
        for i in range(nx):
            A = bil(i / float(nx), j / float(ny))
            B = bil((i + 1) / float(nx), j / float(ny))
            C = bil((i + 1) / float(nx), (j + 1) / float(ny))
            D = bil(i / float(nx), (j + 1) / float(ny))
            tris.append([A, B, C]); tris.append([A, C, D])
    return tris


def _order_quad(pts):
    """Order 4 corner points into a convex cyclic quad (by angle about their
    centroid in the plate plane), so a rectangle meshes correctly whatever the
    selection order."""
    import numpy as np
    P = [np.array([p.x, p.y, p.z], float) for p in pts]
    c = sum(P) / 4.0
    n = np.cross(P[1] - P[0], P[2] - P[0])
    ln = np.linalg.norm(n)
    nn = n / ln if ln > 1e-9 else np.array([0, 0, 1.0])
    u = P[0] - c
    u = u / np.linalg.norm(u) if np.linalg.norm(u) > 1e-9 else np.array([1., 0, 0])
    v = np.cross(nn, u)
    ang = [float(np.arctan2(np.dot(p - c, v), np.dot(p - c, u))) for p in P]
    return [pts[i] for i in sorted(range(4), key=lambda i: ang[i])]


def _make_plate(doc, tris, thk, mat):
    """Create a plate/shell analysis object from a triangle mesh."""
    import json
    faces = []
    for tri in tris:
        try:
            faces.append(Part.Face(Part.makePolygon(
                [FreeCAD.Vector(tri[0]), FreeCAD.Vector(tri[1]),
                 FreeCAD.Vector(tri[2]), FreeCAD.Vector(tri[0])])))
        except Exception:
            pass
    if not faces:
        return None
    o = doc.addObject("Part::Feature", "Plate")
    o.Shape = Part.makeCompound(faces)
    o.Label = "Plate (%s, t=%g mm)" % (mat, thk)
    _set(o, "App::PropertyBool", "IsShell", True)
    _set(o, "App::PropertyFloat", "ShellThk", float(thk))
    _set(o, "App::PropertyString", "Material", mat)
    _set(o, "App::PropertyString", "ShellTris",
         json.dumps([[[p.x, p.y, p.z] for p in tri] for tri in tris]))
    try:
        o.ViewObject.ShapeColor = (0.6, 0.6, 0.65)
        o.ViewObject.Transparency = 35
    except Exception:
        pass
    return o


def _section_props_from_name(name):
    """Section properties (A, Iy, Iz, J, c) from a profile name in the library.
    Works for both solid members and line bars (the analysis entity carries a
    section name, never a swept solid).

    Prefers the analytic section database (pure Python, so it also supplies the
    correct St-Venant torsion constant It for open sections, not the polar
    moment Iy+Iz), falling back to the OpenCASCADE face for unknown names."""
    db = _section_db(name)
    if db is not None:
        return db["A"], db["Iy"], db["Iz"], db["It"], max(db["hx"], db["hy"]) / 2.0
    face = build_face(name, "Center", 0.0, 0.0)
    if face is None:
        return None
    A = face.Area
    try:
        m = face.MatrixOfInertia
        Iz = abs(m.A11); Iy = abs(m.A22)
    except Exception:
        bb = face.BoundBox
        Iz = A * bb.YLength ** 2 / 12.0; Iy = A * bb.XLength ** 2 / 12.0
    bb = face.BoundBox
    c = max(bb.XLength, bb.YLength) / 2.0
    J = Iy + Iz
    return A, Iy, Iz, J, c


def _section_props(obj):
    return _section_props_from_name(getattr(obj, "MemberProfile", ""))


def _section_props_full(name):
    """Richer section properties for code checks:
    (A, Iy, Iz, Wel_y, Wel_z, iy, iz, hx, hy). Iy/Iz match _section_props
    (Iz=about face-x, Iy=about face-y). Delegates to the analytic section
    database, falling back to the OpenCASCADE face for unknown names."""
    db = _section_db(name)
    if db is not None:
        return (db["A"], db["Iy"], db["Iz"], db["Wel_y"], db["Wel_z"],
                db["iy"], db["iz"], db["hx"], db["hy"])
    face = build_face(name, "Center", 0.0, 0.0)
    if face is None:
        return None
    A = face.Area
    try:
        m = face.MatrixOfInertia
        Iz = abs(m.A11); Iy = abs(m.A22)
    except Exception:
        bb = face.BoundBox
        Iz = A * bb.YLength ** 2 / 12.0; Iy = A * bb.XLength ** 2 / 12.0
    bb = face.BoundBox
    hx = max(bb.XLength, 1e-6); hy = max(bb.YLength, 1e-6)
    Wel_y = Iy / (hx / 2.0)     # bending about face-y, extreme fibre at x = hx/2
    Wel_z = Iz / (hy / 2.0)     # bending about face-x, extreme fibre at y = hy/2
    iy = (Iy / A) ** 0.5 if A > 1e-9 else 0.0
    iz = (Iz / A) ** 0.5 if A > 1e-9 else 0.0
    return A, Iy, Iz, Wel_y, Wel_z, iy, iz, hx, hy


# ── analytic section-property engine (pure Python) ───────────────────
# Section geometry comes from the same polygons the profile builders draw,
# so A and I match the OpenCASCADE faces exactly, while plastic moduli,
# torsion/warping constants and classification data are obtained
# analytically — everything a full EN 1993-1-1 code check needs, computable
# without a running FreeCAD kernel.
def _poly_AQI(pts):
    """Signed area and moments of a simple polygon about the origin:
    (A, Qx=int y dA, Qy=int x dA, Ix=int y^2 dA, Iy=int x^2 dA)."""
    A = Qx = Qy = Ix = Iy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        A += cr
        Qy += (x0 + x1) * cr
        Qx += (y0 + y1) * cr
        Iy += (x0 * x0 + x0 * x1 + x1 * x1) * cr
        Ix += (y0 * y0 + y0 * y1 + y1 * y1) * cr
    return A * 0.5, Qx / 6.0, Qy / 6.0, Ix / 12.0, Iy / 12.0


def _clip(pts, axis, c, ge):
    """Clip polygon to the half-plane coord>=c (ge=True) or <=c, axis 0=x,1=y."""
    out = []
    n = len(pts)
    for i in range(n):
        a = pts[i]; b = pts[(i + 1) % n]
        ia = (a[axis] >= c) if ge else (a[axis] <= c)
        ib = (b[axis] >= c) if ge else (b[axis] <= c)
        if ia:
            out.append(a)
        if ia != ib:
            t = (c - a[axis]) / (b[axis] - a[axis])
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return out


def _region_props(contours):
    """Area, centroid and central second moments of a region = outer polygon
    minus holes (first contour is the outer, the rest subtract)."""
    A = Qx = Qy = Ix = Iy = 0.0
    for k, cont in enumerate(contours):
        a, qx, qy, ix, iy = _poly_AQI(cont)
        if a < 0:
            a, qx, qy, ix, iy = -a, -qx, -qy, -ix, -iy
        s = 1.0 if k == 0 else -1.0
        A += s * a; Qx += s * qx; Qy += s * qy; Ix += s * ix; Iy += s * iy
    cx = Qy / A; cy = Qx / A
    return A, cx, cy, Ix - A * cy * cy, Iy - A * cx * cx


def _half_AQ(contours, axis, c, ge):
    """Area and first moment about the cut line coord=c of the region on one
    side of it (ge=True: coord>=c)."""
    A = Q = 0.0
    for k, cont in enumerate(contours):
        cl = _clip(cont, axis, c, ge)
        if len(cl) < 3:
            continue
        a, qx, qy, _, _ = _poly_AQI(cl)
        if a < 0:
            a, qx, qy = -a, -qx, -qy
        s = 1.0 if k == 0 else -1.0
        A += s * a
        Q += s * ((qy if axis == 0 else qx) - c * a)
    return A, Q


def _plastic_modulus(contours, A, lo, hi, axis):
    """Plastic modulus about the centroidal axis perpendicular to `axis`
    (axis 1 -> bending stresses the y-extreme fibres; axis 0 -> x-extreme).
    Finds the equal-area split (plastic neutral axis) by bisection."""
    a, b = lo, hi
    for _ in range(80):
        m = 0.5 * (a + b)
        Ak, _ = _half_AQ(contours, axis, m, True)
        if Ak > A / 2.0:
            a = m
        else:
            b = m
    cp = 0.5 * (a + b)
    _, Qp = _half_AQ(contours, axis, cp, True)
    _, Qn = _half_AQ(contours, axis, cp, False)
    return abs(Qp) + abs(Qn)


def _poly_for(kind, d):
    """Cross-section polygon(s) [outer, hole...] for a profile, mirroring the
    dynframe_profiles builders (centred, in mm)."""
    def rect(bx, hy, cx=0.0, cy=0.0):
        hb, hh = bx / 2.0, hy / 2.0
        return [(cx - hb, cy - hh), (cx + hb, cy - hh),
                (cx + hb, cy + hh), (cx - hb, cy + hh)]

    def recentre(pts):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        ox = (min(xs) + max(xs)) / 2.0; oy = (min(ys) + max(ys)) / 2.0
        return [(x - ox, y - oy) for (x, y) in pts]

    if kind == "I":
        h, b, tw, tf = d["h"], d["b"], d["tw"], d["tf"]
        x1, xw = b / 2.0, tw / 2.0; y1, yf = h / 2.0, h / 2.0 - tf
        return [[(-x1, -y1), (x1, -y1), (x1, -yf), (xw, -yf), (xw, yf), (x1, yf),
                 (x1, y1), (-x1, y1), (-x1, yf), (-xw, yf), (-xw, -yf), (-x1, -yf)]]
    if kind == "U":
        h, b, tw, tf = d["h"], d["b"], d["tw"], d["tf"]
        return [recentre([(0, 0), (b, 0), (b, tf), (tw, tf),
                          (tw, h - tf), (b, h - tf), (b, h), (0, h)])]
    if kind == "L":
        a, b, t = d["a"], d["b"], d["t"]
        return [recentre([(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)])]
    if kind == "T":
        h, b, t = d["h"], d["b"], d["t"]; cx = b / 2.0
        return [recentre([(cx - t / 2.0, 0), (cx + t / 2.0, 0), (cx + t / 2.0, h - t),
                         (b, h - t), (b, h), (0, h), (0, h - t), (cx - t / 2.0, h - t)])]
    if kind == "box":
        b, h, t = d["b"], d["h"], d["t"]
        return [rect(b, h), rect(b - 2 * t, h - 2 * t)]
    if kind == "flat":
        return [rect(d["b"], d["t"])]
    return None


def _torsion_warp(kind, d):
    """St-Venant torsion constant It and warping constant Iw (mm^4, mm^6)."""
    if kind in ("I", "U"):
        h, b, tw, tf = d["h"], d["b"], d["tw"], d["tf"]
        It = (2.0 * b * tf ** 3 + (h - 2.0 * tf) * tw ** 3) / 3.0
        Iw = tf * b ** 3 * (h - tf) ** 2 / 24.0
        return It, Iw
    if kind == "box":
        b, h, t = d["b"], d["h"], d["t"]
        bm, hm = b - t, h - t
        return 2.0 * t * bm ** 2 * hm ** 2 / (bm + hm), 0.0
    if kind == "CHS":
        D, t = d["d"], d["t"]; di = D - 2.0 * t
        import math
        return math.pi / 32.0 * (D ** 4 - di ** 4), 0.0
    if kind == "round":
        import math
        return math.pi / 32.0 * d["d"] ** 4, 0.0
    if kind == "L":
        return (d["a"] + d["b"]) * d["t"] ** 3 / 3.0, 0.0
    if kind == "T":
        return (d["b"] + d["h"] - d["t"]) * d["t"] ** 3 / 3.0, 0.0
    if kind == "flat":
        return d["b"] * d["t"] ** 3 / 3.0, 0.0
    return 0.0, 0.0


_SECTION_DB_CACHE = {}


def _section_db(name):
    """Full analytic section database for a profile name:
    A, Iy, Iz, Wel_y, Wel_z, Wpl_y, Wpl_z, iy, iz, It, Iw, hx, hy, plus the
    raw dimensions (keys '_h', '_b', ...), 'kind', 'hb' and 'dt'. Returns
    None for names not in the profile library (caller falls back to the face).
    Iy/Iz follow the face convention (Iz = about face-X/depth, Iy = about
    face-Y/width)."""
    if name in _SECTION_DB_CACHE:
        return _SECTION_DB_CACHE[name]
    import math
    info_ = None
    try:
        import dynframe_profiles as _P
        info_ = _P.dims_for(name)
    except Exception:
        info_ = None
    db = None
    if info_ is not None:
        kind, d = info_
        db = {"kind": kind}
        if kind in ("CHS", "round"):
            if kind == "CHS":
                D, t = d["d"], d["t"]; di = D - 2.0 * t
                A = math.pi / 4.0 * (D * D - di * di)
                I = math.pi / 64.0 * (D ** 4 - di ** 4)
                Wpl = (D ** 3 - di ** 3) / 6.0
                db["dt"] = D / t
            else:
                D = d["d"]
                A = math.pi / 4.0 * D * D
                I = math.pi / 64.0 * D ** 4
                Wpl = D ** 3 / 6.0
                db["dt"] = 1.0
            Wel = I / (D / 2.0)
            db.update(A=A, Iy=I, Iz=I, Wel_y=Wel, Wel_z=Wel,
                      Wpl_y=Wpl, Wpl_z=Wpl, hx=D, hy=D)
        else:
            contours = _poly_for(kind, d)
            A, cx, cy, Ixx, Iyy = _region_props(contours)
            contours = [[(x - cx, y - cy) for (x, y) in c] for c in contours]
            xs = [p[0] for c in contours for p in c]
            ys = [p[1] for c in contours for p in c]
            hx = max(xs) - min(xs); hy = max(ys) - min(ys)
            db.update(A=A, Iz=Ixx, Iy=Iyy,
                      Wel_z=Ixx / (hy / 2.0), Wel_y=Iyy / (hx / 2.0),
                      Wpl_z=_plastic_modulus(contours, A, min(ys), max(ys), 1),
                      Wpl_y=_plastic_modulus(contours, A, min(xs), max(xs), 0),
                      hx=hx, hy=hy)
            db["dt"] = 1.0
        It, Iw = _torsion_warp(kind, d)
        db["It"] = It; db["Iw"] = Iw
        db["iy"] = (db["Iy"] / db["A"]) ** 0.5 if db["A"] > 1e-9 else 0.0
        db["iz"] = (db["Iz"] / db["A"]) ** 0.5 if db["A"] > 1e-9 else 0.0
        for k, v in d.items():
            db["_" + k] = v
        db["hb"] = (d.get("h", 1.0) / d.get("b", 1.0)) if kind in ("I", "U") else 1.0
    _SECTION_DB_CACHE[name] = db
    return db


def _chi_buckling(lam, alpha):
    """EC3 flexural-buckling reduction factor chi for non-dimensional
    slenderness `lam` and imperfection factor `alpha` (curve a=0.21, b=0.34,
    c=0.49, d=0.76). chi = 1/(Phi+sqrt(Phi^2-lam^2)) <= 1."""
    if lam <= 0.2:
        return 1.0
    phi = 0.5 * (1.0 + alpha * (lam - 0.2) + lam * lam)
    chi = 1.0 / (phi + (phi * phi - lam * lam) ** 0.5)
    return min(chi, 1.0)


# ── full EN 1993-1-1 steel checks: classification, LTB, interaction ──
_ALPHA_CURVE = {"a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}


def _buckling_curves(db):
    """Flexural-buckling curves (major axis, minor axis) per EN 1993-1-1
    Table 6.2, chosen automatically from the section type — the way Robot
    assigns them. 'major'/'minor' are the strong/weak principal axes."""
    kind = db["kind"]
    if kind == "I":
        hb = db.get("hb", 1.0); tf = db.get("_tf", 10.0)
        if hb > 1.2:
            return ("a", "b") if tf <= 40.0 else ("b", "c")
        return ("b", "c") if tf <= 100.0 else ("d", "d")
    if kind in ("box", "CHS"):
        return ("a", "a")            # hot-finished hollow sections
    return ("c", "c")                # channels, tees, angles, solids


def _classify(db, fy, N, Mmaj):
    """EN 1993-1-1 Table 5.2 cross-section class (1..4) under axial force N
    (N<0 = compression) and major-axis moment Mmaj. Returns (class, detail)."""
    eps = (235.0 / fy) ** 0.5
    kind = db["kind"]; A = db["A"]; comp = max(0.0, -N)
    if kind == "CHS":
        dt = db["dt"]
        for c, lim in ((1, 50 * eps * eps), (2, 70 * eps * eps), (3, 90 * eps * eps)):
            if dt <= lim:
                return c, "CHS d/t=%.0f cl%d" % (dt, c)
        return 4, "CHS d/t=%.0f slender" % dt
    if kind == "round":
        return 1, "solid round"
    if kind == "L":
        a, b, t = db["_a"], db["_b"], db["_t"]
        if max(a, b) / t <= 15 * eps and (a + b) / (2 * t) <= 11.5 * eps:
            return 3, "angle cl3"
        return 4, "angle slender"
    if kind == "flat":
        return 1, "flat bar"
    # flange + web (I, channel, tee, box)
    if kind == "I":
        h, b, tw, tf = db["_h"], db["_b"], db["_tw"], db["_tf"]
        cf = (b - tw) / 2.0; tfl = tf; cw = h - 2 * tf; twe = tw; internal = False
    elif kind == "U":
        h, b, tw, tf = db["_h"], db["_b"], db["_tw"], db["_tf"]
        cf = b - tw; tfl = tf; cw = h - 2 * tf; twe = tw; internal = False
    elif kind == "T":
        h, b, t = db["_h"], db["_b"], db["_t"]
        cf = (b - t) / 2.0; tfl = t; cw = h - t; twe = t; internal = False
    else:                                   # box
        b, h, t = db["_b"], db["_h"], db["_t"]
        cf = b - 2 * t; tfl = t; cw = h - 2 * t; twe = t; internal = True
    fl_lims = (33 * eps, 38 * eps, 42 * eps) if internal else (9 * eps, 10 * eps, 14 * eps)
    rf = cf / tfl
    cls_f = 4
    for c, lim in enumerate(fl_lims, 1):
        if rf <= lim:
            cls_f = c; break
    # web under N + bending: general alpha (plastic) / psi (elastic)
    rw = cw / twe
    a_shift = comp / (2.0 * fy * twe) if twe > 0 else 0.0
    alpha = min(1.0, max(0.0, 0.5 + a_shift / cw)) if cw > 0 else 1.0
    if alpha > 0.5:
        l1 = 396 * eps / (13 * alpha - 1); l2 = 456 * eps / (13 * alpha - 1)
    else:
        l1 = 36 * eps / max(alpha, 1e-6); l2 = 41.5 * eps / max(alpha, 1e-6)
    Wz = db["Wel_z"] if db["Iz"] >= db["Iy"] else db["Wel_y"]
    sig_ax = N / A
    sig_b = abs(Mmaj) / Wz if Wz > 0 else 0.0
    s1 = sig_ax - sig_b
    psi = max(-3.0, min(1.0, (sig_ax + sig_b) / s1)) if abs(s1) > 1e-9 else -1.0
    if psi > -1:
        l3 = 42 * eps / (0.67 + 0.33 * psi)
    else:
        l3 = 62 * eps * (1 - psi) * (-psi) ** 0.5
    cls_w = 4
    for c, lim in ((1, l1), (2, l2), (3, l3)):
        if rw <= lim:
            cls_w = c; break
    cls = max(cls_f, cls_w)
    return cls, "flange c/t=%.1f(cl%d) web c/t=%.1f(cl%d)" % (rf, cls_f, rw, cls_w)


def _mcr(db, E, G, L, C1):
    """Elastic critical moment for major-axis lateral-torsional buckling
    (fork supports, no load eccentricity). None for sections not susceptible
    to LTB (hollow/round)."""
    import math
    if db["kind"] in ("box", "CHS", "round"):
        return None
    Imin = min(db["Iz"], db["Iy"])
    if Imin <= 0 or L <= 0:
        return None
    t1 = math.pi ** 2 * E * Imin / L ** 2
    inside = db["Iw"] / Imin + L ** 2 * G * db["It"] / (math.pi ** 2 * E * Imin)
    return C1 * t1 * inside ** 0.5


def _chi_lt(lam_lt, hb):
    """LTB reduction factor, EN 1993-1-1 6.3.2.3 (rolled/equivalent welded):
    lam_LT,0=0.4, beta=0.75, curve b (h/b<=2) or c."""
    if lam_lt <= 0.4:
        return 1.0
    alt = 0.34 if hb <= 2.0 else 0.49
    phi = 0.5 * (1.0 + alt * (lam_lt - 0.4) + 0.75 * lam_lt ** 2)
    v = phi * phi - 0.75 * lam_lt ** 2
    chilt = 1.0 / (phi + v ** 0.5) if v > 0 else 1.0 / phi
    return min(chilt, 1.0, 1.0 / lam_lt ** 2)


def _ec3_member_check(db, fy, E, G, N, My, Mz, Lcr_maj, Lcr_min, Lltb,
                      C1, Cmy, Cmz, CmLT, gM0, gM1, susceptible=None):
    """Full EN 1993-1-1 member verification. My/Mz are the stored moments
    about the section's local y/z (Iy/Iz) axes; the major axis is the larger-I
    one. Returns a dict of class, resistances, reduction factors and the
    governing utilisation from the 6.2 section check and the 6.3.3 (Annex B)
    interaction equations 6.61/6.62."""
    import math
    maj_is_z = db["Iz"] >= db["Iy"]
    Imaj = max(db["Iz"], db["Iy"]); Imin = min(db["Iz"], db["Iy"])
    Mmaj = Mz if maj_is_z else My
    Mmin = My if maj_is_z else Mz
    Wpl_maj = db["Wpl_z"] if maj_is_z else db["Wpl_y"]
    Wel_maj = db["Wel_z"] if maj_is_z else db["Wel_y"]
    Wpl_min = db["Wpl_y"] if maj_is_z else db["Wpl_z"]
    Wel_min = db["Wel_y"] if maj_is_z else db["Wel_z"]
    cls, cdetail = _classify(db, fy, N, Mmaj)
    plastic = cls <= 2
    Wy = Wpl_maj if plastic else Wel_maj
    Wz = Wpl_min if plastic else Wel_min
    A = db["A"]; comp = max(0.0, -N)

    NRk = A * fy; MyRk = Wy * fy; MzRk = Wz * fy
    NcRd = A * fy / gM0
    McyRd0 = Wy * fy / gM0; MczRd0 = Wz * fy / gM0
    # 6.2 cross-section resistance (linear interaction, conservative)
    U_sec = abs(N) / NcRd + (abs(Mmaj) / McyRd0 if McyRd0 > 0 else 0.0) \
        + (abs(Mmin) / MczRd0 if MczRd0 > 0 else 0.0)

    cmaj, cmin = _buckling_curves(db)
    chiy = chiz = chiLT = 1.0
    lam_maj = lam_min = lam_lt = 0.0
    if comp > 1e-9:
        Ncr_maj = math.pi ** 2 * E * Imaj / Lcr_maj ** 2 if Lcr_maj > 0 else 1e30
        Ncr_min = math.pi ** 2 * E * Imin / Lcr_min ** 2 if Lcr_min > 0 else 1e30
        lam_maj = (NRk / Ncr_maj) ** 0.5
        lam_min = (NRk / Ncr_min) ** 0.5
        chiy = _chi_buckling(lam_maj, _ALPHA_CURVE[cmaj])
        chiz = _chi_buckling(lam_min, _ALPHA_CURVE[cmin])
    Mc = _mcr(db, E, G, Lltb, C1)
    if Mc is not None and Mc > 0:
        lam_lt = (Wy * fy / Mc) ** 0.5
        chiLT = _chi_lt(lam_lt, db.get("hb", 2.0))
    NbyRd = chiy * NRk / gM1; NbzRd = chiz * NRk / gM1
    MbRd = chiLT * Wy * fy / gM1
    MczRd1 = Wz * fy / gM1

    # Annex B interaction factors. Susceptibility to torsional deformation picks
    # Table B.2 (susceptible) vs B.1 (not) for kzy; default by section type, but
    # overridable so a restrained column can match a Robot/Robot-style run.
    if susceptible is None:
        susceptible = db["kind"] in ("I", "U", "T")
    nY = comp / NbyRd if NbyRd > 0 else 0.0
    nZ = comp / NbzRd if NbzRd > 0 else 0.0
    kyy = min(Cmy * (1 + (lam_maj - 0.2) * nY), Cmy * (1 + 0.8 * nY))
    kzz = min(Cmz * (1 + (2 * lam_min - 0.6) * nZ), Cmz * (1 + 1.4 * nZ))
    kyz = 0.6 * kzz
    if susceptible:
        denom = max(CmLT - 0.25, 1e-3)
        kzy = max(1 - (0.1 * lam_min * nZ) / denom, 1 - (0.1 * nZ) / denom)
        if lam_min < 0.4:
            kzy = min(0.6 + lam_min, 1 - (0.1 * lam_min * nZ) / denom)
    else:
        kzy = 0.6 * kyy

    tMy = abs(Mmaj) / MbRd if MbRd > 0 else 0.0
    tMz = abs(Mmin) / MczRd1 if MczRd1 > 0 else 0.0
    U61 = (comp / NbyRd if NbyRd > 0 else 0.0) + kyy * tMy + kyz * tMz
    U62 = (comp / NbzRd if NbzRd > 0 else 0.0) + kzy * tMy + kzz * tMz
    U = max(U_sec, U61, U62)
    gov = "Section" if U == U_sec else ("Eq.6.61" if U == U61 else "Eq.6.62")
    return {"cls": cls, "cdetail": cdetail, "plastic": plastic, "Mmaj": Mmaj,
            "Mmin": Mmin, "U_sec": U_sec, "U61": U61, "U62": U62, "U": U,
            "gov": gov, "chiy": chiy, "chiz": chiz, "chiLT": chiLT,
            "lam_lt": lam_lt, "Mcr": Mc, "NcRd": NcRd, "McyRd": McyRd0,
            "MbRd": MbRd, "curves": (cmaj, cmin)}


def _ec3_torsion(T_Ed, It, tw, tf, Az, fy, gM0=1.0):
    """EN 1993-1-1 6.2.7 St-Venant torsion of an open I/H section: the torsional
    shear stresses in the flange and web (tau = T t / It), their utilisation
    against the shear yield fy/sqrt3, and the torsion-reduced plastic shear
    resistance Vpl,T,Rd (eq 6.26 for I/H sections, using the web stress). Warping
    torsion is not included; for the exact warping/St-Venant split an open-section
    thin-walled analysis is needed (what Robot does internally)."""
    T = abs(float(T_Ed))
    tau_y = fy / (3.0 ** 0.5) / gM0
    tau_f = T * tf / It if It > 0 else 0.0
    tau_w = T * tw / It if It > 0 else 0.0
    Vpl = Az * fy / (3.0 ** 0.5) / gM0
    red = (1.0 - tau_w / (1.25 * tau_y)) ** 0.5 if tau_w < 1.25 * tau_y else 0.0
    return {"tau_f": tau_f, "tau_w": tau_w, "tau_y": tau_y,
            "util_f": tau_f / tau_y if tau_y > 0 else 0.0,
            "util_w": tau_w / tau_y if tau_y > 0 else 0.0,
            "Vpl_Rd": Vpl, "Vpl_T_Rd": red * Vpl, "red": red}


# ── materials (name -> E, G, Fy, density) in N/mm^2 and kg/mm^3 ──────
MATERIALS = {
    "Steel S235": (210000.0, 80769.0, 235.0, 7.85e-6),
    "Steel S275": (210000.0, 80769.0, 275.0, 7.85e-6),
    "Steel S355": (210000.0, 80769.0, 355.0, 7.85e-6),
    "Stainless 304": (193000.0, 74000.0, 215.0, 7.90e-6),
    "Aluminium 6061-T6": (70000.0, 26000.0, 240.0, 2.70e-6),
    # concrete: E_cm per EN 1992-1-1, nu = 0.2 (G = E/2.4), rho ~ 2500 kg/m^3.
    # the "Fy" slot carries fck (for a rough elastic stress check); proper RC
    # design is the EC2 plate-reinforcement command.
    "Concrete C25/30": (31476.0, 13115.0, 25.0, 2.5e-9),
    "Concrete C30/37": (32837.0, 13682.0, 30.0, 2.5e-9),
    "Concrete C35/45": (34077.0, 14199.0, 35.0, 2.5e-9),
}
DEFAULT_MAT = "Steel S235"


def _material(name):
    """Return (E, G, Fy, rho) for a material name, defaulting to steel."""
    return MATERIALS.get(name, MATERIALS[DEFAULT_MAT])


# Building thermal materials: name -> (k [W/mK], mu vapour-resistance factor
# [-], fixed R [m2K/W] or None, rho [kg/m3], cp [J/kgK]). k/mu/R feed the
# U-value and condensation tools; rho/cp feed the dynamic (thermal-mass)
# analysis. Air gaps use a fixed R (EN ISO 6946), membranes a very high mu.
THERMAL_MATERIALS = {
    "Concrete (dense)":      (2.00, 120, None, 2300, 1000),
    "Concrete (lightweight)": (0.38, 60, None, 1200, 1000),
    "Reinforced concrete":   (2.30, 130, None, 2400, 1000),
    "Brick (fired clay)":    (0.77, 10, None, 1700, 1000),
    "AAC block (aircrete)":  (0.15, 8, None, 500, 1000),
    "Natural stone":         (3.50, 150, None, 2600, 1000),
    "EPS insulation":        (0.035, 40, None, 20, 1450),
    "XPS insulation":        (0.034, 100, None, 35, 1450),
    "Mineral wool":          (0.035, 1, None, 30, 1030),
    "PIR / PUR board":       (0.022, 60, None, 30, 1400),
    "Wood fibre board":      (0.040, 5, None, 160, 2100),
    "Timber (softwood)":     (0.13, 50, None, 500, 1600),
    "Plywood / OSB":         (0.13, 150, None, 600, 1700),
    "Plasterboard":          (0.25, 8, None, 900, 1000),
    "Gypsum plaster":        (0.57, 10, None, 1300, 1000),
    "Cement render":         (1.00, 25, None, 1800, 1000),
    "Lime plaster":          (0.80, 10, None, 1600, 1000),
    "Glass":                 (1.00, 1e6, None, 2500, 750),
    "Steel":                 (50.0, 1e6, None, 7800, 450),
    "Vapour barrier (PE)":   (0.33, 100000, None, 980, 1800),
    "Air gap (unventilated)": (1.00, 1, 0.18, 1.2, 1000),
}
DEFAULT_THERMAL = "Mineral wool"


def _thermal_mat(name):
    """(k, mu, fixedR, rho, cp) for a thermal material name."""
    return THERMAL_MATERIALS.get(name, THERMAL_MATERIALS[DEFAULT_THERMAL])


def _dynamic_thermal(layers, rsi, rse, period_s=86400.0):
    """Dynamic (periodic) thermal response of a layered element by the
    EN ISO 13786 heat-transfer-matrix method. layers = [(d_m, k, rho, cp), ...]
    inside->outside. Over a daily cycle (period_s) it returns the steady U, the
    decrement factor f (amplitude ratio dynamic/steady, 0..1 - how much a daily
    swing is damped) and the time lag (hours - how long the peak is delayed by
    the thermal mass). Heavy/massive walls give small f and long lag."""
    import math, cmath

    def layer_Z(d, k, rho, cp):
        if k <= 0 or rho <= 0 or cp <= 0 or d <= 0:
            R = (d / k) if k > 0 else 0.0
            return [[1 + 0j, complex(-R, 0)], [0j, 1 + 0j]]
        a = k / (rho * cp)                      # thermal diffusivity
        delta = math.sqrt(a * period_s / math.pi)   # penetration depth
        xi = d / delta
        sh = math.sinh(xi); ch = math.cosh(xi); s = math.sin(xi); c = math.cos(xi)
        Z11 = complex(ch * c, sh * s)
        Z12 = -(delta / (2.0 * k)) * complex(sh * c + ch * s, ch * s - sh * c)
        Z21 = -(k / delta) * complex(sh * c - ch * s, sh * c + ch * s)
        return [[Z11, Z12], [Z21, Z11]]

    def mm(A, B):
        return [[A[0][0] * B[0][0] + A[0][1] * B[1][0],
                 A[0][0] * B[0][1] + A[0][1] * B[1][1]],
                [A[1][0] * B[0][0] + A[1][1] * B[1][0],
                 A[1][0] * B[0][1] + A[1][1] * B[1][1]]]
    Z = [[1 + 0j, complex(-rsi, 0)], [0j, 1 + 0j]]
    for (d, k, rho, cp) in layers:
        Z = mm(Z, layer_Z(d, k, rho, cp))
    Z = mm(Z, [[1 + 0j, complex(-rse, 0)], [0j, 1 + 0j]])
    Rtot = rsi + rse + sum((d / k if k > 0 else 0.0) for (d, k, _r, _c) in layers)
    U = 1.0 / Rtot if Rtot > 1e-9 else 0.0
    Z12 = Z[0][1]
    Y12 = (-1.0 / Z12) if abs(Z12) > 1e-30 else 0j
    f = abs(Y12) / U if U > 1e-9 else 0.0
    lag_h = abs(period_s / (2.0 * math.pi) * cmath.phase(Y12)) / 3600.0
    return {"U": U, "R": Rtot, "f": f, "lag_h": lag_h}


def _cond_tri(p, k):
    """3x3 conduction (Laplace) element matrix for a linear triangle with
    conductivity k: Ke[i,j] = k/(4A) (bi bj + ci cj). Returns (Ke, area)."""
    import numpy as np
    (x1, y1), (x2, y2), (x3, y3) = p
    A = 0.5 * abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
    if A < 1e-15:
        return np.zeros((3, 3)), 0.0
    b = [y2 - y3, y3 - y1, y1 - y2]
    c = [x3 - x2, x1 - x3, x2 - x1]
    Ke = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            Ke[i, j] = k / (4.0 * A) * (b[i] * b[j] + c[i] * c[j])
    return Ke, A


def _run_conduction(nodes, tris, ktri, robin):
    """Solve 2-D steady heat conduction div(k grad T)=0 by linear-triangle FE.
    nodes = [(x,y)...] (metres), tris = [(i,j,l)...], ktri[t] the conductivity,
    robin = [(i,j,h,Ta)...] convective boundary edges (film coeff h=1/Rs,
    ambient Ta). Returns the nodal temperatures (numpy array)."""
    import numpy as np
    n = len(nodes)
    K = np.zeros((n, n)); F = np.zeros(n)
    for t, tri in enumerate(tris):
        Ke, _A = _cond_tri([nodes[i] for i in tri], ktri[t])
        for a in range(3):
            for b in range(3):
                K[tri[a], tri[b]] += Ke[a, b]
    for (i, j, h, Ta) in robin:
        (xi, yi) = nodes[i]; (xj, yj) = nodes[j]
        Le = ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5
        K[i, i] += h * Le / 3.0; K[j, j] += h * Le / 3.0
        K[i, j] += h * Le / 6.0; K[j, i] += h * Le / 6.0
        F[i] += h * Le * Ta / 2.0; F[j] += h * Le * Ta / 2.0
    return np.linalg.solve(K, F)


def _iso834(t_min):
    """Standard fire (ISO 834 / EN 1991-1-2) gas temperature (deg C) at time
    t minutes: 20 + 345 log10(8t+1). ~842 C at 30 min, ~945 C at 60 min."""
    import math
    return 20.0 + 345.0 * math.log10(8.0 * max(0.0, t_min) + 1.0)


def _transient_conduction(nodes, tris, ktri, cap, fixed, Tfunc, T0, dt, nsteps,
                          monitors):
    """Transient 2-D heat conduction by implicit (backward-Euler) time stepping:
    (C/dt + K) T^{n+1} = C/dt T^n, with the exposed/`fixed` nodes driven to
    Tfunc(t) (e.g. the fire curve). cap = lumped nodal heat capacity (rho cp
    A/3). Returns (final nodal T, history [(t, [T at monitors]) ...])."""
    import numpy as np
    n = len(nodes)
    K = np.zeros((n, n))
    for t, tri in enumerate(tris):
        Ke, _A = _cond_tri([nodes[i] for i in tri], ktri[t])
        for a in range(3):
            for b in range(3):
                K[tri[a], tri[b]] += Ke[a, b]
    C = np.asarray(cap, float)
    free = [i for i in range(n) if i not in fixed]
    fx = sorted(fixed)
    Amat = K.copy()
    for i in range(n):
        Amat[i, i] += C[i] / dt
    Aff_inv = np.linalg.inv(Amat[np.ix_(free, free)])
    Afe = Amat[np.ix_(free, fx)] if fx else None
    T = np.full(n, float(T0))
    Cf = C[free]
    hist = [(0.0, [float(T[m]) for m in monitors])]
    for s in range(nsteps):
        tnow = (s + 1) * dt
        rhs = Cf * T[free] / dt
        if fx:
            Te = np.full(len(fx), Tfunc(tnow))
            rhs = rhs - Afe @ Te
        T[free] = Aff_inv @ rhs
        if fx:
            for i in fx:
                T[i] = Tfunc(tnow)
        hist.append((tnow, [float(T[m]) for m in monitors]))
    return T, hist


def _sat_vapour_pressure(theta):
    """Saturation water-vapour pressure (Pa) at temperature theta (deg C), per
    EN ISO 13788 (separate fits above/below 0 C). p_sat(0)=610.5, p_sat(20)~2337."""
    import math
    if theta >= 0.0:
        return 610.5 * math.exp(17.269 * theta / (237.3 + theta))
    return 610.5 * math.exp(21.875 * theta / (265.5 + theta))


def _wall_uvalue(layers, rsi, rse):
    """Thermal transmittance of a layered element (EN ISO 6946).
    layers = [(name, thickness_mm, k, mu, fixedR), ...] from inside to outside.
    Returns (U [W/m2K], R_total [m2K/W], per-layer R list)."""
    rtot = rsi + rse; perR = []
    for (_nm, d_mm, k, _mu, fixedR) in layers:
        Ri = fixedR if fixedR is not None else ((d_mm / 1000.0) / k if k > 1e-9 else 0.0)
        perR.append(Ri); rtot += Ri
    U = 1.0 / rtot if rtot > 1e-9 else 0.0
    return U, rtot, perR


def _wall_thermal(layers, Ti, RHi, Te, RHe, rsi=0.13, rse=0.04):
    """Steady 1-D heat + Glaser vapour-diffusion analysis of a layered wall
    (EN ISO 6946 + EN ISO 13788). layers inside->outside. Returns a dict with
    the U-value, the heat flux, the temperature / vapour-pressure / saturation
    profiles at each interface (internal surface -> external surface), the
    condensation flag per interface, the internal-surface temperature factor
    f_Rsi (mould check) and whether interstitial condensation occurs."""
    U, rtot, perR = _wall_uvalue(layers, rsi, rse)
    q = U * (Ti - Te)                      # heat flux W/m2 (inside->outside +)
    # temperatures at interfaces (node 0 = internal surface ... last = external)
    nodeT = [Ti - q * rsi]; cumR = rsi
    for Ri in perR:
        cumR += Ri; nodeT.append(Ti - q * cumR)
    # vapour-pressure diffusion resistance (equivalent air-layer thickness sd)
    sd = [mu * (d_mm / 1000.0) for (_n, d_mm, _k, mu, _fR) in layers]
    sd_tot = sum(sd) or 1e-9
    pi = max(0.0, min(1.0, RHi / 100.0)) * _sat_vapour_pressure(Ti)
    pe = max(0.0, min(1.0, RHe / 100.0)) * _sat_vapour_pressure(Te)
    nodeP = [pi]; cumsd = 0.0
    for s in sd:
        cumsd += s; nodeP.append(pi - (pi - pe) * (cumsd / sd_tot))
    nodePsat = [_sat_vapour_pressure(T) for T in nodeT]
    cond = [nodeP[i] >= nodePsat[i] - 1e-6 for i in range(len(nodeT))]
    fRsi = (nodeT[0] - Te) / (Ti - Te) if abs(Ti - Te) > 1e-9 else 1.0
    return {"U": U, "R": rtot, "q": q, "nodeT": nodeT, "nodeP": nodeP,
            "nodePsat": nodePsat, "cond": cond, "fRsi": fRsi,
            "condensation": any(cond[1:-1]) if len(cond) > 2 else any(cond)}


# coefficient of thermal expansion (per deg C)
MAT_ALPHA = {"Steel S235": 1.2e-5, "Steel S275": 1.2e-5, "Steel S355": 1.2e-5,
             "Stainless 304": 1.6e-5, "Aluminium 6061-T6": 2.3e-5,
             "Concrete C25/30": 1.0e-5, "Concrete C30/37": 1.0e-5,
             "Concrete C35/45": 1.0e-5}


def _mat_alpha(name):
    return MAT_ALPHA.get(name, 1.2e-5)


def _fef_thermal_local(EA, alpha, dT, L):
    """Fixed-end force vector for a uniform temperature change dT on a bar
    (axial only). A fully-restrained heated bar develops N = -E A alpha dT
    (compression); validated against that closed form."""
    import numpy as np
    f = np.zeros(12)
    N0 = EA * alpha * dT
    f[0] = -N0; f[6] = N0
    return f


# EN 1998-1 (EC8) Type-1 elastic-spectrum soil parameters: (S, TB, TC, TD)
EC8_SOILS = {"A": (1.0, 0.15, 0.4, 2.0), "B": (1.2, 0.15, 0.5, 2.0),
             "C": (1.15, 0.20, 0.6, 2.0), "D": (1.35, 0.20, 0.8, 2.0),
             "E": (1.4, 0.15, 0.5, 2.0)}


def _ec8_sd(T, ag, S, TB, TC, TD, q, beta=0.2):
    """EC8 design spectrum Sd(T) (horizontal), ag and Sd in mm/s^2."""
    f = 2.5 / q
    if T <= TB:
        return ag * S * (2.0 / 3.0 + (T / TB) * (f - 2.0 / 3.0))
    if T <= TC:
        return ag * S * f
    if T <= TD:
        return max(ag * S * f * (TC / T), beta * ag)
    return max(ag * S * f * (TC * TD / (T * T)), beta * ag)


def _ramp(t):
    """Continuous blue->cyan->green->yellow->red colour ramp, t in [0, 1]."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    if t < 0.25:
        f = t / 0.25; return (0.0, f, 1.0)
    if t < 0.5:
        f = (t - 0.25) / 0.25; return (0.0, 1.0, 1.0 - f)
    if t < 0.75:
        f = (t - 0.5) / 0.25; return (f, 1.0, 0.0)
    f = (t - 0.75) / 0.25; return (1.0, 1.0 - f, 0.0)


def _tube_radius(msize):
    """Radius of the result tubes - a bold fraction of the model size so the
    contour reads clearly as a thick 3D shape from any angle, not a thin line
    (the Inventor/Robot contour look). Floored so small models stay visible."""
    return max(msize * 0.022, 8.0)


# ── Frame analysis — Robot-style line/stick model ────────────────
# The analysis entity is a BAR: a line (two nodes) carrying a section and a
# material, not a swept solid. That is how Robot Structural Analysis works
# and it is what scales to large models (a high-rise is thousands of lines,
# which would be impossible as solids). Workflow: build the line model
# (draw lines + section, convert members, or node/bar tables) -> supports ->
# load cases -> loads -> combinations -> Calculate -> gradient N/V/M diagrams
# and node/bar/reaction/displacement/force tables. The solver is the same
# validated 3D direct-stiffness core (6 DOF/node).
SUPPORT_TYPES = {"Fixed (all 6)": "111111", "Pinned (Ux Uy Uz)": "111000",
                 "Roller Z (Uz only)": "001000", "Roller X (Ux only)": "100000",
                 "Roller Y (Uy only)": "010000"}
NATURES = ["Dead", "Live", "Wind", "Snow", "Other"]
SUP_GROUP = "Supports"
LOAD_GROUP = "Loads"
RES_GROUP = "Results"
DIA_GROUP = "Force Diagrams"
STR_GROUP = "Structure"
META_NAME = "DynFrameAnalysis"
ROOT_GROUP = "DynFrame"          # one container for every analysis sub-group
CFD_GROUP = "CFD"                # OpenFOAM case records live here
# the sub-groups that live under the single DynFrame root (keeps the tree tidy)
_SUBGROUPS = (SUP_GROUP, LOAD_GROUP, RES_GROUP, DIA_GROUP, STR_GROUP,
              CFD_GROUP, "Analysis Setup")
DIAG_KINDS = ["N", "Vy", "Vz", "Mx", "My", "Mz", "Stress"]


def _fef_udl(w_global, R, L):
    """Local 12-dof consistent nodal-load vector for a uniform load given in
    GLOBAL coords (R from _beam_T). The local-z-bending moment terms (f[4],
    f[10]) are negated because that plane of _beam_k_local uses the opposite
    transverse-rotation sign (k[uz,ry]=-6EIy/L^2, k[uy,rz]=+6EIz/L^2). Gives
    exact nodal deflections at one element per member; validated to zero error
    against cantilever / simply-supported / fixed-fixed UDL beams, both planes."""
    import numpy as np
    wl = R @ np.array([w_global.x, w_global.y, w_global.z])
    wx, wy, wz = float(wl[0]), float(wl[1]), float(wl[2])
    f = np.zeros(12)
    f[0] += wx * L / 2.0; f[6] += wx * L / 2.0
    f[1] += wy * L / 2.0; f[7] += wy * L / 2.0
    f[5] += wy * L ** 2 / 12.0; f[11] += -wy * L ** 2 / 12.0
    f[2] += wz * L / 2.0; f[8] += wz * L / 2.0
    f[4] += -wz * L ** 2 / 12.0; f[10] += wz * L ** 2 / 12.0
    return f


def _fef_point_local(px, py, pz, L, a):
    """Consistent fixed-end force vector for a POINT load (local components
    px/py/pz) at distance a from node I (b = L-a). Same sign convention as
    _fef_udl: the local-z-bending moment terms (f[4], f[10]) are negated.
    Validated against the fixed-fixed beam with a central point load (end
    moment PL/8, reactions P/2)."""
    import numpy as np
    f = np.zeros(12); b = L - a
    f[0] += px * b / L; f[6] += px * a / L
    f[1] += py * b ** 2 * (L + 2 * a) / L ** 3
    f[7] += py * a ** 2 * (L + 2 * b) / L ** 3
    f[5] += py * a * b ** 2 / L ** 2; f[11] += -py * a ** 2 * b / L ** 2
    f[2] += pz * b ** 2 * (L + 2 * a) / L ** 3
    f[8] += pz * a ** 2 * (L + 2 * b) / L ** 3
    f[4] += -pz * a * b ** 2 / L ** 2; f[10] += pz * a ** 2 * b / L ** 2
    return f


def _fef_tri_local(qx, qy, qz, L):
    """Consistent fixed-end force vector for a TRIANGULAR load that rises from
    0 at node I to intensity q (local per-length components) at node J. Fixed-
    end moments q L^2/30 (light end) and q L^2/20 (heavy end); shear 3qL/20 and
    7qL/20. Same sign convention as _fef_udl."""
    import numpy as np
    f = np.zeros(12)
    f[0] += qx * L / 6.0; f[6] += qx * L / 3.0
    f[1] += qy * 3.0 * L / 20.0; f[7] += qy * 7.0 * L / 20.0
    f[5] += qy * L ** 2 / 30.0; f[11] += -qy * L ** 2 / 20.0
    f[2] += qz * 3.0 * L / 20.0; f[8] += qz * 7.0 * L / 20.0
    f[4] += -qz * L ** 2 / 30.0; f[10] += qz * L ** 2 / 20.0
    return f


def _fef_udl_local(wx, wy, wz, L):
    """Consistent fixed-end force vector for a uniform load given in LOCAL
    components (the local-coordinate form of _fef_udl)."""
    import numpy as np
    f = np.zeros(12)
    f[0] += wx * L / 2.0; f[6] += wx * L / 2.0
    f[1] += wy * L / 2.0; f[7] += wy * L / 2.0
    f[5] += wy * L ** 2 / 12.0; f[11] += -wy * L ** 2 / 12.0
    f[2] += wz * L / 2.0; f[8] += wz * L / 2.0
    f[4] += -wz * L ** 2 / 12.0; f[10] += wz * L ** 2 / 12.0
    return f


def _root(doc):
    """The single top-level 'DynFrame' group that holds every analysis
    sub-group (Supports, Loads, Results, ...), so nothing is scattered loose
    in the document tree."""
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label == ROOT_GROUP:
            return o
    g = doc.addObject("App::DocumentObjectGroup", "DynFrameRoot")
    g.Label = ROOT_GROUP
    return g


def _grp(doc, label):
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label == label:
            return o
    g = doc.addObject("App::DocumentObjectGroup", label.replace(" ", ""))
    g.Label = label
    if label in _SUBGROUPS:          # nest the analysis sub-groups under DynFrame
        try:
            _root(doc).addObject(g)
        except Exception:
            pass
    return g


def _meta(doc):
    o = doc.getObject(META_NAME)
    if o is None:
        o = doc.addObject("App::DocumentObjectGroup", META_NAME)
        o.Label = "Analysis Setup"
        try:
            _root(doc).addObject(o)          # keep setup under the DynFrame root
        except Exception:
            pass
    for p in ("CaseNames", "CaseNatures", "ComboNames", "ComboDefs"):
        if not hasattr(o, p):
            o.addProperty("App::PropertyStringList", p, "DynFrame", p)
    try:
        o.ViewObject.Visibility = False
    except Exception:
        pass
    return o


def _cases(doc):
    m = _meta(doc)
    names = list(getattr(m, "CaseNames", []) or [])
    nats = list(getattr(m, "CaseNatures", []) or [])
    if not names:
        names, nats = ["DL1"], ["Dead"]
        m.CaseNames = names; m.CaseNatures = nats
    return list(zip(names, nats))


def _add_case(doc, name, nature):
    _cases(doc)                      # ensure the default Dead case exists first
    m = _meta(doc)
    names = list(getattr(m, "CaseNames", []) or [])
    nats = list(getattr(m, "CaseNatures", []) or [])
    if name in names:
        nats[names.index(name)] = nature
    else:
        names.append(name); nats.append(nature)
    m.CaseNames = names; m.CaseNatures = nats
    _write_case_sheet(doc)


def _nature_of(doc, case):
    for n, nat in _cases(doc):
        if n == case:
            return nat
    return "Other"


def _write_case_sheet(doc):
    try:
        sh = doc.getObject("LoadCases") or doc.addObject("Spreadsheet::Sheet", "LoadCases")
        sh.Label = "LoadCases"; sh.clearAll()
        sh.set("A1", "LOAD CASES"); sh.set("A2", "Name"); sh.set("B2", "Nature")
        r = 3
        for n, nat in _cases(doc):
            sh.set("A%d" % r, str(n)); sh.set("B%d" % r, str(nat)); r += 1
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: case sheet failed (%s)\n" % e)


def _combos(doc):
    m = _meta(doc)
    return list(zip(list(getattr(m, "ComboNames", []) or []),
                    list(getattr(m, "ComboDefs", []) or [])))


def _set_combos(doc, pairs):
    m = _meta(doc)
    m.ComboNames = [p[0] for p in pairs]; m.ComboDefs = [p[1] for p in pairs]
    try:
        sh = doc.getObject("Combinations") or doc.addObject("Spreadsheet::Sheet", "Combinations")
        sh.Label = "Combinations"; sh.clearAll()
        sh.set("A1", "LOAD COMBINATIONS"); sh.set("A2", "Name"); sh.set("B2", "Definition")
        r = 3
        for nm, df in pairs:
            sh.set("A%d" % r, str(nm)); sh.set("B%d" % r, str(df)); r += 1
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: combo sheet failed (%s)\n" % e)


def _parse_combo(defn):
    out = {}
    for term in str(defn).replace("-", "+-").split("+"):
        term = term.strip()
        if not term:
            continue
        if "*" in term:
            fac, case = term.split("*", 1)
            try:
                f = float(fac.replace(" ", ""))
            except ValueError:
                f, case = 1.0, term
        else:
            f, case = 1.0, term
        case = case.strip()
        if case:
            out[case] = out.get(case, 0.0) + f
    return out


# ── line-model (bar) entity helpers ──────────────────────────────
def is_bar(o):
    return bool(getattr(o, "IsBar", False))


def is_analysis_elem(o):
    return is_bar(o) or is_member(o)


def selected_elems():
    out = []
    for s in FreeCADGui.Selection.getSelectionEx():
        o = s.Object
        if o not in out and is_analysis_elem(o):
            out.append(o)
    return out


def _elem_ends(o):
    if is_bar(o):
        a = getattr(o, "BarStart", None); b = getattr(o, "BarEnd", None)
        if a is not None and b is not None:
            return FreeCAD.Vector(a), FreeCAD.Vector(b)
        vs = o.Shape.Vertexes
        return FreeCAD.Vector(vs[0].Point), FreeCAD.Vector(vs[-1].Point)
    return skeleton(o)


def _elem_section(o):
    return getattr(o, "Section", None) or getattr(o, "MemberProfile", "")


def _elem_material(o):
    return getattr(o, "Material", None) or DEFAULT_MAT


def _analysis_objs(doc):
    """Bars are the analysis model; fall back to solid members if no bars exist
    (so older solid-only documents still analyse)."""
    bars = [o for o in doc.Objects if is_bar(o)]
    if bars:
        return bars, "bar"
    return [o for o in doc.Objects if is_member(o)], "member"


def _model_size(objs):
    bb = None
    for m in objs:
        try:
            b = m.Shape.BoundBox
        except Exception:
            continue
        bb = b if bb is None else bb.united(b)
    if bb is None:
        return 1000.0
    return max(bb.XLength, bb.YLength, bb.ZLength, 1.0)


def _sel_vertices():
    pts = []
    for so in FreeCADGui.Selection.getSelectionEx():
        for sub in getattr(so, "SubObjects", []) or []:
            if getattr(sub, "ShapeType", "") == "Vertex":
                pts.append(FreeCAD.Vector(sub.Point))
    return pts


def _analysis_node_pts(doc):
    """All distinct analysis node points (member/bar centreline ends)."""
    objs, _k = _analysis_objs(doc)
    uniq = []
    for o in objs:
        try:
            s, e = _elem_ends(o)
        except Exception:
            continue
        for p in (s, e):
            if not any((q - p).Length <= 1.0 for q in uniq):
                uniq.append(FreeCAD.Vector(p))
    return uniq


def _snap_to_nodes(pts, doc):
    """Snap each selected point to the nearest analysis node (centreline end).
    This makes supports/loads work when the user clicks a vertex (or face) of a
    SOLID body member - whose corners sit off the centreline - not only a line
    member's end. Points are deduplicated; returns (snapped_pts, n_snapped)."""
    nodes = _analysis_node_pts(doc)
    if not nodes:
        return list(pts), 0
    out = []; nsnap = 0
    for p in pts:
        p = FreeCAD.Vector(p)
        best = min(nodes, key=lambda q: (q - p).Length)
        if (best - p).Length > 1e-6:
            nsnap += 1
        if not any((q - best).Length <= 1.0 for q in out):
            out.append(best)
    return out, nsnap


def _sel_support_points(doc):
    """Node points for a support/load from the current selection: picks selected
    vertices, and the vertices of any selected edge/face, then snaps them to the
    nearest analysis node. So clicking a corner vertex or the base face of a
    solid column lands the support on that column's centreline node."""
    raw = []
    for so in FreeCADGui.Selection.getSelectionEx():
        for sub in getattr(so, "SubObjects", []) or []:
            st = getattr(sub, "ShapeType", "")
            if st == "Vertex":
                raw.append(FreeCAD.Vector(sub.Point))
            elif st in ("Edge", "Face"):
                for v in getattr(sub, "Vertexes", []) or []:
                    raw.append(FreeCAD.Vector(v.Point))
    if not raw:
        return []
    snapped, _n = _snap_to_nodes(raw, doc)
    return snapped


def _pick_case(doc, title):
    cs = [c[0] for c in _cases(doc)]
    item, ok = get_item(title, "Load case:", cs, len(cs) - 1)
    return item if ok else None


def _pick_section(title):
    fams = sorted(profiles.families().keys())
    fam, ok = get_item(title, "Section family:", fams, 0)
    if not ok:
        return None
    sizes = [nm for (nm, _b) in profiles.families()[fam]]
    size, ok = get_item(title, "Section size:", sizes, 0)
    return size if ok else None


def _make_bar(doc, p1, p2, section, material, grp):
    o = doc.addObject("Part::Feature", "Bar")
    o.Shape = Part.makeLine(FreeCAD.Vector(p1), FreeCAD.Vector(p2))
    o.Label = "Bar %s" % section
    _set(o, "App::PropertyBool", "IsBar", True)
    _set(o, "App::PropertyString", "Section", section)
    _set(o, "App::PropertyString", "Material", material)
    _set(o, "App::PropertyVector", "BarStart", FreeCAD.Vector(p1))
    _set(o, "App::PropertyVector", "BarEnd", FreeCAD.Vector(p2))
    try:
        o.ViewObject.LineWidth = 3
        o.ViewObject.LineColor = (0.85, 0.90, 1.0)   # light, so it reads on dark bg
        o.ViewObject.PointSize = 6
        o.ViewObject.PointColor = (1.0, 0.9, 0.2)
    except Exception:
        pass
    if grp is not None:
        grp.addObject(o)
    return o


def _cell(sh, addr):
    try:
        return sh.get(addr)
    except Exception:
        return None


class AddBars:
    def GetResources(self):
        return {"Pixmap": _icon("bar"), "MenuText": "Add Bars (from lines)",
                "ToolTip": "Select straight lines (sketch / Draft wire / any edge), "
                           "pick a section and material, and create analysis bars "
                           "(line members). This is the Robot-style line model.",
                "Accel": "A, A"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        edges = collect_edges()
        if not edges:
            info("Select one or more straight lines first (sketch lines, a Draft "
                 "wire, or model edges). Each line becomes a bar.")
            return
        section = _pick_section("Add Bars")
        if section is None:
            return
        mat, ok = get_item("Add Bars", "Material:", list(MATERIALS.keys()), 0)
        if not ok:
            return
        doc.openTransaction("DynFrame: add bars")
        grp = _grp(doc, STR_GROUP)
        n = 0
        for (p1, p2, _src, _idx) in edges:
            _make_bar(doc, p1, p2, section, mat, grp)
            n += 1
        doc.commitTransaction()
        doc.recompute()
        info("Created %d bar(s): %s, %s." % (n, section, mat))


class BarsFromMembers:
    def GetResources(self):
        return {"Pixmap": _icon("convert"), "MenuText": "Bars from Members",
                "ToolTip": "Convert the solid frame members you already built into "
                           "analysis bars (line model), keeping each member's section.",
                "Accel": "A, F"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        sel = [m for m in selected_members() if is_member(m)]
        members = sel or [o for o in doc.Objects if is_member(o)]
        if not members:
            info("No solid frame members found to convert.")
            return
        mat, ok = get_item("Bars from Members", "Material for all bars:",
                           list(MATERIALS.keys()), 0)
        if not ok:
            return
        doc.openTransaction("DynFrame: bars from members")
        grp = _grp(doc, STR_GROUP)
        n = 0
        for m in members:
            s, e = skeleton(m)
            sec = getattr(m, "MemberProfile", "") or "IPE 200"
            _make_bar(doc, s, e, sec, mat, grp)
            n += 1
        doc.commitTransaction()
        doc.recompute()
        info("Created %d bar(s) from members. The solid members are kept (hide "
             "them if you want a clean line model); analysis now runs on the bars."
             % n)


class EditTables:
    def GetResources(self):
        return {"Pixmap": _icon("table"), "MenuText": "Node/Bar Tables",
                "ToolTip": "Create editable 'Nodes' and 'Bars' spreadsheets (Robot-"
                           "style coordinate tables). Fill them in, then 'Build from "
                           "Tables'.", "Accel": "A, T"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        if doc.getObject("Nodes") or doc.getObject("Bars"):
            keep, ok = get_item("Node/Bar Tables",
                                "Tables already exist. Overwrite with blank "
                                "templates?", ["Keep existing", "Overwrite"], 0)
            if not ok or keep == "Keep existing":
                info("Edit the existing 'Nodes' and 'Bars' spreadsheets, then run "
                     "Build from Tables.")
                return
        doc.openTransaction("DynFrame: node/bar tables")
        nd = doc.getObject("Nodes") or doc.addObject("Spreadsheet::Sheet", "Nodes")
        nd.Label = "Nodes"; nd.clearAll()
        nd.set("A1", "NODES  (fill rows from 3; units mm)")
        for c, h in zip("ABCD", ["Node", "X", "Y", "Z"]):
            nd.set("%s2" % c, h)
        for i, (x, y, z) in enumerate([(0, 0, 0), (0, 0, 3000), (4000, 0, 3000),
                                       (4000, 0, 0)]):
            nd.set("A%d" % (i + 3), str(i + 1)); nd.set("B%d" % (i + 3), str(x))
            nd.set("C%d" % (i + 3), str(y)); nd.set("D%d" % (i + 3), str(z))
        br = doc.getObject("Bars") or doc.addObject("Spreadsheet::Sheet", "Bars")
        br.Label = "Bars"; br.clearAll()
        br.set("A1", "BARS  (NodeI/NodeJ are node numbers above)")
        for c, h in zip("ABCDE", ["Bar", "NodeI", "NodeJ", "Section", "Material"]):
            br.set("%s2" % c, h)
        ex = [(1, 1, 2, "IPE 200", "Steel S235"), (2, 2, 3, "IPE 200", "Steel S235"),
              (3, 4, 3, "IPE 200", "Steel S235")]
        for i, (b, ni, nj, sec, mat) in enumerate(ex):
            r = i + 3
            br.set("A%d" % r, str(b)); br.set("B%d" % r, str(ni))
            br.set("C%d" % r, str(nj)); br.set("D%d" % r, sec); br.set("E%d" % r, mat)
        doc.commitTransaction()
        doc.recompute()
        info("Created 'Nodes' and 'Bars' spreadsheets with an example portal.\n\n"
             "Edit them (node coordinates; bar NodeI/NodeJ/Section/Material), then "
             "run 'Build from Tables'.\n\nSections must be names from the library "
             "(e.g. IPE 200, HEB 160, SHS 80x80x5). Materials: %s."
             % ", ".join(MATERIALS.keys()))


class BuildFromTables:
    def GetResources(self):
        return {"Pixmap": _icon("buildtable"), "MenuText": "Build from Tables",
                "ToolTip": "Read the 'Nodes' and 'Bars' spreadsheets and create the "
                           "bar line model from them.", "Accel": "A, G"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        nd = doc.getObject("Nodes"); br = doc.getObject("Bars")
        if nd is None or br is None:
            info("No 'Nodes'/'Bars' tables found. Run 'Node/Bar Tables' first.")
            return
        coords = {}
        r = 3
        while True:
            nv = _cell(nd, "A%d" % r)
            if nv in (None, ""):
                break
            try:
                key = str(int(float(nv)))
                coords[key] = FreeCAD.Vector(float(_cell(nd, "B%d" % r) or 0),
                                             float(_cell(nd, "C%d" % r) or 0),
                                             float(_cell(nd, "D%d" % r) or 0))
            except Exception:
                pass
            r += 1
        if not coords:
            info("No node rows found in the 'Nodes' table.")
            return
        doc.openTransaction("DynFrame: build from tables")
        grp = _grp(doc, STR_GROUP)
        made = bad = 0
        r = 3
        while True:
            bv = _cell(br, "A%d" % r)
            if bv in (None, ""):
                break
            try:
                ni = str(int(float(_cell(br, "B%d" % r))))
                nj = str(int(float(_cell(br, "C%d" % r))))
                sec = str(_cell(br, "D%d" % r) or "IPE 200").strip()
                mat = str(_cell(br, "E%d" % r) or DEFAULT_MAT).strip()
                if ni in coords and nj in coords and profiles.builder_for(sec):
                    _make_bar(doc, coords[ni], coords[nj], sec, mat, grp)
                    made += 1
                else:
                    bad += 1
            except Exception:
                bad += 1
            r += 1
        doc.commitTransaction()
        doc.recompute()
        info("Built %d bar(s) from the tables%s." %
             (made, "" if bad == 0 else " (%d row(s) skipped - check node numbers "
              "and section names)" % bad))


class NewLoadCase:
    def GetResources(self):
        return {"Pixmap": _icon("case"), "MenuText": "New Load Case",
                "ToolTip": "Create a named load case with a nature (Dead / Live / "
                           "Wind / Snow). Loads belong to a case; combinations are "
                           "built from the cases.", "Accel": "A, N"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        nature, ok = get_item("New Load Case", "Nature:", NATURES, 0)
        if not ok:
            return
        default = {"Dead": "DL", "Live": "LL", "Wind": "WL", "Snow": "SL",
                   "Other": "CASE"}[nature]
        n = sum(1 for _, nat in _cases(doc) if nat == nature) + 1
        name, ok = get_text("New Load Case", "Case name:", "%s%d" % (default, n))
        if not ok or not name.strip():
            return
        _add_case(doc, name.strip(), nature)
        doc.recompute()
        info("Load case '%s' (%s) created." % (name.strip(), nature))


# ── load/support creation (shared by the commands and the manager panel) ──
def _apply_support(doc, type_label, pts):
    restr = SUPPORT_TYPES.get(type_label, "111111")
    grp = _grp(doc, SUP_GROUP)
    objs, _k = _analysis_objs(doc)
    sz = _model_size(objs) * 0.02 + 20.0
    for p in pts:
        p = FreeCAD.Vector(p)
        cone = Part.makeCone(sz, 0.0, sz * 2.0,
                             FreeCAD.Vector(p.x, p.y, p.z - sz * 2.0),
                             FreeCAD.Vector(0, 0, 1))
        o = doc.addObject("Part::Feature", "Support")
        o.Shape = cone
        o.Label = "Support %s" % type_label.split(" (")[0]
        _set(o, "App::PropertyString", "Restrain", restr)
        _set(o, "App::PropertyVector", "AtNode", p)
        try:
            o.ViewObject.ShapeColor = (0.1, 0.4, 1.0)
        except Exception:
            pass
        grp.addObject(o)
    return len(pts)


def _apply_spring_support(doc, springs, pts):
    """Elastic (spring) support: adds stiffness springs to the node DOFs
    instead of rigidly fixing them (foundation / soil modelling). `springs` is
    a list of 6 stiffnesses [Kx,Ky,Kz (N/mm), Krx,Kry,Krz (N.mm/rad)]."""
    import json
    grp = _grp(doc, SUP_GROUP)
    objs, _k = _analysis_objs(doc)
    sz = _model_size(objs) * 0.02 + 20.0
    for p in pts:
        p = FreeCAD.Vector(p)
        # little coil-like glyph: a cone plus a few rings would be heavy; use a
        # cone in a distinct colour to mark an elastic support
        cone = Part.makeCone(sz, sz * 0.4, sz * 2.0,
                             FreeCAD.Vector(p.x, p.y, p.z - sz * 2.0),
                             FreeCAD.Vector(0, 0, 1))
        o = doc.addObject("Part::Feature", "SpringSupport")
        o.Shape = cone
        o.Label = "Elastic support (spring)"
        _set(o, "App::PropertyString", "Restrain", "000000")
        _set(o, "App::PropertyString", "Springs", json.dumps([float(s) for s in springs]))
        _set(o, "App::PropertyVector", "AtNode", p)
        try:
            o.ViewObject.ShapeColor = (0.1, 0.8, 0.9)
        except Exception:
            pass
        grp.addObject(o)
    return len(pts)


def _apply_nodal(doc, case, fvec, pts, mvec=None):
    grp = _grp(doc, LOAD_GROUP)
    objs, _k = _analysis_objs(doc)
    ln = _model_size(objs) * 0.15 + 100.0
    fvec = FreeCAD.Vector(fvec)
    mvec = FreeCAD.Vector(mvec) if mvec is not None else FreeCAD.Vector(0, 0, 0)
    dirn = unit(fvec) if fvec.Length > 1e-9 else FreeCAD.Vector(0, 0, -1)
    for p in pts:
        p = FreeCAD.Vector(p)
        shapes = []
        if fvec.Length > 1e-9:
            tail = p - vscale(dirn, ln)
            shapes.append(Part.makeLine(FreeCAD.Vector(tail), FreeCAD.Vector(p)))
            shapes.append(Part.makeCone(ln * 0.12, 0.0, ln * 0.25,
                                        p - vscale(dirn, ln * 0.25), dirn))
        if mvec.Length > 1e-9:                 # moment: small double ring marker
            md = unit(mvec)
            shapes.append(Part.makeCircle(ln * 0.22, p, md))
            shapes.append(Part.makeCircle(ln * 0.17, p, md))
        if not shapes:
            continue
        o = doc.addObject("Part::Feature", "NodalLoad")
        o.Shape = Part.makeCompound(shapes)
        o.Label = "%s: F(%.0f,%.0f,%.0f) M(%.0f,%.0f,%.0f)" % (
            case, fvec.x, fvec.y, fvec.z, mvec.x, mvec.y, mvec.z)
        _set(o, "App::PropertyString", "LoadType", "Nodal")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyVector", "LoadVec", fvec)
        _set(o, "App::PropertyVector", "LoadMom", mvec)
        _set(o, "App::PropertyVector", "AtNode", p)
        try:
            o.ViewObject.ShapeColor = (1.0, 0.3, 0.0); o.ViewObject.LineWidth = 3
        except Exception:
            pass
        grp.addObject(o)
    return len(pts)


def _apply_line(doc, case, wvec, elems):
    grp = _grp(doc, LOAD_GROUP)
    msize = _model_size(elems)
    wvec = FreeCAD.Vector(wvec)
    dirn = unit(wvec)
    ln = msize * 0.08 + 50.0
    for m in elems:
        s, e = _elem_ends(m)
        arrows = []
        for t in (0.15, 0.35, 0.55, 0.75, 0.95):
            p = s + vscale(e - s, t)
            tail = p - vscale(dirn, ln)
            arrows.append(Part.makeLine(FreeCAD.Vector(tail), FreeCAD.Vector(p)))
            arrows.append(Part.makeCone(ln * 0.14, 0.0, ln * 0.3,
                                        p - vscale(dirn, ln * 0.3), dirn))
        o = doc.addObject("Part::Feature", "BarLoad")
        o.Shape = Part.makeCompound(arrows)
        o.Label = "%s: %.3g N/mm on %s" % (case, wvec.z, m.Label)
        _set(o, "App::PropertyString", "LoadType", "Member")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyString", "OnMember", m.Name)
        _set(o, "App::PropertyVector", "LoadVec", wvec)
        try:
            o.ViewObject.ShapeColor = (1.0, 0.5, 0.0); o.ViewObject.LineWidth = 2
        except Exception:
            pass
        grp.addObject(o)
    return len(elems)


def _apply_point(doc, case, Pvec, pos, elems):
    """Concentrated (point) load Pvec (global N) at fraction `pos` (0..1 from
    the start node) on each selected bar."""
    grp = _grp(doc, LOAD_GROUP)
    msize = _model_size(elems)
    Pvec = FreeCAD.Vector(Pvec); dirn = unit(Pvec)
    ln = msize * 0.12 + 70.0
    pos = min(1.0, max(0.0, float(pos)))
    for m in elems:
        s, e = _elem_ends(m)
        p = s + vscale(e - s, pos)
        tail = p - vscale(dirn, ln)
        arrows = [Part.makeLine(FreeCAD.Vector(tail), FreeCAD.Vector(p)),
                  Part.makeCone(ln * 0.18, 0.0, ln * 0.35,
                                p - vscale(dirn, ln * 0.35), dirn)]
        o = doc.addObject("Part::Feature", "BarPointLoad")
        o.Shape = Part.makeCompound(arrows)
        o.Label = "%s: %.3g N point @%.0f%% on %s" % (case, Pvec.z, pos * 100, m.Label)
        _set(o, "App::PropertyString", "LoadType", "MemberPoint")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyString", "OnMember", m.Name)
        _set(o, "App::PropertyVector", "LoadVec", Pvec)
        _set(o, "App::PropertyFloat", "LoadPos", pos)
        try:
            o.ViewObject.ShapeColor = (1.0, 0.3, 0.0); o.ViewObject.LineWidth = 3
        except Exception:
            pass
        grp.addObject(o)
    return len(elems)


def _apply_trap(doc, case, w1vec, w2vec, elems):
    """Trapezoidal (linearly varying) distributed load from w1 at the start
    node to w2 at the end node (global N/mm) on each selected bar."""
    grp = _grp(doc, LOAD_GROUP)
    msize = _model_size(elems)
    w1vec = FreeCAD.Vector(w1vec); w2vec = FreeCAD.Vector(w2vec)
    wmax = max(abs(w1vec.z), abs(w2vec.z), 1e-9)
    dirn = unit(w2vec if w2vec.Length > w1vec.Length else w1vec)
    lmax = msize * 0.10 + 60.0
    for m in elems:
        s, e = _elem_ends(m)
        arrows = []
        for t in (0.05, 0.225, 0.4, 0.575, 0.75, 0.95):
            wt = abs(w1vec.z + (w2vec.z - w1vec.z) * t)
            ln = lmax * (0.2 + 0.8 * wt / wmax)
            p = s + vscale(e - s, t)
            tail = p - vscale(dirn, ln)
            arrows.append(Part.makeLine(FreeCAD.Vector(tail), FreeCAD.Vector(p)))
            arrows.append(Part.makeCone(ln * 0.13, 0.0, ln * 0.28,
                                        p - vscale(dirn, ln * 0.28), dirn))
        o = doc.addObject("Part::Feature", "BarTrapLoad")
        o.Shape = Part.makeCompound(arrows)
        o.Label = "%s: %.3g..%.3g N/mm on %s" % (case, w1vec.z, w2vec.z, m.Label)
        _set(o, "App::PropertyString", "LoadType", "MemberTrap")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyString", "OnMember", m.Name)
        _set(o, "App::PropertyVector", "LoadVec", w1vec)
        _set(o, "App::PropertyVector", "LoadVec2", w2vec)
        try:
            o.ViewObject.ShapeColor = (1.0, 0.45, 0.0); o.ViewObject.LineWidth = 2
        except Exception:
            pass
        grp.addObject(o)
    return len(elems)


# EN 1991-1-4 terrain categories: name -> (roughness length z0 [m], zmin [m])
WIND_TERRAIN = {
    "0 - Sea / coastal": (0.003, 1.0),
    "I - Lakes / flat open": (0.01, 1.0),
    "II - Open, low vegetation": (0.05, 2.0),
    "III - Suburban / forest": (0.3, 5.0),
    "IV - Urban (>=15 m)": (1.0, 10.0),
}


def _wind_qp(z_m, vb0, z0, zmin, c0=1.0, rho=1.25, cdir=1.0, cseason=1.0):
    """Peak velocity pressure q_p(z) [Pa] at height z [m] per EN 1991-1-4:
    basic velocity v_b = cdir*cseason*vb0, roughness c_r(z) = k_r ln(z/z0) with
    k_r = 0.19 (z0/0.05)^0.07, mean wind v_m = c_r c_o v_b, turbulence
    I_v = k_I/(c_o ln(z/z0)) (k_I=1), and q_p = (1 + 7 I_v) * 0.5 rho v_m^2.
    Returns (q_p [Pa], v_m [m/s], c_e = q_p/q_b)."""
    import math
    z0II = 0.05
    vb = cdir * cseason * vb0
    qb = 0.5 * rho * vb * vb
    kr = 0.19 * (z0 / z0II) ** 0.07
    ze = max(float(z_m), zmin)
    cr = kr * math.log(ze / z0)
    vm = cr * c0 * vb
    iv = 1.0 / (c0 * math.log(ze / z0))
    qp = (1.0 + 7.0 * iv) * 0.5 * rho * vm * vm
    ce = (qp / qb) if qb > 1e-12 else 0.0
    return qp, vm, ce


def _sway_phi(h_m, m):
    """EN 1993-1-1 (5.3.2) global initial sway imperfection
    phi = phi_0 * alpha_h * alpha_m, with phi_0 = 1/200,
    alpha_h = 2/sqrt(h) clamped to [2/3, 1] (h = frame height in m), and
    alpha_m = sqrt(0.5*(1 + 1/m)) (m = number of columns in the row).
    Returns (phi, alpha_h, alpha_m)."""
    import math
    phi0 = 1.0 / 200.0
    ah = (2.0 / math.sqrt(h_m)) if h_m > 1e-9 else 1.0
    ah = max(2.0 / 3.0, min(1.0, ah))
    mm = max(1, int(m))
    am = math.sqrt(0.5 * (1.0 + 1.0 / mm))
    return phi0 * ah * am, ah, am


def _apply_wind(doc, case, items, dirlabel):
    """Create the wind member loads: `items` is a list of (member, w1vec, w2vec)
    where w1/w2 are the horizontal line loads (N/mm) at the member start/end
    node heights. Stored as MemberTrap loads (the solver's trapezoidal path),
    with magnitude-scaled arrows so a horizontal wind reads correctly."""
    grp = _grp(doc, LOAD_GROUP)
    msize = _model_size([m for (m, _a, _b) in items]) if items else 1000.0
    lmax = msize * 0.10 + 60.0
    n = 0
    for (m, w1vec, w2vec) in items:
        w1vec = FreeCAD.Vector(w1vec); w2vec = FreeCAD.Vector(w2vec)
        wmax = max(w1vec.Length, w2vec.Length, 1e-9)
        dirn = unit(w2vec if w2vec.Length >= w1vec.Length else w1vec)
        s, e = _elem_ends(m)
        arrows = []
        try:
            for t in (0.05, 0.225, 0.4, 0.575, 0.75, 0.95):
                wt = (w1vec + vscale(w2vec - w1vec, t)).Length
                ln = lmax * (0.2 + 0.8 * wt / wmax)
                p = s + vscale(e - s, t)
                tail = p - vscale(dirn, ln)
                arrows.append(Part.makeLine(FreeCAD.Vector(tail), FreeCAD.Vector(p)))
                arrows.append(Part.makeCone(ln * 0.13, 0.0, ln * 0.28,
                                            p - vscale(dirn, ln * 0.28), dirn))
            shp = Part.makeCompound(arrows)
        except Exception:
            shp = None
        o = doc.addObject("Part::Feature", "WindLoad")
        if shp is not None:
            o.Shape = shp
        o.Label = "%s: wind %s %.3g..%.3g N/mm on %s" % (
            case, dirlabel, w1vec.Length, w2vec.Length, m.Label)
        _set(o, "App::PropertyString", "LoadType", "MemberTrap")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyString", "OnMember", m.Name)
        _set(o, "App::PropertyVector", "LoadVec", w1vec)
        _set(o, "App::PropertyVector", "LoadVec2", w2vec)
        try:
            o.ViewObject.ShapeColor = (0.0, 0.6, 0.85); o.ViewObject.LineWidth = 2
        except Exception:
            pass
        grp.addObject(o); n += 1
    return n


def _apply_thermal(doc, case, dT, elems):
    """Uniform temperature change dT (deg C) on each selected bar."""
    grp = _grp(doc, LOAD_GROUP)
    for m in elems:
        s, e = _elem_ends(m)
        o = doc.addObject("Part::Feature", "ThermalLoad")
        try:
            o.Shape = Part.makeLine(FreeCAD.Vector(s), FreeCAD.Vector(e))
        except Exception:
            pass
        o.Label = "%s: dT=%.3g C on %s" % (case, dT, m.Label)
        _set(o, "App::PropertyString", "LoadType", "Thermal")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyString", "OnMember", m.Name)
        _set(o, "App::PropertyFloat", "DeltaT", float(dT))
        try:
            o.ViewObject.LineColor = (1.0, 0.25, 0.0); o.ViewObject.LineWidth = 5
        except Exception:
            pass
        grp.addObject(o)
    return len(elems)


def _apply_settlement(doc, case, dvec, mvec, pts):
    """Imposed support displacement (settlement): prescribes a known movement
    at the selected support node(s) for a load case."""
    grp = _grp(doc, LOAD_GROUP)
    objs, _k = _analysis_objs(doc)
    sz = _model_size(objs) * 0.04 + 40.0
    dvec = FreeCAD.Vector(dvec); mvec = FreeCAD.Vector(mvec)
    for p in pts:
        p = FreeCAD.Vector(p)
        o = doc.addObject("Part::Feature", "Settlement")
        try:
            o.Shape = Part.makeLine(FreeCAD.Vector(p),
                                    FreeCAD.Vector(p.x, p.y, p.z - sz))
        except Exception:
            pass
        o.Label = "%s: settlement (%.3g,%.3g,%.3g) mm" % (case, dvec.x, dvec.y, dvec.z)
        _set(o, "App::PropertyString", "LoadType", "Settlement")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyVector", "LoadVec", dvec)
        _set(o, "App::PropertyVector", "LoadMom", mvec)
        _set(o, "App::PropertyVector", "AtNode", p)
        try:
            o.ViewObject.LineColor = (0.6, 0.2, 0.9); o.ViewObject.LineWidth = 4
        except Exception:
            pass
        grp.addObject(o)
    return len(pts)


class DefineSupport:
    def GetResources(self):
        return {"Pixmap": _icon("support"), "MenuText": "Define Support",
                "ToolTip": "Select joint vertices (bar node points), then apply a "
                           "support (Fixed / Pinned / Roller). Blue cone. Supports "
                           "are global (shared by every case).", "Accel": "A, S"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        pts = _sel_support_points(doc)
        if not pts:
            info("Select one or more joint vertices (or the end/base face of a "
                 "solid member), then run Define Support. The pick snaps to the "
                 "nearest structural node, so it works on solid bodies too.")
            return
        opts = list(SUPPORT_TYPES.keys()) + ["Elastic (spring)…"]
        t, ok = get_item("Define Support", "Support type:", opts, 0)
        if not ok:
            return
        if t.startswith("Elastic"):
            vals = form_dialog("Elastic (spring) support", [
                {"key": "_i", "kind": "info", "default":
                 "Spring stiffnesses per node DOF (0 = free). Translational in "
                 "N/mm, rotational in N.mm/rad. E.g. a soil modulus x tributary "
                 "area for Kz."},
                {"key": "kx", "label": "Kx (N/mm)", "kind": "float", "default": 0.0},
                {"key": "ky", "label": "Ky (N/mm)", "kind": "float", "default": 0.0},
                {"key": "kz", "label": "Kz (N/mm)", "kind": "float", "default": 1000.0},
                {"key": "krx", "label": "Krx (N.mm/rad)", "kind": "float", "default": 0.0},
                {"key": "kry", "label": "Kry (N.mm/rad)", "kind": "float", "default": 0.0},
                {"key": "krz", "label": "Krz (N.mm/rad)", "kind": "float", "default": 0.0}])
            if not vals:
                return
            springs = [vals["kx"], vals["ky"], vals["kz"],
                       vals["krx"], vals["kry"], vals["krz"]]
            if max(abs(s) for s in springs) < 1e-12:
                info("All spring stiffnesses are zero - nothing applied."); return
            doc.openTransaction("DynFrame: elastic support")
            _apply_spring_support(doc, springs, pts)
            doc.commitTransaction(); doc.recompute()
            info("Elastic (spring) support applied to %d node(s)." % len(pts))
            return
        doc.openTransaction("DynFrame: support")
        _apply_support(doc, t, pts)
        doc.commitTransaction()
        doc.recompute()
        info("Support applied to %d node(s): %s." % (len(pts), t))


class AddNodalLoad:
    def GetResources(self):
        return {"Pixmap": _icon("load"), "MenuText": "Add Nodal Load",
                "ToolTip": "Select joint vertices, then enter case + point force "
                           "(Fx, Fy, Fz in N) in one dialog. Orange arrow.",
                "Accel": "A, L"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        pts = _sel_support_points(doc)
        if not pts:
            info("Select one or more joint vertices (or a solid member's end "
                 "face), then add a nodal load. The pick snaps to the nearest "
                 "structural node.")
            return
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Add Nodal Load (%d node(s))" % len(pts), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "fx", "label": "Fx (N)", "kind": "float", "default": 0.0},
            {"key": "fy", "label": "Fy (N)", "kind": "float", "default": 0.0},
            {"key": "fz", "label": "Fz (N, + up / - down)", "kind": "float", "default": -1000.0},
            {"key": "mx", "label": "Mx (N.mm)", "kind": "float", "default": 0.0},
            {"key": "my", "label": "My (N.mm)", "kind": "float", "default": 0.0},
            {"key": "mz", "label": "Mz (N.mm)", "kind": "float", "default": 0.0},
        ])
        if not vals:
            return
        fvec = FreeCAD.Vector(vals["fx"], vals["fy"], vals["fz"])
        mvec = FreeCAD.Vector(vals["mx"], vals["my"], vals["mz"])
        if fvec.Length < 1e-9 and mvec.Length < 1e-9:
            warn("Load is zero - nothing added.")
            return
        doc.openTransaction("DynFrame: nodal load")
        _apply_nodal(doc, vals["case"], fvec, pts, mvec)
        doc.commitTransaction()
        doc.recompute()
        info("Nodal load added to case '%s' on %d node(s)." % (vals["case"], len(pts)))


class AddSettlement:
    def GetResources(self):
        return {"Pixmap": _icon("settle"), "MenuText": "Support Settlement",
                "ToolTip": "Select supported node vertices, then prescribe an imposed "
                           "support movement (settlement) for a load case - e.g. a "
                           "foundation that sinks. The analysis solves for the forces "
                           "the settlement induces.", "Accel": "A, G"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        pts = _sel_support_points(doc)
        if not pts:
            info("Select one or more supported node vertices (or a solid "
                 "member's end face), then add a settlement.")
            return
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Support Settlement (%d node(s))" % len(pts), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "_i", "kind": "info", "default":
             "Imposed support movement. Translations in mm (-Z = sinks down), "
             "rotations in rad. Each prescribed DOF is held at this value and the "
             "analysis finds the forces it induces."},
            {"key": "dx", "label": "dx (mm)", "kind": "float", "default": 0.0},
            {"key": "dy", "label": "dy (mm)", "kind": "float", "default": 0.0},
            {"key": "dz", "label": "dz (mm)", "kind": "float", "default": -10.0},
            {"key": "rx", "label": "rx (rad)", "kind": "float", "default": 0.0},
            {"key": "ry", "label": "ry (rad)", "kind": "float", "default": 0.0},
            {"key": "rz", "label": "rz (rad)", "kind": "float", "default": 0.0},
        ])
        if not vals:
            return
        dvec = FreeCAD.Vector(vals["dx"], vals["dy"], vals["dz"])
        mvec = FreeCAD.Vector(vals["rx"], vals["ry"], vals["rz"])
        if dvec.Length < 1e-12 and mvec.Length < 1e-12:
            info("Settlement is zero - nothing added."); return
        doc.openTransaction("DynFrame: settlement")
        _apply_settlement(doc, vals["case"], dvec, mvec, pts)
        doc.commitTransaction(); doc.recompute()
        info("Support settlement added to case '%s' on %d node(s).\n\nNote: the "
             "settled node must also have a support restraining those directions "
             "(the settlement prescribes the movement of that support)."
             % (vals["case"], len(pts)))


class AddMemberLoad:
    def GetResources(self):
        return {"Pixmap": _icon("barload"), "MenuText": "Add Bar Load",
                "ToolTip": "Select bars (lines) or members, then add a load along "
                           "global Z: uniform (UDL), a concentrated point load at a "
                           "position, or a trapezoidal (linearly varying) load - all "
                           "in one dialog.", "Accel": "A, M"}

    def IsActive(self):
        return bool(selected_elems())

    def Activated(self):
        elems = selected_elems()
        if not elems:
            info("Select one or more bars (lines) or members, then add a load.")
            return
        doc = FreeCAD.ActiveDocument
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Add Bar Load (%d bar(s))" % len(elems), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "kind", "label": "Load type", "kind": "combo",
             "options": ["Uniform (UDL)", "Point load", "Trapezoidal (varying)",
                         "Thermal (temperature)"],
             "default": "Uniform (UDL)"},
            {"key": "_i", "kind": "info", "default":
             "Force values are along global Z (+ up / - down). Fill the rows for the "
             "chosen type: UDL -> w; Point -> P and position; Trapezoidal -> w1, w2; "
             "Thermal -> dT (uniform temperature change, deg C)."},
            {"key": "w", "label": "UDL  w (N/mm)", "kind": "float", "default": -5.0},
            {"key": "P", "label": "Point  P (N)", "kind": "float", "default": -1000.0},
            {"key": "pos", "label": "Point position (0..1 from start)",
             "kind": "float", "default": 0.5},
            {"key": "w1", "label": "Trapezoid  w1 at start (N/mm)", "kind": "float", "default": 0.0},
            {"key": "w2", "label": "Trapezoid  w2 at end (N/mm)", "kind": "float", "default": -5.0},
            {"key": "dT", "label": "Thermal  dT (deg C)", "kind": "float", "default": 30.0},
        ])
        if not vals:
            return
        kind = vals["kind"]
        doc.openTransaction("DynFrame: bar load")
        if kind.startswith("Thermal"):
            if abs(vals["dT"]) < 1e-9:
                return
            _apply_thermal(doc, vals["case"], vals["dT"], elems)
            msg = ("Temperature change dT=%.3g C added to case '%s' on %d bar(s)."
                   % (vals["dT"], vals["case"], len(elems)))
        elif kind.startswith("Point"):
            if abs(vals["P"]) < 1e-9:
                return
            _apply_point(doc, vals["case"], FreeCAD.Vector(0, 0, vals["P"]),
                         vals["pos"], elems)
            msg = ("Point load %.3g N (Z) at %.0f%% added to case '%s' on %d bar(s)."
                   % (vals["P"], min(1.0, max(0.0, vals["pos"])) * 100, vals["case"], len(elems)))
        elif kind.startswith("Trapez"):
            if abs(vals["w1"]) < 1e-12 and abs(vals["w2"]) < 1e-12:
                return
            _apply_trap(doc, vals["case"], FreeCAD.Vector(0, 0, vals["w1"]),
                        FreeCAD.Vector(0, 0, vals["w2"]), elems)
            msg = ("Trapezoidal load %.3g..%.3g N/mm (Z) added to case '%s' on "
                   "%d bar(s)." % (vals["w1"], vals["w2"], vals["case"], len(elems)))
        else:
            if abs(vals["w"]) < 1e-12:
                return
            _apply_line(doc, vals["case"], FreeCAD.Vector(0, 0, vals["w"]), elems)
            msg = ("Distributed load %.3g N/mm (Z) added to case '%s' on %d bar(s)."
                   % (vals["w"], vals["case"], len(elems)))
        doc.commitTransaction()
        doc.recompute()
        info(msg)


class AddWindLoad:
    _DIRS = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
             "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}

    def GetResources(self):
        return {"Pixmap": _icon("wind"), "MenuText": "Add Wind Load (EC1)",
                "ToolTip": "EN 1991-1-4 wind load on the selected members: the peak "
                           "velocity pressure q_p(z) is computed up the height and "
                           "applied as a horizontal, height-varying line load "
                           "(pressure x tributary width x pressure coefficient).",
                "Accel": "A, W"}

    def IsActive(self):
        return bool(selected_elems())

    def Activated(self):
        elems = [m for m in selected_elems() if is_bar(m)]
        if not elems:
            info("Select the members the wind acts on (e.g. the windward face "
                 "columns/beams), then add a wind load. The tributary width is the "
                 "width of cladding each selected line carries.")
            return
        doc = FreeCAD.ActiveDocument
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Add Wind Load (EN 1991-1-4) - %d member(s)" % len(elems), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "_i", "kind": "info", "default":
             "Peak velocity pressure q_p(z) is built up the height from the basic "
             "wind velocity and terrain, then applied horizontally as q_p(z) x c_p "
             "x tributary width - a line load that grows with height (stored as a "
             "trapezoid per member). Put the wind onto the windward frame line and "
             "give the cladding width it carries. Make a 'Wind' load case first if "
             "you want it separate."},
            {"key": "dir", "label": "Wind direction", "kind": "combo",
             "options": list(self._DIRS.keys()), "default": "+X"},
            {"key": "vb0", "label": "Basic wind velocity vb,0 (m/s)",
             "kind": "float", "default": 24.0},
            {"key": "terr", "label": "Terrain category", "kind": "combo",
             "options": list(WIND_TERRAIN.keys()), "default": "II - Open, low vegetation"},
            {"key": "cp", "label": "Pressure/force coeff c_p (net)",
             "kind": "float", "default": 1.2},
            {"key": "btrib", "label": "Tributary width (mm)", "kind": "float",
             "default": 5000.0},
            {"key": "c0", "label": "Orography factor c_o", "kind": "float", "default": 1.0},
            {"key": "rho", "label": "Air density (kg/m3)", "kind": "float", "default": 1.25},
            {"key": "cdir", "label": "Directional factor c_dir", "kind": "float", "default": 1.0},
            {"key": "cseas", "label": "Season factor c_season", "kind": "float", "default": 1.0},
        ])
        if not vals:
            return
        d = self._DIRS.get(vals["dir"], (1.0, 0.0, 0.0))
        dirv = FreeCAD.Vector(*d)
        z0, zmin = WIND_TERRAIN.get(vals["terr"], (0.05, 2.0))
        vb0 = float(vals["vb0"]); cp = float(vals["cp"]); btrib = float(vals["btrib"])
        c0 = float(vals["c0"]); rho = float(vals["rho"])
        cdir = float(vals["cdir"]); cseas = float(vals["cseas"])
        # ground datum = lowest node of the whole analysis model
        objs, _k = _analysis_objs(doc)
        zg = None
        for o in objs:
            s, e = _elem_ends(o)
            for p in (s, e):
                zg = p.z if zg is None else min(zg, p.z)
        if zg is None:
            zg = 0.0

        def wline(zmm):           # horizontal line load (N/mm) at height z [mm]
            qp, _vm, _ce = _wind_qp(max(0.0, (zmm - zg)) / 1000.0, vb0, z0, zmin,
                                    c0, rho, cdir, cseas)
            # qp [Pa=N/m2] * cp * btrib [mm] -> N/m, /1000 -> N/mm
            return qp * cp * (btrib / 1000.0) / 1000.0

        items = []; qtop = 0.0; ztop = zg
        for m in elems:
            s, e = _elem_ends(m)
            w1 = vscale(dirv, wline(s.z)); w2 = vscale(dirv, wline(e.z))
            items.append((m, w1, w2))
            for p, w in ((s, w1), (e, w2)):
                if w.Length >= qtop:
                    qtop = w.Length; ztop = p.z
        qp_ref, vm_ref, ce_ref = _wind_qp(max(0.0, (ztop - zg)) / 1000.0, vb0, z0,
                                          zmin, c0, rho, cdir, cseas)
        doc.openTransaction("DynFrame: wind load")
        n = _apply_wind(doc, vals["case"], items, vals["dir"])
        doc.commitTransaction(); doc.recompute()
        info("Wind load (EN 1991-1-4) added to case '%s' on %d member(s), wind %s.\n\n"
             "Basic velocity vb=%.1f m/s, terrain '%s'.\n"
             "At the top of the loaded members (z=%.2f m): q_p=%.3f kPa "
             "(c_e=%.2f, v_m=%.1f m/s); line load there = %.3g N/mm "
             "(= q_p x c_p=%.2f x trib=%.0f mm).\n\n"
             "The load varies with height (trapezoid per member). Re-run Calculate "
             "to apply. Tip: set c_p to your net windward+leeward coefficient."
             % (vals["case"], n, vals["dir"], cdir * cseas * vb0, vals["terr"],
                (ztop - zg) / 1000.0, qp_ref / 1000.0, ce_ref, vm_ref, qtop, cp, btrib))


class AddImperfection:
    _DIRS = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
             "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}

    def GetResources(self):
        return {"Pixmap": _icon("sway"), "MenuText": "Sway Imperfection (EC3)",
                "ToolTip": "EN 1993-1-1 global initial sway imperfection as "
                           "equivalent horizontal forces: phi = (1/200) alpha_h "
                           "alpha_m times each column's axial load, applied at the "
                           "column tops. Run a gravity Calculate first (it uses the "
                           "column axial forces).", "Accel": "A, I"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        bars = [o for o in doc.Objects if is_analysis_elem(o) and hasattr(o, "ResN")]
        if not bars:
            info("Run a gravity Calculate first - the sway imperfection uses the "
                 "column axial forces (N_Ed) from the analysis to form the "
                 "equivalent horizontal forces phi x N.")
            return
        # columns = predominantly vertical members; collect top node + axial
        cols = []; zmin = None; zmax = None
        for o in bars:
            s, e = _elem_ends(o)
            L = s.distanceToPoint(e)
            if L < 1e-6:
                continue
            dz = abs(e.z - s.z)
            for p in (s, e):
                zmin = p.z if zmin is None else min(zmin, p.z)
                zmax = p.z if zmax is None else max(zmax, p.z)
            if dz / L > 0.7:                      # a column
                top = e if e.z >= s.z else s
                ncomp = max(0.0, -float(getattr(o, "ResN", 0.0)))   # compression
                cols.append((top, ncomp))
        if not cols:
            info("No columns (vertical members) found. The sway imperfection needs "
                 "vertical members carrying axial load."); return
        h_m = max(1e-6, (zmax - zmin) / 1000.0)
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Sway Imperfection (EN 1993-1-1)", [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "_i", "kind": "info", "default":
             "phi = (1/200) x alpha_h x alpha_m.  alpha_h = 2/sqrt(h) in [2/3, 1] "
             "with h the frame height; alpha_m = sqrt(0.5(1+1/m)), m = number of "
             "columns. The equivalent horizontal force phi x N (column axial) is "
             "applied at each column top. Apply in a separate case and combine with "
             "gravity. For a multi-storey frame this phi x (column axial) is "
             "conservative (a per-storey split gives less)."},
            {"key": "dir", "label": "Direction", "kind": "combo",
             "options": list(self._DIRS.keys()), "default": "+X"},
            {"key": "m", "label": "Number of columns m", "kind": "int",
             "default": len(cols), "min": 1, "max": 1000},
        ])
        if not vals:
            return
        phi, ah, am = _sway_phi(h_m, int(vals["m"]))
        d = self._DIRS.get(vals["dir"], (1.0, 0.0, 0.0))
        dirv = FreeCAD.Vector(*d)
        # accumulate phi*N per (merged) top node
        acc = {}
        for (top, ncomp) in cols:
            key = (round(top.x, 3), round(top.y, 3), round(top.z, 3))
            acc[key] = acc.get(key, 0.0) + phi * ncomp
        doc.openTransaction("DynFrame: sway imperfection")
        ntot = 0.0; applied = 0
        for (key, mag) in acc.items():
            if mag <= 1e-9:
                continue
            _apply_nodal(doc, vals["case"], vscale(dirv, mag),
                         [FreeCAD.Vector(*key)])
            ntot += mag; applied += 1
        doc.commitTransaction(); doc.recompute()
        info("Sway imperfection (EN 1993-1-1) added to case '%s', direction %s.\n\n"
             "Frame height h = %.2f m, m = %d columns -> phi = %.5f "
             "(alpha_h = %.3f, alpha_m = %.3f).\n"
             "Equivalent horizontal forces phi x N applied at %d column top(s); "
             "total notional shear = %.0f N.\n\nRe-run Calculate (combine this case "
             "with gravity) to capture the second-order sway effect - pair it with "
             "the P-Delta option." % (vals["case"], vals["dir"], h_m, int(vals["m"]),
                                      phi, ah, am, applied, ntot))


class AddPlate:
    def GetResources(self):
        return {"Pixmap": _icon("plate"), "MenuText": "Add Plate / Shell",
                "ToolTip": "Select 3 or 4 node vertices (the plate corners) in the "
                           "3D view, then create a plate/shell: a meshed 2D element "
                           "(walls, slabs, floor diaphragms) analysed with a validated "
                           "flat shell (membrane + plate bending).", "Accel": "A, T"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        pts = _sel_vertices()
        if len(pts) not in (3, 4):
            info("Select 3 or 4 node vertices (the plate corners) in the 3D view "
                 "first.\n\nTip: draw a rectangle/box edges or bar nodes, then pick "
                 "the four corner vertices. A plate shares nodes with any bars at "
                 "the same points (a slab on beams).")
            return
        doc = FreeCAD.ActiveDocument
        mats = list(MATERIALS.keys())
        isquad = (len(pts) == 4)
        fields = [
            {"key": "_i", "kind": "info", "default":
             "A plate/shell meshed into triangles. Thickness and material set its "
             "stiffness; mesh divisions set the accuracy (more = finer)."},
            {"key": "thk", "label": "Thickness (mm)", "kind": "float", "default": 150.0},
            {"key": "mat", "label": "Material", "kind": "combo",
             "options": mats, "default": DEFAULT_MAT}]
        if isquad:
            fields += [
                {"key": "nx", "label": "Mesh divisions, side 1", "kind": "float", "default": 6},
                {"key": "ny", "label": "Mesh divisions, side 2", "kind": "float", "default": 6}]
        vals = form_dialog("Add Plate / Shell", fields)
        if not vals or abs(vals["thk"]) < 1e-6:
            return
        if isquad:
            P = _order_quad(pts)
            nx = max(1, int(round(vals.get("nx", 4))))
            ny = max(1, int(round(vals.get("ny", 4))))
            tris = _mesh_quad(P[0], P[1], P[2], P[3], nx, ny)
        else:
            tris = [[pts[0], pts[1], pts[2]]]
        doc.openTransaction("DynFrame: add plate")
        o = _make_plate(doc, tris, vals["thk"], vals["mat"])
        doc.commitTransaction(); doc.recompute()
        if o is None:
            info("Could not build the plate (degenerate corners?)."); return
        info("Plate created: %d triangle element(s), t=%g mm, %s.\n\nAdd supports "
             "at its edge nodes, a pressure (Add Plate Pressure) or other loads, "
             "then Calculate. The plate von Mises stress appears in the Results "
             "Viewer and the 'PlateForces' table." % (len(tris), vals["thk"], vals["mat"]))


class AddPlateLoad:
    def GetResources(self):
        return {"Pixmap": _icon("barload"), "MenuText": "Add Plate Pressure",
                "ToolTip": "Select one or more plates, then apply a surface pressure "
                           "(N/mm^2) normal to the plate, assigned to a load case.",
                "Accel": "A, R"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx()
               if getattr(s.Object, "IsShell", False)]
        if not sel:
            info("Select one or more plates in the 3D view first, then add a "
                 "pressure.")
            return
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Add Plate Pressure (%d plate(s))" % len(sel), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "p", "label": "Pressure (N/mm^2, + along plate normal)",
             "kind": "float", "default": -0.005}])
        if not vals or abs(vals["p"]) < 1e-12:
            return
        doc.openTransaction("DynFrame: plate pressure")
        grp = _grp(doc, LOAD_GROUP)
        for pl in sel:
            tris = _shell_tris(pl)
            arrows = []
            if tris:
                nrm, _a = _tri_normal_area(tris[0])
                allp = [p for tri in tris for p in tri]
                c = FreeCAD.Vector(sum(p.x for p in allp) / len(allp),
                                   sum(p.y for p in allp) / len(allp),
                                   sum(p.z for p in allp) / len(allp))
                ln = _model_size([pl]) * 0.15 + 50.0
                d = nrm if vals["p"] >= 0 else vscale(nrm, -1.0)
                try:
                    arrows.append(Part.makeLine(FreeCAD.Vector(c - vscale(d, ln)),
                                                FreeCAD.Vector(c)))
                    arrows.append(Part.makeCone(ln * 0.14, 0.0, ln * 0.3,
                                                c - vscale(d, ln * 0.3), d))
                except Exception:
                    pass
            o = doc.addObject("Part::Feature", "PlatePressure")
            if arrows:
                o.Shape = Part.makeCompound(arrows)
            o.Label = "%s: %.4g N/mm^2 on %s" % (vals["case"], vals["p"], pl.Label)
            _set(o, "App::PropertyString", "LoadType", "Pressure")
            _set(o, "App::PropertyString", "LoadCase", vals["case"])
            _set(o, "App::PropertyString", "OnShell", pl.Name)
            _set(o, "App::PropertyFloat", "Pressure", float(vals["p"]))
            try:
                o.ViewObject.ShapeColor = (0.9, 0.2, 0.9); o.ViewObject.LineWidth = 2
            except Exception:
                pass
            grp.addObject(o)
        doc.commitTransaction(); doc.recompute()
        info("Pressure %.4g N/mm^2 added to case '%s' on %d plate(s)."
             % (vals["p"], vals["case"], len(sel)))


# EN 1990 Table A1.1 combination factors (psi0, psi1, psi2) by action nature.
# Representative values: imposed cat A/B, wind, snow (sites <=1000 m).
PSI_FACTORS = {
    "Live":  (0.7, 0.5, 0.3),
    "Wind":  (0.6, 0.2, 0.0),
    "Snow":  (0.5, 0.2, 0.0),
    "Other": (0.7, 0.5, 0.3),
}
GAMMA_G = 1.35      # permanent, unfavourable (EN 1990 Table A1.2(B))
GAMMA_Q = 1.5       # variable, unfavourable
XI_610 = 0.85       # reduction on permanent in eq 6.10b


def _fmt_factor(f):
    f = round(float(f), 4)
    return "%.1f" % f if f == int(f) else "%g" % f


def _combo_terms(pairs):
    """Join (factor, case) pairs into a 'f*Case + ...' string, dropping ~zero."""
    return " + ".join("%s*%s" % (_fmt_factor(f), c)
                      for f, c in pairs if abs(f) > 1e-9)


def _en1990_combos(cases, approach="6.10", gG=GAMMA_G, gQ=GAMMA_Q, psi=None):
    """Full EN 1990 load combinations from (name, nature) cases - the way Robot
    does code combinations, not a single 1.35G+1.5Q lump:

      * ULS (STR, persistent/transient): each variable action taken in turn as
        the LEADING one (factor gammaQ), the others accompanying (gammaQ*psi0).
        approach '6.10' = eq 6.10; '6.10ab' = eqs 6.10a (all variables at psi0)
        and 6.10b (permanent reduced by xi, leading full) - design value is the
        envelope of the two.
      * SLS characteristic: leading at 1.0, accompanying at psi0.
      * SLS frequent: leading at psi1, accompanying at psi2.
      * SLS quasi-permanent: all variable actions at psi2.

    Returns a list of (name, 'factor*Case + ...') pairs. Pure and exact."""
    psi = psi or PSI_FACTORS
    dead = [n for n, nat in cases if nat == "Dead"]
    var = [(n, nat) for n, nat in cases if nat != "Dead"]

    def p0(nat): return psi.get(nat, (0.7, 0.5, 0.3))[0]
    def p1(nat): return psi.get(nat, (0.7, 0.5, 0.3))[1]
    def p2(nat): return psi.get(nat, (0.7, 0.5, 0.3))[2]

    out = []
    if not var:
        if dead:
            out.append(("ULS1", _combo_terms([(gG, d) for d in dead])))
            out.append(("CHAR1", _combo_terms([(1.0, d) for d in dead])))
        return out
    # ULS (STR)
    n = 1
    for i, (ln, lnat) in enumerate(var):
        if approach == "6.10ab":
            a = [(gG, d) for d in dead] + [(gQ * p0(nat), qn) for (qn, nat) in var]
            out.append(("ULS%da" % n, _combo_terms(a)))
            b = [(XI_610 * gG, d) for d in dead]
            b += [((gQ if j == i else gQ * p0(nat)), qn)
                  for j, (qn, nat) in enumerate(var)]
            out.append(("ULS%db" % n, _combo_terms(b)))
        else:
            c = [(gG, d) for d in dead]
            c += [((gQ if j == i else gQ * p0(nat)), qn)
                  for j, (qn, nat) in enumerate(var)]
            out.append(("ULS%d" % n, _combo_terms(c)))
        n += 1
    # SLS characteristic
    for n, (ln, lnat) in enumerate(var, start=1):
        i = n - 1
        c = [(1.0, d) for d in dead]
        c += [((1.0 if j == i else p0(nat)), qn)
              for j, (qn, nat) in enumerate(var)]
        out.append(("CHAR%d" % n, _combo_terms(c)))
    # SLS frequent
    for n, (ln, lnat) in enumerate(var, start=1):
        i = n - 1
        c = [(1.0, d) for d in dead]
        c += [((p1(nat) if j == i else p2(nat)), qn)
              for j, (qn, nat) in enumerate(var)]
        t = _combo_terms(c)
        if t:
            out.append(("FREQ%d" % n, t))
    # SLS quasi-permanent
    qp = _combo_terms([(1.0, d) for d in dead] + [(p2(nat), qn) for (qn, nat) in var])
    if qp:
        out.append(("QP1", qp))
    return out


class Combinations:
    def GetResources(self):
        return {"Pixmap": _icon("combo"), "MenuText": "Load Combinations",
                "ToolTip": "Generate the full EN 1990 load combinations from the "
                           "load cases - ULS (eq 6.10, or 6.10a/6.10b) with each "
                           "variable action taken as leading and the others "
                           "reduced by psi0, plus SLS characteristic / frequent / "
                           "quasi-permanent - or add your own. The way Robot does "
                           "code combinations.",
                "Accel": "A, B"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        cases = _cases(doc)
        mode, ok = get_item("Load Combinations", "Action:",
                            ["Auto EN 1990 - ULS eq 6.10 + SLS",
                             "Auto EN 1990 - ULS eq 6.10a/6.10b + SLS",
                             "Add a custom combination",
                             "Clear all combinations"], 0)
        if not ok:
            return
        if mode.startswith("Clear"):
            _set_combos(doc, [])
            doc.recompute(); info("All combinations cleared."); return
        if mode.startswith("Auto"):
            if not cases:
                info("Define some load cases first (New Load Case)."); return
            approach = "6.10ab" if "6.10a" in mode else "6.10"
            gen = _en1990_combos(cases, approach=approach)
            if not gen:
                info("No usable load cases (need at least one Dead or variable "
                     "case)."); return
            have = {p[0] for p in _combos(doc)}
            pairs = _combos(doc) + [(nm, df) for (nm, df) in gen if nm not in have]
            _set_combos(doc, pairs); doc.recompute()
            uls = [p for p in gen if p[0].startswith("ULS")]
            sls = [p for p in gen if not p[0].startswith("ULS")]
            body = "\n".join("  %s = %s" % (nm, df) for nm, df in gen)
            info("EN 1990 combinations generated (%d ULS, %d SLS) - each variable "
                 "action taken as leading, others reduced by psi0:\n\n%s\n\n"
                 "psi factors (EN 1990 A1.1): Live 0.7/0.5/0.3, Wind 0.6/0.2/0, "
                 "Snow 0.5/0.2/0. Edit the 'Combinations' sheet or add custom ones."
                 % (len(uls), len(sls), body))
            return
        name, ok = get_text("Add Combination", "Name:", "C%d" % (len(_combos(doc)) + 1))
        if not ok or not name.strip():
            return
        hint = "e.g.  1.35*%s + 1.5*%s" % (cases[0][0], cases[-1][0])
        defn, ok = get_text("Add Combination",
                            "Definition (factor*Case + ...). Cases: %s"
                            % ", ".join(c[0] for c in cases), hint)
        if not ok or not defn.strip():
            return
        pairs = [p for p in _combos(doc) if p[0] != name.strip()]
        pairs.append((name.strip(), defn.strip()))
        _set_combos(doc, pairs); doc.recompute()
        info("Combination '%s' = %s added." % (name.strip(), defn.strip()))


class MemberReleases:
    _PRESETS = {
        "Rigid (no release)": ("000000", "000000"),
        "Pinned both ends (My, Mz)": ("000011", "000011"),
        "Pinned start (My, Mz)": ("000011", "000000"),
        "Pinned end (My, Mz)": ("000000", "000011"),
        "Pinned + torsion both ends": ("000111", "000111"),
    }

    def GetResources(self):
        return {"Pixmap": _icon("release"), "MenuText": "Member Releases",
                "ToolTip": "Release member end DOFs (e.g. moment releases for a "
                           "pinned connection, or pin both ends for a truss member) "
                           "on the selected bars.", "Accel": "A, E"}

    def IsActive(self):
        return bool(selected_elems())

    def Activated(self):
        elems = [m for m in selected_elems() if is_bar(m)]
        if not elems:
            info("Select one or more bars, then set their end releases.")
            return
        doc = FreeCAD.ActiveDocument
        vals = form_dialog("Member Releases (%d bar(s))" % len(elems), [
            {"key": "_i", "kind": "info", "default":
             "A release frees that DOF at the member end (the member transfers no "
             "moment there). Pin both ends = a truss-type member."},
            {"key": "p", "label": "Release", "kind": "combo",
             "options": list(self._PRESETS.keys()),
             "default": "Pinned both ends (My, Mz)"},
        ])
        if not vals:
            return
        ri, rj = self._PRESETS[vals["p"]]
        doc.openTransaction("DynFrame: member releases")
        for m in elems:
            _set(m, "App::PropertyString", "RelI", ri)
            _set(m, "App::PropertyString", "RelJ", rj)
        doc.commitTransaction(); doc.recompute()
        info("Set '%s' on %d bar(s). Re-run Calculate to apply."
             % (vals["p"], len(elems)))


class MemberType:
    _OPTS = ["Normal (tension + compression)", "Tension-only (cable / brace)",
             "Compression-only (strut)"]
    _MAP = {_OPTS[0]: "Normal", _OPTS[1]: "Tension-only",
            _OPTS[2]: "Compression-only"}

    def GetResources(self):
        return {"Pixmap": _icon("tension"), "MenuText": "Tension / Compression Member",
                "ToolTip": "Make the selected bars tension-only (a cable or slack "
                           "cross-brace that drops out in compression) or "
                           "compression-only (a strut). Solved with a nonlinear "
                           "active-set iteration.", "Accel": "A, T"}

    def IsActive(self):
        return bool(selected_elems())

    def Activated(self):
        elems = [m for m in selected_elems() if is_bar(m)]
        if not elems:
            info("Select one or more bars, then set their tension/compression type.")
            return
        doc = FreeCAD.ActiveDocument
        vals = form_dialog("Tension / Compression Member (%d bar(s))" % len(elems), [
            {"key": "_i", "kind": "info", "default":
             "A tension-only member (cable, slack cross-brace) carries no "
             "compression; a compression-only member (strut) carries no tension. "
             "The solver drops such members out when their axial force takes the "
             "wrong sign and re-solves until the active set is stable."},
            {"key": "b", "label": "Behaviour", "kind": "combo",
             "options": self._OPTS, "default": self._OPTS[1]},
            {"key": "ends", "label": "Ends", "kind": "combo",
             "options": ["Keep current", "Pin both ends (truss member)"],
             "default": "Pin both ends (truss member)"},
        ])
        if not vals:
            return
        beh = self._MAP[vals["b"]]
        doc.openTransaction("DynFrame: member type")
        for m in elems:
            _set(m, "App::PropertyString", "MemberBehavior", beh)
            if vals["ends"].startswith("Pin"):
                _set(m, "App::PropertyString", "RelI", "000011")
                _set(m, "App::PropertyString", "RelJ", "000011")
        doc.commitTransaction(); doc.recompute()
        info("Set '%s' on %d bar(s). Re-run Calculate to apply." % (beh, len(elems)))


class RunAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("calculate"), "MenuText": "Calculate",
                "ToolTip": "Linear-static solve on the bar line model for a chosen "
                           "load case or combination. Produces reactions, deformed "
                           "shape, gradient N/V/M diagrams and result tables.",
                "Accel": "A, C"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self, run_pick=None, include_sw=None, second_order=False):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        objs, kind = _analysis_objs(doc)
        shell_objs = [o for o in doc.Objects if getattr(o, "IsShell", False)]
        if not objs and not shell_objs:
            info("No bars, members or plates found. Build a line model (Add Bars, "
                 "Bars from Members, or Node/Bar Tables) or add a plate (Add Plate).")
            return

        nodes = []

        def nid(p, make=True):
            for i, q in enumerate(nodes):
                if q.distanceToPoint(p) <= 1.0:
                    return i
            if not make:
                return -1
            nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

        elems = []
        for o in objs:
            sec = _elem_section(o)
            sp = _section_props_from_name(sec)
            if sp is None:
                continue
            A, Iy, Iz, J, c = sp
            s, e = _elem_ends(o)
            n1, n2 = nid(s), nid(e)
            if n1 == n2:
                continue
            E, G, Fy, rho = _material(_elem_material(o))
            elems.append({"o": o, "n1": n1, "n2": n2, "A": A, "Iy": Iy, "Iz": Iz,
                          "J": J, "c": c, "E": E, "G": G, "Fy": Fy, "rho": rho,
                          "alpha": _mat_alpha(_elem_material(o)),
                          "cond": _member_cond(o), "active": True,
                          "sec": sec, "w": FreeCAD.Vector(0, 0, 0)})
        # plates/shells: mesh triangles, share nodes with the bars, store for
        # assembly + stress recovery (validated CST+DKT flat shell)
        shells = []
        for o in shell_objs:
            E, G, Fy, rho = _material(_shell_material(o))
            nu = _poisson(E, G); t = float(getattr(o, "ShellThk", 10.0))
            selem = []
            for tri in _shell_tris(o):
                ni = tuple(nid(p) for p in tri)
                if len(set(ni)) == 3:
                    selem.append((ni, [FreeCAD.Vector(p) for p in tri]))
            if selem:
                shells.append({"o": o, "tris": selem, "E": E, "nu": nu, "t": t,
                               "Fy": Fy, "rho": rho})
        if not elems and not shells:
            info("Could not build an analysis model (check that bars have valid "
                 "section names).")
            return
        by_obj = {el["o"].Name: el for el in elems}

        fixed = set(); sup_nodes = []; springs = []
        for o in doc.Objects:
            r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
            if r and at is not None:
                i = nid(FreeCAD.Vector(at), make=False)
                if i >= 0:
                    sup_nodes.append(i)
                    for k, ch in enumerate(r):
                        if ch == "1":
                            fixed.add(6 * i + k)
                    spj = getattr(o, "Springs", None)
                    if spj:
                        try:
                            import json as _json
                            springs.append((i, _json.loads(spj)))
                        except Exception:
                            pass
        if not fixed and not springs:
            err("No supports defined.\n\nSelect base node vertices and run "
                "'Define Support' (Fixed / Pinned / Roller / Elastic spring), "
                "then Calculate.")
            return

        cases = _cases(doc); combos = _combos(doc)
        run_opts = (["All loads"] + ["Case: %s" % c[0] for c in cases]
                    + ["Combo: %s" % cb[0] for cb in combos])
        if run_pick is not None and run_pick in run_opts:
            pick = run_pick
        else:
            pick, ok = get_item("Calculate", "Analyse:", run_opts, 0)
            if not ok:
                return
        if include_sw is not None:
            sw = "Yes" if include_sw else "No"
        else:
            sw, ok = get_item("Calculate", "Include bar self-weight (as Dead)?",
                              ["Yes", "No"], 0)
            if not ok:
                return
            order, ok = get_item("Calculate", "Analysis order:",
                                 ["1st order (linear)", "2nd order (P-Delta)"], 0)
            if not ok:
                return
            second_order = order.startswith("2nd")
        if pick == "All loads":
            factors = {c[0]: 1.0 for c in cases}; sw_factor = 1.0; run_name = "All loads"
        elif pick.startswith("Case: "):
            cn = pick[6:]; factors = {cn: 1.0}
            sw_factor = 1.0          # self-weight applied when the option is on
            run_name = "Case " + cn
        else:
            cn = pick[7:]; factors = _parse_combo(dict(combos).get(cn, ""))
            sw_factor = sum(f for c, f in factors.items() if _nature_of(doc, c) == "Dead")
            run_name = "Combo " + cn
        if sw != "Yes":
            sw_factor = 0.0

        for o in doc.Objects:
            lt = getattr(o, "LoadType", None)
            if lt not in ("Member", "MemberPoint", "MemberTrap", "Thermal"):
                continue
            f = factors.get(getattr(o, "LoadCase", ""), 0.0)
            el = by_obj.get(getattr(o, "OnMember", ""))
            if not f or el is None:
                continue
            if lt == "Thermal":
                el["dT"] = el.get("dT", 0.0) + f * float(getattr(o, "DeltaT", 0.0))
            elif lt == "Member":
                el["w"] = el["w"] + vscale(FreeCAD.Vector(getattr(o, "LoadVec")), f)
            elif lt == "MemberPoint":
                P = vscale(FreeCAD.Vector(getattr(o, "LoadVec")), f)
                pos = min(1.0, max(0.0, float(getattr(o, "LoadPos", 0.5))))
                el.setdefault("pts_g", []).append((P, pos))
            else:   # MemberTrap
                w1 = vscale(FreeCAD.Vector(getattr(o, "LoadVec")), f)
                w2 = vscale(FreeCAD.Vector(getattr(o, "LoadVec2", getattr(o, "LoadVec"))), f)
                el["trap_w1"] = el.get("trap_w1", FreeCAD.Vector(0, 0, 0)) + w1
                el["trap_w2"] = el.get("trap_w2", FreeCAD.Vector(0, 0, 0)) + w2
        if sw_factor:
            for el in elems:
                el["w"] = el["w"] + FreeCAD.Vector(
                    0, 0, -el["A"] * el["rho"] * GRAV * sw_factor)

        ndof = 6 * len(nodes)
        K = np.zeros((ndof, ndof)); F = np.zeros(ndof)
        for el in elems:
            T, L = _beam_T(nodes[el["n1"]], nodes[el["n2"]])
            el["T"] = T; el["L"] = L
            kl = _beam_k_local(el["E"], el["G"], el["A"], el["Iy"], el["Iz"], el["J"], L)
            el["kl"] = kl
            dofs = ([6 * el["n1"] + i for i in range(6)]
                    + [6 * el["n2"] + i for i in range(6)])
            el["dofs"] = dofs
            w = el["w"]; R3 = T[0:3, 0:3]
            wl = R3 @ np.array([w.x, w.y, w.z])
            el["wx"], el["wy"], el["wz"] = float(wl[0]), float(wl[1]), float(wl[2])
            fl = _fef_udl(w, R3, L) if w.Length > 1e-12 else np.zeros(12)
            # point loads -> exact consistent fixed-end forces + recovery data
            el["pts_local"] = []
            for (P, pos) in el.get("pts_g", []):
                Pl = R3 @ np.array([P.x, P.y, P.z]); a = pos * L
                fl = fl + _fef_point_local(float(Pl[0]), float(Pl[1]), float(Pl[2]), L, a)
                el["pts_local"].append((float(Pl[0]), float(Pl[1]), float(Pl[2]), a))
            # trapezoidal (linearly varying) load -> UDL(w1) + triangle(w2-w1)
            if "trap_w1" in el:
                t1 = el["trap_w1"]; t2 = el["trap_w2"]
                w1l = R3 @ np.array([t1.x, t1.y, t1.z])
                w2l = R3 @ np.array([t2.x, t2.y, t2.z])
                fl = fl + _fef_udl_local(float(w1l[0]), float(w1l[1]), float(w1l[2]), L)
                q = w2l - w1l
                fl = fl + _fef_tri_local(float(q[0]), float(q[1]), float(q[2]), L)
                el["trap_local"] = (w1l, w2l)
            if el.get("dT"):          # temperature change -> axial fixed-end force
                fl = fl + _fef_thermal_local(el["E"] * el["A"], el["alpha"],
                                             el["dT"], L)
            el["fef"] = fl
            # member end releases (condensation of released local DOFs)
            rel = _bar_releases(el["o"])
            kc, fc, el["rel_info"] = _condense(kl, fl, rel)
            Kctr = T.T @ kc @ T; Fctr = T.T @ fc
            el["Kctr"] = Kctr; el["Fctr"] = Fctr   # for the tension-only active set
            K[np.ix_(dofs, dofs)] += Kctr
            F[dofs] += Fctr
        # plate/shell stiffness (flat CST + DKT shell, 6 dof/node)
        for sh in shells:
            for (ni, pts) in sh["tris"]:
                Ke = _shell_k_global(pts, sh["E"], sh["nu"], sh["t"])
                dofs = []
                for n in ni:
                    dofs += [6 * n + i for i in range(6)]
                K[np.ix_(dofs, dofs)] += Ke
        # elastic (spring) supports: add stiffness to the node DOFs
        for (i, sp) in springs:
            for k in range(min(6, len(sp))):
                K[6 * i + k, 6 * i + k] += float(sp[k])
        for o in doc.Objects:
            if getattr(o, "LoadType", None) == "Nodal":
                f = factors.get(getattr(o, "LoadCase", ""), 0.0)
                at = getattr(o, "AtNode", None)
                if f and at is not None:
                    i = nid(FreeCAD.Vector(at), make=False)
                    if i >= 0:
                        v = FreeCAD.Vector(getattr(o, "LoadVec"))
                        F[6 * i] += v.x * f; F[6 * i + 1] += v.y * f; F[6 * i + 2] += v.z * f
                        mv = getattr(o, "LoadMom", None)
                        if mv is not None:
                            F[6 * i + 3] += mv.x * f
                            F[6 * i + 4] += mv.y * f
                            F[6 * i + 5] += mv.z * f
        # pressure loads on plates (normal to each shell triangle)
        for o in doc.Objects:
            if getattr(o, "LoadType", None) == "Pressure":
                f = factors.get(getattr(o, "LoadCase", ""), 0.0)
                sh = next((s for s in shells
                           if s["o"].Name == getattr(o, "OnShell", "")), None)
                if f and sh is not None:
                    pres = f * float(getattr(o, "Pressure", 0.0))
                    for (ni, pts) in sh["tris"]:
                        nrm, Ae = _tri_normal_area(pts)
                        fn = pres * Ae / 3.0
                        for n in ni:
                            F[6 * n] += fn * nrm.x
                            F[6 * n + 1] += fn * nrm.y
                            F[6 * n + 2] += fn * nrm.z
        if sw_factor:
            for sh in shells:          # plate self-weight (downward, as Dead)
                for (ni, pts) in sh["tris"]:
                    _nrm, Ae = _tri_normal_area(pts)
                    fz = -sh["t"] * sh["rho"] * GRAV * sw_factor * Ae / 3.0
                    for n in ni:
                        F[6 * n + 2] += fz

        # prescribed displacements (support settlement) - zero for normal
        # supports, so this reduces to the usual solve when none are present
        u_pre = np.zeros(ndof)
        for o in doc.Objects:
            if getattr(o, "LoadType", None) == "Settlement":
                f = factors.get(getattr(o, "LoadCase", ""), 0.0)
                at = getattr(o, "AtNode", None)
                if f and at is not None:
                    i = nid(FreeCAD.Vector(at), make=False)
                    if i >= 0:
                        dv = FreeCAD.Vector(getattr(o, "LoadVec", FreeCAD.Vector()))
                        mv = FreeCAD.Vector(getattr(o, "LoadMom", FreeCAD.Vector()))
                        comps = [dv.x, dv.y, dv.z, mv.x, mv.y, mv.z]
                        for k in range(6):
                            if abs(comps[k]) > 1e-15:
                                u_pre[6 * i + k] += f * comps[k]
                                fixed.add(6 * i + k)

        free = [d for d in range(ndof) if d not in fixed]
        fx = sorted(fixed)
        upf = u_pre[fx] if fx else np.zeros(0)

        def _solve(Kmat, Fvec=None):
            if Fvec is None:
                Fvec = F
            uu = np.zeros(ndof)
            if fx:
                uu[fx] = upf
            rhs = Fvec[free].copy()
            if fx and np.any(upf):      # settlement: move the RHS by K_fp u_p
                rhs = rhs - Kmat[np.ix_(free, fx)] @ upf
            uu[free] = np.linalg.solve(Kmat[np.ix_(free, free)], rhs)
            return uu

        try:
            u = _solve(K)
        except Exception:
            err("The structure is a mechanism (unstable) with the supports given. "
                "Add more supports (or restrain more directions), then Calculate.")
            return
        # tension-only / compression-only members: an active-set iteration that
        # drops out any such member whose axial force takes the wrong sign (a
        # slack cable or a buckled brace carries nothing), then re-solves, until
        # the active set is stable. Members with no special behaviour, and models
        # with none at all, are untouched - this reduces to the linear solve.
        nl_note = ""
        cond = [el for el in elems if el.get("cond")]
        if cond:
            def _axial(el, uu):
                dl = el["T"] @ uu[el["dofs"]]
                return float(-(el["kl"] @ dl - el["fef"])[0])   # + tension
            for _it in range(25):
                tol = 1e-6 * max(1.0, max(abs(_axial(el, u)) for el in cond))
                changed = False
                for el in cond:
                    N = _axial(el, u); cur = el["active"]
                    if abs(N) <= tol:
                        want = cur                     # hysteresis near zero
                    elif el["cond"] == "tension":
                        want = (N > 0.0)               # keep only if in tension
                    else:
                        want = (N < 0.0)               # keep only if in compression
                    if want != cur:
                        el["active"] = want; changed = True
                        sgn = -1.0 if want else 1.0    # re-add (+) or remove (-)
                        dofs = el["dofs"]
                        K[np.ix_(dofs, dofs)] -= sgn * el["Kctr"]
                        F[dofs] -= sgn * el["Fctr"]
                if not changed:
                    break
                try:
                    u = _solve(K)
                except Exception:
                    # dropping a member made the model a mechanism; undo this
                    # pass's changes and keep the last stable solution
                    for el in cond:
                        if not el["active"]:
                            dofs = el["dofs"]
                            K[np.ix_(dofs, dofs)] += el["Kctr"]
                            F[dofs] += el["Fctr"]; el["active"] = True
                    u = _solve(K)
                    break
            ndrop = sum(1 for el in cond if not el["active"])
            if ndrop:
                nl_note = "  [%d tension/compression-only member(s) inactive]" % ndrop
        Ktot = K
        po_note = ""
        if second_order:
            # P-Delta: iterate with the geometric stiffness from the current
            # axial forces until the displacements converge (validated: the
            # amplification matches 1/(1-P/Pcr)).
            conv = False
            for _it in range(12):
                Kg = np.zeros((ndof, ndof))
                for el in elems:
                    if not el.get("active", True):   # dropped tension/compr member
                        continue
                    dl = el["T"] @ u[el["dofs"]]
                    fe = el["kl"] @ dl - el["fef"]
                    N = -fe[0]
                    Kg[np.ix_(el["dofs"], el["dofs"])] += \
                        el["T"].T @ _beam_kg_local(N, el["L"]) @ el["T"]
                Ktot = K + Kg
                try:
                    un = _solve(Ktot)
                except Exception:
                    err("Second-order solve diverged - the loads are at or above "
                        "the buckling load (run Buckling Analysis). Reduce the load "
                        "or add bracing.")
                    return
                d = np.linalg.norm(un[free] - u[free])
                base = np.linalg.norm(un[free]) or 1.0
                u = un
                if d / base < 1e-5:
                    conv = True
                    break
            po_note = ("  [2nd order, %s]"
                       % ("converged" if conv else "max iterations"))
        run_name = run_name + po_note + nl_note
        Rreac = Ktot @ u - F
        msize = _model_size(list(objs) + shell_objs)
        maxd = max((u[6 * i] ** 2 + u[6 * i + 1] ** 2 + u[6 * i + 2] ** 2) ** 0.5
                   for i in range(len(nodes)))

        NS = 10
        comp_max = {k: 0.0 for k in DIAG_KINDS}
        comp_max["Disp"] = 0.0
        max_util = 0.0
        for el in elems:
            dloc = el["T"] @ u[el["dofs"]]
            ri = el.get("rel_info")
            if ri is not None:                 # recover released DOF displacements
                r, c, kcci, kcr, fc = ri        # zero released end force: q_c = 0
                uc = kcci @ (fc - kcr @ dloc[r])
                dloc = dloc.copy()
                for idx, ci in enumerate(c):
                    dloc[ci] = uc[idx]
            el["dloc"] = dloc
            fend = el["kl"] @ dloc - el["fef"]
            if not el.get("active", True):     # dropped-out member carries nothing
                fend = np.zeros(12)
            el["fend"] = fend
            L = el["L"]; wy, wz, wx = el["wy"], el["wz"], el["wx"]
            A = el["A"]; c = el["c"]; Imin = min(el["Iy"], el["Iz"]); Fy = el["Fy"]
            pts = el.get("pts_local", [])        # [(px,py,pz,a), ...]
            trap = el.get("trap_local", None)    # (w1_local, w2_local)

            def val(kind, x, fend=fend, L=L, wx=wx, wy=wy, wz=wz, A=A, c=c,
                    Imin=Imin, pts=pts, trap=trap):
                # span loads marched from node I (free-body statics): the end
                # forces `fend` already carry each load's exact nodal effect, so
                # a point/trapezoid load only adds its crossed shear/axial and
                # its simply-supported "free" sagging moment on top of the UDL.
                def crossed(ci):          # axial/shear accumulated 0..x in one axis
                    s = 0.0
                    for (px, py, pz, a) in pts:
                        s += (px, py, pz)[ci] * (1.0 if x >= a else 0.0)
                    if trap is not None:
                        w1, w2 = trap
                        q = w2[ci] - w1[ci]
                        s += w1[ci] * x + q * x * x / (2.0 * L)
                    return s

                def free_m(ci):           # simply-supported free sagging moment at x
                    m = 0.0
                    for (px, py, pz, a) in pts:
                        P = (px, py, pz)[ci]
                        m += P * ((L - a) * x / L if x <= a else a * (L - x) / L)
                    if trap is not None:
                        w1, w2 = trap
                        q = w2[ci] - w1[ci]
                        m += w1[ci] * x * (L - x) / 2.0 + q * x * (L * L - x * x) / (6.0 * L)
                    return m

                if kind == "N":
                    return -(fend[0] + wx * x + crossed(0))
                if kind == "Vy":
                    return fend[1] + wy * x + crossed(1)
                if kind == "Vz":
                    return fend[2] + wz * x + crossed(2)
                if kind == "Mx":
                    return -fend[3]
                if kind == "My":
                    return fend[4] * (1 - x / L) - fend[10] * (x / L) \
                        - wz * x * (L - x) / 2.0 - free_m(2)
                if kind == "Mz":
                    return -fend[5] * (1 - x / L) + fend[11] * (x / L) \
                        - wy * x * (L - x) / 2.0 - free_m(1)
                # Stress: axial + biaxial bending magnitude at x
                myx = fend[4] * (1 - x / L) - fend[10] * (x / L) \
                    - wz * x * (L - x) / 2.0 - free_m(2)
                mzx = -fend[5] * (1 - x / L) + fend[11] * (x / L) \
                    - wy * x * (L - x) / 2.0 - free_m(1)
                nx = -(fend[0] + wx * x + crossed(0))
                mm = (myx * myx + mzx * mzx) ** 0.5
                return abs(nx) / A + (mm * c / Imin if Imin > 1e-9 else 0.0)

            el["val"] = val
            samp = {}
            for k in DIAG_KINDS:
                vals = [val(k, L * s / NS) for s in range(NS + 1)]
                samp[k] = vals
                comp_max[k] = max(comp_max[k], max(abs(v) for v in vals))
            el["samp"] = samp
            util = (max(samp["Stress"]) / Fy) if Fy > 0 else 0.0
            el["util"] = util; max_util = max(max_util, util)
            # persist peak member forces for the code check (ResN signed:
            # + tension, - compression)
            try:
                o = el["o"]
                _set(o, "App::PropertyFloat", "ResN", float(-el["fend"][0]))
                _set(o, "App::PropertyFloat", "ResMy", float(max(abs(v) for v in samp["My"])))
                _set(o, "App::PropertyFloat", "ResMz", float(max(abs(v) for v in samp["Mz"])))
                _set(o, "App::PropertyFloat", "ResVy", float(max(abs(v) for v in samp["Vy"])))
                _set(o, "App::PropertyFloat", "ResVz", float(max(abs(v) for v in samp["Vz"])))
                _set(o, "App::PropertyFloat", "ResUtil", float(util))
                _set(o, "App::PropertyFloat", "ResL", float(L))
            except Exception:
                pass

        # plate/shell stress + bending-moment recovery (per triangle). Moments
        # (Mx, My, Mxy) are expressed in one shared plate frame so the contour
        # is smooth; von Mises is the surface stress.
        shell_vm_max = 0.0
        mcomps = ("Mx", "My", "Mxy", "M1", "M2", "WAxb", "WAyb", "WAxt", "WAyt")
        mom_peak = {c: 0.0 for c in mcomps}
        for sh in shells:
            En, Ex, Ey = _plate_frame([pts for (ni, pts) in sh["tris"]])
            sh["Ex"] = Ex; sh["Ey"] = Ey; sh["traj"] = []
            pervm = []; per = {c: [] for c in mcomps}
            for (ni, pts) in sh["tris"]:
                ug = []
                for n in ni:
                    ug += list(u[6 * n:6 * n + 6])
                pervm.append(_shell_vm_stress(pts, sh["E"], sh["nu"], sh["t"], ug))
                mxx, myy, mxy, m1, m2 = _shell_moments(
                    pts, sh["E"], sh["nu"], sh["t"], ug, En, Ex, Ey)
                mxb, myb, mxt, myt = _wood_armer(mxx, myy, mxy)
                per["Mx"].append(mxx); per["My"].append(myy); per["Mxy"].append(mxy)
                per["M1"].append(m1); per["M2"].append(m2)
                per["WAxb"].append(mxb); per["WAyb"].append(myb)
                per["WAxt"].append(mxt); per["WAyt"].append(myt)
                cen = vscale(FreeCAD.Vector(pts[0]) + FreeCAD.Vector(pts[1])
                             + FreeCAD.Vector(pts[2]), 1.0 / 3.0)
                _n, area = _tri_normal_area(pts)
                sh["traj"].append((cen, mxx, myy, mxy, m1, m2, (2.0 * area) ** 0.5))
            sh["pervm"] = pervm
            for c in per:
                sh["per" + c] = per[c]
                if per[c]:
                    mom_peak[c] = max(mom_peak[c], max(abs(v) for v in per[c]))
            sh["vmmax"] = max(pervm) if pervm else 0.0
            shell_vm_max = max(shell_vm_max, sh["vmmax"])
            try:
                _set(sh["o"], "App::PropertyFloat", "ShellVM", float(sh["vmmax"]))
                _set(sh["o"], "App::PropertyFloat", "ShellUtil",
                     float(sh["vmmax"] / sh["Fy"]) if sh["Fy"] > 0 else 0.0)
                for c in ("Mx", "My", "Mxy", "WAxb", "WAyb", "WAxt", "WAyt"):
                    pk = max((abs(v) for v in sh.get("per" + c, [])), default=0.0)
                    _set(sh["o"], "App::PropertyFloat", "Shell" + c, float(pk))
            except Exception:
                pass

        # ---- results are rendered lazily, one at a time, on demand ----
        # The solve stores the per-bar force samples + deformed state; a single
        # result is then drawn by _render_result (coloured contour - tubes or
        # the members' real swept profiles). This keeps the object count low,
        # lets the deformation scale / tube-vs-solid choice re-render instantly,
        # and guarantees the colour gradient along each bar.
        doc.openTransaction("DynFrame: results")
        for o in list(doc.Objects):
            if getattr(o, "DiagKind", None) is not None \
                    or o.Name.startswith(("Diagram_", "Result_", "DeformedShape",
                                          "Legend", "MomentDiagram", "ResultPeak")):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        rg = _grp(doc, RES_GROUP); dg = _grp(doc, DIA_GROUP)
        _, maxoff = _deformed_points(nodes, u,
                                     [(el["n1"], el["n2"]) for el in elems], 0.0)
        comp_max["Disp"] = maxoff
        dscale = (0.08 * msize / maxoff) if maxoff > 1e-9 else 1.0
        radius = _tube_radius(msize)
        _store_analysis_state(doc, nodes, u, elems, dscale, msize, radius,
                              run_name, comp_max)
        doc.commitTransaction()

        _render_result(doc, "Disp", scale_mult=1.0)     # default view
        if shells:
            _build_plate_stress(doc, dg, shells, shell_vm_max,
                                visible=(not elems))
            # moments, principal moments and Wood-Armer reinforcement contours
            _build_plate_fields(doc, dg, shells, mom_peak, visible=False)
            _build_plate_trajectories(doc, dg, shells, mom_peak["M1"],
                                      mom_peak["M2"], visible=False)
            self._plate_table(doc, shells, rg)
            self._plate_reinf_table(doc, shells, rg)
        self._tables(doc, nodes, sup_nodes, Rreac, u, elems, run_name, rg, "Disp")
        doc.recompute()
        _apply_result_colors(doc)       # restore per-face gradient after recompute

        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        pnote = ""
        if shells:
            ntri = sum(len(s["tris"]) for s in shells)
            pnote = ("\n\n%d plate(s) / %d shell elements: max von Mises %.1f MPa; "
                     "max |Mx| %.0f, |My| %.0f, |Mxy| %.0f N.mm/mm. Results Viewer: "
                     "'Plate stress', 'Plate Mx / My / Mxy', principal 'M1 / M2' and "
                     "the 'Wood-Armer' reinforcement moments (top & bottom, X & Y). "
                     "Tables: 'PlateForces' and 'PlateReinforcement'."
                     % (len(shells), ntri, shell_vm_max,
                        mom_peak["Mx"], mom_peak["My"], mom_peak["Mxy"]))
        info("Analysis complete - %s  (%d bars, %d plates).\n\n"
             "Nodes %d | Restrained DOFs %d\n"
             "Max displacement:  %.3f mm\n"
             "Max |My| %.0f | Max |Mz| %.0f | Max |N| %.0f  N(.mm)\n"
             "Max utilisation:  %.2f  (stress / yield)\n\n"
             "Showing the DISPLACEMENT contour. Use the Results Viewer (or 'Show "
             "Result / Diagram') to switch to N, Vy, Vz, Mx, My, Mz, Stress or the "
             "plate stress contour. Tables: Reactions, Displacements, BarForces, "
             "plus your Nodes/Bars.%s" %
             (run_name, len(elems), len(shells), len(nodes), len(fixed), maxd,
              comp_max["My"], comp_max["Mz"], comp_max["N"], max_util, pnote))

    def _plate_table(self, doc, shells, rg):
        try:
            sh = doc.getObject("PlateForces") or doc.addObject("Spreadsheet::Sheet", "PlateForces")
            sh.Label = "PlateForces"; sh.clearAll()
            sh.set("A1", "PLATE / SHELL RESULTS (von Mises + bending moments)")
            for c, h in zip("ABCDEFGH", ["Plate", "Thk (mm)", "Elements",
                                         "Max von Mises (MPa)", "Utilisation",
                                         "Max |Mx| (N.mm/mm)", "Max |My| (N.mm/mm)",
                                         "Max |Mxy| (N.mm/mm)"]):
                sh.set("%s2" % c, h)
            r = 3

            def _pk(s, c):
                return max((abs(v) for v in s.get("per" + c, [])), default=0.0)
            for s in shells:
                row = [str(s["o"].Label), s["t"], len(s["tris"]), s.get("vmmax", 0.0),
                       (s.get("vmmax", 0.0) / s["Fy"]) if s["Fy"] > 0 else 0.0,
                       _pk(s, "Mx"), _pk(s, "My"), _pk(s, "Mxy")]
                for c, v in zip("ABCDEFGH", row):
                    sh.set("%s%d" % (c, r), ("%.4g" % v if isinstance(v, float) else str(v)))
                r += 1
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: plate table failed (%s)\n" % e)

    def _plate_reinf_table(self, doc, shells, rg):
        """Per-plate Wood-Armer design moments for orthogonal reinforcement:
        the peak sagging (bottom) and hogging (top) design moment in each
        direction - what you size the x- and y-bars against, top and bottom."""
        try:
            sh = (doc.getObject("PlateReinforcement")
                  or doc.addObject("Spreadsheet::Sheet", "PlateReinforcement"))
            sh.Label = "PlateReinforcement"; sh.clearAll()
            sh.set("A1", "PLATE REINFORCEMENT - Wood-Armer design moments (N.mm/mm)")
            for c, h in zip("ABCDE", ["Plate", "Mxd bottom (+x steel)",
                                      "Myd bottom (+y steel)", "Mxd top (-x steel)",
                                      "Myd top (-y steel)"]):
                sh.set("%s2" % c, h)
            r = 3

            def _pk(s, c):
                return max((abs(v) for v in s.get("per" + c, [])), default=0.0)
            for s in shells:
                row = [str(s["o"].Label), _pk(s, "WAxb"), _pk(s, "WAyb"),
                       _pk(s, "WAxt"), _pk(s, "WAyt")]
                for c, v in zip("ABCDE", row):
                    sh.set("%s%d" % (c, r), ("%.4g" % v if isinstance(v, float) else str(v)))
                r += 1
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: reinforcement table failed (%s)\n" % e)

    def _tables(self, doc, nodes, sup_nodes, Rreac, u, elems, run_name, rg, akind):
        def sheet(name):
            sh = doc.getObject(name) or doc.addObject("Spreadsheet::Sheet", name)
            sh.Label = name; sh.clearAll()
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
            return sh
        try:
            sh = sheet("Reactions")
            sh.set("A1", "REACTIONS - %s" % run_name)
            for col, h in zip("ABCDEFG", ["Node", "Rx (N)", "Ry (N)", "Rz (N)",
                                          "Mx (N.mm)", "My (N.mm)", "Mz (N.mm)"]):
                sh.set("%s2" % col, h)
            r = 3
            for i in sorted(set(sup_nodes)):
                sh.set("A%d" % r, "N%d (%.0f,%.0f,%.0f)" % (i + 1, nodes[i].x, nodes[i].y, nodes[i].z))
                for c, col in enumerate("BCDEFG"):
                    sh.set("%s%d" % (col, r), "%.1f" % Rreac[6 * i + c])
                r += 1

            sh = sheet("Displacements")
            sh.set("A1", "NODAL DISPLACEMENTS - %s" % run_name)
            for col, h in zip("ABCDEFG", ["Node", "Ux (mm)", "Uy (mm)", "Uz (mm)",
                                          "Rx (rad)", "Ry (rad)", "Rz (rad)"]):
                sh.set("%s2" % col, h)
            for i in range(len(nodes)):
                r = i + 3
                sh.set("A%d" % r, "N%d (%.0f,%.0f,%.0f)" % (i + 1, nodes[i].x, nodes[i].y, nodes[i].z))
                for c, col in zip(range(3), "BCD"):
                    sh.set("%s%d" % (col, r), "%.4g" % u[6 * i + c])
                for c, col in zip(range(3, 6), "EFG"):
                    sh.set("%s%d" % (col, r), "%.3e" % u[6 * i + c])

            sh = sheet("BarForces")
            sh.set("A1", "BAR FORCES - %s  (Start x=0, End x=L)" % run_name)
            for col, h in zip("ABCDEFGHIJK",
                              ["Bar", "Section", "End", "N (N)", "Vy (N)", "Vz (N)",
                               "Mx (N.mm)", "My (N.mm)", "Mz (N.mm)", "Stress(MPa)",
                               "Util."]):
                sh.set("%s2" % col, h)
            r = 3
            for el in elems:
                L = el["L"]; v = el["val"]
                for endname, x in (("Start", 0.0), ("End", L)):
                    first = (endname == "Start")
                    sh.set("A%d" % r, str(el["o"].Label) if first else "")
                    sh.set("B%d" % r, el["sec"] if first else "")
                    sh.set("C%d" % r, endname)
                    sh.set("D%d" % r, "%.1f" % v("N", x)); sh.set("E%d" % r, "%.1f" % v("Vy", x))
                    sh.set("F%d" % r, "%.1f" % v("Vz", x)); sh.set("G%d" % r, "%.0f" % v("Mx", x))
                    sh.set("H%d" % r, "%.0f" % v("My", x)); sh.set("I%d" % r, "%.0f" % v("Mz", x))
                    sh.set("J%d" % r, "%.1f" % v("Stress", x))
                    if first:
                        sh.set("K%d" % r, "%.2f" % el["util"])
                    r += 1
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: result tables failed (%s)\n" % e)


RESULT_LABELS = {"Disp": "Displacement (mm)", "N": "N - axial force (N)",
                 "Vy": "Vy - shear local y (N)", "Vz": "Vz - shear local z (N)",
                 "Mx": "Mx - torsion (N.mm)", "My": "My - bending major (N.mm)",
                 "Mz": "Mz - bending minor (N.mm)", "Stress": "Stress - combined (MPa)",
                 "_plate": "Plate stress - von Mises (MPa)",
                 "_plateMx": "Plate Mx - bending (N.mm/mm)",
                 "_plateMy": "Plate My - bending (N.mm/mm)",
                 "_plateMxy": "Plate Mxy - twisting (N.mm/mm)",
                 "_plateM1": "Plate M1 - principal max (N.mm/mm)",
                 "_plateM2": "Plate M2 - principal min (N.mm/mm)",
                 "_plateWAxb": "Plate Wood-Armer bottom X (N.mm/mm)",
                 "_plateWAyb": "Plate Wood-Armer bottom Y (N.mm/mm)",
                 "_plateWAxt": "Plate Wood-Armer top X (N.mm/mm)",
                 "_plateWAyt": "Plate Wood-Armer top Y (N.mm/mm)",
                 "_plateT1": "Plate M1 trajectories (N.mm/mm)",
                 "_plateT2": "Plate M2 trajectories (N.mm/mm)"}
RESULT_ORDER = ["Disp", "N", "Vy", "Vz", "Mx", "My", "Mz", "Stress"]


class ShowDiagram:
    def GetResources(self):
        return {"Pixmap": _icon("diagram"), "MenuText": "Show Result / Diagram",
                "ToolTip": "Switch the displayed result: Displacement contour, or an "
                           "N / Vy / Vz / Mx / My / Mz / Stress diagram (gradient-"
                           "coloured). The colour bar updates. Run Calculate first.",
                "Accel": "A, D"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self, kind=None):
        doc = FreeCAD.ActiveDocument
        avail = [k for (lab, k, knd) in _result_list(doc) if knd == "diag"]
        if not avail:
            info("No results yet. Run Calculate first."); return
        if kind is None:
            pick, ok = get_item("Show Result / Diagram", "Result:",
                                [RESULT_LABELS[k] for k in avail], 0)
            if not ok:
                return
            kind = avail[[RESULT_LABELS[k] for k in avail].index(pick)]
        if kind not in avail:
            return
        # render the chosen result on demand (tubes, or solid beams if toggled)
        _render_result(doc, kind, scale_mult=1.0)


class ClearAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("clear"), "MenuText": "Clear Results",
                "ToolTip": "Remove analysis results (diagrams, deformed shape, legend "
                           "and result tables). Keeps the bar model, supports and "
                           "loads.", "Accel": "A, X"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        kill, ok = get_item("Clear",
                            "What to remove?",
                            ["Results only (keep model/loads)",
                             "Everything (supports, loads, combinations, results)"], 0)
        if not ok:
            return
        everything = kill.startswith("Everything")
        doc.openTransaction("DynFrame: clear")
        res_sheets = ("Reactions", "Displacements", "BarForces",
                      "ModalFrequencies", "CodeCheck", "Envelope", "Seismic",
                      "PlateForces", "PlateReinforcement", "PlateSteel",
                      "PunchingShear", "MovingEnvelope", "ResponseHistory",
                      "StoreyDrift", "GMSpectrum", "WallThermal",
                      "ThermalBridge", "FireThermal")
        all_sheets = res_sheets + ("LoadCases", "Combinations", "AnalysisResults")
        to_del = []
        for o in list(doc.Objects):
            nm = o.Name
            is_res = (getattr(o, "DiagKind", None) is not None
                      or nm.startswith(("Diagram_", "DeformedShape", "Legend",
                                        "MomentDiagram", "Mode", "Buckling", "Seismic"))
                      or nm in res_sheets
                      or (o.TypeId == "App::DocumentObjectGroup"
                          and o.Label in (RES_GROUP, DIA_GROUP)))
            is_load = (getattr(o, "Restrain", None) is not None
                       or getattr(o, "LoadType", None) is not None
                       or nm in all_sheets or nm == META_NAME
                       or (o.TypeId == "App::DocumentObjectGroup"
                           and o.Label in (SUP_GROUP, LOAD_GROUP, "Analysis Setup")))
            if is_res or (everything and is_load):
                to_del.append(nm)
        for name in to_del:
            try:
                doc.removeObject(name)
            except Exception:
                pass
        doc.commitTransaction(); doc.recompute()
        info("Cleared %s." % ("everything" if everything else "results"))


class ModalAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("modal"), "MenuText": "Modal Analysis",
                "ToolTip": "Natural frequencies and mode shapes (eigenvalue "
                           "analysis, consistent mass). Each bar is meshed into "
                           "sub-elements for accuracy. Define supports first.",
                "Accel": "A, V"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        objs, _k = _analysis_objs(doc)
        if not objs:
            info("No bars/members found. Build a line model first."); return
        nodes = []

        def nid(p, make=True):
            for i, q in enumerate(nodes):
                if q.distanceToPoint(p) <= 1.0:
                    return i
            if not make:
                return -1
            nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

        bars = []
        for o in objs:
            sp = _section_props_from_name(_elem_section(o))
            if sp is None:
                continue
            A, Iy, Iz, J, c = sp
            s, e = _elem_ends(o)
            n1, n2 = nid(s), nid(e)
            if n1 == n2:
                continue
            E, Gm, Fy, rho = _material(_elem_material(o))
            bars.append({"n1": n1, "n2": n2, "A": A, "Iy": Iy, "Iz": Iz, "J": J,
                         "E": E, "G": Gm, "rho": rho})
        if not bars:
            info("Could not build a model (check section names)."); return

        fixed = set()
        for o in doc.Objects:
            r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
            if r and at is not None:
                i = nid(FreeCAD.Vector(at), make=False)
                if i >= 0:
                    for k, ch in enumerate(r):
                        if ch == "1":
                            fixed.add(6 * i + k)
        if not fixed:
            err("No supports defined. Add supports first, then run Modal Analysis.")
            return

        nmodes, ok = get_int("Modal Analysis", "Number of modes:", 6, 1, 50)
        if not ok:
            return

        # fine mesh: subdivide each bar into NSUB sub-elements (coarse nodes kept
        # as the first entries, so support DOFs keep their indices)
        NSUB = 4
        fine = [FreeCAD.Vector(p) for p in nodes]

        def fid(p):
            for i, q in enumerate(fine):
                if q.distanceToPoint(p) <= 0.5:
                    return i
            fine.append(FreeCAD.Vector(p)); return len(fine) - 1

        subel = []
        for b in bars:
            p1 = nodes[b["n1"]]; p2 = nodes[b["n2"]]
            prev = b["n1"]
            for s in range(1, NSUB + 1):
                pt = p1 + vscale(p2 - p1, s / float(NSUB))
                cur = b["n2"] if s == NSUB else fid(pt)
                subel.append((prev, cur, b)); prev = cur

        ndof = 6 * len(fine)
        K = np.zeros((ndof, ndof)); M = np.zeros((ndof, ndof))
        for (a, bidx, b) in subel:
            T, L = _beam_T(fine[a], fine[bidx])
            kl = _beam_k_local(b["E"], b["G"], b["A"], b["Iy"], b["Iz"], b["J"], L)
            ml = _beam_mass_local(b["rho"] * 1e-3, b["A"], b["J"], L)   # kg->tonne
            dofs = [6 * a + i for i in range(6)] + [6 * bidx + i for i in range(6)]
            ix = np.ix_(dofs, dofs)
            K[ix] += T.T @ kl @ T; M[ix] += T.T @ ml @ T
        free = [d for d in range(ndof) if d not in fixed]
        Kf = K[np.ix_(free, free)]; Mf = M[np.ix_(free, free)]
        try:
            Lc = np.linalg.cholesky(Mf); Lci = np.linalg.inv(Lc)
            Astd = Lci @ Kf @ Lci.T; Astd = 0.5 * (Astd + Astd.T)
            w2, Y = np.linalg.eigh(Astd)
        except Exception:
            err("Modal solve failed - the structure may be a mechanism. Add "
                "supports so it is fully held.")
            return
        order = [i for i in np.argsort(w2) if w2[i] > 1e-6][:nmodes]
        freqs = [float(np.sqrt(w2[i]) / (2 * np.pi)) for i in order]

        # frequencies table
        try:
            sh = doc.getObject("ModalFrequencies") or doc.addObject("Spreadsheet::Sheet", "ModalFrequencies")
            sh.Label = "ModalFrequencies"; sh.clearAll()
            sh.set("A1", "MODAL ANALYSIS - natural frequencies")
            sh.set("A2", "Mode"); sh.set("B2", "Frequency (Hz)"); sh.set("C2", "Period (s)")
            for m, f in enumerate(freqs):
                sh.set("A%d" % (m + 3), str(m + 1))
                sh.set("B%d" % (m + 3), "%.4f" % f)
                sh.set("C%d" % (m + 3), "%.5f" % (1.0 / f if f > 1e-9 else 0.0))
            _grp(doc, RES_GROUP).addObject(sh)
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: modal table failed (%s)\n" % e)

        # display mode 1 as a coloured deformed tube
        doc.openTransaction("DynFrame: modal")
        for o in list(doc.Objects):
            if o.Name.startswith("Mode") and getattr(o, "DiagKind", None):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        msize = _model_size(objs)
        i0 = order[0]
        y = Y[:, i0]
        phi = np.zeros(ndof); phi[free] = Lci.T @ y
        dmax = max((phi[6 * i] ** 2 + phi[6 * i + 1] ** 2 + phi[6 * i + 2] ** 2) ** 0.5
                   for i in range(len(fine))) or 1.0
        sc = 0.1 * msize / dmax
        perbar = []
        for (a, bidx, b) in subel:
            pa = fine[a] + FreeCAD.Vector(phi[6 * a] * sc, phi[6 * a + 1] * sc, phi[6 * a + 2] * sc)
            pb = fine[bidx] + FreeCAD.Vector(phi[6 * bidx] * sc, phi[6 * bidx + 1] * sc, phi[6 * bidx + 2] * sc)
            da = (phi[6 * a] ** 2 + phi[6 * a + 1] ** 2 + phi[6 * a + 2] ** 2) ** 0.5
            db = (phi[6 * bidx] ** 2 + phi[6 * bidx + 1] ** 2 + phi[6 * bidx + 2] ** 2) ** 0.5
            perbar.append(([pa, pb], [da, db]))
        ob = _result_tube(doc, _grp(doc, RES_GROUP), "Mode1", "_mode", perbar,
                          _tube_radius(msize), dmax, True)
        if ob is not None:
            ob.Label = "Mode 1  (%.3f Hz)" % freqs[0]
        doc.commitTransaction(); doc.recompute(); _apply_result_colors(doc)
        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Modal analysis complete.\n\nFirst %d natural frequencies (Hz):\n%s\n\n"
             "Shown: Mode 1 shape. Full list in the 'ModalFrequencies' table.\n\n"
             "(Consistent-mass eigenvalue analysis, each bar meshed into %d "
             "sub-elements.)" %
             (len(freqs), "   ".join("%d: %.3f" % (m + 1, f) for m, f in enumerate(freqs)),
              NSUB))


class BucklingAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("buckling"), "MenuText": "Buckling Analysis",
                "ToolTip": "Linear (Euler) buckling: the critical load factor by "
                           "which the analysed loads must be multiplied to buckle the "
                           "structure, and the buckling mode. Run Calculate first.",
                "Accel": "A, U"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        objs, _k = _analysis_objs(doc)
        bars = [o for o in objs if hasattr(o, "ResN")]
        if not bars:
            info("Run Calculate first - buckling uses the member axial forces from "
                 "the latest analysis.")
            return
        nodes = []

        def nid(p, make=True):
            for i, q in enumerate(nodes):
                if q.distanceToPoint(p) <= 1.0:
                    return i
            if not make:
                return -1
            nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

        bardata = []
        for o in bars:
            sp = _section_props_from_name(_elem_section(o))
            if sp is None:
                continue
            A, Iy, Iz, J, c = sp
            s, e = _elem_ends(o)
            n1, n2 = nid(s), nid(e)
            if n1 == n2:
                continue
            E, Gm, Fy, rho = _material(_elem_material(o))
            bardata.append({"n1": n1, "n2": n2, "A": A, "Iy": Iy, "Iz": Iz, "J": J,
                            "E": E, "G": Gm, "N": float(getattr(o, "ResN", 0.0))})
        if not bardata:
            info("Could not build a model (check section names)."); return

        fixed = set()
        for o in doc.Objects:
            r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
            if r and at is not None:
                i = nid(FreeCAD.Vector(at), make=False)
                if i >= 0:
                    for k, ch in enumerate(r):
                        if ch == "1":
                            fixed.add(6 * i + k)
        if not fixed:
            err("No supports defined. Add supports first, then Buckling Analysis.")
            return
        if all(abs(b["N"]) < 1e-6 for b in bardata):
            info("All members have ~zero axial force, so there is nothing to buckle "
                 "in this load case. Apply axial/compression loads and Calculate.")
            return

        NSUB = 4
        fine = [FreeCAD.Vector(p) for p in nodes]

        def fid(p):
            for i, q in enumerate(fine):
                if q.distanceToPoint(p) <= 0.5:
                    return i
            fine.append(FreeCAD.Vector(p)); return len(fine) - 1

        subel = []
        for b in bardata:
            p1 = nodes[b["n1"]]; p2 = nodes[b["n2"]]; prev = b["n1"]
            for s in range(1, NSUB + 1):
                pt = p1 + vscale(p2 - p1, s / float(NSUB))
                cur = b["n2"] if s == NSUB else fid(pt)
                subel.append((prev, cur, b)); prev = cur

        ndof = 6 * len(fine)
        K = np.zeros((ndof, ndof)); Kg = np.zeros((ndof, ndof))
        for (a, bidx, b) in subel:
            T, L = _beam_T(fine[a], fine[bidx])
            kl = _beam_k_local(b["E"], b["G"], b["A"], b["Iy"], b["Iz"], b["J"], L)
            kgl = _beam_kg_local(b["N"], L)
            dofs = [6 * a + i for i in range(6)] + [6 * bidx + i for i in range(6)]
            ix = np.ix_(dofs, dofs)
            K[ix] += T.T @ kl @ T; Kg[ix] += T.T @ kgl @ T
        free = [d for d in range(ndof) if d not in fixed]
        Kf = K[np.ix_(free, free)]; Kgf = Kg[np.ix_(free, free)]
        try:
            # (K + lam Kg) phi = 0  ->  eig(-K^-1 Kg) = 1/lam ; smallest positive lam
            M = -np.linalg.solve(Kf, Kgf)
            ev, vecs = np.linalg.eig(M)
        except Exception:
            err("Buckling solve failed (unstable model). Add supports and retry.")
            return
        mu = ev.real
        good = [(mu[i], i) for i in range(len(mu))
                if abs(ev[i].imag) < 1e-5 and mu[i] > 1e-9]
        if not good:
            info("No positive buckling factor found - the analysed load case puts "
                 "the members in tension (no buckling)."); return
        good.sort(reverse=True)          # largest mu = smallest lam = critical
        lam_cr = 1.0 / good[0][0]
        i_cr = good[0][1]

        # buckling mode shape as a tube
        doc.openTransaction("DynFrame: buckling")
        for o in list(doc.Objects):
            if o.Name.startswith("Buckling") and getattr(o, "DiagKind", None):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        phi = np.zeros(ndof); phi[free] = vecs[:, i_cr].real
        msize = _model_size(objs)
        dmax = max((phi[6 * i] ** 2 + phi[6 * i + 1] ** 2 + phi[6 * i + 2] ** 2) ** 0.5
                   for i in range(len(fine))) or 1.0
        sc = 0.1 * msize / dmax
        perbar = []
        for (a, bidx, b) in subel:
            pa = fine[a] + FreeCAD.Vector(phi[6 * a] * sc, phi[6 * a + 1] * sc, phi[6 * a + 2] * sc)
            pb = fine[bidx] + FreeCAD.Vector(phi[6 * bidx] * sc, phi[6 * bidx + 1] * sc, phi[6 * bidx + 2] * sc)
            da = (phi[6 * a] ** 2 + phi[6 * a + 1] ** 2 + phi[6 * a + 2] ** 2) ** 0.5
            db = (phi[6 * bidx] ** 2 + phi[6 * bidx + 1] ** 2 + phi[6 * bidx + 2] ** 2) ** 0.5
            perbar.append(([pa, pb], [da, db]))
        ob = _result_tube(doc, _grp(doc, RES_GROUP), "Buckling1", "_buckling", perbar,
                          _tube_radius(msize), dmax, True)
        if ob is not None:
            ob.Label = "Buckling mode 1  (factor %.3f)" % lam_cr
        doc.commitTransaction(); doc.recompute(); _apply_result_colors(doc)
        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        verdict = ("SAFE (factor > 1)" if lam_cr > 1.0 else
                   "UNSAFE - buckles below the applied load!")
        info("Buckling analysis complete.\n\nCritical load factor:  %.3f\n%s\n\n"
             "The structure buckles when the analysed loads are multiplied by "
             "%.3f. Mode 1 shape is shown.\n\n(Linear Euler buckling with the "
             "geometric stiffness from the analysed axial forces; each bar meshed "
             "into %d sub-elements.)" % (lam_cr, verdict, lam_cr, NSUB))


def _cqc_rho(fi, fj, zeta):
    """CQC cross-correlation coefficient between two modes with equal damping
    (Der Kiureghian), used by EN 1998 modal combination. fi, fj are modal
    frequencies; zeta the damping ratio. rho=1 for identical modes, ->0 for
    well-separated ones (so CQC -> SRSS)."""
    if fi <= 0.0 or fj <= 0.0:
        return 1.0 if fi == fj else 0.0
    r = fi / fj
    denom = (1.0 - r * r) ** 2 + 4.0 * zeta * zeta * r * (1.0 + r) ** 2
    if denom <= 0.0:
        return 1.0
    return 8.0 * zeta * zeta * (1.0 + r) * r ** 1.5 / denom


def _cqc_scalar(values, freqs, zeta=0.05):
    """CQC-combine per-mode scalar responses (e.g. base shears)."""
    import math
    s = 0.0
    for i, vi in enumerate(values):
        for j, vj in enumerate(values):
            s += _cqc_rho(freqs[i], freqs[j], zeta) * vi * vj
    return math.sqrt(max(s, 0.0))


def _cqc_vector(vectors, freqs, zeta=0.05):
    """CQC-combine a list of modal response vectors (numpy) into one vector."""
    import numpy as np
    if not vectors:
        return None
    acc = np.zeros_like(np.asarray(vectors[0], dtype=float))
    for i in range(len(vectors)):
        vi = np.asarray(vectors[i], dtype=float)
        for j in range(len(vectors)):
            acc += (_cqc_rho(freqs[i], freqs[j], zeta)
                    * vi * np.asarray(vectors[j], dtype=float))
    return np.sqrt(np.maximum(acc, 0.0))


class ResponseSpectrum:
    def GetResources(self):
        return {"Pixmap": _icon("seismic"), "MenuText": "Seismic (Response Spectrum)",
                "ToolTip": "EC8 response-spectrum seismic analysis: modal masses, "
                           "spectral base shear per mode and SRSS total, and the "
                           "seismic displacement shape. Define supports first.",
                "Accel": "A, Q"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        objs, _k = _analysis_objs(doc)
        if not objs:
            info("No bars/members found. Build a line model first."); return
        vals = form_dialog("Seismic - EC8 Response Spectrum", [
            {"key": "_i", "kind": "info", "default":
             "Elastic/design response spectrum (EN 1998-1, Type 1). Modes combined "
             "by CQC (correlated, better for closely-spaced modes) or SRSS."},
            {"key": "dir", "label": "Direction", "kind": "combo",
             "options": ["X", "Y", "Z"], "default": "X"},
            {"key": "ag", "label": "Ground accel. ag (x g)", "kind": "float", "default": 0.25},
            {"key": "soil", "label": "Ground type", "kind": "combo",
             "options": list(EC8_SOILS.keys()), "default": "B"},
            {"key": "q", "label": "Behaviour factor q", "kind": "float", "default": 1.5},
            {"key": "n", "label": "Modes", "kind": "int", "default": 10},
            {"key": "comb", "label": "Modal combination", "kind": "combo",
             "options": ["CQC", "SRSS"], "default": "CQC"},
            {"key": "zeta", "label": "Damping ratio (%, for CQC)", "kind": "float",
             "default": 5.0},
        ])
        if not vals:
            return
        comp = {"X": 0, "Y": 1, "Z": 2}[vals["dir"]]
        ag = vals["ag"] * 9810.0                     # mm/s^2
        S, TB, TC, TD = EC8_SOILS[vals["soil"]]
        q = max(vals["q"], 1e-3); nmodes = int(vals["n"])

        nodes = []

        def nid(p, make=True):
            for i, qv in enumerate(nodes):
                if qv.distanceToPoint(p) <= 1.0:
                    return i
            if not make:
                return -1
            nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

        bardata = []
        for o in objs:
            sp = _section_props_from_name(_elem_section(o))
            if sp is None:
                continue
            A, Iy, Iz, J, c = sp
            s, e = _elem_ends(o)
            n1, n2 = nid(s), nid(e)
            if n1 == n2:
                continue
            E, Gm, Fy, rho = _material(_elem_material(o))
            bardata.append({"n1": n1, "n2": n2, "A": A, "Iy": Iy, "Iz": Iz, "J": J,
                            "E": E, "G": Gm, "rho": rho})
        if not bardata:
            info("Could not build a model (check section names)."); return
        fixed = set()
        for o in doc.Objects:
            r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
            if r and at is not None:
                i = nid(FreeCAD.Vector(at), make=False)
                if i >= 0:
                    for k, ch in enumerate(r):
                        if ch == "1":
                            fixed.add(6 * i + k)
        if not fixed:
            err("No supports defined. Add supports first, then Seismic.")
            return

        NSUB = 4
        fine = [FreeCAD.Vector(p) for p in nodes]

        def fid(p):
            for i, qv in enumerate(fine):
                if qv.distanceToPoint(p) <= 0.5:
                    return i
            fine.append(FreeCAD.Vector(p)); return len(fine) - 1

        subel = []
        for b in bardata:
            p1 = nodes[b["n1"]]; p2 = nodes[b["n2"]]; prev = b["n1"]
            for s in range(1, NSUB + 1):
                pt = p1 + vscale(p2 - p1, s / float(NSUB))
                cur = b["n2"] if s == NSUB else fid(pt)
                subel.append((prev, cur, b)); prev = cur
        ndof = 6 * len(fine)
        K = np.zeros((ndof, ndof)); M = np.zeros((ndof, ndof))
        for (a, bidx, b) in subel:
            T, L = _beam_T(fine[a], fine[bidx])
            kl = _beam_k_local(b["E"], b["G"], b["A"], b["Iy"], b["Iz"], b["J"], L)
            ml = _beam_mass_local(b["rho"] * 1e-3, b["A"], b["J"], L)
            dofs = [6 * a + i for i in range(6)] + [6 * bidx + i for i in range(6)]
            ix = np.ix_(dofs, dofs)
            K[ix] += T.T @ kl @ T; M[ix] += T.T @ ml @ T
        free = [d for d in range(ndof) if d not in fixed]
        Kf = K[np.ix_(free, free)]; Mf = M[np.ix_(free, free)]
        try:
            Lc = np.linalg.cholesky(Mf); Lci = np.linalg.inv(Lc)
            Astd = Lci @ Kf @ Lci.T; Astd = 0.5 * (Astd + Astd.T)
            w2, Y = np.linalg.eigh(Astd)
        except Exception:
            err("Seismic solve failed - add supports so the model is fully held.")
            return
        order = [i for i in np.argsort(w2) if w2[i] > 1e-6][:nmodes]
        r = np.zeros(ndof)
        for i in range(len(fine)):
            r[6 * i + comp] = 1.0
        rf = r[free]
        Mrf = Mf @ rf
        total_mass = float(rf @ Mrf)
        rows = []; uis = []; Vis = []; fis = []
        for idx in order:
            w = float(np.sqrt(w2[idx])); T = 2 * np.pi / w; f = w / (2 * np.pi)
            phi = Lci.T @ Y[:, idx]            # mass-normalised (phi^T M phi = 1)
            gamma = float(phi @ Mrf)
            meff = gamma * gamma               # tonne
            Sd = _ec8_sd(T, ag, S, TB, TC, TD, q)
            Vi = meff * Sd                     # N
            ui = np.zeros(ndof)
            ui[free] = gamma * phi * Sd / (w * w)   # mm
            uis.append(ui); Vis.append(Vi); fis.append(f)
            rows.append((T, f, 100.0 * meff / total_mass if total_mass > 1e-12 else 0.0,
                         Sd / 9810.0, Vi))
        method = vals.get("comb", "CQC")
        zeta = max(float(vals.get("zeta", 5.0)) / 100.0, 1e-4)
        if method == "CQC" and uis:
            u_srss = _cqc_vector(uis, fis, zeta)
            base_shear = _cqc_scalar(Vis, fis, zeta)
        else:
            method = "SRSS"
            u_srss = np.sqrt(np.sum([u * u for u in uis], axis=0)) if uis else np.zeros(ndof)
            base_shear = float(np.sqrt(sum(v * v for v in Vis)))
        sum_mass = sum(rw[2] for rw in rows)

        # table
        try:
            sh = doc.getObject("Seismic") or doc.addObject("Spreadsheet::Sheet", "Seismic")
            sh.Label = "Seismic"; sh.clearAll()
            sh.set("A1", "SEISMIC - EC8 response spectrum, dir %s, ag=%.2fg, soil %s, q=%.2f"
                   % (vals["dir"], vals["ag"], vals["soil"], q))
            for c, h in zip("ABCDE", ["Mode/T (s)", "Freq (Hz)", "Modal mass %",
                                      "Sd (x g)", "Base shear Vi (N)"]):
                sh.set("%s2" % c, h)
            r2 = 3
            for (T, f, pm, sdg, Vi) in rows:
                sh.set("A%d" % r2, "%.4f" % T); sh.set("B%d" % r2, "%.3f" % f)
                sh.set("C%d" % r2, "%.1f" % pm); sh.set("D%d" % r2, "%.4f" % sdg)
                sh.set("E%d" % r2, "%.0f" % Vi); r2 += 1
            sh.set("A%d" % (r2 + 1), "%s base shear (N)" % method)
            sh.set("E%d" % (r2 + 1), "%.0f" % base_shear)
            sh.set("A%d" % (r2 + 2), "Sum modal mass %%")
            sh.set("C%d" % (r2 + 2), "%.1f" % sum_mass)
            _grp(doc, RES_GROUP).addObject(sh)
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: seismic table failed (%s)\n" % e)

        # SRSS seismic displacement shape
        doc.openTransaction("DynFrame: seismic")
        for o in list(doc.Objects):
            if o.Name.startswith("Seismic") and getattr(o, "DiagKind", None):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        msize = _model_size(objs)
        dmax = max((u_srss[6 * i] ** 2 + u_srss[6 * i + 1] ** 2 + u_srss[6 * i + 2] ** 2) ** 0.5
                   for i in range(len(fine))) or 1.0
        sc = 0.1 * msize / dmax
        perbar = []
        for (a, bidx, b) in subel:
            pa = fine[a] + FreeCAD.Vector(u_srss[6 * a] * sc, u_srss[6 * a + 1] * sc, u_srss[6 * a + 2] * sc)
            pb = fine[bidx] + FreeCAD.Vector(u_srss[6 * bidx] * sc, u_srss[6 * bidx + 1] * sc, u_srss[6 * bidx + 2] * sc)
            da = (u_srss[6 * a] ** 2 + u_srss[6 * a + 1] ** 2 + u_srss[6 * a + 2] ** 2) ** 0.5
            db = (u_srss[6 * bidx] ** 2 + u_srss[6 * bidx + 1] ** 2 + u_srss[6 * bidx + 2] ** 2) ** 0.5
            perbar.append(([pa, pb], [da, db]))
        ob = _result_tube(doc, _grp(doc, RES_GROUP), "SeismicShape", "_seismic", perbar,
                          _tube_radius(msize), dmax, True)
        if ob is not None:
            ob.Label = "Seismic displacement (%s)" % method
        doc.commitTransaction(); doc.recompute(); _apply_result_colors(doc)
        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Seismic response-spectrum analysis complete (EC8, dir %s).\n\n"
             "%s base shear:  %.0f N  (%.1f kN)\n"
             "Modal mass captured:  %.1f%% (%d modes)\n\n"
             "Per-mode period / modal-mass / Sd / base shear in the 'Seismic' "
             "table; the %s seismic displacement shape is shown.\n\n%s" %
             (vals["dir"], method, base_shear, base_shear / 1000.0, sum_mass,
              len(rows), method,
              "" if sum_mass >= 90.0 else "Note: < 90%% modal mass - include more "
              "modes for a code-compliant run."))


def _defl_limits(span):
    """SLS vertical-deflection limits (EN 1990 A1.4 / EN 1993-1-1 7.2): span/250
    for total deflection (appearance/function), span/350 for deflection damaging
    brittle finishes/partitions, span/500 for very sensitive ones."""
    return {"L/250": span / 250.0, "L/350": span / 350.0, "L/500": span / 500.0}


def _member_transverse_deflection(axis_unit, L, ts, us):
    """Maximum deflection of a member PERPENDICULAR to its axis, measured from
    the straight chord between the two end-node displacements (so a rigid-body
    translation or rotation gives zero). axis_unit is the member's unit vector;
    ts the fractional positions (0..1) of the sampled nodes; us their (3,)
    displacement vectors. Returns (delta, span/delta ratio). This is the part a
    per-member SLS deflection check gets wrong, so it is unit-tested."""
    import numpy as np
    a = np.asarray(axis_unit, float)
    i0 = min(range(len(ts)), key=lambda i: ts[i])
    i1 = max(range(len(ts)), key=lambda i: ts[i])
    uA = np.asarray(us[i0], float); uB = np.asarray(us[i1], float)
    dmax = 0.0
    for t, u in zip(ts, us):
        res = np.asarray(u, float) - ((1.0 - t) * uA + t * uB)
        perp = res - (res @ a) * a
        dmax = max(dmax, float(np.linalg.norm(perp)))
    return dmax, (L / dmax if dmax > 1e-12 else 1e12)


class DeflectionCheck:
    def GetResources(self):
        return {"Pixmap": _icon("settle"), "MenuText": "Deflection Check (SLS)",
                "ToolTip": "Check every member's maximum span deflection from the "
                           "latest analysis against the serviceability limit "
                           "(span/250 by default; span/350 or span/500 for brittle "
                           "finishes) - the deflection measured perpendicular to "
                           "the member, relative to its displaced end-to-end chord. "
                           "Run Calculate first.",
                "Accel": "A, D"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        state = _load_state(doc)
        if state is None:
            info("Run Calculate first - the deflection check uses the displacements "
                 "from the latest analysis."); return
        nodes, U, elems, scale, msize, radius = state[:6]
        lim_name, ok = get_item("Deflection Check (SLS)", "Deflection limit:",
                                ["span/250 (appearance)", "span/350 (brittle)",
                                 "span/500 (sensitive)"], 0)
        if not ok:
            return
        denom = {"span/250": 250.0, "span/350": 350.0, "span/500": 500.0}[
            lim_name.split(" ")[0]]
        bars = [o for o in _analysis_objs(doc)[0] if hasattr(o, "ResN") or
                getattr(o, "IsBar", False)]
        if not bars:
            bars = _analysis_objs(doc)[0]

        def nidx(p):
            best = -1; bd = 1e9
            for i, q in enumerate(nodes):
                d = q.distanceToPoint(p)
                if d < bd:
                    bd = d; best = i
            return best if bd <= 1.0 else -1
        rows = []
        for o in bars:
            try:
                A, B = _elem_ends(o)
            except Exception:
                continue
            axis = B - A; L = axis.Length
            if L < 1e-6:
                continue
            ax = unit(axis)
            au = (ax.x, ax.y, ax.z)
            ts = []; us = []
            for i, q in enumerate(nodes):
                w = q - A
                t = (w.x * ax.x + w.y * ax.y + w.z * ax.z) / L
                if -1e-6 <= t <= 1.0 + 1e-6:
                    # on the member axis (perpendicular distance ~ 0)?
                    proj = A + vscale(ax, t * L)
                    if proj.distanceToPoint(q) <= max(1.0, 1e-3 * L):
                        ts.append(min(max(t, 0.0), 1.0))
                        us.append((float(U[6 * i]), float(U[6 * i + 1]), float(U[6 * i + 2])))
            if len(ts) < 2:
                continue
            delta, ratio = _member_transverse_deflection(au, L, ts, us)
            allow = L / denom
            rows.append((getattr(o, "Label", o.Name), L, delta, ratio, allow,
                         delta <= allow))
        if not rows:
            info("No member spans found to check (run Calculate, and use line "
                 "members)."); return
        rows.sort(key=lambda r: (r[5], -r[2]))      # failures first, worst first
        worst = min((r[3] for r in rows), default=1e12)
        nfail = sum(1 for r in rows if not r[5])
        doc.openTransaction("DynFrame: deflection check")
        try:
            s = doc.getObject("Deflections") or doc.addObject("Spreadsheet::Sheet",
                                                              "Deflections")
            s.Label = "Deflections"; s.clearAll()
            s.set("A1", "DEFLECTION CHECK (SLS) - limit %s | %d member(s), %d FAIL"
                  % (lim_name.split(" ")[0], len(rows), nfail))
            for c, hh in zip("ABCDE", ["Member", "Span L (mm)", "Deflection (mm)",
                                       "L / delta", "Verdict"]):
                s.set("%s2" % c, hh)
            r2 = 3
            for (nm, L, d, ratio, allow, okk) in rows:
                s.set("A%d" % r2, str(nm)); s.set("B%d" % r2, "%.0f" % L)
                s.set("C%d" % r2, "%.2f" % d)
                s.set("D%d" % r2, "%.0f" % ratio if ratio < 1e11 else "-")
                s.set("E%d" % r2, "OK" if okk else "FAIL"); r2 += 1
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Deflection check failed: %s" % e); return
        info("Deflection check (SLS, limit %s) - %d member(s), %d FAIL.\n\n"
             "Worst span/deflection ratio = %s (limit %.0f).\n\n"
             "Each member's span deflection (perpendicular to the member, relative "
             "to its displaced end-to-end chord) vs the limit is in the "
             "'Deflections' table. Deflections come from the latest analysis - use "
             "an SLS combination (characteristic/frequent) for a code check." %
             (lim_name.split(" ")[0], len(rows), nfail,
              "%.0f" % worst if worst < 1e11 else "inf", denom))


class CodeCheck:
    def GetResources(self):
        return {"Pixmap": _icon("check"), "MenuText": "Steel Code Check (EC3)",
                "ToolTip": "Verify steel members to EN 1993-1-1: automatic cross-"
                           "section classification (Class 1-4), plastic or elastic "
                           "resistance, flexural buckling (auto curve), lateral-"
                           "torsional buckling via Mcr, and the Annex-B beam-column "
                           "interaction -> utilisation and pass/fail. Run Calculate "
                           "(or Envelope) first.", "Accel": "A, K"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    # moment-distribution presets -> (C1 for LTB, Cm for interaction)
    _SHAPES = {"Uniform (conservative)": (1.0, 1.0),
               "Parabolic / UDL": (1.13, 0.95),
               "Triangular / linear": (1.77, 0.60)}

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        bars = [o for o in doc.Objects if is_analysis_elem(o) and hasattr(o, "ResN")]
        if not bars:
            info("Run Calculate first - the code check uses the latest member "
                 "forces (N, My, Mz) from the analysis.")
            return
        vals = form_dialog("Steel Code Check (EN 1993-1-1)", [
            {"key": "_i", "kind": "info", "default":
             "Full EC3 member check on the latest analysis forces: automatic "
             "section classification, plastic/elastic resistance, flexural + "
             "lateral-torsional buckling and the Annex-B interaction. Buckling "
             "curves are assigned automatically from the section type."},
            {"key": "gm0", "label": "gamma_M0", "kind": "float", "default": 1.0},
            {"key": "gm1", "label": "gamma_M1", "kind": "float", "default": 1.0},
            {"key": "ky", "label": "Buckling length factor, major axis", "kind": "float", "default": 1.0},
            {"key": "kz", "label": "Buckling length factor, minor axis", "kind": "float", "default": 1.0},
            {"key": "klt", "label": "LTB length factor (restraint spacing / L)", "kind": "float", "default": 1.0},
            {"key": "shape", "label": "Moment distribution", "kind": "combo",
             "options": list(self._SHAPES.keys()), "default": "Uniform (conservative)"},
            {"key": "susc", "label": "LTB-susceptible (torsion)", "kind": "combo",
             "options": ["Auto", "Yes", "No (restrained)"], "default": "Auto"},
        ])
        if not vals:
            return
        gM0 = max(vals["gm0"], 1e-6); gM1 = max(vals["gm1"], 1e-6)
        ky = max(vals["ky"], 1e-6); kz = max(vals["kz"], 1e-6)
        klt = max(vals["klt"], 1e-6)
        C1, Cm = self._SHAPES.get(vals["shape"], (1.0, 1.0))
        susc = {"Auto": None, "Yes": True, "No (restrained)": False}[vals.get("susc", "Auto")]
        rows = []; worst = 0.0; worstbar = "-"; skipped = 0; cls4 = 0
        doc.openTransaction("DynFrame: code check")
        for o in bars:
            db = _section_db(_elem_section(o))
            E, Gm, Fy, rho = _material(_elem_material(o))
            if db is None:
                skipped += 1
                continue
            N = getattr(o, "ResN", 0.0)
            My = getattr(o, "ResMy", 0.0); Mz = getattr(o, "ResMz", 0.0)
            L = getattr(o, "ResL", 1000.0)
            r = _ec3_member_check(db, Fy, E, Gm, N, My, Mz, ky * L, kz * L,
                                  klt * L, C1, Cm, Cm, Cm, gM0, gM1, susc)
            U = r["U"]
            if r["cls"] >= 4:
                cls4 += 1
            verdict = "OK" if U <= 1.0 else "FAIL"
            rows.append((str(o.Label), _elem_section(o), r["cls"], N / 1e3,
                         r["Mmaj"] / 1e6, r["Mmin"] / 1e6, r["chiLT"],
                         r["U61"], r["U62"], U, r["gov"], verdict))
            if U > worst:
                worst = U; worstbar = str(o.Label)
            try:
                uc = max(0.0, min(1.0, U))
                o.ViewObject.LineColor = (float(uc), float(1.0 - uc), 0.1)
                o.ViewObject.LineWidth = 4
            except Exception:
                pass
        try:
            sh = doc.getObject("CodeCheck") or doc.addObject("Spreadsheet::Sheet", "CodeCheck")
            sh.Label = "CodeCheck"; sh.clearAll()
            sh.set("A1", "STEEL CODE CHECK (EN 1993-1-1) - gammaM0=%.2f gammaM1=%.2f, "
                   "moment shape: %s (C1=%.2f, Cm=%.2f)" % (gM0, gM1, vals["shape"], C1, Cm))
            heads = ["Member", "Section", "Class", "N (kN)", "My,maj (kNm)",
                     "Mz,min (kNm)", "chi_LT", "U (6.61)", "U (6.62)",
                     "U (gov)", "Governs", "Verdict"]
            for c, h in zip("ABCDEFGHIJKL", heads):
                sh.set("%s2" % c, h)
            rr = 3
            for row in rows:
                for c, v in zip("ABCDEFGHIJKL", row):
                    sh.set("%s%d" % (c, rr), ("%.4g" % v if isinstance(v, float) else str(v)))
                rr += 1
            _grp(doc, RES_GROUP).addObject(sh)
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: code-check table failed (%s)\n" % e)
        doc.commitTransaction(); doc.recompute()
        notes = ""
        if skipped:
            notes += ("\n%d member(s) skipped (non-steel material or section not "
                      "in the library)." % skipped)
        if cls4:
            notes += ("\n%d Class-4 member(s): checked on gross elastic properties "
                      "(effective-section reduction not applied - treat as "
                      "indicative and verify separately)." % cls4)
        info("Steel code check complete (EN 1993-1-1).\n\n"
             "Members checked: %d\nMax utilisation: %.2f  (on %s)\nOverall: %s\n\n"
             "Each member is classified (Class 1-4) and checked for cross-section "
             "resistance, flexural buckling (curve chosen automatically from the "
             "section), lateral-torsional buckling via the elastic critical moment "
             "Mcr, and the Annex-B interaction equations 6.61/6.62. Members are "
             "coloured green->red by utilisation; the 'CodeCheck' table lists class, "
             "chi_LT and both interaction utilisations.%s\n\nSection properties use "
             "the idealised (sharp-corner) profile, so the torsion constant is "
             "marginally conservative versus a rolled section with root fillets." %
             (len(rows), worst, worstbar,
              "PASS" if worst <= 1.0 else "FAIL - over-stressed members", notes))


class PlateReinfEC2:
    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Plate Reinforcement (EC2)",
                "ToolTip": "Required slab reinforcement to EN 1992-1-1 from the "
                           "Wood-Armer design moments of the latest analysis: area "
                           "of steel (mm2/m) top and bottom in X and Y for each "
                           "plate, with minimum-steel and section-adequacy checks. "
                           "Run Calculate first.", "Accel": "A, R"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        plates = [o for o in doc.Objects if hasattr(o, "ShellWAxb")]
        if not plates:
            info("Run Calculate on a model with plates first - the reinforcement "
                 "design uses the Wood-Armer plate moments from the analysis.")
            return
        grades = list(CONCRETE_GRADES.keys())
        vals = form_dialog("Plate Reinforcement (EN 1992-1-1)", [
            {"key": "_i", "kind": "info", "default":
             "Required orthogonal reinforcement from the Wood-Armer design "
             "moments: area of steel (mm2/m) for the bottom (sagging) and top "
             "(hogging) face in X and Y, per plate, singly reinforced. Minimum "
             "steel (9.2.1.1) is applied; a section needing compression steel is "
             "flagged. The slab thickness is taken from each plate."},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": grades, "default": "C30/37"},
            {"key": "fyk", "label": "Steel fyk (MPa)", "kind": "float", "default": 500.0},
            {"key": "cover", "label": "Cover to bar (mm)", "kind": "float", "default": 25.0},
            {"key": "dia", "label": "Bar diameter (mm)", "kind": "float", "default": 12.0},
            {"key": "gc", "label": "gamma_c (concrete)", "kind": "float", "default": 1.5},
            {"key": "gs", "label": "gamma_s (steel)", "kind": "float", "default": 1.15},
            {"key": "acc", "label": "alpha_cc", "kind": "float", "default": 0.85},
        ])
        if not vals:
            return
        fck = CONCRETE_GRADES.get(vals["grade"], 30.0)
        fyk = float(vals["fyk"]); cover = float(vals["cover"]); dia = float(vals["dia"])
        gc = float(vals["gc"]); gs = float(vals["gs"]); acc = float(vals["acc"])
        doc.openTransaction("DynFrame: plate reinforcement (EC2)")
        try:
            sh = (doc.getObject("PlateSteel")
                  or doc.addObject("Spreadsheet::Sheet", "PlateSteel"))
            sh.Label = "PlateSteel"; sh.clearAll()
            sh.set("A1", "SLAB REINFORCEMENT (EN 1992-1-1) - %s, fyk=%g, cover=%g, "
                   "dia=%g mm" % (vals["grade"], fyk, cover, dia))
            for c, h in zip("ABCDEFGHI",
                            ["Plate", "h (mm)", "As x bot (mm2/m)", "As y bot (mm2/m)",
                             "As x top (mm2/m)", "As y top (mm2/m)", "d bot (mm)",
                             "d top (mm)", "Notes"]):
                sh.set("%s2" % c, h)
            r = 3; worst_note = ""
            peaks = {}
            for o in plates:
                h = float(getattr(o, "ShellThk", 0.0))
                mxb = float(getattr(o, "ShellWAxb", 0.0))
                myb = float(getattr(o, "ShellWAyb", 0.0))
                mxt = float(getattr(o, "ShellWAxt", 0.0))
                myt = float(getattr(o, "ShellWAyt", 0.0))
                asxb, dxb, nxb = _ec2_slab_as(mxb, h, cover, dia, 0, fck, fyk, gc, gs, acc)
                asyb, dyb, nyb = _ec2_slab_as(myb, h, cover, dia, 1, fck, fyk, gc, gs, acc)
                asxt, dxt, nxt = _ec2_slab_as(mxt, h, cover, dia, 0, fck, fyk, gc, gs, acc)
                asyt, dyt, nyt = _ec2_slab_as(myt, h, cover, dia, 1, fck, fyk, gc, gs, acc)
                notes = "; ".join(sorted(set(n for n in (nxb, nyb, nxt, nyt) if n)))
                if "compression" in notes:
                    worst_note = notes
                row = [str(o.Label), h, asxb, asyb, asxt, asyt, dxb, dyb, notes or "-"]
                for c, v in zip("ABCDEFGHI", row):
                    sh.set("%s%d" % (c, r),
                           ("%.4g" % v if isinstance(v, float) else str(v)))
                r += 1
                peaks[str(o.Label)] = max(asxb, asyb, asxt, asyt)
            rg = _grp(doc, RES_GROUP)
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
            doc.commitTransaction(); doc.recompute()
            govp = max(peaks.values()) if peaks else 0.0
            govn = max(peaks, key=peaks.get) if peaks else "-"
            info("Slab reinforcement (EN 1992-1-1) computed for %d plate(s).\n\n"
                 "Grade %s (fck=%g), fyk=%g, cover=%g, bar dia=%g mm.\n"
                 "Governing area of steel: %.0f mm2/m  (plate '%s').\n\n"
                 "See the 'PlateSteel' table for As top/bottom in X and Y per "
                 "plate. As is the Wood-Armer demand divided by fyd and the lever "
                 "arm; minimum steel per 9.2.1.1 is applied.%s"
                 % (len(plates), vals["grade"], fck, fyk, cover, dia, govp, govn,
                    ("\n\nWARNING: " + worst_note) if worst_note else ""))
        except Exception as e:
            doc.abortTransaction()
            err("Reinforcement design failed: %s" % e)


class PunchingEC2:
    def GetResources(self):
        return {"Pixmap": _icon("punch"), "MenuText": "Punching Shear (EC2)",
                "ToolTip": "EN 1992-1-1 punching-shear check at slab-column "
                           "junctions: the design column load over the 2d control "
                           "perimeter vs v_Rd,c (and the column face vs the crushing "
                           "limit). Select the columns and run Calculate first so it "
                           "reads their axial loads.", "Accel": "A, P"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        sel = [m for m in selected_elems() if is_bar(m) and hasattr(m, "ResN")]
        if not sel:
            sel = [o for o in doc.Objects if is_analysis_elem(o) and hasattr(o, "ResN")
                   and self._vertical(o)]
        if not sel:
            info("Select the column(s) supporting the slab (or run a gravity "
                 "Calculate first). Punching uses each column's axial load N_Ed.")
            return
        grades = list(CONCRETE_GRADES.keys())
        vals = form_dialog("Punching Shear (EN 1992-1-1) - %d column(s)" % len(sel), [
            {"key": "_i", "kind": "info", "default":
             "Checks each selected column's axial load as the punching force over "
             "the control perimeter at 2d from the column face. Needs punching "
             "reinforcement when v_Ed > v_Rd,c; the column face is also checked "
             "against the crushing limit v_Rd,max. Column load = |N| from the "
             "analysis (override below if you prefer)."},
            {"key": "pos", "label": "Column position", "kind": "combo",
             "options": list(PUNCH_BETA.keys()), "default": "Internal"},
            {"key": "c1", "label": "Column size c1 (mm)", "kind": "float", "default": 400.0},
            {"key": "c2", "label": "Column size c2 (mm)", "kind": "float", "default": 400.0},
            {"key": "d", "label": "Slab effective depth d (mm)", "kind": "float", "default": 200.0},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": grades, "default": "C30/37"},
            {"key": "rhol", "label": "Reinf. ratio rho_l (0..0.02)", "kind": "float",
             "default": 0.01, "decimals": 4},
            {"key": "ved", "label": "V_Ed override (N, 0 = use column N)",
             "kind": "float", "default": 0.0},
        ])
        if not vals:
            return
        beta = PUNCH_BETA.get(vals["pos"], 1.15)
        fck = CONCRETE_GRADES.get(vals["grade"], 30.0)
        c1 = float(vals["c1"]); c2 = float(vals["c2"]); d = float(vals["d"])
        rhol = float(vals["rhol"]); override = float(vals["ved"])
        doc.openTransaction("DynFrame: punching shear (EC2)")
        try:
            sh = (doc.getObject("PunchingShear")
                  or doc.addObject("Spreadsheet::Sheet", "PunchingShear"))
            sh.Label = "PunchingShear"; sh.clearAll()
            sh.set("A1", "PUNCHING SHEAR (EN 1992-1-1) - %s, %s, d=%g, c=%gx%g, "
                   "rho_l=%.4f" % (vals["pos"], vals["grade"], d, c1, c2, rhol))
            for c, h in zip("ABCDEFGH",
                            ["Column", "V_Ed (kN)", "u1 (mm)", "v_Ed (MPa)",
                             "v_Rd,c (MPa)", "Util", "Face v/v_Rd,max", "Verdict"]):
                sh.set("%s2" % c, h)
            r = 3; worst = 0.0; wn = "-"
            for o in sel:
                ved = override if override > 0 else abs(float(getattr(o, "ResN", 0.0)))
                res = _punching(ved, c1, c2, d, fck, rhol, beta)
                verdict = ("OK" if res["util"] <= 1.0 and res["crush"] <= 1.0
                           else ("CRUSHING" if res["crush"] > 1.0
                                 else "needs punching reinf."))
                row = [str(o.Label), "%.1f" % (ved / 1000.0), "%.0f" % res["u1"],
                       "%.3f" % res["vEd"], "%.3f" % res["vRdc"],
                       "%.2f" % res["util"], "%.2f" % res["crush"], verdict]
                for c, v in zip("ABCDEFGH", row):
                    sh.set("%s%d" % (c, r), v)
                r += 1
                if res["util"] > worst:
                    worst = res["util"]; wn = str(o.Label)
            rg = _grp(doc, RES_GROUP)
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
            doc.commitTransaction(); doc.recompute()
            info("Punching shear (EN 1992-1-1) checked on %d column(s), %s.\n\n"
                 "Grade %s, d = %g mm, column %g x %g mm, rho_l = %.4f.\n"
                 "Worst utilisation v_Ed/v_Rd,c = %.2f (column '%s').\n\n%s\n\nSee "
                 "the 'PunchingShear' table. Where util > 1 the slab needs punching "
                 "reinforcement (links/studs) or a thicker slab / drop panel; where "
                 "the face ratio > 1 the section is crushing - enlarge the column or "
                 "slab." % (len(sel), vals["pos"], vals["grade"], d, c1, c2, rhol,
                            worst, wn,
                            "All columns OK." if worst <= 1.0
                            else "Some columns need punching reinforcement."))
        except Exception as e:
            doc.abortTransaction()
            err("Punching check failed: %s" % e)

    @staticmethod
    def _vertical(o):
        try:
            s, e = _elem_ends(o)
            L = s.distanceToPoint(e)
            return L > 1e-6 and abs(e.z - s.z) / L > 0.7
        except Exception:
            return False


# ── EC2 reinforced-concrete beam design (flexure + shear) ────────
def _rc_beam_flexure(M, b, d, fck, fyk, d2=50.0, gc=1.5, gs=1.15):
    """EN 1992-1-1 rectangular-stress-block design of a rectangular RC beam for a
    sagging moment M (N.mm). b, d, d2 in mm; fck, fyk in MPa. Singly reinforced
    while K = M/(b d^2 fck) <= K' = 0.167; above that a doubly-reinforced section
    adds compression steel. Returns As (tension), As2 (compression), lever arm z,
    neutral-axis depth x, and the EC2 min/max steel. Validated to the standard
    textbook hand calc."""
    import math
    M = abs(float(M))
    Kbal = 0.167
    K = M / (b * d * d * fck) if (b * d * d * fck) > 0 else 0.0
    res = {"K": K, "Kbal": Kbal, "doubly": False, "As2": 0.0}
    if K <= Kbal:
        z = min(d * (0.5 + math.sqrt(max(0.25 - K / 1.134, 0.0))), 0.95 * d)
        As = M / (0.87 * fyk * z)
        res.update({"As": As, "z": z, "x": (d - z) / 0.4})
    else:
        res["doubly"] = True
        z = min(d * (0.5 + math.sqrt(max(0.25 - Kbal / 1.134, 0.0))), 0.95 * d)
        As2 = (K - Kbal) * fck * b * d * d / (0.87 * fyk * (d - d2))
        As = Kbal * fck * b * d * d / (0.87 * fyk * z) + As2
        res.update({"As": As, "z": z, "x": (d - z) / 0.4, "As2": As2})
    fctm = _fctm(fck)
    res["As_min"] = max(0.26 * fctm / fyk * b * d, 0.0013 * b * d)
    res["As_max"] = 0.04 * b * d
    res["As_req"] = max(res["As"], res["As_min"])
    res["over"] = res["As"] > res["As_max"]
    return res


def _rc_beam_shear(V, bw, d, fck, fyk, As_prov, gc=1.5, gs=1.15, cot=2.5):
    """EN 1992-1-1 6.2 shear: concrete resistance V_Rd,c (6.2.2) and, when V_Ed
    exceeds it, designed vertical links by the variable-strut method (6.2.3) -
    the required link area per unit length Asw/s and the crushing limit
    V_Rd,max. V in N; lengths mm; stresses MPa. Validated to the hand calc."""
    import math
    V = abs(float(V))
    fcd = fck / gc
    fywd = fyk / gs
    k = min(1.0 + math.sqrt(200.0 / d), 2.0)
    rho1 = min(As_prov / (bw * d) if bw * d > 0 else 0.0, 0.02)
    vRdc = (0.18 / gc) * k * (100.0 * rho1 * fck) ** (1.0 / 3.0)
    vmin = 0.035 * k ** 1.5 * math.sqrt(fck)
    VRdc = max(vRdc, vmin) * bw * d
    z = 0.9 * d
    nu1 = 0.6 * (1.0 - fck / 250.0)
    cot = max(1.0, min(float(cot), 2.5)); tan = 1.0 / cot
    VRdmax = bw * z * nu1 * fcd / (cot + tan)
    asw_s_min = 0.08 * math.sqrt(fck) / fyk * bw        # rho_w,min * bw
    res = {"VRdc": VRdc, "VRdmax": VRdmax, "k": k, "rho1": rho1, "z": z,
           "cot": cot, "ok": V <= VRdmax}
    if V <= VRdc:
        res["links"] = "minimum"
        res["asw_s"] = asw_s_min
    else:
        res["links"] = "designed"
        res["asw_s"] = max(V / (z * fywd * cot), asw_s_min)
    return res


def _rc_column_nm_point(x, b, h, d2, As_tot, fck, fyk, gc=1.5, gs=1.15):
    """One point (N, M) on the N-M interaction of a symmetrically-reinforced
    rectangular RC column, for a neutral-axis depth x (mm). Rectangular stress
    block (eta=1, lambda=0.8), steel on the two faces (As_tot split equally),
    strains from plane sections with eps_cu=0.0035, steel capped at +/-fyd.
    Compression is positive; M is taken about the section centroid (h/2)."""
    import math
    fcd = fck / gc; fyd = fyk / gs; Es = 200000.0; ecu = 0.0035
    As = As_tot / 2.0
    d_comp = d2; d_tens = h - d2
    a = min(0.8 * x, h)
    Fc = fcd * b * a
    def sforce(di, Asi):
        eps = ecu * (x - di) / x if x > 1e-9 else -ecu
        return Asi * max(-fyd, min(fyd, Es * eps))
    Fs1 = sforce(d_comp, As); Fs2 = sforce(d_tens, As)
    N = Fc + Fs1 + Fs2
    M = (Fc * (h / 2.0 - a / 2.0) + Fs1 * (h / 2.0 - d_comp)
         + Fs2 * (h / 2.0 - d_tens))
    return N, M


def _rc_column_MRd(N_Ed, b, h, d2, As_tot, fck, fyk, gc=1.5, gs=1.15, nx=600):
    """Moment capacity M_Rd (N.mm) of a symmetric RC column section at axial load
    N_Ed (N), by scanning the neutral axis and interpolating the interaction
    curve. 0 if N_Ed exceeds the squash load. Max over crossings = the capacity."""
    xs = (h * 3.0 * (i + 1) / nx for i in range(nx))
    prev = None; best = 0.0
    for x in xs:
        cur = _rc_column_nm_point(x, b, h, d2, As_tot, fck, fyk, gc, gs)
        if prev is not None:
            N0, M0 = prev; N1, M1 = cur
            if N1 != N0 and (N0 - N_Ed) * (N1 - N_Ed) <= 0.0:
                t = (N_Ed - N0) / (N1 - N0)
                best = max(best, abs(M0 + t * (M1 - M0)))
        prev = cur
    return best


def _biaxial_exponent(n):
    """EN 1992-1-1 5.8.9 exponent a for the biaxial interaction, from the axial
    ratio n = N_Ed/N_Rd: a = 1.0 at n<=0.1, 1.5 at 0.7, 2.0 at 1.0 (linear)."""
    if n <= 0.1:
        return 1.0
    if n >= 1.0:
        return 2.0
    return (1.0 + (n - 0.1) / 0.6 * 0.5) if n <= 0.7 else (1.5 + (n - 0.7) / 0.3 * 0.5)


def _biaxial_check(N_Ed, Mz, My, MRdz, MRdy, NRd):
    """EN 1992-1-1 5.8.9 biaxial-bending interaction:
    (M_Edz/M_Rdz)^a + (M_Edy/M_Rdy)^a <= 1."""
    n = N_Ed / NRd if NRd > 1e-9 else 0.0
    a = _biaxial_exponent(n)
    if MRdz <= 1e-9 or MRdy <= 1e-9:
        return {"a": a, "util": 99.9, "ok": False}
    util = (Mz / MRdz) ** a + (My / MRdy) ** a
    return {"a": a, "util": util, "ok": util <= 1.0}


def _column_slenderness(N_Ed, Ac, fck, l0, h, gc=1.5, A=0.7, B=1.1, Cf=0.7):
    """EN 1992-1-1 5.8.3 slenderness of a rectangular column about the h axis:
    lambda = l0/i (i = h/sqrt(12)) against lambda_lim = 20 A B C / sqrt(n),
    n = N_Ed/(Ac fcd). slender when lambda > lambda_lim."""
    import math
    fcd = fck / gc
    n = N_Ed / (Ac * fcd) if Ac * fcd > 0 else 0.0
    i = h / math.sqrt(12.0)
    lam = l0 / i if i > 0 else 0.0
    lam_lim = 20.0 * A * B * Cf / math.sqrt(n) if n > 0 else 1e9
    return {"n": n, "i": i, "lambda": lam, "lambda_lim": lam_lim,
            "slender": lam > lam_lim}


def _column_2nd_order(N_Ed, l0, d, As, Ac, fck, fyk, gc=1.5, gs=1.15, c=10.0,
                      Kphi=1.0):
    """EN 1992-1-1 5.8.8 nominal-curvature second-order moment M2 = N_Ed e2,
    e2 = (1/r) l0^2/c, 1/r = Kr Kphi (eps_yd)/(0.45 d), Kr = (nu-n)/(nu-nbal)
    with nu = 1+omega, omega = As fyd/(Ac fcd), nbal = 0.4."""
    fcd = fck / gc; fyd = fyk / gs; Es = 200000.0
    n = N_Ed / (Ac * fcd) if Ac * fcd > 0 else 0.0
    omega = As * fyd / (Ac * fcd) if Ac * fcd > 0 else 0.0
    nu = 1.0 + omega
    Kr = (nu - n) / (nu - 0.4) if (nu - 0.4) > 1e-9 else 1.0
    Kr = min(max(Kr, 0.0), 1.0)
    inv_r = Kr * Kphi * (fyd / Es) / (0.45 * d) if d > 0 else 0.0
    e2 = inv_r * l0 * l0 / c
    return {"n": n, "omega": omega, "Kr": Kr, "e2": e2, "M2": N_Ed * e2}


def _pad_footing(N_sls, M_sls, N_uls, B, L, h, c, fck, fyk, cover, bar, q_allow,
                 gc=1.5, gs=1.15):
    """EN 1992-1-1 / EN 1997 pad (isolated) footing under a square column. Forces
    in N (N_sls/N_uls already include any self-weight the caller added), M in
    N.mm, lengths in mm, q_allow (allowable bearing) in MPa. Returns the bearing
    pressures and required area (SLS), the cantilever design moment + flexural
    steel per metre, the one-way shear check and the punching check at 2d."""
    import math
    A = B * L
    e = M_sls / N_sls if N_sls > 1e-9 else 0.0
    p_avg = N_sls / A
    if e <= L / 6.0:
        p_max = p_avg * (1.0 + 6.0 * e / L); p_min = p_avg * (1.0 - 6.0 * e / L)
    else:                                    # partial bearing (resultant outside middle third)
        p_max = 2.0 * N_sls / (3.0 * B * (L / 2.0 - e)); p_min = 0.0
    A_req = N_sls / q_allow
    d = h - cover - 0.5 * bar
    p_u = N_uls / A
    a = (L - c) / 2.0                        # cantilever span from the column face
    M_strip = p_u * a * a / 2.0 * 1000.0     # N.mm for a 1 m wide strip
    fx = _rc_beam_flexure(M_strip, 1000.0, d, fck, fyk)
    V1 = p_u * max(a - d, 0.0) * B           # one-way shear at d from the face, across B
    sh = _rc_beam_shear(V1, B, d, fck, fyk, fx["As_req"] * B / 1000.0)
    u1 = 4.0 * c + 4.0 * math.pi * d         # punching control perimeter at 2d
    a_in = c * c + 4.0 * c * (2.0 * d) + math.pi * (2.0 * d) ** 2
    Vred = N_uls - p_u * a_in                # reduce for upward pressure inside u1
    vEd = Vred / (u1 * d) if u1 * d > 0 else 0.0
    k = min(1.0 + math.sqrt(200.0 / d), 2.0)
    rho = min(fx["As_req"] / (1000.0 * d), 0.02)
    vRdc = max((0.18 / gc) * k * (100.0 * rho * fck) ** (1.0 / 3.0),
               0.035 * k ** 1.5 * math.sqrt(fck))
    return {"p_avg": p_avg, "p_max": p_max, "p_min": p_min, "A_req": A_req,
            "bearing_ok": p_max <= q_allow, "d": d, "a": a, "M_strip": M_strip,
            "As": fx["As_req"], "As_min": fx["As_min"], "shear": sh, "u1": u1,
            "vEd_punch": vEd, "vRdc_punch": vRdc, "punch_ok": vEd <= vRdc}


class RcBeamEC2:
    _GRADES = {"C20/25": (20.0, 2.2), "C25/30": (25.0, 2.6), "C30/37": (30.0, 2.9),
               "C35/45": (35.0, 3.2), "C40/50": (40.0, 3.5), "C45/55": (45.0, 3.8),
               "C50/60": (50.0, 4.1)}

    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "RC Beam Design (EC2)",
                "ToolTip": "Design a rectangular reinforced-concrete beam to "
                           "EN 1992-1-1: tension (and, if needed, compression) "
                           "steel for the bending moment by the rectangular stress "
                           "block, and vertical shear links by the variable-strut "
                           "method, with EC2 minimum/maximum steel - the way Robot "
                           "does RC member design.",
                "Accel": "A, R"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        grades = list(self._GRADES.keys())
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Rectangular RC beam design to EN 1992-1-1. Enter the section and the "
             "design forces (ULS envelope values). Flexure: rectangular stress "
             "block (doubly reinforced if K>0.167). Shear: variable-strut links."},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": grades, "default": "C30/37"},
            {"key": "fyk", "label": "Steel fyk (MPa)", "kind": "float", "default": 500.0},
            {"key": "b", "label": "Width b (mm)", "kind": "float", "default": 300.0},
            {"key": "h", "label": "Height h (mm)", "kind": "float", "default": 500.0},
            {"key": "cover", "label": "Cover to link (mm)", "kind": "float", "default": 35.0},
            {"key": "link", "label": "Link diameter (mm)", "kind": "float", "default": 8.0},
            {"key": "bar", "label": "Main bar diameter (mm)", "kind": "float", "default": 20.0},
            {"key": "M", "label": "Design moment M_Ed (kN.m)", "kind": "float", "default": 250.0},
            {"key": "V", "label": "Design shear V_Ed (kN)", "kind": "float", "default": 300.0},
        ]
        vals = form_dialog("RC Beam Design (EC2)", fields)
        if not vals:
            return
        fck = self._GRADES[vals["grade"]][0]
        fyk = float(vals["fyk"]); b = float(vals["b"]); h = float(vals["h"])
        d = h - float(vals["cover"]) - float(vals["link"]) - 0.5 * float(vals["bar"])
        if d <= 0:
            info("Effective depth is non-positive - check the section/cover."); return
        d2 = float(vals["cover"]) + float(vals["link"]) + 0.5 * float(vals["bar"])
        M = float(vals["M"]) * 1e6        # kN.m -> N.mm
        V = float(vals["V"]) * 1e3        # kN -> N
        fx = _rc_beam_flexure(M, b, d, fck, fyk, d2)
        sh = _rc_beam_shear(V, b, d, fck, fyk, fx["As_req"])
        doc.openTransaction("DynFrame: RC beam design")
        try:
            s = doc.getObject("RcBeam") or doc.addObject("Spreadsheet::Sheet", "RcBeam")
            s.Label = "RcBeam"; s.clearAll()
            s.set("A1", "RC BEAM EC2 - %s, fyk=%g, %gx%g mm, d=%.0f mm | M=%g kNm, "
                  "V=%g kN" % (vals["grade"], fyk, b, h, d, vals["M"], vals["V"]))
            rows = [
                ("K = M/bd^2 fck", "%.4f  (K' = %.3f%s)" % (fx["K"], fx["Kbal"],
                 ", doubly reinforced" if fx["doubly"] else "")),
                ("Lever arm z (mm)", "%.1f" % fx["z"]),
                ("Neutral axis x (mm)", "%.1f  (x/d = %.3f)" % (fx["x"], fx["x"] / d)),
                ("As tension required (mm2)", "%.0f" % fx["As_req"]),
                ("As compression (mm2)", "%.0f" % fx["As2"]),
                ("As,min / As,max (mm2)", "%.0f / %.0f" % (fx["As_min"], fx["As_max"])),
                ("V_Rd,c no links (kN)", "%.1f" % (sh["VRdc"] / 1e3)),
                ("V_Rd,max crushing (kN)", "%.1f  %s" % (sh["VRdmax"] / 1e3,
                 "OK" if sh["ok"] else "SECTION TOO SMALL")),
                ("Links (%s)" % sh["links"], "Asw/s = %.3f mm2/mm = %.0f mm2/m"
                 % (sh["asw_s"], sh["asw_s"] * 1000.0)),
            ]
            for i, (a, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, a); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("RC beam design failed: %s" % e); return
        link_leg = 3.14159 * (float(vals["link"]) / 2.0) ** 2 * 2.0   # 2-leg area
        smax = link_leg / sh["asw_s"] if sh["asw_s"] > 0 else 0.0
        info("RC beam (EN 1992-1-1) - %s, %g x %g mm, d = %.0f mm.\n\n"
             "BENDING  M_Ed = %g kNm:  K = %.3f%s\n"
             "  tension steel As = %.0f mm2  (min %.0f, max %.0f)%s\n"
             "  lever arm z = %.0f mm, x/d = %.2f\n\n"
             "SHEAR  V_Ed = %g kN:  V_Rd,c = %.0f kN, V_Rd,max = %.0f kN %s\n"
             "  %s links: Asw/s = %.0f mm2/m  (e.g. H%g 2-leg at ~%.0f mm)\n\n"
             "See the 'RcBeam' table. Design values are ULS envelope forces." %
             (vals["grade"], b, h, d, vals["M"], fx["K"],
              " (doubly reinforced)" if fx["doubly"] else "", fx["As_req"],
              fx["As_min"], fx["As_max"],
              "  As2 = %.0f mm2" % fx["As2"] if fx["doubly"] else "",
              fx["z"], fx["x"] / d, vals["V"], sh["VRdc"] / 1e3, sh["VRdmax"] / 1e3,
              "OK" if sh["ok"] else "- SECTION TOO SMALL, increase it",
              sh["links"], sh["asw_s"] * 1000.0, float(vals["link"]), smax))


class RcColumnEC2:
    _GRADES = RcBeamEC2._GRADES

    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "RC Column Design (EC2)",
                "ToolTip": "Check / design a symmetrically-reinforced rectangular "
                           "RC column to EN 1992-1-1: the N-M interaction capacity "
                           "at the design axial load, the utilisation for the "
                           "design moment, and the steel required if it fails - "
                           "Robot-style RC column design.",
                "Accel": "A, C"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        grades = list(self._GRADES.keys())
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Symmetric rectangular RC column to EN 1992-1-1 (bars on the two "
             "faces perpendicular to bending). Enter the section, the bars and the "
             "design N_Ed (compression +) and M_Ed. Reports the N-M capacity, the "
             "utilisation, and the steel needed if it fails."},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": grades, "default": "C30/37"},
            {"key": "fyk", "label": "Steel fyk (MPa)", "kind": "float", "default": 500.0},
            {"key": "b", "label": "Width b (mm)", "kind": "float", "default": 300.0},
            {"key": "h", "label": "Depth h, in bending plane (mm)", "kind": "float",
             "default": 400.0},
            {"key": "cover", "label": "Cover to link (mm)", "kind": "float", "default": 35.0},
            {"key": "link", "label": "Link diameter (mm)", "kind": "float", "default": 8.0},
            {"key": "bar", "label": "Bar diameter (mm)", "kind": "float", "default": 20.0},
            {"key": "nbar", "label": "Total number of bars (split both faces)",
             "kind": "int", "default": 6, "min": 4, "max": 40},
            {"key": "N", "label": "Design axial N_Ed (kN, compression +)",
             "kind": "float", "default": 960.0},
            {"key": "M", "label": "Moment Mz about the h axis (kN.m)", "kind": "float",
             "default": 150.0},
            {"key": "My", "label": "Moment My about the b axis (kN.m, 0 = uniaxial)",
             "kind": "float", "default": 0.0},
            {"key": "l0", "label": "Effective length l0 (mm, 0 = ignore slenderness)",
             "kind": "float", "default": 0.0},
        ]
        vals = form_dialog("RC Column Design (EC2)", fields)
        if not vals:
            return
        fck = self._GRADES[vals["grade"]][0]
        fyk = float(vals["fyk"]); b = float(vals["b"]); h = float(vals["h"])
        d2 = float(vals["cover"]) + float(vals["link"]) + 0.5 * float(vals["bar"])
        abar = 3.14159265 * (float(vals["bar"]) / 2.0) ** 2
        As_tot = int(vals["nbar"]) * abar
        N = float(vals["N"]) * 1e3; M0 = float(vals["M"]) * 1e6
        l0 = float(vals.get("l0", 0.0))
        Nsquash = (fck / 1.5) * b * h + As_tot * (fyk / 1.15)
        # EC2 5.8: slenderness and nominal-curvature 2nd-order moment
        slen = None; M2 = 0.0; M = M0
        if l0 > 0:
            slen = _column_slenderness(N, b * h, fck, l0, h)
            M0e = max(M0, N * max(h / 30.0, 20.0))   # include EC2 5.8.8.2 minimum
            if slen["slender"]:
                so = _column_2nd_order(N, l0, h - d2, As_tot, b * h, fck, fyk)
                M2 = so["M2"]
            M = M0e + M2
        MRd = _rc_column_MRd(N, b, h, d2, As_tot, fck, fyk)
        util = (M / MRd) if MRd > 1e-6 else (99.9 if M > 0 else 0.0)
        rho = As_tot / (b * h)
        # EC2 5.8.9 biaxial bending (when a moment about the b axis is given)
        My = float(vals.get("My", 0.0)) * 1e6
        biax = None
        if My > 0:
            MRdy = _rc_column_MRd(N, h, b, d2, As_tot, fck, fyk)   # bending about b
            biax = _biaxial_check(N, M, My, MRd, MRdy, Nsquash)
            biax["MRdy"] = MRdy
            util = biax["util"]
        # auto-size: if it fails, grow As_tot (more bars) until M_Rd >= M_Ed
        need_As = As_tot; need_n = int(vals["nbar"])
        if util > 1.0 and N < Nsquash:
            nn = int(vals["nbar"])
            while nn < 400:
                nn += 2
                if biax is not None:
                    mrz = _rc_column_MRd(N, b, h, d2, nn * abar, fck, fyk)
                    mry = _rc_column_MRd(N, h, b, d2, nn * abar, fck, fyk)
                    if _biaxial_check(N, M, My, mrz, mry, Nsquash)["ok"]:
                        need_n = nn; need_As = nn * abar; break
                elif _rc_column_MRd(N, b, h, d2, nn * abar, fck, fyk) >= M:
                    need_n = nn; need_As = nn * abar; break
        doc.openTransaction("DynFrame: RC column design")
        try:
            s = doc.getObject("RcColumn") or doc.addObject("Spreadsheet::Sheet", "RcColumn")
            s.Label = "RcColumn"; s.clearAll()
            s.set("A1", "RC COLUMN EC2 - %s, fyk=%g, %gx%g mm, %d x H%g bars (As=%.0f "
                  "mm2, rho=%.2f%%) | N=%g kN, M=%g kNm"
                  % (vals["grade"], fyk, b, h, int(vals["nbar"]), float(vals["bar"]),
                     As_tot, 100 * rho, vals["N"], vals["M"]))
            rows = [("Squash load N_Rd0 (kN)", "%.0f" % (Nsquash / 1e3))]
            if slen is not None:
                rows.append(("Slenderness lambda / lambda_lim",
                             "%.1f / %.1f  (%s)" % (slen["lambda"], slen["lambda_lim"],
                              "SLENDER - 2nd order included" if slen["slender"]
                              else "short - no 2nd order")))
                if M2 > 0:
                    rows.append(("2nd-order moment M2 (kNm)", "%.1f" % (M2 / 1e6)))
                rows.append(("Design moment M_Ed (kNm)",
                             "%.1f  (1st order %.1f)" % (M / 1e6, M0 / 1e6)))
            if biax is not None:
                rows += [
                    ("M_Rdz / M_Rdy at N_Ed (kNm)", "%.1f / %.1f"
                     % (MRd / 1e6, biax["MRdy"] / 1e6)),
                    ("Biaxial (Mz/MRdz)^a+(My/MRdy)^a", "%.2f  (a=%.2f)  %s"
                     % (biax["util"], biax["a"], "OK" if biax["ok"] else "FAIL")),
                    ("Reinforcement ratio", "%.2f%%" % (100 * rho)),
                ]
            else:
                rows += [
                    ("M_Rd at N_Ed (kNm)", "%.1f" % (MRd / 1e6)),
                    ("Utilisation M_Ed/M_Rd", "%.2f  %s"
                     % (util, "OK" if util <= 1.0 else "FAIL")),
                    ("Reinforcement ratio", "%.2f%%  (min 0.10%% of Ac or 0.10 N_Ed/fyd)"
                     % (100 * rho)),
                ]
            if util > 1.0 and need_As > As_tot:
                rows.append(("Steel required", "%d x H%g = %.0f mm2 (rho=%.2f%%)"
                             % (need_n, float(vals["bar"]), need_As,
                                100 * need_As / (b * h))))
            for i, (a, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, a); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("RC column design failed: %s" % e); return
        extra = ""
        if N >= Nsquash:
            extra = "\n\nN_Ed exceeds the squash load - the section/steel is too " \
                    "small for this axial load."
        elif util > 1.0:
            extra = ("\n\nFails in bending. Steel required: %d x H%g = %.0f mm2 "
                     "(rho = %.2f%%)." % (need_n, float(vals["bar"]), need_As,
                                          100 * need_As / (b * h))) if need_As > As_tot \
                else "\n\nFails - increase the section."
        slen_txt = ""
        if slen is not None:
            slen_txt = ("Slenderness lambda = %.0f vs lambda_lim = %.0f (%s)%s\n"
                        % (slen["lambda"], slen["lambda_lim"],
                           "SLENDER" if slen["slender"] else "short",
                           ", M2 = %.0f kNm" % (M2 / 1e6) if M2 > 0 else ""))
        if biax is not None:
            cap_txt = ("At N_Ed = %g kN:  M_Rdz = %.0f, M_Rdy = %.0f kNm\n"
                       "Biaxial (EC2 5.8.9):  (Mz/MRdz)^%.2f + (My/MRdy)^%.2f = "
                       "%.2f  %s" % (vals["N"], MRd / 1e6, biax["MRdy"] / 1e6,
                        biax["a"], biax["a"], biax["util"],
                        "OK" if biax["ok"] else "FAIL"))
        else:
            cap_txt = ("At N_Ed = %g kN:  M_Rd = %.0f kNm\n"
                       "M_Ed = %.0f kNm (1st order %g)  ->  utilisation = %.2f  %s"
                       % (vals["N"], MRd / 1e6, M / 1e6, vals["M"], util,
                          "OK" if util <= 1.0 else "FAIL"))
        info("RC column (EN 1992-1-1) - %s, %g x %g mm, %d x H%g bars (As = %.0f "
             "mm2, rho = %.2f%%).\n\n"
             "Squash load N_Rd0 = %.0f kN\n%s%s%s\n\n"
             "See the 'RcColumn' table. Symmetric reinforcement; EC2 5.8.8 nominal "
             "curvature when l0 is given, 5.8.9 biaxial when My is given; ULS "
             "envelope forces." %
             (vals["grade"], b, h, int(vals["nbar"]), float(vals["bar"]), As_tot,
              100 * rho, Nsquash / 1e3, slen_txt, cap_txt, extra))


class PadFootingEC2:
    _GRADES = RcBeamEC2._GRADES

    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Pad Footing Design (EC2)",
                "ToolTip": "Design an isolated (pad) footing under a square column "
                           "to EN 1992-1-1 / EN 1997: bearing pressure vs the "
                           "allowable (SLS), cantilever bending steel, one-way "
                           "shear and punching shear at 2d - Robot-style foundation "
                           "design.",
                "Accel": "A, F"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        grades = list(self._GRADES.keys())
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Isolated pad footing under a square column (EN 1992-1-1 / EN 1997). "
             "Enter the column load (add the footing self-weight to the SLS load "
             "yourself if you want it in the bearing check), the footing plan, the "
             "allowable bearing pressure and the materials."},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": grades, "default": "C30/37"},
            {"key": "fyk", "label": "Steel fyk (MPa)", "kind": "float", "default": 500.0},
            {"key": "Nsls", "label": "Column load N (kN, SLS)", "kind": "float",
             "default": 1000.0},
            {"key": "Msls", "label": "Column moment M (kN.m, SLS)", "kind": "float",
             "default": 0.0},
            {"key": "Nuls", "label": "Column load N (kN, ULS; 0 = 1.35xSLS)",
             "kind": "float", "default": 0.0},
            {"key": "c", "label": "Square column size (mm)", "kind": "float",
             "default": 400.0},
            {"key": "B", "label": "Footing width B (mm)", "kind": "float", "default": 2500.0},
            {"key": "L", "label": "Footing length L (mm)", "kind": "float", "default": 2500.0},
            {"key": "h", "label": "Footing depth h (mm)", "kind": "float", "default": 500.0},
            {"key": "cover", "label": "Cover (mm)", "kind": "float", "default": 50.0},
            {"key": "bar", "label": "Bar diameter (mm)", "kind": "float", "default": 16.0},
            {"key": "qall", "label": "Allowable bearing (kPa)", "kind": "float",
             "default": 200.0},
        ]
        vals = form_dialog("Pad Footing Design (EC2)", fields)
        if not vals:
            return
        fck = self._GRADES[vals["grade"]][0]; fyk = float(vals["fyk"])
        Nsls = float(vals["Nsls"]) * 1e3; Msls = float(vals["Msls"]) * 1e6
        Nuls = (float(vals["Nuls"]) * 1e3) if float(vals["Nuls"]) > 0 else 1.35 * Nsls
        B = float(vals["B"]); L = float(vals["L"]); h = float(vals["h"])
        c = float(vals["c"]); qall = float(vals["qall"]) / 1000.0     # kPa -> MPa
        r = _pad_footing(Nsls, Msls, Nuls, B, L, h, c, fck, fyk,
                         float(vals["cover"]), float(vals["bar"]), qall)
        doc.openTransaction("DynFrame: pad footing")
        try:
            s = doc.getObject("PadFooting") or doc.addObject("Spreadsheet::Sheet",
                                                             "PadFooting")
            s.Label = "PadFooting"; s.clearAll()
            s.set("A1", "PAD FOOTING EC2 - %s, %gx%g mm plan, h=%g, col %g mm | "
                  "N=%g kN (SLS), q_all=%g kPa"
                  % (vals["grade"], B, L, h, c, vals["Nsls"], vals["qall"]))
            rows = [
                ("Bearing p_max / p_avg (kPa)", "%.0f / %.0f  %s"
                 % (r["p_max"] * 1000, r["p_avg"] * 1000,
                    "OK" if r["bearing_ok"] else "EXCEEDS ALLOWABLE")),
                ("Required area / provided (m2)", "%.2f / %.2f"
                 % (r["A_req"] / 1e6, B * L / 1e6)),
                ("Effective depth d (mm)", "%.0f" % r["d"]),
                ("Cantilever a / design M (kNm/m)", "%.0f / %.1f"
                 % (r["a"], r["M_strip"] / 1e6)),
                ("Flexural steel As (mm2/m)", "%.0f  (min %.0f)"
                 % (r["As"], r["As_min"])),
                ("One-way shear V_Rd,c (kN)", "%.0f  %s"
                 % (r["shear"]["VRdc"] / 1e3, "links" if r["shear"]["links"]
                    == "designed" else "OK no links")),
                ("Punching v_Ed / v_Rd,c at 2d (MPa)", "%.3f / %.3f  %s"
                 % (r["vEd_punch"], r["vRdc_punch"],
                    "OK" if r["punch_ok"] else "FAIL - thicken / add shear reinf")),
            ]
            for i, (a, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, a); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Pad footing design failed: %s" % e); return
        info("Pad footing (EN 1992-1-1 / EN 1997) - %gx%g mm, h=%g mm, square "
             "column %g mm.\n\n"
             "BEARING (SLS):  p_max = %.0f kPa vs allowable %g kPa  %s\n"
             "  required area %.2f m2, provided %.2f m2\n\n"
             "BENDING (ULS):  cantilever a = %.0f mm, M = %.0f kNm/m\n"
             "  flexural steel As = %.0f mm2/m (min %.0f), d = %.0f mm\n\n"
             "SHEAR:  one-way V_Rd,c = %.0f kN (%s);  punching v_Ed = %.3f vs "
             "v_Rd,c = %.3f MPa at 2d  %s\n\n"
             "See the 'PadFooting' table." %
             (B, L, h, c, r["p_max"] * 1000, vals["qall"],
              "OK" if r["bearing_ok"] else "EXCEEDS", r["A_req"] / 1e6, B * L / 1e6,
              r["a"], r["M_strip"] / 1e6, r["As"], r["As_min"], r["d"],
              r["shear"]["VRdc"] / 1e3,
              "links needed" if r["shear"]["links"] == "designed" else "OK no links",
              r["vEd_punch"], r["vRdc_punch"], "OK" if r["punch_ok"] else "FAIL"))


# ── EC5 timber member design (EN 1995-1-1) ──────────────────────
# Strength class -> (f_m,k, f_t,0,k, f_c,0,k, f_v,k, E_0,mean, E_0,05, rho_k, gamma_M)
# Solid (EN 338) and glulam (EN 14080), representative values (MPa / kg/m3).
TIMBER_CLASSES = {
    "C16": (16.0, 10.0, 17.0, 3.2, 8000.0, 5400.0, 310.0, 1.3),
    "C24": (24.0, 14.0, 21.0, 4.0, 11000.0, 7400.0, 350.0, 1.3),
    "C30": (30.0, 18.0, 23.0, 4.0, 12000.0, 8000.0, 380.0, 1.3),
    "GL24h": (24.0, 16.5, 24.0, 3.5, 11500.0, 9600.0, 385.0, 1.25),
    "GL28h": (28.0, 19.5, 28.0, 3.5, 12600.0, 10200.0, 425.0, 1.25),
}
# k_mod, EN 1995-1-1 Table 3.1 (service class -> load-duration class)
KMOD = {
    1: {"permanent": 0.60, "long": 0.70, "medium": 0.80, "short": 0.90, "instant": 1.10},
    2: {"permanent": 0.60, "long": 0.70, "medium": 0.80, "short": 0.90, "instant": 1.10},
    3: {"permanent": 0.50, "long": 0.55, "medium": 0.65, "short": 0.70, "instant": 0.90},
}


def _timber_kc(lam_rel, beta_c=0.2):
    """EN 1995-1-1 6.3.2 buckling reduction factor k_c from the relative
    slenderness (beta_c = 0.2 solid timber, 0.1 glulam/LVL)."""
    if lam_rel <= 0.3:
        return 1.0
    k = 0.5 * (1.0 + beta_c * (lam_rel - 0.3) + lam_rel * lam_rel)
    return 1.0 / (k + (k * k - lam_rel * lam_rel) ** 0.5)


class TimberEC5:
    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Timber Member Check (EC5)",
                "ToolTip": "Check a rectangular solid-timber or glulam member to "
                           "EN 1995-1-1: design strengths from k_mod / gamma_M, "
                           "biaxial bending, combined axial + bending with column "
                           "buckling (k_c), and shear (k_cr) - the way Robot checks "
                           "timber members.",
                "Accel": "A, T"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        classes = list(TIMBER_CLASSES.keys())
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Rectangular timber member to EN 1995-1-1. Enter the section, strength "
             "class, service class + load duration (set k_mod) and the design "
             "forces. Checks biaxial bending, axial+bending with buckling, shear."},
            {"key": "cls", "label": "Strength class", "kind": "combo",
             "options": classes, "default": "C24"},
            {"key": "sc", "label": "Service class", "kind": "combo",
             "options": ["1", "2", "3"], "default": "1"},
            {"key": "dur", "label": "Load duration", "kind": "combo",
             "options": ["permanent", "long", "medium", "short", "instant"],
             "default": "medium"},
            {"key": "b", "label": "Width b (mm)", "kind": "float", "default": 100.0},
            {"key": "h", "label": "Depth h (mm)", "kind": "float", "default": 200.0},
            {"key": "My", "label": "Moment My about y (kN.m)", "kind": "float", "default": 5.0},
            {"key": "Mz", "label": "Moment Mz about z (kN.m)", "kind": "float", "default": 0.0},
            {"key": "N", "label": "Axial N (kN, + compression)", "kind": "float", "default": 0.0},
            {"key": "V", "label": "Shear V (kN)", "kind": "float", "default": 0.0},
            {"key": "lef", "label": "Buckling length l_ef (mm, 0 = no buckling)",
             "kind": "float", "default": 0.0},
        ]
        vals = form_dialog("Timber Member Check (EC5)", fields)
        if not vals:
            return
        fmk, ft0k, fc0k, fvk, E0m, E005, rhok, gM = TIMBER_CLASSES[vals["cls"]]
        kmod = KMOD[int(vals["sc"])][vals["dur"]]
        beta_c = 0.1 if vals["cls"].startswith("GL") else 0.2
        kcr = 0.67
        b = float(vals["b"]); h = float(vals["h"]); A = b * h
        Wy = b * h * h / 6.0; Wz = h * b * b / 6.0
        fmd = kmod * fmk / gM; fc0d = kmod * fc0k / gM
        ft0d = kmod * ft0k / gM; fvd = kmod * fvk / gM
        My = float(vals["My"]) * 1e6; Mz = float(vals["Mz"]) * 1e6
        N = float(vals["N"]) * 1e3; V = abs(float(vals["V"])) * 1e3
        lef = float(vals["lef"])
        smy = My / Wy; smz = Mz / Wz
        km = 0.7           # rectangular sections
        bend = max(smy / fmd + km * smz / fmd, km * smy / fmd + smz / fmd)
        checks = [("Bending (biaxial)", bend)]
        kc = 1.0; lam_rel = 0.0
        if N > 0:
            sc0d = N / A
            if lef > 0:
                i = b / (12.0 ** 0.5)          # buckling about the weak (b) axis
                lam = lef / i
                lam_rel = (lam / 3.14159265) * (fc0k / E005) ** 0.5
                kc = _timber_kc(lam_rel, beta_c)
            comb = sc0d / (kc * fc0d) + smy / fmd + km * smz / fmd
            checks.append(("Compression + bending (buckling)", comb))
        elif N < 0:
            st0d = -N / A
            checks.append(("Tension + bending", st0d / ft0d + smy / fmd + km * smz / fmd))
        if V > 0:
            tau = 1.5 * V / (kcr * A)
            checks.append(("Shear", tau / fvd))
        gov = max(c[1] for c in checks)
        doc.openTransaction("DynFrame: timber check")
        try:
            s = doc.getObject("Timber") or doc.addObject("Spreadsheet::Sheet", "Timber")
            s.Label = "Timber"; s.clearAll()
            s.set("A1", "TIMBER EC5 - %s, %gx%g mm, SC%s/%s, k_mod=%.2f, gamma_M=%.2f"
                  % (vals["cls"], b, h, vals["sc"], vals["dur"], kmod, gM))
            s.set("A2", "Design strengths (MPa)")
            s.set("B2", "f_m,d=%.2f  f_c,0,d=%.2f  f_t,0,d=%.2f  f_v,d=%.2f"
                  % (fmd, fc0d, ft0d, fvd))
            r2 = 3
            for (nm, u) in checks:
                s.set("A%d" % r2, nm)
                s.set("B%d" % r2, "%.2f  %s" % (u, "OK" if u <= 1.0 else "FAIL")); r2 += 1
            if kc < 1.0:
                s.set("A%d" % r2, "Buckling lambda_rel / k_c")
                s.set("B%d" % r2, "%.2f / %.3f" % (lam_rel, kc))
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Timber check failed: %s" % e); return
        info("Timber member (EN 1995-1-1) - %s, %g x %g mm.\n\n"
             "k_mod = %.2f (SC%s, %s), gamma_M = %.2f\n"
             "f_m,d = %.2f, f_c,0,d = %.2f, f_v,d = %.2f MPa\n\n%s\n\n"
             "Governing utilisation = %.2f  %s%s\n\nSee the 'Timber' table." %
             (vals["cls"], b, h, kmod, vals["sc"], vals["dur"], gM, fmd, fc0d, fvd,
              "\n".join("  %s: %.2f %s" % (nm, u, "OK" if u <= 1 else "FAIL")
                        for nm, u in checks), gov, "OK" if gov <= 1.0 else "FAIL",
              "  (buckling k_c = %.3f, lambda_rel = %.2f)" % (kc, lam_rel)
              if kc < 1.0 else ""))


def _base_plate(N, bc, hc, bp, hp, fck, fy, gM0=1.0, kj=1.0, betaj=2.0 / 3.0):
    """EN 1993-1-8 6.2.5 axially-loaded column base plate (cantilever method):
    concrete bearing strength f_jd = betaj kj fcd, the required bearing area, the
    actual pressure, and the plate thickness from the plate overhang acting as a
    cantilever under the bearing pressure. N in N, lengths mm, stresses MPa."""
    fcd = fck / 1.5
    f_jd = betaj * kj * fcd
    A = bp * hp
    p = N / A if A > 0 else 0.0
    A_req = N / f_jd if f_jd > 0 else 0.0
    a = max((hp - hc) / 2.0, (bp - bc) / 2.0)
    M = p * a * a / 2.0                 # per unit width
    t_req = (6.0 * M * gM0 / fy) ** 0.5 if fy > 0 else 0.0
    return {"f_jd": f_jd, "p": p, "A_req": A_req, "a": a, "t_req": t_req,
            "area_ok": A >= A_req and p <= f_jd}


class BasePlateEC3:
    _GRADES = {"C20/25": 20.0, "C25/30": 25.0, "C30/37": 30.0, "C35/45": 35.0}

    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Steel Base Plate (EC3)",
                "ToolTip": "Design an axially-loaded steel column base plate to "
                           "EN 1993-1-8: the concrete bearing strength f_jd, the "
                           "required bearing area, the actual pressure and the "
                           "plate thickness (plate overhang as a cantilever). "
                           "Robot-style steel column-base design.",
                "Accel": "A, P"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Axially-loaded steel column base plate (EN 1993-1-8). Enter the "
             "column footprint, the plate size and thickness, the axial load and "
             "the concrete grade. Concentric load; cantilever-method thickness."},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": list(self._GRADES.keys()), "default": "C30/37"},
            {"key": "fy", "label": "Plate steel fy (MPa)", "kind": "float", "default": 235.0},
            {"key": "N", "label": "Axial load N_Ed (kN, compression)", "kind": "float",
             "default": 1000.0},
            {"key": "bc", "label": "Column width (mm)", "kind": "float", "default": 200.0},
            {"key": "hc", "label": "Column depth (mm)", "kind": "float", "default": 200.0},
            {"key": "bp", "label": "Plate width (mm)", "kind": "float", "default": 400.0},
            {"key": "hp", "label": "Plate depth (mm)", "kind": "float", "default": 400.0},
            {"key": "tp", "label": "Plate thickness provided (mm)", "kind": "float",
             "default": 30.0},
            {"key": "kj", "label": "Concentration factor k_j (1-3)", "kind": "float",
             "default": 1.0},
        ]
        vals = form_dialog("Steel Base Plate (EC3)", fields)
        if not vals:
            return
        fck = self._GRADES[vals["grade"]]; fy = float(vals["fy"])
        N = float(vals["N"]) * 1e3
        r = _base_plate(N, float(vals["bc"]), float(vals["hc"]), float(vals["bp"]),
                        float(vals["hp"]), fck, fy, kj=max(1.0, float(vals["kj"])))
        tp = float(vals["tp"]); t_ok = tp >= r["t_req"]
        doc.openTransaction("DynFrame: base plate")
        try:
            s = doc.getObject("BasePlate") or doc.addObject("Spreadsheet::Sheet", "BasePlate")
            s.Label = "BasePlate"; s.clearAll()
            s.set("A1", "STEEL BASE PLATE EC3 - %s, fy=%g, plate %gx%g mm, col %gx%g "
                  "| N=%g kN" % (vals["grade"], fy, vals["bp"], vals["hp"],
                                 vals["bc"], vals["hc"], vals["N"]))
            rows = [
                ("Bearing strength f_jd (MPa)", "%.2f" % r["f_jd"]),
                ("Actual pressure p (MPa)", "%.2f  %s"
                 % (r["p"], "OK" if r["p"] <= r["f_jd"] else "EXCEEDS f_jd")),
                ("Required / provided area (mm2)", "%.0f / %.0f  %s"
                 % (r["A_req"], float(vals["bp"]) * float(vals["hp"]),
                    "OK" if r["area_ok"] else "TOO SMALL")),
                ("Plate overhang a (mm)", "%.0f" % r["a"]),
                ("Plate thickness req / prov (mm)", "%.1f / %.1f  %s"
                 % (r["t_req"], tp, "OK" if t_ok else "TOO THIN")),
            ]
            for i, (a, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, a); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Base plate design failed: %s" % e); return
        info("Steel base plate (EN 1993-1-8) - plate %g x %g mm, column %g x %g mm.\n\n"
             "Concrete bearing f_jd = %.2f MPa; actual pressure p = %.2f MPa  %s\n"
             "Required area %.0f mm2, provided %.0f mm2  %s\n"
             "Plate overhang a = %.0f mm -> thickness required %.1f mm, provided "
             "%.1f mm  %s\n\nSee the 'BasePlate' table." %
             (vals["bp"], vals["hp"], vals["bc"], vals["hc"], r["f_jd"], r["p"],
              "OK" if r["p"] <= r["f_jd"] else "EXCEEDS",
              r["A_req"], float(vals["bp"]) * float(vals["hp"]),
              "OK" if r["area_ok"] else "TOO SMALL", r["a"], r["t_req"], tp,
              "OK" if t_ok else "TOO THIN - thicken the plate"))


class TorsionCheckEC3:
    _GRADES = {"S235": 235.0, "S275": 275.0, "S355": 355.0, "S420": 420.0}

    def GetResources(self):
        return {"Pixmap": _icon("tension"), "MenuText": "Torsion Check (EC3)",
                "ToolTip": "EN 1993-1-1 6.2.7 St-Venant torsion check of an open "
                           "I/H member: the torsional shear stresses in flange and "
                           "web, their utilisation against fy/sqrt3, and the "
                           "torsion-reduced plastic shear resistance Vpl,T,Rd with "
                           "the shear utilisation - the torsion check the main "
                           "member check leaves out.",
                "Accel": "A, X"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "St-Venant torsion of an open I/H section (EN 1993-1-1 6.2.7). Enter "
             "the section (torsion constant It, flange/web thickness, shear area "
             "Az), the grade, and the design torsion and shear. Warping torsion is "
             "not included."},
            {"key": "grade", "label": "Steel grade", "kind": "combo",
             "options": list(self._GRADES.keys()), "default": "S355"},
            {"key": "It", "label": "Torsion constant It (mm4)", "kind": "float", "default": 770000.0},
            {"key": "tf", "label": "Flange thickness tf (mm)", "kind": "float", "default": 15.0},
            {"key": "tw", "label": "Web thickness tw (mm)", "kind": "float", "default": 11.0},
            {"key": "Az", "label": "Shear area Az (mm2)", "kind": "float", "default": 6694.0},
            {"key": "T", "label": "Design torsion T_Ed (kN.m)", "kind": "float", "default": 10.33},
            {"key": "V", "label": "Design shear V_z,Ed (kN)", "kind": "float", "default": 510.32},
        ]
        vals = form_dialog("Torsion Check (EC3)", fields)
        if not vals:
            return
        fy = self._GRADES[vals["grade"]]
        r = _ec3_torsion(float(vals["T"]) * 1e6, float(vals["It"]), float(vals["tw"]),
                         float(vals["tf"]), float(vals["Az"]), fy)
        V = abs(float(vals["V"])) * 1e3
        uV = V / r["Vpl_T_Rd"] if r["Vpl_T_Rd"] > 0 else 99.9
        gov = max(r["util_f"], r["util_w"], uV)
        doc.openTransaction("DynFrame: torsion check")
        try:
            s = doc.getObject("Torsion") or doc.addObject("Spreadsheet::Sheet", "Torsion")
            s.Label = "Torsion"; s.clearAll()
            s.set("A1", "TORSION EC3 (6.2.7) - %s, It=%g, T_Ed=%g kNm, V_z,Ed=%g kN"
                  % (vals["grade"], vals["It"], vals["T"], vals["V"]))
            rows = [
                ("Flange tau_t / (fy/sqrt3)", "%.0f / %.0f MPa = %.2f %s"
                 % (r["tau_f"], r["tau_y"], r["util_f"], "OK" if r["util_f"] <= 1 else "FAIL")),
                ("Web tau_t / (fy/sqrt3)", "%.0f / %.0f MPa = %.2f %s"
                 % (r["tau_w"], r["tau_y"], r["util_w"], "OK" if r["util_w"] <= 1 else "FAIL")),
                ("Vpl,Rd / Vpl,T,Rd (kN)", "%.0f / %.0f  (factor %.3f)"
                 % (r["Vpl_Rd"] / 1e3, r["Vpl_T_Rd"] / 1e3, r["red"])),
                ("Shear V_Ed/Vpl,T,Rd", "%.2f  %s" % (uV, "OK" if uV <= 1 else "FAIL")),
            ]
            for i, (aa, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, aa); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Torsion check failed: %s" % e); return
        info("Torsion check (EN 1993-1-1 6.2.7) - %s, St-Venant.\n\n"
             "Torsional shear: flange %.0f MPa (util %.2f), web %.0f MPa (util "
             "%.2f) vs fy/sqrt3 = %.0f MPa\n"
             "Plastic shear Vpl,Rd = %.0f kN -> torsion-reduced Vpl,T,Rd = %.0f kN "
             "(x %.3f)\n"
             "Shear V_Ed/Vpl,T,Rd = %.2f\n\nGoverning utilisation = %.2f  %s\n\n"
             "See the 'Torsion' table. Warping torsion not included." %
             (vals["grade"], r["tau_f"], r["util_f"], r["tau_w"], r["util_w"],
              r["tau_y"], r["Vpl_Rd"] / 1e3, r["Vpl_T_Rd"] / 1e3, r["red"], uV,
              gov, "OK" if gov <= 1 else "FAIL"))


# ── EC3-1-8 bolted connection ───────────────────────────────────
BOLT_AREAS = {"M12": 84.3, "M16": 157.0, "M20": 245.0, "M24": 353.0, "M30": 561.0}
BOLT_DIA = {"M12": 12.0, "M16": 16.0, "M20": 20.0, "M24": 24.0, "M30": 30.0}
BOLT_HOLE = {"M12": 13.0, "M16": 18.0, "M20": 22.0, "M24": 26.0, "M30": 33.0}
BOLT_GRADES = {"4.6": 400.0, "5.6": 500.0, "8.8": 800.0, "10.9": 1000.0}


def _bolt_shear(As, Ashank, fub, grade, threads_in_plane, planes=1, gM2=1.25):
    """EN 1993-1-8 Table 3.4 bolt shear resistance F_v,Rd (per the given number of
    shear planes). alpha_v = 0.5 for 10.9, else 0.6; area = tensile-stress area if
    the threads are in the shear plane, else the shank area."""
    alpha_v = 0.5 if grade == "10.9" else 0.6
    A = As if threads_in_plane else Ashank
    return planes * alpha_v * fub * A / gM2


def _bolt_bearing(d, d0, t, fu, fub, e1, p1, e2, p2, gM2=1.25):
    """EN 1993-1-8 Table 3.4 bearing resistance F_b,Rd of one bolt on a plate."""
    alpha_b = min(e1 / (3.0 * d0), p1 / (3.0 * d0) - 0.25, fub / fu, 1.0)
    k1 = min(2.8 * e2 / d0 - 1.7, 1.4 * p2 / d0 - 1.7, 2.5)
    return k1 * alpha_b * fu * d * t / gM2


def _bolt_tension(As, fub, gM2=1.25):
    """EN 1993-1-8 Table 3.4 bolt tension resistance F_t,Rd (k2 = 0.9)."""
    return 0.9 * fub * As / gM2


class BoltedConnEC3:
    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Bolted Connection (EC3)",
                "ToolTip": "Check a bolt group in a shear/tension connection to "
                           "EN 1993-1-8: per-bolt shear F_v,Rd, bearing F_b,Rd and "
                           "tension F_t,Rd (from the edge/end distances and "
                           "spacings), and the group capacity vs the applied shear "
                           "and tension - Robot-style connection design.",
                "Accel": "A, J"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Bolt group in a shear / tension connection (EN 1993-1-8). Enter the "
             "bolt size and grade, the plate (thickness + steel f_u), the edge/end "
             "distances and spacings, and the applied forces."},
            {"key": "size", "label": "Bolt size", "kind": "combo",
             "options": list(BOLT_AREAS.keys()), "default": "M20"},
            {"key": "grade", "label": "Bolt grade", "kind": "combo",
             "options": list(BOLT_GRADES.keys()), "default": "8.8"},
            {"key": "n", "label": "Number of bolts", "kind": "int", "default": 4, "min": 1, "max": 100},
            {"key": "planes", "label": "Shear planes per bolt", "kind": "int",
             "default": 1, "min": 1, "max": 2},
            {"key": "thread", "label": "Threads in the shear plane", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
            {"key": "t", "label": "Plate thickness t (mm)", "kind": "float", "default": 10.0},
            {"key": "fu", "label": "Plate steel f_u (MPa)", "kind": "float", "default": 430.0},
            {"key": "e1", "label": "End distance e1 (mm)", "kind": "float", "default": 40.0},
            {"key": "p1", "label": "Pitch p1 (mm)", "kind": "float", "default": 60.0},
            {"key": "e2", "label": "Edge distance e2 (mm)", "kind": "float", "default": 40.0},
            {"key": "p2", "label": "Gauge p2 (mm)", "kind": "float", "default": 60.0},
            {"key": "V", "label": "Applied shear V_Ed (kN)", "kind": "float", "default": 200.0},
            {"key": "T", "label": "Applied tension T_Ed (kN, total)", "kind": "float",
             "default": 0.0},
        ]
        vals = form_dialog("Bolted Connection (EC3)", fields)
        if not vals:
            return
        size = vals["size"]; grade = vals["grade"]
        As = BOLT_AREAS[size]; d = BOLT_DIA[size]; d0 = BOLT_HOLE[size]
        fub = BOLT_GRADES[grade]; Ashank = 3.14159265 * d * d / 4.0
        n = int(vals["n"])
        Fv = _bolt_shear(As, Ashank, fub, grade, vals["thread"] == "Yes",
                         int(vals["planes"]))
        Fb = _bolt_bearing(d, d0, float(vals["t"]), float(vals["fu"]), fub,
                           float(vals["e1"]), float(vals["p1"]), float(vals["e2"]),
                           float(vals["p2"]))
        Ft = _bolt_tension(As, fub)
        per_bolt = min(Fv, Fb)
        VRd = n * per_bolt; TRd = n * Ft
        V = float(vals["V"]) * 1e3; T = float(vals["T"]) * 1e3
        uV = V / VRd if VRd > 0 else 0.0
        uT = T / TRd if TRd > 0 else 0.0
        # combined shear + tension (EN 1993-1-8 Table 3.4): Fv/Fv,Rd + Ft/(1.4 Ft,Rd) <= 1
        uC = (V / n) / Fv + (T / n) / (1.4 * Ft) if (Fv > 0 and Ft > 0 and T > 0) else 0.0
        doc.openTransaction("DynFrame: bolted connection")
        try:
            s = doc.getObject("BoltGroup") or doc.addObject("Spreadsheet::Sheet", "BoltGroup")
            s.Label = "BoltGroup"; s.clearAll()
            s.set("A1", "BOLTED CONNECTION EC3 - %d x %s gr %s, t=%g mm, f_u=%g | "
                  "V=%g kN, T=%g kN" % (n, size, grade, vals["t"], vals["fu"],
                                        vals["V"], vals["T"]))
            rows = [
                ("Shear F_v,Rd / bolt (kN)", "%.1f" % (Fv / 1e3)),
                ("Bearing F_b,Rd / bolt (kN)", "%.1f  (%s governs)"
                 % (Fb / 1e3, "bearing" if Fb < Fv else "shear")),
                ("Tension F_t,Rd / bolt (kN)", "%.1f" % (Ft / 1e3)),
                ("Group shear V_Rd (kN)", "%.0f" % (VRd / 1e3)),
                ("Shear utilisation V/V_Rd", "%.2f  %s" % (uV, "OK" if uV <= 1 else "FAIL")),
            ]
            if T > 0:
                rows.append(("Tension util / combined", "%.2f / %.2f  %s"
                             % (uT, uC, "OK" if max(uT, uC) <= 1 else "FAIL")))
            for i, (a, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, a); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Bolted connection failed: %s" % e); return
        tline = ("\nTension: F_t,Rd = %.1f kN/bolt, util = %.2f, combined "
                 "shear+tension = %.2f %s" % (Ft / 1e3, uT, uC,
                 "OK" if max(uT, uC) <= 1 else "FAIL")) if T > 0 else ""
        info("Bolted connection (EN 1993-1-8) - %d x %s grade %s.\n\n"
             "Per bolt: shear F_v,Rd = %.1f kN, bearing F_b,Rd = %.1f kN "
             "(%s governs), tension F_t,Rd = %.1f kN\n"
             "Group shear V_Rd = %.0f kN  ->  V_Ed/V_Rd = %.2f  %s%s\n\n"
             "See the 'BoltGroup' table." %
             (n, size, grade, Fv / 1e3, Fb / 1e3,
              "bearing" if Fb < Fv else "shear", Ft / 1e3, VRd / 1e3, uV,
              "OK" if uV <= 1 else "FAIL", tline))


# ── EC3-1-8 fillet weld ─────────────────────────────────────────
WELD_BETAW = {"S235": 0.80, "S275": 0.85, "S355": 0.90, "S420": 1.00, "S460": 1.00}


def _fillet_weld_fvwd(fu, betaw, gM2=1.25):
    """EN 1993-1-8 4.5.3.3 simplified-method design shear strength of a fillet
    weld, f_vw,d = (f_u/sqrt3) / (beta_w gamma_M2). The weld resistance per unit
    length is then F_w,Rd = f_vw,d * a (throat)."""
    return (fu / (3.0 ** 0.5)) / (betaw * gM2)


class FilletWeldEC3:
    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Fillet Weld (EC3)",
                "ToolTip": "Check a fillet weld to EN 1993-1-8 (simplified method): "
                           "the design shear strength f_vw,d from the parent-metal "
                           "f_u and the correlation factor beta_w, the resistance "
                           "per unit length F_w,Rd = f_vw,d * throat, and the group "
                           "capacity vs the applied force.",
                "Accel": "A, W"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Fillet weld, EN 1993-1-8 simplified method. Enter the throat a, the "
             "total effective weld length, the steel grade (sets beta_w) and f_u, "
             "and the applied force on the weld group."},
            {"key": "a", "label": "Weld throat a (mm)", "kind": "float", "default": 5.0},
            {"key": "l", "label": "Total weld length (mm)", "kind": "float", "default": 400.0},
            {"key": "grade", "label": "Steel grade (beta_w)", "kind": "combo",
             "options": list(WELD_BETAW.keys()), "default": "S275"},
            {"key": "fu", "label": "Parent metal f_u (MPa)", "kind": "float", "default": 430.0},
            {"key": "F", "label": "Applied force on the weld (kN)", "kind": "float",
             "default": 300.0},
        ]
        vals = form_dialog("Fillet Weld (EC3)", fields)
        if not vals:
            return
        betaw = WELD_BETAW[vals["grade"]]; fu = float(vals["fu"])
        a = float(vals["a"]); l = float(vals["l"])
        fvwd = _fillet_weld_fvwd(fu, betaw)
        Fw_per_mm = fvwd * a                       # N/mm
        Fw_Rd = Fw_per_mm * l                       # N
        F = float(vals["F"]) * 1e3
        util = F / Fw_Rd if Fw_Rd > 0 else 99.9
        doc.openTransaction("DynFrame: fillet weld")
        try:
            s = doc.getObject("Weld") or doc.addObject("Spreadsheet::Sheet", "Weld")
            s.Label = "Weld"; s.clearAll()
            s.set("A1", "FILLET WELD EC3 - a=%g mm, l=%g mm, %s (beta_w=%.2f), "
                  "f_u=%g | F=%g kN" % (a, l, vals["grade"], betaw, fu, vals["F"]))
            rows = [
                ("f_vw,d (MPa)", "%.1f" % fvwd),
                ("F_w,Rd per mm (kN/mm)", "%.3f" % (Fw_per_mm / 1e3)),
                ("Group capacity F_w,Rd (kN)", "%.0f" % (Fw_Rd / 1e3)),
                ("Utilisation F/F_w,Rd", "%.2f  %s" % (util, "OK" if util <= 1 else "FAIL")),
            ]
            for i, (aa, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, aa); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Fillet weld failed: %s" % e); return
        info("Fillet weld (EN 1993-1-8, simplified) - a = %g mm, length = %g mm, "
             "%s.\n\nf_vw,d = %.1f MPa\nF_w,Rd = %.3f kN/mm x %g mm = %.0f kN\n"
             "F_Ed = %g kN  ->  utilisation = %.2f  %s\n\nSee the 'Weld' table." %
             (a, l, vals["grade"], fvwd, Fw_per_mm / 1e3, l, Fw_Rd / 1e3, vals["F"],
              util, "OK" if util <= 1 else "FAIL"))


# ── EC2 combined (two-column / strip) footing ───────────────────
def _combined_footing_moments(L, w, cols, nx=1001):
    """Bending-moment envelope of a combined/strip footing: length L (mm), uniform
    upward soil pressure w (N/mm), downward column loads cols = [(x, N)].
    M(x) = w x^2/2 - sum_{xi<=x} Ni (x - xi). Returns (M_max sagging sense,
    M_min hogging sense) over the length (column positions are sampled exactly)."""
    xs = sorted(set([L * i / (nx - 1) for i in range(nx)] + [c[0] for c in cols]))
    Mmax = -1e30; Mmin = 1e30
    for x in xs:
        M = w * x * x / 2.0 - sum(N * (x - xi) for (xi, N) in cols if xi <= x)
        Mmax = max(Mmax, M); Mmin = min(Mmin, M)
    return Mmax, Mmin


class CombinedFootingEC2:
    _GRADES = RcBeamEC2._GRADES

    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Combined Footing (EC2)",
                "ToolTip": "Design a combined (two-column) rectangular footing to "
                           "EN 1992-1-1 / EN 1997: size it so the bearing is "
                           "uniform under the load resultant, check the pressure, "
                           "and design the longitudinal top (hogging) and bottom "
                           "(sagging) steel from the footing-as-a-beam moments.",
                "Accel": "A, G"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Combined footing under two columns (EN 1992-1-1 / EN 1997). Enter the "
             "two column loads and positions, the footing plan + depth, materials "
             "and allowable bearing. The footing is analysed as a beam on uniform "
             "soil pressure to get the top/bottom steel."},
            {"key": "grade", "label": "Concrete grade", "kind": "combo",
             "options": list(self._GRADES.keys()), "default": "C30/37"},
            {"key": "fyk", "label": "Steel fyk (MPa)", "kind": "float", "default": 500.0},
            {"key": "N1", "label": "Column 1 load (kN, ULS)", "kind": "float", "default": 1000.0},
            {"key": "x1", "label": "Column 1 position from left (mm)", "kind": "float",
             "default": 1000.0},
            {"key": "N2", "label": "Column 2 load (kN, ULS)", "kind": "float", "default": 1000.0},
            {"key": "x2", "label": "Column 2 position from left (mm)", "kind": "float",
             "default": 4000.0},
            {"key": "L", "label": "Footing length L (mm)", "kind": "float", "default": 5000.0},
            {"key": "B", "label": "Footing width B (mm)", "kind": "float", "default": 2000.0},
            {"key": "h", "label": "Footing depth h (mm)", "kind": "float", "default": 700.0},
            {"key": "cover", "label": "Cover (mm)", "kind": "float", "default": 50.0},
            {"key": "bar", "label": "Bar diameter (mm)", "kind": "float", "default": 20.0},
            {"key": "qall", "label": "Allowable bearing (kPa, SLS check)", "kind": "float",
             "default": 200.0},
        ]
        vals = form_dialog("Combined Footing (EC2)", fields)
        if not vals:
            return
        fck = self._GRADES[vals["grade"]][0]; fyk = float(vals["fyk"])
        N1 = float(vals["N1"]) * 1e3; N2 = float(vals["N2"]) * 1e3
        x1 = float(vals["x1"]); x2 = float(vals["x2"])
        L = float(vals["L"]); B = float(vals["B"]); h = float(vals["h"])
        R = N1 + N2
        w = R / L                                   # N/mm upward
        p = R / (B * L)                             # MPa
        qall = float(vals["qall"]) / 1000.0
        Mmax, Mmin = _combined_footing_moments(L, w, [(x1, N1), (x2, N2)])
        d = h - float(vals["cover"]) - float(vals["bar"])
        fb_sag = _rc_beam_flexure(abs(Mmax), B, d, fck, fyk)
        fb_hog = _rc_beam_flexure(abs(Mmin), B, d, fck, fyk)
        doc.openTransaction("DynFrame: combined footing")
        try:
            s = doc.getObject("CombFooting") or doc.addObject("Spreadsheet::Sheet",
                                                              "CombFooting")
            s.Label = "CombFooting"; s.clearAll()
            s.set("A1", "COMBINED FOOTING EC2 - %gx%g mm, h=%g | N1=%g@%g, N2=%g@%g kN"
                  % (B, L, h, vals["N1"], x1, vals["N2"], x2))
            rows = [
                ("Bearing pressure p (kPa)", "%.0f  %s"
                 % (p * 1000, "OK" if p <= qall else "EXCEEDS ALLOWABLE")),
                ("Max sagging M (kNm)", "%.0f" % (abs(Mmax) / 1e6)),
                ("Bottom steel As (mm2)", "%.0f  (min %.0f)"
                 % (fb_sag["As_req"], fb_sag["As_min"])),
                ("Max hogging M (kNm)", "%.0f" % (abs(Mmin) / 1e6)),
                ("Top steel As (mm2)", "%.0f  (min %.0f)"
                 % (fb_hog["As_req"], fb_hog["As_min"])),
            ]
            for i, (aa, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, aa); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Combined footing failed: %s" % e); return
        info("Combined footing (EN 1992-1-1) - %g x %g mm, h = %g mm, two columns.\n\n"
             "Resultant %g kN, bearing p = %.0f kPa vs allowable %g kPa  %s\n\n"
             "Longitudinal bending (footing as a beam on uniform pressure):\n"
             "  sagging M = %.0f kNm -> bottom As = %.0f mm2\n"
             "  hogging M = %.0f kNm -> top As = %.0f mm2\n\n"
             "See the 'CombFooting' table." %
             (B, L, h, R / 1e3, p * 1000, vals["qall"],
              "OK" if p <= qall else "EXCEEDS", abs(Mmax) / 1e6, fb_sag["As_req"],
              abs(Mmin) / 1e6, fb_hog["As_req"]))


# ── EC6 unreinforced masonry wall (vertical load) ───────────────
def _masonry_fk(fb, fm, K=0.5, alpha=0.7, beta=0.3):
    """EN 1996-1-1 3.6.1.2 characteristic compressive strength of masonry,
    f_k = K f_b^alpha f_m^beta (general-purpose mortar: alpha=0.7, beta=0.3)."""
    return K * (fb ** alpha) * (fm ** beta)


def _masonry_phi_mid(hef, tef, t, e_mk, fk, E_factor=1000.0):
    """EN 1996-1-1 Annex G capacity reduction factor at mid-height from the
    slenderness and eccentricity. lambda = (h_ef/t_ef) sqrt(f_k/E), E=1000 f_k."""
    import math
    lam = (hef / tef) * math.sqrt(fk / (E_factor * fk))
    A1 = 1.0 - 2.0 * e_mk / t
    u = (lam - 0.063) / (0.73 - 1.17 * e_mk / t)
    return A1 * math.exp(-u * u / 2.0)


class MasonryEC6:
    def GetResources(self):
        return {"Pixmap": _icon("rebar"), "MenuText": "Masonry Wall (EC6)",
                "ToolTip": "Vertical-load capacity of an unreinforced masonry wall "
                           "to EN 1996-1-1: characteristic strength f_k = K f_b^a "
                           "f_m^b, design strength f_d, and the capacity reduction "
                           "Phi (top/bottom from eccentricity, mid-height from "
                           "Annex G slenderness) - Robot-style masonry design.",
                "Accel": "A, M"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Unreinforced masonry wall, vertical load (EN 1996-1-1), per metre "
             "length. Enter the unit and mortar strengths, the wall geometry and "
             "the eccentricity. Phi = min(top/bottom, Annex-G mid-height)."},
            {"key": "fb", "label": "Normalised unit strength f_b (MPa)", "kind": "float",
             "default": 10.0},
            {"key": "fm", "label": "Mortar strength f_m (MPa)", "kind": "float", "default": 5.0},
            {"key": "K", "label": "Constant K (unit/mortar)", "kind": "float",
             "default": 0.5, "decimals": 3},
            {"key": "t", "label": "Wall thickness t (mm)", "kind": "float", "default": 215.0},
            {"key": "hef", "label": "Effective height h_ef (mm)", "kind": "float",
             "default": 2500.0},
            {"key": "e", "label": "Load eccentricity e (mm)", "kind": "float", "default": 10.0},
            {"key": "gM", "label": "Partial factor gamma_M", "kind": "float", "default": 2.5},
            {"key": "N", "label": "Applied load N_Ed (kN/m)", "kind": "float", "default": 300.0},
        ]
        vals = form_dialog("Masonry Wall (EC6)", fields)
        if not vals:
            return
        fb = float(vals["fb"]); fm = float(vals["fm"]); K = float(vals["K"])
        t = float(vals["t"]); hef = float(vals["hef"]); e = float(vals["e"])
        gM = max(float(vals["gM"]), 1e-3)
        fk = _masonry_fk(fb, fm, K)
        fd = fk / gM
        e_i = max(e, 0.05 * t)
        phi_top = max(1.0 - 2.0 * e_i / t, 0.0)
        e_mk = max(e + hef / 450.0, 0.05 * t)       # mid-height eccentricity (+ h/450)
        phi_mid = max(_masonry_phi_mid(hef, t, t, e_mk, fk), 0.0)
        phi = min(phi_top, phi_mid)
        NRd = phi * t * fd                          # N per mm length = N/mm = kN/m
        N = float(vals["N"]) * 1e3 / 1000.0         # kN/m -> N/mm
        util = N / NRd if NRd > 0 else 99.9
        doc.openTransaction("DynFrame: masonry wall")
        try:
            s = doc.getObject("Masonry") or doc.addObject("Spreadsheet::Sheet", "Masonry")
            s.Label = "Masonry"; s.clearAll()
            s.set("A1", "MASONRY WALL EC6 - f_b=%g, f_m=%g, t=%g mm, h_ef=%g | "
                  "N=%g kN/m" % (fb, fm, t, hef, vals["N"]))
            rows = [
                ("f_k = K f_b^0.7 f_m^0.3 (MPa)", "%.2f" % fk),
                ("Design strength f_d (MPa)", "%.2f  (gamma_M=%.1f)" % (fd, gM)),
                ("Phi top / mid-height", "%.3f / %.3f" % (phi_top, phi_mid)),
                ("Capacity N_Rd (kN/m)", "%.0f" % (NRd * 1000.0 / 1e3)),
                ("Utilisation N_Ed/N_Rd", "%.2f  %s" % (util, "OK" if util <= 1 else "FAIL")),
            ]
            for i, (a, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, a); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e2:
            doc.abortTransaction(); err("Masonry wall failed: %s" % e2); return
        info("Masonry wall (EN 1996-1-1) - t = %g mm, h_ef = %g mm.\n\n"
             "f_k = K f_b^0.7 f_m^0.3 = %.2f MPa; f_d = %.2f MPa (gamma_M = %.1f)\n"
             "Phi = min(top %.3f, mid-height %.3f) = %.3f\n"
             "Capacity N_Rd = %.0f kN/m  ->  N_Ed/N_Rd = %.2f  %s\n\n"
             "See the 'Masonry' table. Unreinforced, vertical load, per metre." %
             (t, hef, fk, fd, gM, phi_top, phi_mid, phi, NRd, util,
              "OK" if util <= 1 else "FAIL"))


def _pushover_klocal(EA, EI, L):
    import numpy as np
    k = np.zeros((6, 6))
    k[0, 0] = EA / L; k[0, 3] = -EA / L; k[3, 0] = -EA / L; k[3, 3] = EA / L
    a = 12 * EI / L ** 3; b = 6 * EI / L ** 2; c = 4 * EI / L; d = 2 * EI / L
    k[1, 1] = a; k[1, 2] = b; k[1, 4] = -a; k[1, 5] = b
    k[2, 1] = b; k[2, 2] = c; k[2, 4] = -b; k[2, 5] = d
    k[4, 1] = -a; k[4, 2] = -b; k[4, 4] = a; k[4, 5] = -b
    k[5, 1] = b; k[5, 2] = d; k[5, 4] = -b; k[5, 5] = c
    return k


def _pushover_condense(k, dof):
    import numpy as np
    k = k.copy(); piv = k[dof, dof]
    if abs(piv) < 1e-12:
        k[dof, :] = 0; k[:, dof] = 0; return k
    k = k - np.outer(k[:, dof], k[dof, :]) / piv
    k[dof, :] = 0; k[:, dof] = 0
    return k


def _pushover_elem(EA, EI, L, cs, sn, released):
    import numpy as np
    k = _pushover_klocal(EA, EI, L)
    for dof in released:
        k = _pushover_condense(k, dof)
    T = np.zeros((6, 6)); R = np.array([[cs, sn, 0], [-sn, cs, 0], [0, 0, 1]])
    T[0:3, 0:3] = R; T[3:6, 3:6] = R
    return T.T @ k @ T, T, k


def _pushover2d(nodes, elems, fixed, loads, Mp, EA=1e13, maxsteps=200):
    """Plane-frame elastic-plastic pushover by the event-to-event plastic-hinge
    method. Nodes [(x,y)], elems [(ni,nj,EI)], fixed {node:(fu,fv,ft)}, loads
    {node:(Fx,Fy,Mz)} reference pattern, Mp the plastic moment. Returns the
    collapse load factor (the multiplier on the reference loads at which a
    mechanism forms), the hinge sequence and the capacity curve. Validated to the
    exact single-span collapse loads (8/6/4 Mp/L)."""
    import numpy as np
    nn = len(nodes); ndof = 3 * nn
    rest = set()
    for n, (fu, fv, ft) in fixed.items():
        if fu: rest.add(3 * n)
        if fv: rest.add(3 * n + 1)
        if ft: rest.add(3 * n + 2)
    free = [i for i in range(ndof) if i not in rest]
    if not free:
        return {"lambda_c": 0.0, "seq": [], "curve": [], "mechanism": False}
    P = np.zeros(ndof)
    for n, (fx, fy, mz) in loads.items():
        P[3 * n] += fx; P[3 * n + 1] += fy; P[3 * n + 2] += mz
    geo = []
    for (ni, nj, ei) in elems:
        xi, yi = nodes[ni]; xj, yj = nodes[nj]
        L = ((xj - xi) ** 2 + (yj - yi) ** 2) ** 0.5
        if L < 1e-9:
            continue
        geo.append((ni, nj, L, (xj - xi) / L, (yj - yi) / L, ei))
    hinges = set(); Macc = {}
    for e in range(len(geo)):
        Macc[(e, 0)] = 0.0; Macc[(e, 1)] = 0.0
    lam = 0.0; seq = []; curve = [(0.0, 0.0)]
    ctrl = free[0]
    for _ in range(maxsteps):
        K = np.zeros((ndof, ndof)); Ts = []
        for e, (ni, nj, L, cs, sn, ei) in enumerate(geo):
            rel = []
            if (e, 0) in hinges: rel.append(2)
            if (e, 1) in hinges: rel.append(5)
            kg, T, kl = _pushover_elem(EA, ei, L, cs, sn, rel); Ts.append((T, kl))
            dofs = [3 * ni, 3 * ni + 1, 3 * ni + 2, 3 * nj, 3 * nj + 1, 3 * nj + 2]
            for a in range(6):
                for b in range(6):
                    K[dofs[a], dofs[b]] += kg[a, b]
        Kff = K[np.ix_(free, free)]
        if np.linalg.matrix_rank(Kff) < Kff.shape[0]:
            return {"lambda_c": lam, "seq": seq, "curve": curve, "mechanism": True}
        du = np.zeros(ndof)
        try:
            du[free] = np.linalg.solve(Kff, P[free])
        except np.linalg.LinAlgError:
            return {"lambda_c": lam, "seq": seq, "curve": curve, "mechanism": True}
        dM = {}
        for e, (ni, nj, L, cs, sn, ei) in enumerate(geo):
            dofs = [3 * ni, 3 * ni + 1, 3 * ni + 2, 3 * nj, 3 * nj + 1, 3 * nj + 2]
            T, kl = Ts[e]
            fl = kl @ (T @ du[dofs])
            dM[(e, 0)] = fl[2]; dM[(e, 1)] = fl[5]
        best = 1e30; crit = None
        for key in Macc:
            if key in hinges:
                continue
            dm = dM[key]
            if abs(dm) < 1e-9:
                continue
            dl = (Mp - Macc[key]) / dm if dm > 0 else (-Mp - Macc[key]) / dm
            if -1e-6 <= dl < best:
                best = dl; crit = key
        if crit is None:
            return {"lambda_c": lam, "seq": seq, "curve": curve, "mechanism": False}
        best = max(best, 0.0); lam += best
        for key in Macc:
            if key not in hinges:
                Macc[key] += best * dM[key]
        hinges.add(crit); seq.append((crit, lam))
        curve.append((abs(du[ctrl]), lam))
    return {"lambda_c": lam, "seq": seq, "curve": curve, "mechanism": False}


class Pushover:
    def GetResources(self):
        return {"Pixmap": _icon("sway"), "MenuText": "Pushover (plastic hinges)",
                "ToolTip": "Nonlinear static (pushover) of the planar frame by the "
                           "event-to-event plastic-hinge method: the collapse load "
                           "factor at which a mechanism forms, the hinge sequence "
                           "and the capacity curve. Lateral unit load pattern; "
                           "uniform plastic moment M_p. Define supports first.",
                "Accel": "A, H"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        objs = _analysis_objs(doc)[0]
        bars = [o for o in objs if hasattr(o, "ResN") or getattr(o, "IsBar", False)]
        if not bars:
            bars = objs
        if not bars:
            info("No members found. Build a line model first."); return
        vals = form_dialog("Pushover (plastic hinges)", [
            {"key": "_i", "kind": "info", "default":
             "Nonlinear static pushover of the frame in the X-Z plane (event-to-"
             "event plastic hinges). A unit lateral (X) load is applied at every "
             "free node; the collapse load factor multiplies that pattern. Enter a "
             "uniform plastic moment M_p."},
            {"key": "Mp", "label": "Plastic moment M_p (kN.m)", "kind": "float",
             "default": 100.0},
            {"key": "dir", "label": "Push direction", "kind": "combo",
             "options": ["X", "Z"], "default": "X"},
        ])
        if not vals:
            return
        Mp = float(vals["Mp"]) * 1e6
        comp = 0 if vals["dir"] == "X" else 1
        # build planar nodes (X-Z plane) + elements
        nodes = []

        def nid(x, z):
            for i, (px, pz) in enumerate(nodes):
                if abs(px - x) <= 1.0 and abs(pz - z) <= 1.0:
                    return i
            nodes.append((x, z)); return len(nodes) - 1
        elems = []
        for o in bars:
            try:
                a, b = _elem_ends(o)
            except Exception:
                continue
            ni = nid(a.x, a.z); nj = nid(b.x, b.z)
            if ni != nj:
                elems.append((ni, nj, 1.0e12))
        if not elems:
            info("Could not build a planar frame from the members."); return
        fixed = {}
        for o in doc.Objects:
            r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
            if r and at is not None:
                i = nid(at.x, at.z)
                # map 6-dof restraint -> 2D (u=X, v=Z, theta=RY)
                fu = len(r) > 0 and r[0] == "1"
                fv = len(r) > 2 and r[2] == "1"
                ft = len(r) > 4 and r[4] == "1"
                pf = fixed.get(i, (False, False, False))
                fixed[i] = (pf[0] or fu, pf[1] or fv, pf[2] or ft)
        if not fixed:
            info("Define supports first - pushover needs a restrained frame."); return
        loads = {}
        nloaded = 0
        for i in range(len(nodes)):
            if i in fixed and all(fixed[i]):
                continue
            L = [0.0, 0.0, 0.0]; L[comp] = 1.0
            loads[i] = tuple(L); nloaded += 1
        res = _pushover2d(nodes, elems, fixed, loads, Mp)
        lam = res["lambda_c"]
        base_shear = lam * nloaded          # N (unit loads)
        doc.openTransaction("DynFrame: pushover")
        try:
            s = doc.getObject("Pushover") or doc.addObject("Spreadsheet::Sheet", "Pushover")
            s.Label = "Pushover"; s.clearAll()
            s.set("A1", "PUSHOVER (plastic hinges) - push %s, M_p=%g kNm, %d nodes "
                  "loaded | %s" % (vals["dir"], vals["Mp"], nloaded,
                  "MECHANISM" if res["mechanism"] else "no mechanism in range"))
            s.set("A2", "Collapse load factor"); s.set("B2", "%.1f" % lam)
            s.set("A3", "Collapse base shear (N)"); s.set("B3", "%.0f" % base_shear)
            s.set("A4", "Plastic hinges formed"); s.set("B4", "%d" % len(res["seq"]))
            s.set("A5", "Hinge sequence (elem,end @ factor)")
            s.set("B5", "; ".join("%d/%d@%.0f" % (e, en, lf)
                                  for ((e, en), lf) in res["seq"][:12]))
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Pushover failed: %s" % e); return
        info("Pushover (event-to-event plastic hinges) - push %s.\n\n"
             "Collapse load factor = %.1f  (%s)\n"
             "%d plastic hinges formed before the mechanism.\n"
             "Collapse base shear = %.0f N for the unit pattern (%d loaded nodes).\n\n"
             "See the 'Pushover' table for the hinge sequence. Uniform M_p = %g "
             "kNm; the factor multiplies the applied lateral pattern." %
             (vals["dir"], lam, "mechanism formed" if res["mechanism"]
              else "no mechanism within range - raise M_p or check supports",
              len(res["seq"]), base_shear, nloaded, vals["Mp"]))


# ── Plastic collapse (limit analysis) of a single-span beam ─────
# (case, load) -> (coefficient, kind). P_c = coef*Mp/L ; w_c = coef*Mp/L^2.
PLASTIC_CASES = {
    ("Simply supported", "point"): (4.0, "P"),
    ("Simply supported", "udl"): (8.0, "w"),
    ("Propped cantilever", "point"): (6.0, "P"),
    ("Propped cantilever", "udl"): (11.657, "w"),      # 2(3+2sqrt2)
    ("Fixed-fixed", "point"): (8.0, "P"),
    ("Fixed-fixed", "udl"): (16.0, "w"),
}


def _plastic_collapse(case, load, L, Mp):
    """Plastic-collapse (limit-analysis) load of a single-span beam from the
    kinematic mechanism. Returns (collapse load, kind): a point load P_c (N) or a
    UDL w_c (N/mm). These are the exact mechanism results used in plastic design."""
    coef, kind = PLASTIC_CASES[(case, load)]
    return (coef * Mp / L, "P") if kind == "P" else (coef * Mp / (L * L), "w")


class PlasticCollapse:
    def GetResources(self):
        return {"Pixmap": _icon("tension"), "MenuText": "Plastic Collapse (limit)",
                "ToolTip": "Plastic collapse (limit analysis) of a single-span "
                           "steel beam: the plastic moment M_p = f_y Z and the "
                           "collapse load from the kinematic mechanism (simply "
                           "supported / propped cantilever / fixed-fixed, point or "
                           "UDL), with the load factor against the applied load.",
                "Accel": "A, L"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        cases = sorted(set(k[0] for k in PLASTIC_CASES))
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Plastic collapse of a single-span beam (limit analysis). Enter the "
             "plastic modulus Z and f_y (-> M_p), the span, the support/load case "
             "and the applied load; reports the collapse load and the load factor."},
            {"key": "Z", "label": "Plastic modulus Z (mm3)", "kind": "float", "default": 1.0e6},
            {"key": "fy", "label": "Steel f_y (MPa)", "kind": "float", "default": 355.0},
            {"key": "L", "label": "Span L (mm)", "kind": "float", "default": 5000.0},
            {"key": "case", "label": "Support case", "kind": "combo",
             "options": cases, "default": "Fixed-fixed"},
            {"key": "load", "label": "Load type", "kind": "combo",
             "options": ["point", "udl"], "default": "point"},
            {"key": "applied", "label": "Applied load (kN point, or kN/m UDL)",
             "kind": "float", "default": 100.0},
        ]
        vals = form_dialog("Plastic Collapse (limit)", fields)
        if not vals:
            return
        Mp = float(vals["Z"]) * float(vals["fy"])          # N.mm
        L = float(vals["L"])
        Pc, kind = _plastic_collapse(vals["case"], vals["load"], L, Mp)
        if kind == "P":
            coll = Pc / 1e3; unit = "kN"; applied = float(vals["applied"])
        else:
            coll = Pc * 1000.0 / 1e3; unit = "kN/m"; applied = float(vals["applied"])
        factor = coll / applied if applied > 1e-9 else 0.0
        doc.openTransaction("DynFrame: plastic collapse")
        try:
            s = doc.getObject("PlasticCollapse") or doc.addObject("Spreadsheet::Sheet",
                                                                 "PlasticCollapse")
            s.Label = "PlasticCollapse"; s.clearAll()
            s.set("A1", "PLASTIC COLLAPSE - %s, %s load, L=%g mm, M_p=%.1f kNm"
                  % (vals["case"], vals["load"], L, Mp / 1e6))
            rows = [
                ("Plastic moment M_p (kNm)", "%.1f" % (Mp / 1e6)),
                ("Collapse load (%s)" % unit, "%.1f" % coll),
                ("Applied load (%s)" % unit, "%.1f" % applied),
                ("Collapse load factor", "%.2f  %s" % (factor,
                 "OK (>=1)" if factor >= 1.0 else "UNSAFE (<1)")),
            ]
            for i, (aa, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, aa); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Plastic collapse failed: %s" % e); return
        info("Plastic collapse (limit analysis) - %s beam, %s load, L = %g mm.\n\n"
             "Plastic moment M_p = f_y Z = %.1f kNm\n"
             "Collapse load = %.1f %s (applied %.1f %s)\n"
             "Collapse load factor = %.2f  %s\n\nSee the 'PlasticCollapse' table. "
             "Exact kinematic-mechanism result for a single span." %
             (vals["case"], vals["load"], L, Mp / 1e6, coll, unit, applied, unit,
              factor, "OK" if factor >= 1.0 else "UNSAFE"))


# ── AISC 360-16 steel member (US code, LRFD) ────────────────────
def _aisc_Fcr(KLr, E, Fy):
    """AISC 360-16 E3 flexural-buckling critical stress F_cr (MPa)."""
    import math
    if KLr <= 1e-9:
        return Fy
    Fe = math.pi ** 2 * E / (KLr * KLr)
    if KLr <= 4.71 * math.sqrt(E / Fy):
        return (0.658 ** (Fy / Fe)) * Fy        # inelastic
    return 0.877 * Fe                            # elastic


def _aisc_member(A, Z, r, E, Fy, KL, Pr, Mr, phi_c=0.90, phi_b=0.90):
    """AISC 360-16 LRFD compact-section member check (axial + strong-axis
    bending). Returns phiPn, phiMn and the H1-1 interaction utilisation."""
    KLr = KL / r if r > 0 else 0.0
    Fcr = _aisc_Fcr(KLr, E, Fy)
    phiPn = phi_c * Fcr * A
    phiMn = phi_b * Fy * Z
    pr = Pr / phiPn if phiPn > 0 else 0.0
    mr = Mr / phiMn if phiMn > 0 else 0.0
    util = (pr + (8.0 / 9.0) * mr) if pr >= 0.2 else (pr / 2.0 + mr)
    return {"Fcr": Fcr, "phiPn": phiPn, "phiMn": phiMn, "KLr": KLr,
            "util": util, "ok": util <= 1.0}


class AiscSteel:
    _GRADES = {"A36 (Fy=250)": 250.0, "A992/Gr50 (Fy=345)": 345.0,
               "Gr65 (Fy=450)": 450.0}

    def GetResources(self):
        return {"Pixmap": _icon("tension"), "MenuText": "AISC Steel Check (US)",
                "ToolTip": "Check a compact steel member to ANSI/AISC 360-16 (LRFD): "
                           "flexural-buckling phiP_n (chapter E), flexure phiM_n = "
                           "phi Fy Z (chapter F), and the chapter H combined "
                           "axial+bending interaction - the US-code counterpart of "
                           "the EC3 check.",
                "Accel": "A, 3"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Compact steel member to ANSI/AISC 360-16 (LRFD), SI units. Enter the "
             "section (area, plastic modulus Z, radius of gyration r), the steel "
             "grade, the effective length KL and the required strengths."},
            {"key": "grade", "label": "Steel grade", "kind": "combo",
             "options": list(self._GRADES.keys()), "default": "A992/Gr50 (Fy=345)"},
            {"key": "A", "label": "Area A (mm2)", "kind": "float", "default": 10000.0},
            {"key": "Z", "label": "Plastic modulus Z (mm3)", "kind": "float", "default": 1.0e6},
            {"key": "r", "label": "Radius of gyration r (mm)", "kind": "float", "default": 100.0},
            {"key": "KL", "label": "Effective length KL (mm)", "kind": "float", "default": 4000.0},
            {"key": "Pr", "label": "Required axial P_r (kN)", "kind": "float", "default": 1000.0},
            {"key": "Mr", "label": "Required moment M_r (kN.m)", "kind": "float", "default": 150.0},
        ]
        vals = form_dialog("AISC Steel Check (US)", fields)
        if not vals:
            return
        Fy = self._GRADES[vals["grade"]]; E = 200000.0
        res = _aisc_member(float(vals["A"]), float(vals["Z"]), float(vals["r"]), E,
                           Fy, float(vals["KL"]), float(vals["Pr"]) * 1e3,
                           float(vals["Mr"]) * 1e6)
        doc.openTransaction("DynFrame: AISC check")
        try:
            s = doc.getObject("AISC") or doc.addObject("Spreadsheet::Sheet", "AISC")
            s.Label = "AISC"; s.clearAll()
            s.set("A1", "AISC 360-16 LRFD - %s, A=%g, Z=%g, r=%g | KL=%g, P_r=%g kN, "
                  "M_r=%g kNm" % (vals["grade"], vals["A"], vals["Z"], vals["r"],
                                  vals["KL"], vals["Pr"], vals["Mr"]))
            rows = [
                ("KL/r / F_cr (MPa)", "%.0f / %.1f" % (res["KLr"], res["Fcr"])),
                ("phi P_n (kN)", "%.0f" % (res["phiPn"] / 1e3)),
                ("phi M_n (kNm)", "%.0f" % (res["phiMn"] / 1e6)),
                ("H1-1 interaction", "%.2f  %s" % (res["util"], "OK" if res["ok"] else "FAIL")),
            ]
            for i, (aa, bb) in enumerate(rows, start=2):
                s.set("A%d" % i, aa); s.set("B%d" % i, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("AISC check failed: %s" % e); return
        info("AISC 360-16 (LRFD) - %s.\n\nKL/r = %.0f, F_cr = %.1f MPa\n"
             "phi P_n = %.0f kN, phi M_n = %.0f kNm\n"
             "H1-1 interaction = %.2f  %s\n\nSee the 'AISC' table. Compact section, "
             "strong-axis bending." %
             (vals["grade"], res["KLr"], res["Fcr"], res["phiPn"] / 1e3,
              res["phiMn"] / 1e6, res["util"], "OK" if res["ok"] else "FAIL"))


# ── EC9 aluminium member (EN 1999-1-1) ──────────────────────────
ALU_ALLOYS = {"6063-T6 (fo=160)": 160.0, "6082-T6 (fo=250)": 250.0,
              "7020-T6 (fo=280)": 280.0}


def _ec9_chi(lam, alpha=0.2, lam0=0.1):
    """EN 1999-1-1 6.3.1 flexural-buckling reduction factor chi (class-A curve:
    alpha=0.2, lambda_0=0.1)."""
    if lam <= lam0:
        return 1.0
    phi = 0.5 * (1.0 + alpha * (lam - lam0) + lam * lam)
    return min(1.0 / (phi + (phi * phi - lam * lam) ** 0.5), 1.0)


def _ec9_member(A, W, fo, E, L, i, Pr, Mr, gM1=1.1, alpha_shape=1.0):
    """EN 1999-1-1 member check (SI): section/buckling axial resistance and
    bending resistance, plus a simplified axial+bending interaction."""
    import math
    M_Rd = alpha_shape * W * fo / gM1
    lam = (L / i) / (math.pi * math.sqrt(E / fo)) if i > 0 else 0.0
    chi = _ec9_chi(lam)
    N_bRd = chi * A * fo / gM1
    pr = Pr / N_bRd if N_bRd > 0 else 0.0
    mr = Mr / M_Rd if M_Rd > 0 else 0.0
    return {"M_Rd": M_Rd, "N_bRd": N_bRd, "lam": lam, "chi": chi,
            "util": pr + mr, "ok": (pr + mr) <= 1.0}


class AluminiumEC9:
    def GetResources(self):
        return {"Pixmap": _icon("tension"), "MenuText": "Aluminium Member (EC9)",
                "ToolTip": "Check an aluminium member to EN 1999-1-1: bending "
                           "resistance W fo/gamma_M1, flexural buckling (relative "
                           "slenderness -> chi) axial resistance, and the combined "
                           "axial+bending interaction - a fourth material alongside "
                           "steel, concrete and timber.",
                "Accel": "A, 9"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Aluminium member to EN 1999-1-1 (SI). Enter the alloy (0.2% proof "
             "f_o), the section (area, modulus W, radius of gyration i), the "
             "buckling length and the design forces."},
            {"key": "alloy", "label": "Alloy (f_o)", "kind": "combo",
             "options": list(ALU_ALLOYS.keys()), "default": "6082-T6 (fo=250)"},
            {"key": "A", "label": "Area A (mm2)", "kind": "float", "default": 3000.0},
            {"key": "W", "label": "Section modulus W (mm3)", "kind": "float", "default": 1.0e5},
            {"key": "i", "label": "Radius of gyration i (mm)", "kind": "float", "default": 40.0},
            {"key": "L", "label": "Buckling length L (mm)", "kind": "float", "default": 2000.0},
            {"key": "Pr", "label": "Axial N_Ed (kN)", "kind": "float", "default": 100.0},
            {"key": "Mr", "label": "Moment M_Ed (kN.m)", "kind": "float", "default": 10.0},
        ]
        vals = form_dialog("Aluminium Member (EC9)", fields)
        if not vals:
            return
        fo = ALU_ALLOYS[vals["alloy"]]; E = 70000.0      # aluminium E
        res = _ec9_member(float(vals["A"]), float(vals["W"]), fo, E,
                          float(vals["L"]), float(vals["i"]),
                          float(vals["Pr"]) * 1e3, float(vals["Mr"]) * 1e6)
        doc.openTransaction("DynFrame: EC9 check")
        try:
            s = doc.getObject("Aluminium") or doc.addObject("Spreadsheet::Sheet",
                                                            "Aluminium")
            s.Label = "Aluminium"; s.clearAll()
            s.set("A1", "ALUMINIUM EC9 - %s, A=%g, W=%g, i=%g | L=%g, N=%g kN, M=%g kNm"
                  % (vals["alloy"], vals["A"], vals["W"], vals["i"], vals["L"],
                     vals["Pr"], vals["Mr"]))
            rows = [
                ("Bending M_Rd (kNm)", "%.1f" % (res["M_Rd"] / 1e6)),
                ("Slenderness lam_bar / chi", "%.2f / %.3f" % (res["lam"], res["chi"])),
                ("Buckling N_b,Rd (kN)", "%.0f" % (res["N_bRd"] / 1e3)),
                ("Interaction N/N_b + M/M_Rd", "%.2f  %s"
                 % (res["util"], "OK" if res["ok"] else "FAIL")),
            ]
            for i2, (aa, bb) in enumerate(rows, start=2):
                s.set("A%d" % i2, aa); s.set("B%d" % i2, bb)
            _grp(doc, RES_GROUP).addObject(s)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("EC9 check failed: %s" % e); return
        info("Aluminium member (EN 1999-1-1) - %s.\n\n"
             "M_Rd = %.1f kNm\nlambda_bar = %.2f -> chi = %.3f, N_b,Rd = %.0f kN\n"
             "Interaction N/N_b,Rd + M/M_Rd = %.2f  %s\n\nSee the 'Aluminium' table." %
             (vals["alloy"], res["M_Rd"] / 1e6, res["lam"], res["chi"],
              res["N_bRd"] / 1e3, res["util"], "OK" if res["ok"] else "FAIL"))


class WallThermal:
    _NLAYER = 6

    def GetResources(self):
        return {"Pixmap": _icon("thermal"), "MenuText": "Wall U-value & Condensation",
                "ToolTip": "Thermal performance of a layered wall/roof: U-value "
                           "(EN ISO 6946) and interstitial-condensation / mould "
                           "risk by the Glaser method (EN ISO 13788) - temperature "
                           "and vapour-pressure profile through the build-up.",
                "Accel": "A, U"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        mats = ["(none)"] + list(THERMAL_MATERIALS.keys())
        defmat = ["Plasterboard", "Mineral wool", "Brick (fired clay)",
                  "(none)", "(none)", "(none)"]
        defthk = [12.5, 120.0, 100.0, 0.0, 0.0, 0.0]
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Layers from INSIDE (warm) to OUTSIDE (cold). U-value per EN ISO "
             "6946, interstitial condensation / mould by the Glaser method (EN "
             "ISO 13788). Leave a layer '(none)' to skip it."}]
        for i in range(self._NLAYER):
            fields.append({"key": "m%d" % i, "label": "Layer %d material" % (i + 1),
                           "kind": "combo", "options": mats, "default": defmat[i]})
            fields.append({"key": "d%d" % i, "label": "Layer %d thickness (mm)" % (i + 1),
                           "kind": "float", "default": defthk[i]})
        fields += [
            {"key": "Ti", "label": "Inside air temp (C)", "kind": "float", "default": 20.0},
            {"key": "RHi", "label": "Inside RH (%)", "kind": "float", "default": 60.0},
            {"key": "Te", "label": "Outside air temp (C)", "kind": "float", "default": -5.0},
            {"key": "RHe", "label": "Outside RH (%)", "kind": "float", "default": 90.0},
            {"key": "rsi", "label": "Rsi inside surface (m2K/W)", "kind": "float",
             "default": 0.13, "decimals": 3},
            {"key": "rse", "label": "Rse outside surface (m2K/W)", "kind": "float",
             "default": 0.04, "decimals": 3},
        ]
        vals = form_dialog("Wall U-value & Condensation", fields)
        if not vals:
            return
        layers = []
        for i in range(self._NLAYER):
            nm = vals["m%d" % i]; d = float(vals["d%d" % i])
            if nm == "(none)" or d <= 0.0:
                continue
            k, mu, fR = _thermal_mat(nm)[:3]
            layers.append((nm, d, k, mu, fR))
        if not layers:
            info("Add at least one layer (material + thickness)."); return
        r = _wall_thermal(layers, float(vals["Ti"]), float(vals["RHi"]),
                          float(vals["Te"]), float(vals["RHe"]),
                          float(vals["rsi"]), float(vals["rse"]))
        # dynamic (thermal-mass) response, EN ISO 13786
        dlayers = [(d / 1000.0, k, _thermal_mat(nm)[3], _thermal_mat(nm)[4])
                   for (nm, d, k, _mu, _fR) in layers]
        dyn = _dynamic_thermal(dlayers, float(vals["rsi"]), float(vals["rse"]))
        doc.openTransaction("DynFrame: wall thermal")
        try:
            sh = doc.getObject("WallThermal") or \
                doc.addObject("Spreadsheet::Sheet", "WallThermal")
            sh.Label = "WallThermal"; sh.clearAll()
            sh.set("A1", "WALL THERMAL - U=%.3f W/m2K, R=%.3f, q=%.1f W/m2, "
                   "f_Rsi=%.3f | dynamic: decrement f=%.3f, time lag=%.1f h%s"
                   % (r["U"], r["R"], r["q"], r["fRsi"], dyn["f"], dyn["lag_h"],
                      "  CONDENSATION RISK" if r["condensation"] else ""))
            for c, h in zip("ABCDEF", ["Interface", "T (C)", "p_vapour (Pa)",
                                       "p_sat (Pa)", "RH (%)", "Condensation?"]):
                sh.set("%s2" % c, h)
            names = ["Internal surface"] + [L[0] + "/next" for L in layers[:-1]] \
                + ["External surface"]
            row = 3
            for i in range(len(r["nodeT"])):
                T = r["nodeT"][i]; p = r["nodeP"][i]; ps = r["nodePsat"][i]
                nm = names[i] if i < len(names) else "node %d" % i
                vals_row = [nm, "%.2f" % T, "%.0f" % p, "%.0f" % ps,
                            "%.0f" % (100.0 * p / ps if ps > 1e-6 else 0.0),
                            "YES" if r["cond"][i] else "-"]
                for c, v in zip("ABCDEF", vals_row):
                    sh.set("%s%d" % (c, row), v)
                row += 1
            _grp(doc, RES_GROUP).addObject(sh)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Wall thermal failed: %s" % e); return
        mould = r["fRsi"] < 0.70
        info("Wall thermal (EN ISO 6946 / 13788) - %d layer(s).\n\n"
             "U-value = %.3f W/m2K   (R = %.3f m2K/W)\n"
             "Heat flux = %.1f W/m2 at %g/%g C.\n"
             "Internal surface temp = %.1f C, f_Rsi = %.3f%s\n"
             "Interstitial condensation: %s\n"
             "Dynamic (EN ISO 13786): decrement factor f = %.3f, time lag = "
             "%.1f h (thermal mass damps a daily swing to %.0f%% of it, delayed "
             "%.1f h).\n\n"
             "See the 'WallThermal' table for the temperature / vapour / "
             "saturation profile through the build-up. (Condensation where the "
             "vapour pressure reaches saturation; mould risk if f_Rsi < 0.70.)" %
             (len(layers), r["U"], r["R"], r["q"], float(vals["Ti"]),
              float(vals["Te"]), r["nodeT"][0], r["fRsi"],
              "  - MOULD RISK (f_Rsi < 0.70)" if mould else "",
              "RISK - vapour reaches saturation inside the build-up"
              if r["condensation"] else "none predicted",
              dyn["f"], dyn["lag_h"], 100.0 * dyn["f"], dyn["lag_h"]))


class ThermalBridge2D:
    _NLAYER = 5

    def GetResources(self):
        return {"Pixmap": _icon("bridge2d"), "MenuText": "Thermal Bridge (2D)",
                "ToolTip": "2-D steady heat-conduction FE (EN ISO 10211) through a "
                           "wall with a repeating conductive element bridging the "
                           "insulation (steel/timber stud, concrete rib): the "
                           "temperature field, the bridged U-value and the surface "
                           "temperature factor f_Rsi (mould/condensation risk).",
                "Accel": "A, B"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        mats = ["(none)"] + list(THERMAL_MATERIALS.keys())
        defmat = ["Plasterboard", "Mineral wool", "Brick (fired clay)",
                  "(none)", "(none)"]
        defthk = [12.5, 140.0, 100.0, 0.0, 0.0]
        fields = [{"key": "_i", "kind": "info", "default":
                   "2-D conduction through the wall (inside->outside layers) with a "
                   "repeating bridge of the given material/width at the given "
                   "spacing, placed across the insulation (lowest-conductivity) "
                   "layer. Solves the temperature field and the bridged U-value."}]
        for i in range(self._NLAYER):
            fields.append({"key": "m%d" % i, "label": "Layer %d material" % (i + 1),
                           "kind": "combo", "options": mats, "default": defmat[i]})
            fields.append({"key": "d%d" % i, "label": "Layer %d thickness (mm)" % (i + 1),
                           "kind": "float", "default": defthk[i]})
        fields += [
            {"key": "bmat", "label": "Bridge material", "kind": "combo",
             "options": list(THERMAL_MATERIALS.keys()), "default": "Timber (softwood)"},
            {"key": "bw", "label": "Bridge width (mm)", "kind": "float", "default": 48.0},
            {"key": "bs", "label": "Bridge spacing (mm)", "kind": "float", "default": 600.0},
            {"key": "Ti", "label": "Inside air temp (C)", "kind": "float", "default": 20.0},
            {"key": "Te", "label": "Outside air temp (C)", "kind": "float", "default": -5.0},
            {"key": "rsi", "label": "Rsi (m2K/W)", "kind": "float", "default": 0.13, "decimals": 3},
            {"key": "rse", "label": "Rse (m2K/W)", "kind": "float", "default": 0.04, "decimals": 3},
        ]
        vals = form_dialog("Thermal Bridge (2D conduction)", fields)
        if not vals:
            return
        layers = []
        for i in range(self._NLAYER):
            nm = vals["m%d" % i]; d = float(vals["d%d" % i])
            if nm == "(none)" or d <= 0.0:
                continue
            k, mu, fR = _thermal_mat(nm)[:3]
            layers.append((nm, d / 1000.0, k))      # (name, thickness_m, k)
        if not layers:
            info("Add at least one layer."); return
        Ti = float(vals["Ti"]); Te = float(vals["Te"])
        rsi = float(vals["rsi"]); rse = float(vals["rse"])
        kb = _thermal_mat(vals["bmat"])[0]
        Wb = max(1e-4, float(vals["bw"]) / 1000.0)
        Wsp = max(Wb + 1e-4, float(vals["bs"]) / 1000.0)
        bridged = min(range(len(layers)), key=lambda i: layers[i][2])   # insulation
        # layer x-boundaries and the bridged layer's x-range
        xb = [0.0]
        for (_n, d, _k) in layers:
            xb.append(xb[-1] + d)
        Xtot = xb[-1]
        bx0, bx1 = xb[bridged], xb[bridged + 1]
        # x node coords aligned to layer interfaces, subdivided
        target = Xtot / 35.0
        xs = [0.0]
        for i in range(len(layers)):
            d = layers[i][1]; n = max(2, int(round(d / target)))
            for s in range(1, n + 1):
                xs.append(xb[i] + d * s / n)
        # y node coords: 0..Wsp with a node at the bridge edge Wb
        NY = 26
        ys = sorted(set([Wsp * j / NY for j in range(NY + 1)] + [Wb]))
        nx = len(xs); ny = len(ys)

        def nid(ix, iy):
            return iy * nx + ix
        nodes = [(xs[ix], ys[iy]) for iy in range(ny) for ix in range(nx)]
        tris = []; ktri = []

        def kat(xc, yc):
            lay = 0
            for i in range(len(layers)):
                if xb[i] <= xc <= xb[i + 1] + 1e-12:
                    lay = i; break
            if lay == bridged and yc <= Wb:
                return kb
            return layers[lay][2]
        for iy in range(ny - 1):
            for ix in range(nx - 1):
                a = nid(ix, iy); b = nid(ix + 1, iy)
                c = nid(ix + 1, iy + 1); d = nid(ix, iy + 1)
                xc = 0.5 * (xs[ix] + xs[ix + 1]); yc = 0.5 * (ys[iy] + ys[iy + 1])
                kc = kat(xc, yc)
                tris.append((a, b, c)); ktri.append(kc)
                tris.append((a, c, d)); ktri.append(kc)
        # convective boundary edges: inside face x=0 (ix=0), outside x=Xtot (ix=nx-1)
        robin = []
        hi = 1.0 / rsi if rsi > 1e-9 else 1e6
        he = 1.0 / rse if rse > 1e-9 else 1e6
        for iy in range(ny - 1):
            robin.append((nid(0, iy), nid(0, iy + 1), hi, Ti))
            robin.append((nid(nx - 1, iy), nid(nx - 1, iy + 1), he, Te))
        try:
            T = _run_conduction(nodes, tris, ktri, robin)
        except Exception as e:
            err("Conduction solve failed: %s" % e); return
        # heat flow in through the inside face -> 2-D U-value over the spacing
        Qin = 0.0; tsurf = []
        for iy in range(ny - 1):
            i = nid(0, iy); j = nid(0, iy + 1)
            Le = abs(ys[iy + 1] - ys[iy])
            Qin += hi * Le * (Ti - 0.5 * (T[i] + T[j]))
        for iy in range(ny):
            tsurf.append(T[nid(0, iy)])
        U2d = Qin / (Wsp * (Ti - Te)) if abs(Ti - Te) > 1e-9 else 0.0
        U1d, R1d, _p = _wall_uvalue([(n, d * 1000.0, k, 1, None) for (n, d, k) in layers],
                                    rsi, rse)
        Tsi_min = min(tsurf)
        fRsi = (Tsi_min - Te) / (Ti - Te) if abs(Ti - Te) > 1e-9 else 1.0

        doc.openTransaction("DynFrame: thermal bridge")
        self._contour(doc, nodes, tris, T, Te, Ti)
        try:
            sh = doc.getObject("ThermalBridge") or \
                doc.addObject("Spreadsheet::Sheet", "ThermalBridge")
            sh.Label = "ThermalBridge"; sh.clearAll()
            sh.set("A1", "THERMAL BRIDGE (EN ISO 10211, 2D conduction)")
            rows = [("U 1-D plain wall (W/m2K)", "%.3f" % U1d),
                    ("U 2-D with bridge (W/m2K)", "%.3f" % U2d),
                    ("Increase from bridge", "%.0f %%" % (100.0 * (U2d / U1d - 1.0)
                                                          if U1d > 1e-9 else 0.0)),
                    ("Min internal surface T (C)", "%.2f" % Tsi_min),
                    ("Temperature factor f_Rsi", "%.3f" % fRsi),
                    ("Mould risk (f_Rsi < 0.70)", "YES" if fRsi < 0.70 else "no"),
                    ("Bridge", "%s %.0f mm @ %.0f mm" % (vals["bmat"],
                                                         Wb * 1000, Wsp * 1000))]
            for n, (a, b) in enumerate(rows):
                sh.set("A%d" % (n + 3), a); sh.set("B%d" % (n + 3), b)
            _grp(doc, RES_GROUP).addObject(sh)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Thermal bridge table failed: %s" % e); return
        try:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Thermal bridge (EN ISO 10211) solved on a %dx%d node 2-D section.\n\n"
             "U plain wall = %.3f, U with the %s bridge = %.3f W/m2K "
             "(+%.0f%%).\nMin internal surface temp = %.2f C, f_Rsi = %.3f%s.\n\n"
             "Showing the temperature field; see the 'ThermalBridge' table. "
             "(f_Rsi < 0.70 means mould/condensation risk at the bridge.)" %
             (nx, ny, U1d, vals["bmat"], U2d, 100.0 * (U2d / U1d - 1.0) if U1d > 1e-9
              else 0.0, Tsi_min, fRsi,
              " - MOULD RISK" if fRsi < 0.70 else ""))

    def _contour(self, doc, nodes, tris, T, Tmin, Tmax):
        for o in list(doc.Objects):
            if o.Name.startswith("ThermMap"):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        span = (Tmax - Tmin) or 1.0; NB = 16
        bands = [[] for _ in range(NB)]
        for t, tri in enumerate(tris):
            try:
                pts = [FreeCAD.Vector(nodes[i][0] * 1000.0, nodes[i][1] * 1000.0, 0.0)
                       for i in tri]
                f = Part.Face(Part.makePolygon(pts + [pts[0]]))
            except Exception:
                continue
            tav = (T[tri[0]] + T[tri[1]] + T[tri[2]]) / 3.0
            bands[min(NB - 1, max(0, int((tav - Tmin) / span * NB)))].append(f)
        grp = _grp(doc, DIA_GROUP)
        for b, fs in enumerate(bands):
            if not fs:
                continue
            ob = doc.addObject("Part::Feature", "ThermMap_b%d" % b)
            ob.Shape = Part.makeCompound(fs)
            ob.Label = "Temperature (C)"
            _set(ob, "App::PropertyString", "DiagKind", "_thermal")
            _set(ob, "App::PropertyFloat", "CompMax", float(Tmax))
            _set(ob, "App::PropertyFloat", "CompMin", float(Tmin))
            col = _ramp((b + 0.5) / NB)
            try:
                ob.ViewObject.ShapeColor = col; ob.ViewObject.LineColor = col
            except Exception:
                pass
            grp.addObject(ob)


class FireThermal:
    _EXPOSURE = {"All 4 sides (column)": "all", "3 sides (beam soffit+webs)": "three",
                 "Underside only (slab/floor)": "bottom", "One face (wall)": "one"}

    def GetResources(self):
        return {"Pixmap": _icon("fire"), "MenuText": "Fire Resistance (transient)",
                "ToolTip": "Transient 2-D heat conduction through a section exposed "
                           "to the standard fire (ISO 834 / EN 1991-1-2): the "
                           "temperature field over time, with the temperature at the "
                           "reinforcement cover depth - for fire-rating / reduced-"
                           "capacity checks.", "Accel": "A, F"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        mats = list(THERMAL_MATERIALS.keys())
        vals = form_dialog("Fire Resistance (transient thermal)", [
            {"key": "_i", "kind": "info", "default":
             "2-D transient conduction in a rectangular section exposed to the "
             "standard fire (ISO 834). The exposed faces follow the fire gas "
             "temperature; reports the temperature at the cover depth and the "
             "core over time. (Surface = gas temperature, i.e. conservative.)"},
            {"key": "mat", "label": "Section material", "kind": "combo",
             "options": mats, "default": "Reinforced concrete"},
            {"key": "w", "label": "Section width (mm)", "kind": "float", "default": 300.0},
            {"key": "h", "label": "Section depth (mm)", "kind": "float", "default": 300.0},
            {"key": "exp", "label": "Fire exposure", "kind": "combo",
             "options": list(self._EXPOSURE.keys()), "default": "All 4 sides (column)"},
            {"key": "cover", "label": "Reinforcement cover (mm)", "kind": "float",
             "default": 35.0},
            {"key": "dur", "label": "Fire duration (min)", "kind": "float", "default": 60.0},
            {"key": "dt", "label": "Time step (s)", "kind": "float", "default": 15.0},
            {"key": "ndiv", "label": "Mesh divisions (each way)", "kind": "int",
             "default": 30, "min": 6, "max": 120},
        ])
        if not vals:
            return
        k, _mu, _fR, rho, cp = _thermal_mat(vals["mat"])
        W = float(vals["w"]) / 1000.0; H = float(vals["h"]) / 1000.0
        cover = float(vals["cover"]) / 1000.0
        dur = max(1.0, float(vals["dur"])); dt = max(1.0, float(vals["dt"]))
        nd = max(6, int(vals["ndiv"]))
        exposure = self._EXPOSURE.get(vals["exp"], "all")
        nx = nd + 1; ny = max(6, int(nd * H / W)) + 1 if W > 1e-9 else nd + 1
        xs = [W * i / (nx - 1) for i in range(nx)]
        ys = [H * j / (ny - 1) for j in range(ny)]

        def nid(ix, iy):
            return iy * nx + ix
        nodes = [(xs[ix], ys[iy]) for iy in range(ny) for ix in range(nx)]
        tris = []; ktri = []; cap = [0.0] * len(nodes)
        for iy in range(ny - 1):
            for ix in range(nx - 1):
                a = nid(ix, iy); b = nid(ix + 1, iy)
                c = nid(ix + 1, iy + 1); d = nid(ix, iy + 1)
                for tri in ((a, b, c), (a, c, d)):
                    _Ke, A = _cond_tri([nodes[i] for i in tri], k)
                    tris.append(tri); ktri.append(k)
                    for nn in tri:
                        cap[nn] += rho * cp * A / 3.0        # lumped heat capacity
        # exposed (fire-driven) boundary nodes
        fixed = set()
        for ix in range(nx):
            for iy in range(ny):
                left = ix == 0; right = ix == nx - 1
                bot = iy == 0; top = iy == ny - 1
                if exposure == "all" and (left or right or bot or top):
                    fixed.add(nid(ix, iy))
                elif exposure == "three" and (left or right or bot):
                    fixed.add(nid(ix, iy))
                elif exposure == "bottom" and bot:
                    fixed.add(nid(ix, iy))
                elif exposure == "one" and bot:
                    fixed.add(nid(ix, iy))
        # monitor nodes: cover depth from the (bottom) fire face, and the centre
        iy_cov = min(range(ny), key=lambda j: abs(ys[j] - cover))
        mon_cov = nid(nx // 2, iy_cov)
        mon_core = nid(nx // 2, ny // 2)
        nsteps = int(round(dur * 60.0 / dt))
        Tf, hist = _transient_conduction(nodes, tris, ktri, cap, fixed,
                                         lambda t: _iso834(t / 60.0), 20.0, dt,
                                         nsteps, [mon_cov, mon_core])
        Tcov = hist[-1][1][0]; Tcore = hist[-1][1][1]
        # time for the cover depth to pass 500 C (steel critical temperature)
        t500 = None
        for (t, mv) in hist:
            if mv[0] >= 500.0:
                t500 = t / 60.0; break
        doc.openTransaction("DynFrame: fire thermal")
        self._contour(doc, nodes, tris, Tf)
        try:
            sh = doc.getObject("FireThermal") or \
                doc.addObject("Spreadsheet::Sheet", "FireThermal")
            sh.Label = "FireThermal"; sh.clearAll()
            sh.set("A1", "FIRE RESISTANCE (ISO 834) - %s %gx%g mm, %s, %g min" %
                   (vals["mat"], vals["w"], vals["h"], vals["exp"], dur))
            sh.set("A2", "t (min)"); sh.set("B2", "fire gas T (C)")
            sh.set("C2", "T at cover %.0f mm (C)" % (cover * 1000))
            sh.set("D2", "T core (C)")
            step = max(1, len(hist) // 60); r = 3
            for (t, mv) in hist[::step]:
                sh.set("A%d" % r, "%.1f" % (t / 60.0))
                sh.set("B%d" % r, "%.0f" % _iso834(t / 60.0))
                sh.set("C%d" % r, "%.0f" % mv[0]); sh.set("D%d" % r, "%.0f" % mv[1])
                r += 1
            _grp(doc, RES_GROUP).addObject(sh)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Fire thermal failed: %s" % e); return
        try:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Fire resistance (ISO 834 standard fire) - %s %gx%g mm, %s.\n\n"
             "After %g min: fire gas %.0f C; temperature at the %.0f mm cover = "
             "%.0f C; section core = %.0f C.\n%s\n\nShowing the temperature field; "
             "see the 'FireThermal' table for the time history. (Steel loses ~50%% "
             "strength by ~550 C; concrete spalls/weakens above ~400-500 C.)" %
             (vals["mat"], vals["w"], vals["h"], vals["exp"], dur,
              _iso834(dur), cover * 1000, Tcov, Tcore,
              ("Reinforcement reached 500 C at ~%.0f min." % t500) if t500
              else "Reinforcement stayed below 500 C."))

    def _contour(self, doc, nodes, tris, T):
        for o in list(doc.Objects):
            if o.Name.startswith("FireMap"):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        Tmin = min(T); Tmax = max(T); span = (Tmax - Tmin) or 1.0; NB = 16
        bands = [[] for _ in range(NB)]
        for t, tri in enumerate(tris):
            try:
                pts = [FreeCAD.Vector(nodes[i][0] * 1000.0, nodes[i][1] * 1000.0, 0.0)
                       for i in tri]
                f = Part.Face(Part.makePolygon(pts + [pts[0]]))
            except Exception:
                continue
            tav = (T[tri[0]] + T[tri[1]] + T[tri[2]]) / 3.0
            bands[min(NB - 1, max(0, int((tav - Tmin) / span * NB)))].append(f)
        grp = _grp(doc, DIA_GROUP)
        for b, fs in enumerate(bands):
            if not fs:
                continue
            ob = doc.addObject("Part::Feature", "FireMap_b%d" % b)
            ob.Shape = Part.makeCompound(fs); ob.Label = "Fire temperature (C)"
            _set(ob, "App::PropertyString", "DiagKind", "_thermal")
            _set(ob, "App::PropertyFloat", "CompMax", float(Tmax))
            _set(ob, "App::PropertyFloat", "CompMin", float(Tmin))
            col = _ramp((b + 0.5) / NB)
            try:
                ob.ViewObject.ShapeColor = col; ob.ViewObject.LineColor = col
            except Exception:
                pass
            grp.addObject(ob)


# ── CFD (OpenFOAM) ───────────────────────────────────────────────
def _cfd_outdir():
    """Windows-visible folder where DynFrame writes the generated .sh scripts
    and receives the VTK results for ParaView. Overridable in tests."""
    return os.path.join(os.path.expanduser("~"), "dynframe_cfd")


def _write_lf(path, text):
    """Write a shell script with LF endings, so bash in WSL is happy even though
    FreeCAD wrote it from Windows."""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    data = (text if text.endswith("\n") else text + "\n").encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data.replace(b"\r\n", b"\n"))


def _try_launch_terminal(argv):
    """Best-effort: start a visible terminal running argv (Windows Terminal, else
    a headless WSL process that logs to the case). Never raises; returns a short
    status string."""
    import subprocess
    try:
        subprocess.Popen(["wt.exe"] + list(argv), close_fds=True)
        return "launched in Windows Terminal"
    except Exception:
        pass
    try:
        subprocess.Popen(list(argv), close_fds=True)
        return "launched (headless; watch the case log)"
    except Exception as e:
        return "could not auto-launch (%s) - run the command yourself" % e


def _cfd_record(doc, name, rows):
    """Store the case summary + the exact WSL commands in a CFD_<name> sheet."""
    if doc is None:
        return
    doc.openTransaction("DynFrame: CFD case")
    try:
        sh = doc.getObject("CFD_%s" % name) or \
            doc.addObject("Spreadsheet::Sheet", "CFD_%s" % name)
        sh.Label = "CFD_%s" % name
        sh.clearAll()
        for i, (a, b) in enumerate(rows, start=1):
            sh.set("A%d" % i, str(a))
            sh.set("B%d" % i, str(b))
        _grp(doc, CFD_GROUP).addObject(sh)
        doc.commitTransaction()
        doc.recompute()
    except Exception:
        try:
            doc.abortTransaction()
        except Exception:
            pass


def _cfd_clear_setup(doc, name):
    for nm in ("CFDDomain_%s" % name, "CFDInlet_%s" % name):
        o = doc.getObject(nm)
        if o is not None:
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass


def _draw_cfd_domain(doc, dom_mm, Ux=0.0, name="part1"):
    """Draw the flow domain as a transparent box with its six faces coloured by
    boundary condition (green inlet, red outlet, blue far-field, tan ground) plus
    a grid of inlet arrows along +X - a SimScale-style visual of the CFD setup in
    the FreeCAD 3D view. dom_mm is the domain (x0,y0,z0,x1,y1,z1) in millimetres.
    All drawing is best-effort so it never breaks the command."""
    if doc is None or cfdgen is None:
        return
    try:
        import Part
    except Exception:
        return
    x0, y0, z0, x1, y1, z1 = [float(v) for v in dom_mm]
    _cfd_clear_setup(doc, name)
    try:
        box = Part.makeBox(max(x1 - x0, 1e-6), max(y1 - y0, 1e-6),
                           max(z1 - z0, 1e-6), FreeCAD.Vector(x0, y0, z0))
        ob = doc.addObject("Part::Feature", "CFDDomain_%s" % name)
        ob.Shape = box
        ob.Label = "CFD domain: %s" % name
        _set(ob, "App::PropertyString", "DiagKind", "_cfd")
        try:
            vo = ob.ViewObject
            vo.DisplayMode = "Shaded"
            vo.Transparency = 82
            vo.DiffuseColor = [tuple(c) for c in cfdgen.DOMAIN_FACE_COLORS]
        except Exception:
            pass
        _grp(doc, CFD_GROUP).addObject(ob)
    except Exception:
        pass
    # inlet velocity arrows (3x3 grid on the inlet face, pointing +X)
    try:
        Lx = x1 - x0
        aL = max(Lx * 0.12, (y1 - y0) * 0.12, 1e-3)
        rad = aL * 0.09
        parts = []
        for fy in (0.3, 0.5, 0.7):
            for fz in (0.3, 0.5, 0.7):
                yy = y0 + (y1 - y0) * fy
                zz = z0 + (z1 - z0) * fz
                parts.append(Part.makeCylinder(rad, aL * 0.7,
                             FreeCAD.Vector(x0, yy, zz), FreeCAD.Vector(1, 0, 0)))
                parts.append(Part.makeCone(rad * 2.2, 0.0, aL * 0.3,
                             FreeCAD.Vector(x0 + aL * 0.7, yy, zz),
                             FreeCAD.Vector(1, 0, 0)))
        ar = doc.addObject("Part::Feature", "CFDInlet_%s" % name)
        ar.Shape = Part.makeCompound(parts)
        ar.Label = "CFD inlet +X" + (" %.3g m/s" % Ux if Ux else "")
        _set(ar, "App::PropertyString", "DiagKind", "_cfd")
        try:
            ar.ViewObject.ShapeColor = (0.10, 0.80, 0.30)
            ar.ViewObject.LineColor = (0.10, 0.80, 0.30)
        except Exception:
            pass
        _grp(doc, CFD_GROUP).addObject(ar)
    except Exception:
        pass


class CfdDomain:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_domain"),
                "MenuText": "CFD Domain & BCs (preview)",
                "ToolTip": "Show the CFD setup on the selected solid, SimScale-"
                           "style: draw the flow domain as a box with its faces "
                           "coloured by boundary condition (green inlet, red "
                           "outlet, blue far-field, tan ground) and inlet arrows "
                           "along +X. Visual preview only - no meshing or solving; "
                           "run CFD Flow to solve.",
                "Accel": "C, D"}

    def IsActive(self):
        return cfdgen is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        if cfdgen is None:
            err("The CFD module (dynframe_cfd_gen.py) failed to load."); return
        try:
            sel = [o for o in FreeCADGui.Selection.getSelection()
                   if getattr(o, "Shape", None) is not None]
        except Exception:
            sel = []
        if not sel:
            info("Select the solid the air flows around, then run CFD Domain.")
            return
        obj = sel[0]
        try:
            bb = global_shape(obj).BoundBox       # millimetres
        except Exception as e:
            err("Could not read the geometry of '%s': %s"
                % (getattr(obj, "Label", "?"), e)); return
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Preview the CFD flow domain + boundary-condition faces on '%s' in "
             "the 3D view. +X is the flow direction. Margins are multiples of the "
             "body length. Green = inlet, red = outlet, blue = far-field sides/"
             "top, tan = ground." % getattr(obj, "Label", "body")},
            {"key": "name", "label": "Case name", "kind": "text", "default": "flow1"},
            {"key": "U", "label": "Inlet speed (m/s, for the arrow label)",
             "kind": "float", "default": 10.0, "decimals": 3},
            {"key": "up", "label": "Upstream margin (x L)", "kind": "float", "default": 3.0},
            {"key": "down", "label": "Downstream margin (x L)", "kind": "float", "default": 6.0},
            {"key": "side", "label": "Side margin (x L)", "kind": "float", "default": 3.0},
            {"key": "top", "label": "Top margin (x L)", "kind": "float", "default": 3.0},
            {"key": "ground", "label": "Below margin (x L)", "kind": "float", "default": 3.0},
        ]
        vals = form_dialog("CFD Domain & BCs (preview)", fields,
                           **_cfd_dialog_kwargs(
                               "CFD Domain & Boundary Conditions",
                               "Flow domain + colour-coded BC faces on the "
                               "selected solid (+X is the flow direction)."))
        if not vals:
            return
        name = (str(vals.get("name") or "flow1").strip().replace(" ", "_")) or "flow1"
        dom = cfdgen.domain_from_bbox(
            bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax,
            up=float(vals["up"]), down=float(vals["down"]), side=float(vals["side"]),
            top=float(vals["top"]), ground=float(vals["ground"]))
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: CFD domain")
        try:
            _draw_cfd_domain(doc, dom, float(vals["U"]), name)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            err("Could not draw the CFD domain: %s" % e); return
        try:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Drew the CFD setup for '%s' on the part.\n\nThe box is the flow "
             "domain; its faces are the boundary conditions - GREEN = inlet (air "
             "enters, +X), RED = outlet, BLUE = far-field sides/top, TAN = ground. "
             "The green arrows are the inlet velocity. Adjust the margins and re-"
             "run to resize it. When it looks right, run CFD Flow to mesh + solve."
             % name)


class CfdCase:
    def GetResources(self):
        return {"Pixmap": _icon("cfd"), "MenuText": "CFD Case (OpenFOAM)",
                "ToolTip": "Set up and run a CFD case on your OpenFOAM install "
                           "(the same engine SimScale uses), from any of its 20 "
                           "solver modules - flow, heat/CHT, multiphase, "
                           "combustion, particles. DynFrame copies OpenFOAM's "
                           "own validated tutorial for the chosen physics, sets "
                           "your run controls, runs it, and converts the result "
                           "to VTK for ParaView. Same case -> same results.",
                "Accel": "C, F"}

    def IsActive(self):
        return cfd is not None

    def Activated(self):
        if cfd is None:
            err("The CFD module (dynframe_cfd.py) failed to load."); return
        titles = [c["title"] for c in cfd.CATALOG]
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Drive OpenFOAM - the same solver SimScale runs - from FreeCAD. "
             "Pick a physics module; DynFrame copies OpenFOAM's validated "
             "tutorial for it, applies your run controls, runs it on your "
             "WSL/Linux OpenFOAM and converts the result to VTK for ParaView. "
             "For the SAME case (mesh + BCs + model) you get the SAME results. "
             "Changing it to your own geometry/BCs is the case-specific step "
             "(CfdOF's mesher for flow; adapt the tutorial for advanced physics)."},
            {"key": "phys", "label": "Physics module", "kind": "combo",
             "options": titles, "default": titles[0]},
            {"key": "name", "label": "Case name (folder)", "kind": "text",
             "default": "case1"},
            {"key": "endTime", "label": "End time", "kind": "float",
             "default": 100.0, "decimals": 4},
            {"key": "deltaT", "label": "Time step (0 = keep tutorial's)",
             "kind": "float", "default": 0.0, "decimals": 6},
            {"key": "writeInterval", "label": "Write interval (0 = keep)",
             "kind": "float", "default": 0.0, "decimals": 4},
            {"key": "inletU", "label": "Inlet velocity Ux m/s (0 = keep; needs an "
             "'inlet' patch)", "kind": "float", "default": 0.0, "decimals": 4},
            {"key": "case", "label": "Tutorial case (blank = first available)",
             "kind": "text", "default": ""},
            {"key": "latest", "label": "View: latest time only", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
            {"key": "distro", "label": "WSL distro (blank = your default)",
             "kind": "text", "default": ""},
            {"key": "env", "label": "OpenFOAM env (source)", "kind": "text",
             "default": cfd.DEFAULT_OF_ENV},
            {"key": "run", "label": "Try to launch the run now", "kind": "combo",
             "options": ["No", "Yes"], "default": "No"},
        ]
        vals = form_dialog("CFD Case (OpenFOAM)", fields,
                           **_cfd_dialog_kwargs(
                               "CFD Case - OpenFOAM",
                               "Run any of the 20 OpenFOAM physics modules from "
                               "its validated tutorial (the engine SimScale runs)."))
        if not vals:
            return
        ent = next((c for c in cfd.CATALOG if c["title"] == vals["phys"]),
                   cfd.CATALOG[0])
        name = (str(vals.get("name") or "case1").strip().replace(" ", "_")) or "case1"
        of_env = str(vals.get("env") or cfd.DEFAULT_OF_ENV).strip()
        distro = str(vals.get("distro") or "").strip()  # blank => WSL default distro
        edits = cfd.control_edits({"endTime": vals.get("endTime"),
                                   "deltaT": vals.get("deltaT"),
                                   "writeInterval": vals.get("writeInterval")})
        try:
            if float(vals.get("inletU") or 0.0) != 0.0:
                edits.append(cfd.inlet_velocity_edit(float(vals["inletU"])))
        except (TypeError, ValueError):
            pass
        case = str(vals.get("case") or "").strip() or None
        run_script = cfd.build_case_script(
            {"of_env": of_env, "module": ent["module"],
             "multiRegion": ent["multiRegion"], "solve": ent["solve"],
             "tutorial": ent["tutorial"], "case": case, "name": name,
             "edits": edits})
        outdir = _cfd_outdir()
        win_out = os.path.join(outdir, name)
        view_script = cfd.build_view_script(
            {"of_env": of_env, "name": name, "win_out": win_out,
             "latest": vals.get("latest", "Yes") == "Yes"})
        run_path = os.path.join(outdir, "run_%s.sh" % name)
        view_path = os.path.join(outdir, "view_%s.sh" % name)
        try:
            _write_lf(run_path, run_script)
            _write_lf(view_path, view_script)
        except Exception as e:
            err("Could not write the CFD scripts to %s:\n%s" % (outdir, e)); return
        run_cmd = "bash %s" % cfd.win_to_wsl(run_path, distro)
        view_cmd = "bash %s" % cfd.win_to_wsl(view_path, distro)
        _cfd_record(FreeCAD.ActiveDocument, name, [
            ("Module", ent["title"]), ("Solver", ent["module"] or "(mesh only)"),
            ("Tutorial", ent["tutorial"]), ("Case name", name),
            ("Applies to", ent["use"]),
            ("1) Run (paste in WSL)", run_cmd),
            ("2) View (paste in WSL)", view_cmd),
            ("Then open in ParaView", os.path.join(win_out, "VTK")),
            ("Run script", run_path), ("View script", view_path)])
        launch = ""
        if vals.get("run") == "Yes":
            launch = "\n\nAuto-run: " + _try_launch_terminal(
                cfd.wsl_run_argv(run_script, distro))
        info("CFD case '%s' - %s\n(engine: OpenFOAM, the same SimScale runs)\n\n"
             "DynFrame wrote two ready scripts. In your WSL OpenFOAM terminal:\n\n"
             "  1) run it:\n     %s\n\n"
             "  2) convert + copy results for ParaView:\n     %s\n\n"
             "Then open in ParaView:  %s\n\n"
             "The case is built from OpenFOAM's own '%s' tutorial, so it runs as-"
             "is; edit %s\\run_%s.sh (or the case's 0/ and constant/ files) to put "
             "in your geometry's boundary conditions. The full command list is in "
             "the 'CFD_%s' sheet.%s" %
             (name, ent["title"], run_cmd, view_cmd,
              os.path.join(win_out, "VTK"), ent["tutorial"], outdir, name, name,
              launch))


class CfdView:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_view"), "MenuText": "CFD View (export VTK)",
                "ToolTip": "Convert an existing OpenFOAM case's latest results to "
                           "VTK (all regions) and copy them to a Windows folder, "
                           "ready to open in ParaView. Use after a run, or to "
                           "re-export a case you set up elsewhere.",
                "Accel": "C, V"}

    def IsActive(self):
        return cfd is not None

    def Activated(self):
        if cfd is None:
            err("The CFD module (dynframe_cfd.py) failed to load."); return
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Convert an OpenFOAM case's latest results to VTK and copy them to a "
             "Windows folder for ParaView (File > Open the VTK folder, Apply, "
             "colour by T or U). The case must already exist under ~/dynframe_cfd "
             "on the Linux side (that is where CFD Case builds them)."},
            {"key": "name", "label": "Case name (folder under ~/dynframe_cfd)",
             "kind": "text", "default": "case1"},
            {"key": "latest", "label": "Latest time only", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
            {"key": "distro", "label": "WSL distro (blank = your default)",
             "kind": "text", "default": ""},
            {"key": "env", "label": "OpenFOAM env (source)", "kind": "text",
             "default": cfd.DEFAULT_OF_ENV},
            {"key": "run", "label": "Try to run the conversion now", "kind": "combo",
             "options": ["No", "Yes"], "default": "No"},
        ]
        vals = form_dialog("CFD View in ParaView", fields,
                           **_cfd_dialog_kwargs(
                               "CFD View in ParaView",
                               "Convert a case's latest results to VTK and copy "
                               "them to Windows for ParaView."))
        if not vals:
            return
        name = (str(vals.get("name") or "case1").strip().replace(" ", "_")) or "case1"
        of_env = str(vals.get("env") or cfd.DEFAULT_OF_ENV).strip()
        distro = str(vals.get("distro") or "").strip()  # blank => WSL default distro
        outdir = _cfd_outdir()
        win_out = os.path.join(outdir, name)
        view_script = cfd.build_view_script(
            {"of_env": of_env, "name": name, "win_out": win_out,
             "latest": vals.get("latest", "Yes") == "Yes"})
        view_path = os.path.join(outdir, "view_%s.sh" % name)
        try:
            _write_lf(view_path, view_script)
        except Exception as e:
            err("Could not write the view script to %s:\n%s" % (outdir, e)); return
        view_cmd = "bash %s" % cfd.win_to_wsl(view_path, distro)
        _cfd_record(FreeCAD.ActiveDocument, name, [
            ("Case name", name), ("View (paste in WSL)", view_cmd),
            ("Then open in ParaView", os.path.join(win_out, "VTK")),
            ("View script", view_path)])
        launch = ""
        if vals.get("run") == "Yes":
            launch = "\n\nAuto-run: " + _try_launch_terminal(
                cfd.wsl_run_argv(view_script, distro))
        info("CFD view for case '%s'.\n\nIn your WSL OpenFOAM terminal:\n\n"
             "  %s\n\nThen in ParaView: File > Open > %s > select the .vtk files > "
             "Apply > colour by T (or U).%s" %
             (name, view_cmd, os.path.join(win_out, "VTK"), launch))


class CfdMeshFromCad:
    def GetResources(self):
        return {"Pixmap": _icon("cfdmesh"),
                "MenuText": "CFD Mesh from CAD (snappyHexMesh)",
                "ToolTip": "Auto-mesh a selected solid for CFD the accurate way: a "
                           "background hex box with the body carved out and "
                           "boundary-layered by snappyHexMesh - the same mesher "
                           "SimScale's standard mesh uses. Exports the solid to "
                           "STL, generates the blockMesh / snappyHexMesh dicts and "
                           "runs them on your OpenFOAM; inspect the result "
                           "(checkMesh + ParaView). +X is the flow direction.",
                "Accel": "C, M"}

    def IsActive(self):
        return (cfd is not None and cfdgen is not None
                and FreeCAD.ActiveDocument is not None)

    def Activated(self):
        if cfd is None or cfdgen is None:
            err("The CFD modules (dynframe_cfd / dynframe_cfd_gen) failed to load.")
            return
        try:
            sel = [o for o in FreeCADGui.Selection.getSelection()
                   if getattr(o, "Shape", None) is not None]
        except Exception:
            sel = []
        if not sel:
            info("Select the solid (the body the fluid flows around or through) "
                 "first, then run CFD Mesh from CAD.")
            return
        obj = sel[0]
        try:
            shp = global_shape(obj)                       # mm, placement baked in
            mat = FreeCAD.Matrix(); mat.scale(1e-3, 1e-3, 1e-3)
            shp_m = shp.transformGeometry(mat)            # -> metres
            bb = shp_m.BoundBox
            Lm = max(bb.XLength, bb.YLength, bb.ZLength, 1e-6)
            verts, facets = shp_m.tessellate(max(Lm / 400.0, 1e-5))
            pts = [(v.x, v.y, v.z) for v in verts]
        except Exception as e:
            err("Could not tessellate '%s': %s" % (getattr(obj, "Label", "?"), e))
            return
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Auto-mesh '%s' with snappyHexMesh (the mesher SimScale's standard "
             "mesh uses). Body ~%.3g x %.3g x %.3g m; +X is the flow direction. "
             "Margins are multiples of the body length; higher surface level = "
             "finer mesh on the body." %
             (getattr(obj, "Label", "body"), bb.XLength, bb.YLength, bb.ZLength)},
            {"key": "name", "label": "Case name", "kind": "text", "default": "part1"},
            {"key": "ncb", "label": "Background cells across body", "kind": "int",
             "default": 8, "min": 2, "max": 200},
            {"key": "lmin", "label": "Surface refinement level min", "kind": "int",
             "default": 2, "min": 0, "max": 8},
            {"key": "lmax", "label": "Surface refinement level max", "kind": "int",
             "default": 4, "min": 0, "max": 9},
            {"key": "nlay", "label": "Boundary layers on the body", "kind": "int",
             "default": 3, "min": 0, "max": 20},
            {"key": "up", "label": "Upstream margin (x body length)",
             "kind": "float", "default": 2.0},
            {"key": "down", "label": "Downstream margin (x L)", "kind": "float",
             "default": 4.0},
            {"key": "side", "label": "Side margin (x L)", "kind": "float",
             "default": 2.0},
            {"key": "top", "label": "Top margin (x L)", "kind": "float",
             "default": 2.0},
            {"key": "ground", "label": "Ground margin (x L; small = on ground)",
             "kind": "float", "default": 1.0},
            {"key": "distro", "label": "WSL distro (blank = your default)",
             "kind": "text", "default": ""},
            {"key": "env", "label": "OpenFOAM env (source)", "kind": "text",
             "default": cfd.DEFAULT_OF_ENV},
            {"key": "run", "label": "Try to mesh now", "kind": "combo",
             "options": ["No", "Yes"], "default": "No"},
        ]
        vals = form_dialog("CFD Mesh from CAD (snappyHexMesh)", fields,
                           **_cfd_dialog_kwargs(
                               "CFD Mesh from CAD",
                               "snappyHexMesh a selected solid: background hex box "
                               "with the body carved out and boundary-layered."))
        if not vals:
            return
        name = (str(vals.get("name") or "part1").strip().replace(" ", "_")) or "part1"
        dom = cfdgen.domain_from_bbox(
            bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax,
            up=float(vals["up"]), down=float(vals["down"]), side=float(vals["side"]),
            top=float(vals["top"]), ground=float(vals["ground"]))
        h = Lm / max(2, int(vals["ncb"]))
        nx, ny, nz = cfdgen.cell_counts(*dom, h=h)
        loc = cfdgen.location_in_mesh(*dom, bx0=bb.XMin)
        bm = cfdgen.block_mesh_dict(*dom, nx, ny, nz)
        sn = cfdgen.snappy_hex_mesh_dict(
            stl="body.stl", name="body", level_min=int(vals["lmin"]),
            level_max=int(vals["lmax"]), feature_level=int(vals["lmax"]),
            n_layers=int(vals["nlay"]), location=loc)
        sf = cfdgen.surface_features_dict("body.stl")
        stl = cfdgen.ascii_stl("body", pts, facets)
        outdir = _cfd_outdir()
        stage = os.path.join(outdir, name + "_src")
        try:
            _write_lf(os.path.join(stage, "blockMeshDict"), bm)
            _write_lf(os.path.join(stage, "snappyHexMeshDict"), sn)
            _write_lf(os.path.join(stage, "surfaceFeaturesDict"), sf)
            _write_lf(os.path.join(stage, "body.stl"), stl)
        except Exception as e:
            err("Could not write the CFD mesh files to %s:\n%s" % (stage, e)); return
        of_env = str(vals.get("env") or cfd.DEFAULT_OF_ENV).strip()
        distro = str(vals.get("distro") or "").strip()  # blank => WSL default distro
        win_out = os.path.join(outdir, name)
        ms = cfdgen.build_mesh_script({"of_env": of_env, "name": name,
                                       "stage_win": stage, "win_out": win_out})
        mpath = os.path.join(outdir, "mesh_%s.sh" % name)
        try:
            _write_lf(mpath, ms)
        except Exception as e:
            err("Could not write the mesh script:\n%s" % e); return
        mesh_cmd = "bash %s" % cfd.win_to_wsl(mpath, distro)
        ncell = nx * ny * nz
        _cfd_record(FreeCAD.ActiveDocument, name, [
            ("Geometry", getattr(obj, "Label", "body")),
            ("Mesher", "snappyHexMesh (same as SimScale's standard mesh)"),
            ("Body size (m)", "%.3g x %.3g x %.3g" % (bb.XLength, bb.YLength, bb.ZLength)),
            ("Background cells", "%d x %d x %d = %d" % (nx, ny, nz, ncell)),
            ("Surface level", "%d-%d, %d layers"
             % (int(vals["lmin"]), int(vals["lmax"]), int(vals["nlay"]))),
            ("Mesh (paste in WSL)", mesh_cmd),
            ("Then open in ParaView", os.path.join(win_out, "VTK")),
            ("Mesh script", mpath), ("Staged files", stage)])
        launch = ""
        if vals.get("run") == "Yes":
            launch = "\n\nAuto-run: " + _try_launch_terminal(cfd.wsl_run_argv(ms, distro))
        info("CFD mesh for '%s' -> case '%s'.\n\nsnappyHexMesh setup written "
             "(background %d x %d x %d cells; surface level %d-%d; %d boundary "
             "layers). In your WSL OpenFOAM terminal:\n\n  %s\n\nIt meshes and "
             "prints a checkMesh summary (look for 'Mesh OK'), then writes the "
             "mesh VTK to:\n  %s\n\nOpen that in ParaView (Surface With Edges) to "
             "inspect it; tune the levels / margins and re-run if needed. Details "
             "in the 'CFD_%s' sheet.%s" %
             (getattr(obj, "Label", "body"), name, nx, ny, nz, int(vals["lmin"]),
              int(vals["lmax"]), int(vals["nlay"]), mesh_cmd,
              os.path.join(win_out, "VTK"), name, launch))


# ── SimScale-style simulation tree (document objects in the Model panel) ──
_CFD_STATUS_GLYPH = {"done": "✓", "todo": "○"}   # check / open circle


def _cfd_study_container(doc, node):
    """The study container group that holds `node` (its parent in the tree)."""
    for o in getattr(doc, "Objects", []):
        if node in (getattr(o, "Group", []) or []):
            return o
    return None


def _cfd_mark_node_done(node, label):
    try:
        node.Label = "%s %s" % (_CFD_STATUS_GLYPH["done"], label)
    except Exception:
        pass


def _cfd_pick_material(node):
    """Materials step: pick the working fluid from the library and store it on the
    study, so the solve uses its viscosity - SimScale's material assignment."""
    if cfdmat is None:
        info("The material library failed to load."); return
    fields = [
        {"key": "_i", "kind": "info", "default":
         "Pick a fluid from the library, or enter your own viscosity/density "
         "(leave a custom field at 0 to use the library value)."},
        {"key": "fluid", "label": "Fluid", "kind": "combo",
         "options": cfdmat.fluid_names(), "default": cfdmat.fluid_names()[0]},
        {"key": "nu", "label": "Custom viscosity nu (m2/s; 0 = library)",
         "kind": "float", "default": 0.0, "decimals": 9},
        {"key": "rho", "label": "Custom density rho (kg/m3; 0 = library)",
         "kind": "float", "default": 0.0, "decimals": 4},
    ]
    def _apply(vals):
        f = cfdmat.fluid_by_name(vals.get("fluid")) or cfdmat.FLUIDS[0]
        nu = float(vals.get("nu") or 0.0) or f["nu"]
        rho = float(vals.get("rho") or 0.0) or f["rho"]
        custom = (nu != f["nu"]) or (rho != f["rho"])
        doc = FreeCAD.ActiveDocument
        cont = _cfd_study_container(doc, node)
        for tgt in (node, cont):
            if tgt is not None:
                _cfd_set_str(tgt, "CfdFluid", "custom" if custom else f["key"])
                _cfd_set_str(tgt, "CfdNu", _g(nu))
                _cfd_set_str(tgt, "CfdRho", _g(rho))
        _cfd_mark_node_done(node, "Materials")
        try:
            doc.recompute()
        except Exception:
            pass
        info("Fluid set to %s (nu = %g m2/s, rho = %g kg/m3). The flow solve now "
             "uses this viscosity." %
             ("custom" if custom else f["name"], nu, rho))

    _cfd_show_step_panel(
        "Material (fluid)",
        "Pick a library fluid or type your own viscosity and density; the solver "
        "uses these.", fields, _apply)


def _cfd_study_nu(doc, default=1.5e-5):
    """The viscosity chosen in a study's Materials step, if any (else default)."""
    for o in getattr(doc, "Objects", []):
        v = getattr(o, "CfdNu", "")
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return default


def _cfd_study_set(doc, node, **kv):
    """Store key/value settings on both the node and its study container."""
    cont = _cfd_study_container(doc, node)
    for tgt in (node, cont):
        if tgt is not None:
            for k, v in kv.items():
                _cfd_set_str(tgt, k, v)
    return cont


def _cfd_study_get(doc, key, default=""):
    """Read a study setting stored on any CFD object (first non-empty)."""
    for o in getattr(doc, "Objects", []):
        v = getattr(o, key, "")
        if v:
            return v
    return default


def _cfd_doc_solids(doc):
    """Document objects that are solids (have a Shape with faces)."""
    out = []
    for o in getattr(doc, "Objects", []):
        sh = getattr(o, "Shape", None)
        if sh is not None and getattr(sh, "Faces", None):
            out.append(o)
    return out


def _cfd_resolve_solid(doc):
    """Find the study's geometry solid without needing it selected: a selected
    solid, else the solid set in the Geometry step, else one that has BC
    assignments, else the only solid in the document."""
    try:
        sel = [o for o in FreeCADGui.Selection.getSelection()
               if getattr(o, "Shape", None) is not None
               and getattr(o.Shape, "Faces", None)]
        if sel:
            return sel[0]
    except Exception:
        pass
    gname = _cfd_study_get(doc, "CfdGeometry", "")
    if gname:
        o = doc.getObject(gname)
        if o is not None and getattr(o, "Shape", None) is not None:
            return o
    for o in getattr(doc, "Objects", []):
        bs = getattr(o, "CfdBCSolid", "")
        if bs:
            s = doc.getObject(bs)
            if s is not None and getattr(s, "Shape", None) is not None:
                return s
    solids = _cfd_doc_solids(doc)
    if len(solids) == 1:
        return solids[0]
    return None


def _cfd_zoom_selection():
    """Zoom the 3D view to the current selection (SimScale 'zoom to part'); falls
    back to fit-all. Safe with no GUI."""
    try:
        FreeCADGui.SendMsgToActiveView("ViewSelection")
    except Exception:
        try:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass


_CFD_IMPORT_LABEL = "⬏  Import a CAD file (STEP / IGES / BREP)…"


def _cfd_import_cad(doc):
    """Import a CAD file (STEP / IGES / BREP) into `doc` so it can be the flow
    geometry - lets you bring in complex / specific parts, as SimScale does.
    Returns the imported solid (the largest new solid body), or None."""
    path = ""
    try:
        r = QW.QFileDialog.getOpenFileName(
            _mw(), "Import CAD geometry", "",
            "CAD files (*.step *.stp *.iges *.igs *.brep *.brp);;"
            "STEP (*.step *.stp);;IGES (*.iges *.igs);;BREP (*.brep *.brp);;"
            "All files (*)")
        path = r[0] if isinstance(r, (tuple, list)) else r
    except Exception:
        path = ""
    if not path:
        return None
    before = set(id(o) for o in getattr(doc, "Objects", []))
    try:
        import Part
        Part.insert(path, doc.Name)
    except Exception:
        try:
            import Import
            Import.insert(path, doc.Name)
        except Exception as e:
            err("Could not import '%s':\n%s" % (path, e)); return None
    try:
        doc.recompute()
    except Exception:
        pass
    new = [o for o in getattr(doc, "Objects", [])
           if id(o) not in before and getattr(o, "Shape", None) is not None
           and getattr(o.Shape, "Faces", None)]
    if not new:
        info("Imported '%s', but it has no solid body to simulate. Use a STEP / "
             "IGES / BREP file that contains a solid." % os.path.basename(path))
        return None

    def _vol(o):
        try:
            return float(getattr(global_shape(o), "Volume", 0.0) or 0.0)
        except Exception:
            return 0.0
    new.sort(key=_vol, reverse=True)       # the main body of an assembly first
    return new[0]


def _cfd_apply_geometry(node, solid):
    """Store `solid` as the study geometry, mark the step done, then select and
    zoom to it so the chosen part fills the 3D view (SimScale 'focus on part')."""
    doc = FreeCAD.ActiveDocument
    _cfd_study_set(doc, node, CfdGeometry=getattr(solid, "Name", ""))
    _cfd_mark_node_done(node, "Geometry")
    try:
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(solid)
    except Exception:
        pass
    _cfd_zoom_selection()
    try:
        doc.recompute()
    except Exception:
        pass
    info("Geometry set to '%s'. Next: open Boundary conditions and click its faces "
         "in the 3D view to tag inlet / outlet / walls." %
         getattr(solid, "Label", "solid"))


def _cfd_pick_geometry(node):
    """Geometry step (docked, SimScale-style): use the part you have selected, pick
    an already-imported solid, or import your own complex / specific CAD. The
    chosen part is selected and zoomed so you can inspect it."""
    doc = FreeCAD.ActiveDocument
    # 1) a solid selected in the 3D view or tree wins - immediate, like clicking
    #    the part in SimScale.
    try:
        sel = [o for o in FreeCADGui.Selection.getSelection()
               if getattr(o, "Shape", None) is not None]
        if sel:
            _cfd_apply_geometry(node, sel[0]); return
    except Exception:
        pass
    # 2) nothing in the document yet -> go straight to CAD import.
    solids = _cfd_doc_solids(doc)
    if not solids:
        imported = _cfd_import_cad(doc)
        if imported is None:
            info("Create a solid (Part workbench -> Cube) or import your CAD "
                 "(STEP / IGES / BREP), then open Geometry."); return
        _cfd_apply_geometry(node, imported); return
    # 3) a docked panel: pick an existing solid or import a new one.
    names = [getattr(o, "Label", o.Name) for o in solids]
    options = names + [_CFD_IMPORT_LABEL]
    fields = [
        {"key": "_i", "kind": "info", "default":
         "Choose the solid that is the flow region (the part the fluid flows "
         "through or around), or import your own complex CAD. Tip: select a part "
         "in the 3D view or tree before opening Geometry and it is used directly."},
        {"key": "g", "label": "Geometry (solid)", "kind": "combo",
         "options": options, "default": names[0]},
    ]

    def _apply(vals):
        d = FreeCAD.ActiveDocument
        choice = vals.get("g") or names[0]
        if choice == _CFD_IMPORT_LABEL:
            solid = _cfd_import_cad(d)
            if solid is None:
                info("No geometry imported. Open Geometry again to pick or import "
                     "a part."); return
        else:
            cur = _cfd_doc_solids(d)
            solid = next((o for o in cur
                          if getattr(o, "Label", o.Name) == choice), None)
        if solid is None:
            info("Could not find '%s'. Open Geometry again." % choice); return
        _cfd_apply_geometry(node, solid)

    _cfd_show_step_panel(
        "Geometry", "Pick the simulation geometry, or import your own CAD.",
        fields, _apply)


def _cfd_pick_numerics(node):
    """Numerics step: turbulence model, steady/transient, turbulence intensity."""
    doc = FreeCAD.ActiveDocument
    fields = [
        {"key": "_i", "kind": "info", "default":
         "Turbulence model, accuracy and heat transfer. kOmegaSST is a robust "
         "default; enable heat transfer to also solve a temperature field."},
        {"key": "turb", "label": "Turbulence model", "kind": "combo",
         "options": ["kOmegaSST", "kEpsilon", "Laminar"], "default":
         _cfd_study_get(doc, "CfdTurbulence", "kOmegaSST")},
        {"key": "time", "label": "Time dependency", "kind": "combo",
         "options": ["Steady-state", "Transient"], "default": "Steady-state"},
        {"key": "ti", "label": "Turbulence intensity (%)", "kind": "float",
         "default": 5.0, "decimals": 2},
        {"key": "so", "label": "Second-order schemes (accuracy)", "kind": "combo",
         "options": ["No", "Yes"],
         "default": "Yes" if _cfd_study_get(doc, "CfdSecondOrder", "") == "1" else "No"},
        {"key": "heat", "label": "Heat transfer (solve temperature)", "kind": "combo",
         "options": ["No", "Yes"],
         "default": "Yes" if _cfd_study_get(doc, "CfdHeat", "") == "1" else "No"},
        {"key": "tin", "label": "Inlet temperature (K)", "kind": "float",
         "default": float(_cfd_study_get(doc, "CfdTin", "300") or 300), "decimals": 2},
        {"key": "twall", "label": "Heated wall temperature (K)", "kind": "float",
         "default": float(_cfd_study_get(doc, "CfdTwall", "350") or 350), "decimals": 2},
        {"key": "pr", "label": "Prandtl number", "kind": "float",
         "default": float(_cfd_study_get(doc, "CfdPr", "0.71") or 0.71), "decimals": 3},
    ]
    def _apply(vals):
        d = FreeCAD.ActiveDocument
        _cfd_study_set(d, node, CfdTurbulence=vals.get("turb", "kOmegaSST"),
                       CfdSteady=("1" if vals.get("time") == "Steady-state" else "0"),
                       CfdIntensity=_g(vals.get("ti", 5.0)),
                       CfdSecondOrder=("1" if vals.get("so") == "Yes" else "0"),
                       CfdHeat=("1" if vals.get("heat") == "Yes" else "0"),
                       CfdTin=_g(vals.get("tin", 300.0)),
                       CfdTwall=_g(vals.get("twall", 350.0)),
                       CfdPr=_g(vals.get("pr", 0.71)))
        _cfd_mark_node_done(node, "Numerics")
        try:
            d.recompute()
        except Exception:
            pass
        info("Numerics: %s, %s, intensity %.1f%%%s%s."
             % (vals.get("turb"), vals.get("time"), float(vals.get("ti", 5.0)),
                ", 2nd-order" if vals.get("so") == "Yes" else "",
                ", heat transfer on" if vals.get("heat") == "Yes" else ""))

    _cfd_show_step_panel("Numerics", "Turbulence, accuracy, heat transfer.",
                         fields, _apply)


def _cfd_pick_control(node):
    """Simulation-control step: iterations, write interval, convergence residual."""
    doc = FreeCAD.ActiveDocument
    fields = [
        {"key": "_i", "kind": "info", "default":
         "Run controls: how many steady iterations, how often to write, and the "
         "residual at which the solve is called converged."},
        {"key": "iters", "label": "Iterations (steady)", "kind": "int",
         "default": int(float(_cfd_study_get(doc, "CfdIters", "1000") or 1000)),
         "min": 50, "max": 200000},
        {"key": "write", "label": "Write interval (iterations)", "kind": "int",
         "default": 200, "min": 1, "max": 200000},
        {"key": "res", "label": "Convergence residual", "kind": "float",
         "default": 1e-4, "decimals": 8},
    ]
    def _apply(vals):
        d = FreeCAD.ActiveDocument
        _cfd_study_set(d, node, CfdIters=str(int(vals.get("iters", 1000))),
                       CfdWrite=str(int(vals.get("write", 200))),
                       CfdResidual=_g(vals.get("res", 1e-4)))
        _cfd_mark_node_done(node, "Simulation control")
        try:
            d.recompute()
        except Exception:
            pass
        info("Simulation control: %d iterations, write every %d, converge at %g."
             % (int(vals.get("iters", 1000)), int(vals.get("write", 200)),
                float(vals.get("res", 1e-4))))

    _cfd_show_step_panel("Simulation control",
                         "Iterations, output and convergence.", fields, _apply)


def _cfd_pick_mesh(node):
    """Mesh step: base resolution, surface refinement and boundary layers, plus an
    option to mesh + checkMesh now to preview the mesh quality (SimScale-style)."""
    doc = FreeCAD.ActiveDocument
    fields = [
        {"key": "_i", "kind": "info", "default":
         "Mesh controls. A box uses blockMesh; any other solid uses snappyHexMesh "
         "with surface refinement and boundary layers for near-wall accuracy. "
         "'Mesh and check now' meshes and reports quality before you solve."},
        {"key": "cells", "label": "Base cells across domain", "kind": "int",
         "default": int(float(_cfd_study_get(doc, "CfdCells", "20") or 20)),
         "min": 4, "max": 400},
        {"key": "rmin", "label": "Surface refinement level (min)", "kind": "int",
         "default": int(float(_cfd_study_get(doc, "CfdRefineMin", "1") or 1)),
         "min": 0, "max": 6},
        {"key": "rmax", "label": "Surface refinement level (max)", "kind": "int",
         "default": int(float(_cfd_study_get(doc, "CfdRefineMax", "2") or 2)),
         "min": 0, "max": 8},
        {"key": "layers", "label": "Boundary layers on walls", "kind": "int",
         "default": int(float(_cfd_study_get(doc, "CfdLayers", "3") or 3)),
         "min": 0, "max": 12},
        {"key": "meshnow", "label": "Mesh and check quality now", "kind": "combo",
         "options": ["No", "Yes"], "default": "No"},
        {"key": "showmesh", "label": "Show the mesh in ParaView", "kind": "combo",
         "options": ["Yes", "No"], "default": "Yes"},
        {"key": "distro", "label": "WSL distro (blank = default)", "kind": "text", "default": ""},
        {"key": "env", "label": "OpenFOAM env (source)", "kind": "text", "default": cfd.DEFAULT_OF_ENV},
    ]

    def _apply(vals):
        d = FreeCAD.ActiveDocument
        _cfd_study_set(d, node, CfdCells=str(int(vals.get("cells", 20))),
                       CfdRefineMin=str(int(vals.get("rmin", 1))),
                       CfdRefineMax=str(int(vals.get("rmax", 2))),
                       CfdLayers=str(int(vals.get("layers", 3))))
        _cfd_mark_node_done(node, "Mesh")
        try:
            d.recompute()
        except Exception:
            pass
        if vals.get("meshnow") == "Yes":
            _cfd_mesh_preview(d, vals)
        else:
            info("Mesh: %d base cells, surface refinement %d-%d, %d boundary "
                 "layers. Set 'Mesh and check quality now = Yes' to build it and "
                 "see it in ParaView, or go to Run."
                 % (int(vals.get("cells", 20)), int(vals.get("rmin", 1)),
                    int(vals.get("rmax", 2)), int(vals.get("layers", 3))))

    _cfd_show_step_panel("Mesh", "Resolution, refinement, boundary layers.",
                         fields, _apply)


def _cfd_mesh_preview(doc, vals):
    """Mesh the geometry (no solve) and run checkMesh, then report mesh quality -
    SimScale's separate mesh operation, so you can trust the mesh first."""
    solid = _cfd_resolve_solid(doc)
    if solid is None:
        info("Set the Geometry node first, then preview the mesh."); return
    assigns = _cfd_collect_bc_assignments(doc, getattr(solid, "Name", ""))
    if not assigns:
        info("Assign boundary-condition faces first, so the mesh has named "
             "patches."); return
    try:
        mat = FreeCAD.Matrix(); mat.scale(1e-3, 1e-3, 1e-3)
        bb = global_shape(solid).transformGeometry(mat).BoundBox
    except Exception as e:
        err("Could not read geometry: %s" % e); return
    Lm = max(bb.XLength, bb.YLength, bb.ZLength, 1e-6)
    n = max(4, int(vals.get("cells", 20)))
    nlay = int(vals.get("layers", 3))
    rmin = int(vals.get("rmin", 1)); rmax = int(vals.get("rmax", 2))
    outdir = _cfd_outdir(); name = "mesh_preview"
    stage = os.path.join(outdir, name + "_src"); win_out = os.path.join(outdir, name)
    try:
        used, is_box = _cfd_build_mesh_dicts(doc, solid, assigns, bb, Lm, stage,
                                             n, nlay, rmin, rmax)
        # the mesh utilities need a minimal controlDict/fvSchemes/fvSolution
        _write_lf(os.path.join(stage, "controlDict"),
                  cfdgen.control_dict_simple("incompressibleFluid", 1, 1))
        _write_lf(os.path.join(stage, "fvSchemes"), cfdgen.fv_schemes_simple())
        _write_lf(os.path.join(stage, "fvSolution"), cfdgen.fv_solution_simple())
    except Exception as e:
        err("Could not build the mesh dictionaries: %s" % e); return
    of_env = str(vals.get("env") or cfd.DEFAULT_OF_ENV).strip()
    distro = str(vals.get("distro") or "").strip()  # blank => WSL default distro
    fs = cfdgen.build_mesh_check_script(
        {"of_env": of_env, "name": name, "stage_win": stage,
         "win_out": win_out, "patch_names": sorted(used)})
    fpath = os.path.join(outdir, "mesh_%s.sh" % name)
    try:
        _write_lf(fpath, fs)
    except Exception as e:
        err("Could not write the mesh script: %s" % e); return
    import subprocess
    try:
        r = subprocess.run(cfd.wsl_run_argv(fs, distro), capture_output=True,
                           timeout=1800)
        out = ((r.stdout or b"").decode("utf-8", "replace")
               + (r.stderr or b"").decode("utf-8", "replace"))
    except Exception as e:
        info("Mesh staged. Run it in your WSL terminal:\n  bash %s\n(%s)"
             % (cfd.win_to_wsl(fpath, distro), e)); return
    q = cfd.parse_checkmesh(out)
    msg = "Mesh %s (%s).\n" % ("OK" if q["ok"] else "has warnings", mesher_name(is_box))
    if q.get("cells"):
        msg += "Cells: %d.\n" % q["cells"]
    if q.get("max_nonortho") is not None:
        msg += "Max non-orthogonality: %.1f (good < 65).\n" % q["max_nonortho"]
    if q.get("max_skewness") is not None:
        msg += "Max skewness: %.2f (good < 4).\n" % q["max_skewness"]
    msg += "\nMesh written to VTK:\n  %s" % os.path.join(win_out, "VTK")
    # Show the mesh in ParaView (SimScale-style) unless the user opted out.
    if str(vals.get("showmesh", "Yes")) == "Yes" and q.get("cells"):
        if _cfd_launch_paraview(name, distro):
            msg += ("\n\nOpening the mesh in ParaView - click the case in the "
                    "Pipeline, press Apply, then set the representation to "
                    "'Surface With Edges' to see the cells.")
        else:
            msg += ("\n\nInstall ParaView in WSL (sudo apt install paraview) to "
                    "view the mesh, or open the VTK folder above.")
    _cfd_report("Mesh preview", msg)


def mesher_name(is_box):
    return "blockMesh" if is_box else "snappyHexMesh + layers"


def _cfd_open_node(node):
    """Drive the workflow from the clicked simulation-tree node - the SimScale way,
    where each node runs its own step. Reuses the dedicated commands so the tree
    is the single control centre for the study."""
    panel = getattr(node, "CfdPanel", "") or ""
    try:
        if panel == "bcs":
            CfdAssignBC().Activated()
        elif panel == "run":
            CfdFlowInternal().Activated()
        elif panel == "geometry":
            _cfd_pick_geometry(node)
        elif panel == "mesh":
            _cfd_pick_mesh(node)
        elif panel in ("materials", "mat_fluid"):
            _cfd_pick_material(node)
        elif panel == "mat_solid":
            info("Material (solid): for conjugate heat transfer. Coming with the "
                 "multi-region solver panel.")
        elif panel == "numerics":
            _cfd_pick_numerics(node)
        elif panel == "control":
            _cfd_pick_control(node)
        elif panel == "bcedit":
            _cfd_edit_bc(node)
        else:
            info("This step uses validated defaults; a dedicated panel is coming.")
    except Exception as e:
        err("Could not open the '%s' step: %s" % (panel, e))


class _CfdNodeObj:
    """Minimal object proxy for a CFD simulation-tree node. Required so the node
    is an App::DocumentObjectGroupPython whose Python view provider (and its
    doubleClicked) is honoured by FreeCAD."""
    def __init__(self, obj=None):
        try:
            if obj is not None:
                obj.Proxy = self
        except Exception:
            pass

    def execute(self, obj):
        return None

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class _CfdNodeVP:
    """View provider so double-clicking a simulation-tree node runs its step
    (SimScale-style). Only a Python-enabled object (DocumentObjectGroupPython)
    dispatches doubleClicked to this proxy - a plain DocumentObjectGroup does not."""
    def __init__(self, vobj=None):
        try:
            if vobj is not None:
                vobj.Proxy = self
        except Exception:
            pass

    def attach(self, vobj):
        try:
            self.Object = vobj.Object
        except Exception:
            pass

    def doubleClicked(self, vobj):
        try:
            _cfd_open_node(vobj.Object)
        except Exception:
            pass
        return True

    def setEdit(self, vobj, mode=0):
        try:
            _cfd_open_node(vobj.Object)
        except Exception:
            pass
        return False

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def _cfd_set_str(obj, name, value):
    """Add (if needed) and set a string property on a document object."""
    try:
        if not hasattr(obj, name):
            obj.addProperty("App::PropertyString", name, "CFD")
        setattr(obj, name, str(value))
    except Exception:
        pass


def build_cfd_tree(doc, study):
    """Create the SimScale-style simulation tree for `study` (a dict with id/title/
    multiRegion) as document-object groups in the Model panel: a study container
    with a child node per setup step. Returns the container object."""
    container = doc.addObject("App::DocumentObjectGroup",
                              cfdtree.safe_name(study.get("title", "study")))
    try:
        container.Label = "CFD · " + str(study.get("title", "study"))
    except Exception:
        pass
    _cfd_set_str(container, "CfdStudy", study.get("id", ""))
    steps = cfdtree.study_steps(study.get("id"), study.get("multiRegion"))
    for st in steps:
        # DocumentObjectGroupPython (not plain group) so the Python view provider's
        # doubleClicked actually fires when the node is double-clicked.
        node = doc.addObject("App::DocumentObjectGroupPython",
                             cfdtree.safe_name(st["label"], prefix="Cfd"))
        _CfdNodeObj(node)
        try:
            glyph = _CFD_STATUS_GLYPH.get(st.get("status"), "")
            node.Label = ("%s %s" % (glyph, st["label"])).strip()
        except Exception:
            pass
        _cfd_set_str(node, "CfdStudy", study.get("id", ""))
        _cfd_set_str(node, "CfdStep", st["key"])
        _cfd_set_str(node, "CfdPanel", st["panel"])
        try:
            if getattr(node, "ViewObject", None) is not None:
                _CfdNodeVP(node.ViewObject)
        except Exception:
            pass
        container.addObject(node)
    return container


class CfdStudy:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_study"),
                "MenuText": "CFD Study (new simulation)",
                "ToolTip": "Start a SimScale-style CFD study: pick the physics "
                           "(any OpenFOAM module) and DynFrame builds the "
                           "simulation tree in the Model panel - Geometry, "
                           "Materials, Boundary conditions, Numerics, Simulation "
                           "control, Mesh, Run - each a node you open to set up. "
                           "Double-click 'Run' to mesh + solve.",
                "Accel": "C, S"}

    def IsActive(self):
        return (cfd is not None and cfdtree is not None
                and FreeCAD.ActiveDocument is not None)

    def Activated(self):
        if cfd is None or cfdtree is None:
            err("The CFD modules failed to load."); return
        titles = cfdtree.study_titles()
        if not titles:
            err("No OpenFOAM study catalog available."); return
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Start a CFD study (the SimScale way): pick the physics module and "
             "DynFrame builds its simulation tree in the Model panel. Open each "
             "node to set it up; double-click 'Run' to mesh + solve on OpenFOAM."},
            {"key": "phys", "label": "Study type (OpenFOAM physics)", "kind": "combo",
             "options": titles, "default": titles[0]},
        ]
        def _build(vals):
            study = cfdtree.find_study(vals.get("phys")) or cfdtree.study_types()[0]
            doc = FreeCAD.ActiveDocument
            doc.openTransaction("DynFrame: new CFD study")
            try:
                build_cfd_tree(doc, study)
                doc.commitTransaction(); doc.recompute()
            except Exception as e:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                err("Could not build the CFD study tree: %s" % e); return
            info("Created the CFD study '%s' in the Model panel.\n\nIts simulation "
                 "tree has a node for each setup step (Geometry, Materials, "
                 "Boundary conditions, Numerics, Simulation control, Mesh, Run), "
                 "SimScale-style. Double-click a node to set it up - start with "
                 "Geometry to pick or import your part.\n\nPhysics: %s (%s)." %
                 (study.get("title"), study.get("id"), study.get("use", "")))

        _cfd_show_step_panel(
            "New CFD Study",
            "Pick the physics; DynFrame builds the SimScale-style simulation "
            "tree.", fields, _build)


def _cfd_collect_bc_assignments(doc, solid_name):
    """Gather every face->BC assignment for `solid_name` from the BC objects in
    the document, as {face_index: bc_key}."""
    out = {}
    for o in getattr(doc, "Objects", []):
        if getattr(o, "CfdBCSolid", "") != solid_name:
            continue
        key = getattr(o, "CfdBCType", "") or ""
        faces = getattr(o, "CfdBCFaces", "") or ""
        for part in str(faces).split(","):
            part = part.strip()
            if part.isdigit():
                out[int(part)] = key
    return out


def _cfd_recolor_solid(solid, assignments):
    """Paint a solid's faces by their assigned BC colour (unassigned = base)."""
    if cfdbc is None:
        return
    try:
        nfaces = len(global_shape(solid).Faces)
        cols = cfdbc.face_colors(nfaces, assignments)
        solid.ViewObject.DiffuseColor = [tuple(c) for c in cols]
    except Exception:
        pass


def _cfd_find_bc_node(doc):
    """The study tree's 'Boundary conditions' node, if a CFD study exists."""
    for o in getattr(doc, "Objects", []):
        if getattr(o, "CfdStep", "") == "bcs":
            return o
    return None


def _cfd_create_bc(doc, solid, bc, faces, value):
    """Record a BC on `faces` of `solid` and recolour the solid. Shared by the
    non-modal panel and the modal fallback."""
    faces = sorted(set(int(i) for i in faces))
    node = doc.addObject("App::FeaturePython", "CfdBC_%s" % bc["key"])
    try:
        node.Label = "%s (%d face%s)" % (bc["label"], len(faces),
                                         "" if len(faces) == 1 else "s")
    except Exception:
        pass
    _cfd_set_str(node, "CfdBCType", bc["key"])
    _cfd_set_str(node, "CfdBCSolid", getattr(solid, "Name", ""))
    _cfd_set_str(node, "CfdBCFaces", ",".join(str(i) for i in faces))
    _cfd_set_str(node, "CfdBCValue", _g(value))
    # Make the node double-click editable (SimScale-style: open it to change the
    # type, value or faces, or delete it).
    _cfd_set_str(node, "CfdPanel", "bcedit")
    _CfdNodeObj(node)
    try:
        if getattr(node, "ViewObject", None) is not None:
            _CfdNodeVP(node.ViewObject)
    except Exception:
        pass
    parent = _cfd_find_bc_node(doc)
    if parent is not None:
        try:
            parent.addObject(node)
        except Exception:
            pass
    _cfd_recolor_solid(solid, _cfd_collect_bc_assignments(doc, getattr(solid, "Name", "")))
    return node


class _CfdBCSelObserver:
    """Feeds 3D-view face clicks into the open BC panel (live selection)."""
    def __init__(self, panel):
        self._panel = panel

    def _ping(self, *a):
        try:
            self._panel.refresh_selection()
        except Exception:
            pass
    addSelection = _ping
    removeSelection = _ping
    clearSelection = _ping
    setSelection = _ping


class _CfdBCTaskPanel:
    """Non-modal BC panel (SimScale-style): it stays open while you click faces in
    the 3D view, pick a type and type your own value, Assign, repeat, Close."""
    def __init__(self):
        self._cur_solid = None
        self._cur_faces = []
        self.form = self._build()
        self._obs = _CfdBCSelObserver(self)
        try:
            FreeCADGui.Selection.addObserver(self._obs)
        except Exception:
            self._obs = None
        self.refresh_selection()

    def _build(self):
        w = QW.QWidget(); w.setObjectName("cfdPanel")
        w.setWindowTitle("Boundary conditions")
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "subtext": "#9aa7b4"})
        if cfdui is not None:
            try:
                w.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        lay = QW.QVBoxLayout(w)
        hdr = QW.QLabel("Boundary conditions")
        hdr.setStyleSheet("background:%s;color:#fff;font-weight:700;font-size:14px;"
                          "padding:7px 10px;" % pal["accent"])
        lay.addWidget(hdr)
        tip = QW.QLabel("Click one or more faces of the solid in the 3D view, pick "
                        "a type and value, then Assign. Repeat per patch; Close "
                        "when done.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:%s;padding:4px 2px;" % pal["subtext"])
        lay.addWidget(tip)
        form = QW.QFormLayout()
        self._type = QW.QComboBox(); self._type.addItems(cfdbc.bc_labels())
        self._type.currentIndexChanged.connect(self._sync_value_label)
        form.addRow("Type", self._type)
        self._value = QW.QComboBox()
        self._value.setEditable(True)          # presets in the list, or type your own
        self._vrow = QW.QLabel("Inlet speed (m/s)")
        form.addRow(self._vrow, self._value)
        lay.addLayout(form)
        self._facelbl = QW.QLabel("Selected faces: none")
        lay.addWidget(self._facelbl)
        self._assign = QW.QPushButton("Assign to selected faces")
        self._assign.clicked.connect(self._do_assign)
        lay.addWidget(self._assign)
        self._status = QW.QLabel(""); self._status.setWordWrap(True)
        lay.addWidget(self._status)
        lay.addStretch(1)
        self._sync_value_label()
        return w

    def _sync_value_label(self, *a):
        bc = cfdbc.bc_by_label(self._type.currentText()) or cfdbc.BC_TYPES[0]
        lab = bc.get("value_label") or "Value (not needed)"
        self._vrow.setText(lab)
        needs = bool(bc.get("value_label"))
        self._value.setEnabled(needs)
        try:
            self._value.clear()
            if needs:
                self._value.addItems([str(v) for v in
                                      (bc.get("presets") or [bc.get("value", 0.0)])])
                self._value.setEditText(str(bc.get("value", 0.0)))
        except Exception:
            pass

    def refresh_selection(self):
        try:
            sel = FreeCADGui.Selection.getSelectionEx()
        except Exception:
            sel = []
        solid = None; faces = []
        for s in sel:
            o = getattr(s, "Object", None)
            if o is None:
                continue
            if solid is None:
                solid = o
            if o is solid:
                faces += cfdbc.parse_face_indices(getattr(s, "SubElementNames", []) or [])
        self._cur_solid = solid
        self._cur_faces = sorted(set(faces))
        n = len(self._cur_faces)
        if n:
            self._facelbl.setText("Selected faces: %d on '%s'"
                                  % (n, getattr(solid, "Label", "-")))
        else:
            self._facelbl.setText("Selected faces: none (click a face)")

    def _do_assign(self):
        if not self._cur_solid or not self._cur_faces:
            self._status.setText("Select one or more faces in the 3D view first.")
            return
        bc = cfdbc.bc_by_label(self._type.currentText()) or cfdbc.BC_TYPES[0]
        try:
            val = float(self._value.currentText())
        except (TypeError, ValueError):
            val = 0.0
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: assign BC")
        try:
            _cfd_create_bc(doc, self._cur_solid, bc, self._cur_faces, val)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            self._status.setText("Could not assign: %s" % e); return
        counts = cfdbc.summarize(
            _cfd_collect_bc_assignments(doc, self._cur_solid.Name))
        self._status.setText(
            "Assigned %s to %d face(s). Patches so far: %s. Select the next "
            "faces for another patch." %
            (bc["label"], len(self._cur_faces),
             ", ".join("%s=%d" % kv for kv in sorted(counts.items()))))

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Close)

    def accept(self):
        self._cleanup(); _close_task_dialog(); return True

    def reject(self):
        self._cleanup(); _close_task_dialog(); return True

    def _cleanup(self):
        try:
            if self._obs is not None:
                FreeCADGui.Selection.removeObserver(self._obs)
        except Exception:
            pass


def _cfd_dock(make_panel):
    """Create and show a docked Task panel robustly. It first closes any stuck or
    leftover Task dialog (an orphaned dialog otherwise blocks every new panel and
    forces the ugly modal fallback - the cause of panels 'never opening'), then
    builds the panel, catching and LOGGING any construction error to the Report
    view, and shows it. Returns True if shown, else False (caller's fallback)."""
    Ctrl = getattr(FreeCADGui, "Control", None)
    if Ctrl is None or not hasattr(Ctrl, "showDialog"):
        return False
    try:
        if hasattr(Ctrl, "activeDialog") and Ctrl.activeDialog():
            try:
                Ctrl.closeDialog()
            except Exception:
                pass
    except Exception:
        pass
    try:
        Ctrl.showDialog(make_panel())
        return True
    except Exception as e:
        try:
            import traceback
            FreeCAD.Console.PrintError(
                "DynFrame: could not open the Task panel: %s\n%s\n"
                % (e, traceback.format_exc()))
        except Exception:
            pass
        return False


def _show_cfd_bc_panel():
    """Open the non-modal BC panel. True if shown (GUI), else False so the caller
    falls back to the modal path (headless)."""
    return _cfd_dock(lambda: _CfdBCTaskPanel())


def _cfd_node_faces(node):
    """0-based face indices stored on a BC node."""
    out = []
    for x in str(getattr(node, "CfdBCFaces", "") or "").split(","):
        x = x.strip()
        if x.isdigit():
            out.append(int(x))
    return out


def _cfd_update_bc_node(node, bc, faces, value):
    """Apply an edit to an existing BC node: new type/value and (optionally) new
    faces, then relabel and recolour the solid. `faces` None keeps the faces."""
    doc = FreeCAD.ActiveDocument
    doc.openTransaction("DynFrame: edit BC")
    try:
        _cfd_set_str(node, "CfdBCType", bc["key"])
        _cfd_set_str(node, "CfdBCValue", _g(value))
        if faces is not None:
            fs = sorted(set(int(i) for i in faces))
            _cfd_set_str(node, "CfdBCFaces", ",".join(str(i) for i in fs))
        else:
            fs = _cfd_node_faces(node)
        try:
            node.Label = "%s (%d face%s)" % (bc["label"], len(fs),
                                             "" if len(fs) == 1 else "s")
        except Exception:
            pass
        solid = doc.getObject(getattr(node, "CfdBCSolid", "") or "")
        if solid is not None:
            _cfd_recolor_solid(
                solid, _cfd_collect_bc_assignments(doc, solid.Name))
        doc.commitTransaction(); doc.recompute()
        return True
    except Exception as e:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        err("Could not update the boundary condition: %s" % e)
        return False


def _cfd_delete_bc_node(node):
    """Remove a BC node and recolour its solid."""
    doc = FreeCAD.ActiveDocument
    solid_name = getattr(node, "CfdBCSolid", "") or ""
    name = getattr(node, "Name", "")
    doc.openTransaction("DynFrame: delete BC")
    try:
        doc.removeObject(name)
        solid = doc.getObject(solid_name)
        if solid is not None:
            _cfd_recolor_solid(
                solid, _cfd_collect_bc_assignments(doc, solid_name))
        doc.commitTransaction(); doc.recompute()
        return True
    except Exception as e:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        err("Could not delete the boundary condition: %s" % e)
        return False


class _CfdBCEditPanel:
    """Non-modal editor for an existing BC node (double-click it): change the
    type, type any value (presets provided), optionally re-pick its faces from the
    3D view, Apply - or Delete it. Keeps the SimScale docked-panel feel."""
    def __init__(self, node):
        self._node = node
        self._picked = None          # None => keep the node's current faces
        self.form = self._build()
        self._obs = _CfdBCSelObserver(self)
        try:
            FreeCADGui.Selection.addObserver(self._obs)
        except Exception:
            self._obs = None

    def _build(self):
        w = QW.QWidget(); w.setObjectName("cfdPanel")
        w.setWindowTitle("Edit boundary condition")
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "subtext": "#9aa7b4"})
        if cfdui is not None:
            try:
                w.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        lay = QW.QVBoxLayout(w)
        hdr = QW.QLabel("Edit boundary condition")
        hdr.setStyleSheet("background:%s;color:#fff;font-weight:700;font-size:14px;"
                          "padding:7px 10px;" % pal["accent"])
        lay.addWidget(hdr)
        tip = QW.QLabel("Change the type or value (pick a preset or type your own). "
                        "To move it, select new faces in the 3D view and click "
                        "'Use selected faces'. Apply to save, or Delete to remove.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:%s;padding:4px 2px;" % pal["subtext"])
        lay.addWidget(tip)
        form = QW.QFormLayout()
        self._type = QW.QComboBox(); self._type.addItems(cfdbc.bc_labels())
        cur = cfdbc.bc_type(getattr(self._node, "CfdBCType", "") or "")
        if cur is not None:
            self._type.setCurrentText(cur.get("label", ""))
        self._type.currentIndexChanged.connect(self._sync_value_label)
        form.addRow("Type", self._type)
        self._value = QW.QComboBox(); self._value.setEditable(True)
        self._vrow = QW.QLabel("Value")
        form.addRow(self._vrow, self._value)
        lay.addLayout(form)
        self._facelbl = QW.QLabel("")
        lay.addWidget(self._facelbl)
        pick = QW.QPushButton("Use selected faces (from 3D view)")
        pick.clicked.connect(self._use_selection)
        lay.addWidget(pick)
        dele = QW.QPushButton("Delete this boundary condition")
        dele.clicked.connect(self._do_delete)
        lay.addWidget(dele)
        self._status = QW.QLabel(""); self._status.setWordWrap(True)
        lay.addWidget(self._status)
        lay.addStretch(1)
        self._sync_value_label(initial=True)
        self._update_face_label()
        return w

    def _sync_value_label(self, *a, **k):
        bc = cfdbc.bc_by_label(self._type.currentText()) or cfdbc.BC_TYPES[0]
        self._vrow.setText(bc.get("value_label") or "Value (not needed)")
        needs = bool(bc.get("value_label"))
        self._value.setEnabled(needs)
        try:
            self._value.clear()
            if needs:
                self._value.addItems([str(v) for v in
                                      (bc.get("presets") or [bc.get("value", 0.0)])])
                # On first build keep the node's stored value; after a type change
                # fall back to that type's default.
                if k.get("initial"):
                    self._value.setEditText(str(getattr(self._node, "CfdBCValue", "0")))
                else:
                    self._value.setEditText(str(bc.get("value", 0.0)))
        except Exception:
            pass

    def refresh_selection(self):
        # Just note how many faces are currently selected; the user clicks
        # 'Use selected faces' to actually move the BC onto them.
        try:
            sel = FreeCADGui.Selection.getSelectionEx()
        except Exception:
            sel = []
        faces = []
        for s in sel:
            faces += cfdbc.parse_face_indices(getattr(s, "SubElementNames", []) or [])
        self._sel_faces = sorted(set(faces))
        self._update_face_label()

    def _update_face_label(self):
        cur = _cfd_node_faces(self._node)
        tgt = self._picked if self._picked is not None else cur
        extra = ""
        sf = getattr(self, "_sel_faces", [])
        if sf:
            extra = "  (%d face(s) selected in view)" % len(sf)
        self._facelbl.setText("Faces: %d%s" % (len(tgt), extra))

    def _use_selection(self):
        sf = getattr(self, "_sel_faces", [])
        if not sf:
            self._status.setText("Select one or more faces in the 3D view first.")
            return
        self._picked = list(sf)
        self._status.setText("Will move this BC onto %d selected face(s) on Apply."
                             % len(sf))
        self._update_face_label()

    def _value_num(self):
        try:
            return float(self._value.currentText())
        except (TypeError, ValueError):
            return 0.0

    def _do_delete(self):
        self._cleanup()
        _cfd_delete_bc_node(self._node)
        _close_task_dialog()

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Ok | QW.QDialogButtonBox.Cancel)

    def isAllowedAlterDocument(self):
        return True

    def accept(self):
        bc = cfdbc.bc_by_label(self._type.currentText()) or cfdbc.BC_TYPES[0]
        _cfd_update_bc_node(self._node, bc, self._picked, self._value_num())
        self._cleanup(); _close_task_dialog(); return True

    def reject(self):
        self._cleanup(); _close_task_dialog(); return True

    def _cleanup(self):
        try:
            if self._obs is not None:
                FreeCADGui.Selection.removeObserver(self._obs)
        except Exception:
            pass


def _show_cfd_bc_edit_panel(node):
    """Open the non-modal BC editor; False if unavailable (headless fallback)."""
    return _cfd_dock(lambda: _CfdBCEditPanel(node))


def _cfd_edit_bc(node):
    """Double-click handler for a BC node: edit its type/value/faces or delete it."""
    if cfdbc is None:
        err("The CFD BC module failed to load."); return
    if _show_cfd_bc_edit_panel(node):
        return
    # Modal fallback (headless / tests).
    cur = cfdbc.bc_type(getattr(node, "CfdBCType", "") or "") or cfdbc.BC_TYPES[0]
    try:
        cur_val = float(getattr(node, "CfdBCValue", "0") or 0)
    except (TypeError, ValueError):
        cur_val = 0.0
    fields = [
        {"key": "type", "label": "Boundary condition", "kind": "combo",
         "options": cfdbc.bc_labels(), "default": cur.get("label")},
        {"key": "value", "label": "Value (speed m/s or pressure Pa)",
         "kind": "float", "default": cur_val, "decimals": 6},
    ]
    vals = form_dialog("Edit Boundary Condition", fields)
    if not vals:
        return
    nb = cfdbc.bc_by_label(vals.get("type")) or cur
    _cfd_update_bc_node(node, nb, None, vals.get("value", cur_val))


class CfdAssignBC:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_bc"),
                "MenuText": "Assign Boundary Condition (faces)",
                "ToolTip": "SimScale-style boundary conditions: select one or more "
                           "faces of the solid in the 3D view, then run this to "
                           "assign a BC (velocity inlet, pressure outlet, wall, "
                           "slip/symmetry). The faces are colour-coded and the "
                           "assignment is stored as a node under the study's "
                           "Boundary conditions.",
                "Accel": "C, B"}

    def IsActive(self):
        return cfdbc is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        if cfdbc is None:
            err("The CFD BC module failed to load."); return
        # Preferred: the non-modal panel - stays open so you can click faces in
        # the 3D view while it is up (SimScale-style). Fall back to a modal form
        # only when the Task-panel control is unavailable (headless / tests).
        if _show_cfd_bc_panel():
            return
        try:
            sel = FreeCADGui.Selection.getSelectionEx()
        except Exception:
            sel = []
        solid = None; subs = []
        for s in sel:
            o = getattr(s, "Object", None)
            if o is None:
                continue
            if solid is None:
                solid = o
            if o is solid:
                subs += list(getattr(s, "SubElementNames", []) or [])
        faces = cfdbc.parse_face_indices(subs)
        if solid is None or not faces:
            info("Select one or more FACES of the solid in the 3D view, then run "
                 "Assign Boundary Condition. (Click a face; Ctrl-click for more.)")
            return
        fields = [
            {"key": "type", "label": "Boundary condition", "kind": "combo",
             "options": cfdbc.bc_labels(), "default": cfdbc.bc_labels()[0]},
            {"key": "value", "label": "Value (speed m/s or pressure Pa)",
             "kind": "float", "default": 10.0, "decimals": 4},
        ]
        vals = form_dialog("Assign Boundary Condition", fields)
        if not vals:
            return
        bc = cfdbc.bc_by_label(vals.get("type")) or cfdbc.BC_TYPES[0]
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: assign BC")
        try:
            _cfd_create_bc(doc, solid, bc, faces, vals.get("value", 0.0))
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            err("Could not assign the boundary condition: %s" % e); return
        counts = cfdbc.summarize(_cfd_collect_bc_assignments(doc, solid.Name))
        summary = ", ".join("%s=%d" % (k, n) for k, n in sorted(counts.items()))
        info("Assigned %s to %d face(s) of '%s'. BCs so far: %s." %
             (bc["label"], len(faces), getattr(solid, "Label", "solid"), summary))


def _g(v):
    """Compact number format (mirrors dynframe_cfd_gen._g)."""
    return ("%.6g" % float(v))


def _cfd_bc_values(doc, solid_name):
    """Per-BC-key value for a solid, from its BC objects: {bc_key: value}."""
    out = {}
    for o in getattr(doc, "Objects", []):
        if getattr(o, "CfdBCSolid", "") != solid_name:
            continue
        k = getattr(o, "CfdBCType", "") or ""
        try:
            out.setdefault(k, float(getattr(o, "CfdBCValue", "0") or 0))
        except (TypeError, ValueError):
            out.setdefault(k, 0.0)
    return out


def _cfd_patch_type(bc_key):
    b = cfdbc.bc_type(bc_key) if cfdbc is not None else None
    return b.get("patch", "wall") if b else "wall"


def _cfd_export_grouped_stls(solid, assigns, stage, scale=1e-3):
    """Tessellate the solid's faces grouped by assigned BC, and write one STL per
    group (scaled to metres) into `stage`. Faces with no BC default to a wall.
    Returns a list of {"name": bc_key, "type": patch_type} for snappyHexMesh."""
    shp = global_shape(solid)
    faces = list(shp.Faces)
    try:
        diag = shp.BoundBox.DiagonalLength
    except Exception:
        diag = 100.0
    tol = max(diag / 250.0, 1e-4)        # tessellation chord tolerance (mm)
    groups = {}
    for i, f in enumerate(faces):
        key = assigns.get(i, "wall")
        try:
            pts, facets = f.tessellate(tol)
        except Exception:
            continue
        g = groups.setdefault(key, ([], []))
        base = len(g[0])
        g[0].extend([(p.x * scale, p.y * scale, p.z * scale) for p in pts])
        g[1].extend([(a + base, b + base, c + base) for (a, b, c) in facets])
    patch_list = []
    for key, (pts, facets) in groups.items():
        if not facets:
            continue
        _write_lf(os.path.join(stage, key + ".stl"),
                  cfdgen.ascii_stl(key, pts, facets))
        patch_list.append({"name": key, "type": _cfd_patch_type(key)})
    return patch_list


def _cfd_build_mesh_dicts(doc, solid, assigns, bb, Lm, stage, n, nlay, rmin, rmax):
    """Write the mesh dictionaries into `stage`: an exact blockMesh box, or a
    background box + snappyHexMesh (with STL patches, refinement and boundary
    layers) for an arbitrary solid. Returns (used_bc_keys, is_box). Shared by the
    Run and the Mesh-preview commands so the mesh controls apply to both."""
    is_box = (len(global_shape(solid).Faces) == 6)
    if is_box:
        face_patches = {}; used = set()
        for idx, fk in enumerate(cfdgen.BOX_FACE_ORDER):
            key = assigns.get(idx, "wall")
            face_patches[fk] = (key, _cfd_patch_type(key)); used.add(key)
        _write_lf(os.path.join(stage, "blockMeshDict"),
                  cfdgen.box_blockmesh_named(
                      bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax,
                      n, n, n, face_patches))
    else:
        patch_list = _cfd_export_grouped_stls(solid, assigns, stage)
        used = set(p["name"] for p in patch_list)
        mrg = 0.10 * Lm
        bx0, by0, bz0 = bb.XMin - mrg, bb.YMin - mrg, bb.ZMin - mrg
        bx1, by1, bz1 = bb.XMax + mrg, bb.YMax + mrg, bb.ZMax + mrg
        cs = max(bx1 - bx0, by1 - by0, bz1 - bz0) / max(4, n)
        nx = max(4, int((bx1 - bx0) / cs))
        ny = max(4, int((by1 - by0) / cs))
        nz = max(4, int((bz1 - bz0) / cs))
        loc = (0.5 * (bb.XMin + bb.XMax), 0.5 * (bb.YMin + bb.YMax),
               0.5 * (bb.ZMin + bb.ZMax))
        _write_lf(os.path.join(stage, "blockMeshDict"),
                  cfdgen.background_box_dict(bx0, by0, bz0, bx1, by1, bz1, nx, ny, nz))
        _write_lf(os.path.join(stage, "snappyHexMeshDict"),
                  cfdgen.snappy_multipatch_dict(
                      patch_list, loc, level_min=rmin, level_max=rmax, n_layers=nlay))
        _write_lf(os.path.join(stage, "surfaceFeaturesDict"),
                  cfdgen.surface_features_multi(sorted(used)))
    return used, is_box


def _cfd_patch_flow_dirs(solid, assigns):
    """Unit flow direction per BC key, taken from geometry so it is correct for
    any face orientation (not just +X): into the fluid domain for inlets, out of
    it for outlets. Direction = face-centre -> domain-centre, area-weighted over
    the faces that carry the BC, which for a box is exactly the inward normal.
    Faces and centre both come from the same global shape (same mm frame as the
    mesh), so the unit direction is frame- and unit-consistent."""
    import math
    out = {}
    try:
        shp = global_shape(solid)
        faces = shp.Faces
        c = shp.BoundBox.Center
        cx, cy, cz = float(c.x), float(c.y), float(c.z)
    except Exception:
        return out
    acc = {}
    for idx, key in (assigns or {}).items():
        try:
            f = faces[int(idx)]
            fc = f.CenterOfMass
            a = float(f.Area)
        except Exception:
            continue
        v = acc.setdefault(key, [0.0, 0.0, 0.0])
        v[0] += (cx - float(fc.x)) * a
        v[1] += (cy - float(fc.y)) * a
        v[2] += (cz - float(fc.z)) * a
    for key, v in acc.items():
        m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if m < 1e-12:
            continue
        ux, uy, uz = v[0] / m, v[1] / m, v[2] / m          # inward (toward centre)
        if key in ("velocity_outlet", "pressure_outlet"):
            ux, uy, uz = -ux, -uy, -uz                     # outlets point outward
        out[key] = (ux, uy, uz)
    return out


def _cfd_run_internal_flow(doc, solid, assigns, bb, vals0, vals):
    """Stage and (optionally) solve the internal-flow case from the collected
    panel values, then report. Shared by the docked Run panel and its modal
    fallback so both run exactly the same validated OpenFOAM pipeline."""
    name = (str(vals.get("name") or "flowint1").strip().replace(" ", "_")) or "flowint1"
    n = max(4, int(vals["ncells"]))
    Lm = max(bb.XLength, bb.YLength, bb.ZLength, 1e-6)
    intensity = float(_cfd_study_get(doc, "CfdIntensity", "5") or 5) / 100.0
    of_env = str(vals.get("env") or cfd.DEFAULT_OF_ENV).strip()
    distro = str(vals.get("distro") or "").strip()  # blank => WSL default distro
    outdir = _cfd_outdir()
    stage = os.path.join(outdir, name + "_src")
    win_out = os.path.join(outdir, name)
    try:
        nlay = int(float(_cfd_study_get(doc, "CfdLayers", "3") or 3))
        rmin = int(float(_cfd_study_get(doc, "CfdRefineMin", "1") or 1))
        rmax = int(float(_cfd_study_get(doc, "CfdRefineMax", "2") or 2))
        used, is_box = _cfd_build_mesh_dicts(
            doc, solid, assigns, bb, Lm, stage, n, nlay, rmin, rmax)
        if not used:
            err("Could not build the mesh (no patches)."); return
        mesher = ("blockMesh (box)" if is_box else
                  "snappyHexMesh (%d layers, refinement %d-%d)"
                  % (nlay, rmin, rmax))
        dirs = _cfd_patch_flow_dirs(solid, assigns)
        patches = [{"name": k, "bc": k, "value": vals0.get(k, 0.0),
                    "dir": dirs.get(k)} for k in sorted(used)]
        # Incompressible flow needs one fixed-pressure reference. If the user
        # tagged no pressure inlet/outlet, solve the (velocity) outlet as a 0 Pa
        # pressure outlet so the case is well-posed - otherwise OpenFOAM's
        # adjustPhi fails (no adjustable outflow) and no results are written.
        pref_note = ""
        if not any(p["bc"] in ("pressure_outlet", "pressure_inlet")
                   for p in patches):
            outp = next((p for p in patches if p["bc"] == "velocity_outlet"), None)
            if outp is not None:
                outp["bc"] = "pressure_outlet"; outp["value"] = 0.0
                pref_note = ("\n\nNote: no pressure boundary was assigned, so the "
                             "outlet '%s' was solved as a 0 Pa pressure outlet - "
                             "an incompressible case needs one pressure reference."
                             % outp["name"])
        casefiles, k0, om0 = cfdgen.bc_field_files(
            patches, nu=float(vals["nu"]), intensity=intensity, L=Lm)
        turb = _cfd_study_get(doc, "CfdTurbulence", "kOmegaSST")
        casefiles["momentumTransport"] = cfdgen.momentum_transport_dict(turb)
        heat = _cfd_study_get(doc, "CfdHeat", "") == "1"
        so = _cfd_study_get(doc, "CfdSecondOrder", "") == "1"
        casefiles["fvSchemes"] = cfdgen.fv_schemes_simple(second_order=so, heat=heat)
        casefiles["fvSolution"] = cfdgen.fv_solution_simple(heat=heat)
        write = int(float(_cfd_study_get(doc, "CfdWrite", "")
                          or max(1, int(int(vals["iters"]) / 5))))
        funcs = ""
        if heat:
            Pr = float(_cfd_study_get(doc, "CfdPr", "0.71") or 0.71)
            T_in = float(_cfd_study_get(doc, "CfdTin", "300") or 300)
            T_wall = float(_cfd_study_get(doc, "CfdTwall", "350") or 350)
            casefiles["T"] = cfdgen.temperature_field(
                patches, T_in=T_in, T_wall=T_wall, heated=True)
            funcs = cfdgen.scalar_transport_functions(float(vals["nu"]) / max(Pr, 1e-6))
        casefiles["controlDict"] = cfdgen.control_dict_simple(
            "incompressibleFluid", int(vals["iters"]), max(1, write),
            functions=funcs)
        for fn, txt in casefiles.items():
            _write_lf(os.path.join(stage, fn), txt)
    except Exception as e:
        err("Could not write the case files to %s:\n%s" % (stage, e)); return
    if is_box:
        fs = cfdgen.build_internal_flow_script(
            {"of_env": of_env, "name": name, "stage_win": stage,
             "win_out": win_out, "latest": True, "open_image": False})
    else:
        fs = cfdgen.build_snappy_flow_script(
            {"of_env": of_env, "name": name, "stage_win": stage,
             "win_out": win_out, "patch_names": sorted(used), "latest": True,
             "open_image": False})
    fpath = os.path.join(outdir, "run_%s.sh" % name)
    try:
        _write_lf(fpath, fs)
    except Exception as e:
        err("Could not write the run script:\n%s" % e); return
    flow_cmd = "bash %s" % cfd.win_to_wsl(fpath, distro)
    _cfd_record(FreeCAD.ActiveDocument, name, [
        ("Analysis", "Internal flow (RANS kOmegaSST) from assigned faces"),
        ("Geometry", getattr(solid, "Label", "solid")),
        ("Patches", ", ".join(sorted(used))),
        ("Inlet k / omega", "%.4g / %.4g" % (k0, om0)),
        ("Run (paste in WSL)", flow_cmd),
        ("Then open in ParaView", os.path.join(win_out, "VTK")),
        ("Run script", fpath), ("Staged files", stage)])
    # Solve now (blocking) and report convergence - the SimScale "job status".
    # A box solve is seconds; a big case should be run from the terminal cmd.
    status = ""
    if vals.get("run") == "Yes":
        status = _cfd_run_and_report(fs, distro, win_out)
        ran_ok = ("Results written to" in status)
        if ran_ok:
            opened = _cfd_open_result(name, distro, win_out)
            if opened == "paraview":
                status += ("\n\nOpening the result in ParaView (native Windows): in "
                           "the Pipeline Browser click the case, press Apply, and "
                           "colour by U or p.")
            elif opened == "image":
                status += ("\n\nResult images (velocity + pressure) were rendered "
                           "and opened; they are saved in the case's images folder. "
                           "Install ParaView for Windows for interactive viewing.")
            else:
                status += "\n\nResults (VTK + images) saved in the case folder."
    status += pref_note
    _cfd_report("Internal flow result",
         "Internal-flow case '%s' from your face BCs on '%s'.\n\nPatches: %s.\n"
         "Mesh: %s. Solver: incompressibleFluid (%s).%s\n\nTo (re)run it "
         "yourself, in your WSL OpenFOAM terminal:\n  %s\n\nResults for "
         "ParaView:\n  %s" %
         (name, getattr(solid, "Label", "solid"), ", ".join(sorted(used)),
          mesher, turb, status, flow_cmd, os.path.join(win_out, "VTK")))


class CfdFlowInternal:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_run"),
                "MenuText": "Run Flow from BCs (internal)",
                "ToolTip": "Solve internal flow through the selected box solid "
                           "using the boundary conditions you assigned to its "
                           "faces (Assign Boundary Condition). The box interior is "
                           "meshed with blockMesh, each face group becomes its "
                           "named patch, and OpenFOAM solves it - SimScale-style, "
                           "with exactly your inlet/outlet/wall faces.",
                "Accel": "C, R"}

    def IsActive(self):
        return (cfd is not None and cfdgen is not None and cfdbc is not None
                and FreeCAD.ActiveDocument is not None)

    def Activated(self):
        if cfd is None or cfdgen is None or cfdbc is None:
            err("The CFD modules failed to load."); return
        doc = FreeCAD.ActiveDocument
        solid = _cfd_resolve_solid(doc)
        if solid is None:
            info("No geometry found. Open the 'Geometry' node to choose the solid, "
                 "or select it in the tree, then Run."); return
        assigns = _cfd_collect_bc_assignments(doc, getattr(solid, "Name", ""))
        if not assigns:
            info("No boundary conditions on '%s' yet. Open 'Boundary conditions', "
                 "tag at least an inlet and an outlet face, then Run."
                 % getattr(solid, "Label", "solid")); return
        try:
            shp = global_shape(solid)
            nfaces = len(shp.Faces)
        except Exception as e:
            err("Could not read '%s': %s" % (getattr(solid, "Label", "?"), e)); return
        is_box = (nfaces == 6)
        # box bounds in metres
        try:
            mat = FreeCAD.Matrix(); mat.scale(1e-3, 1e-3, 1e-3)
            bb = shp.transformGeometry(mat).BoundBox
        except Exception as e:
            err("Could not scale geometry: %s" % e); return
        vals0 = _cfd_bc_values(doc, solid.Name)
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Internal flow through '%s' using your face BCs. A box is meshed with "
             "blockMesh; any other solid with snappyHexMesh (named patches + "
             "boundary layers). Solved with incompressibleFluid. Patches: %s."
             % (getattr(solid, "Label", "solid"),
                ", ".join(sorted(set(assigns.values()))))},
            {"key": "name", "label": "Case name", "kind": "text", "default": "flowint1"},
            {"key": "ncells", "label": "Cells across the domain", "kind": "int",
             "default": int(float(_cfd_study_get(doc, "CfdCells", "20") or 20)),
             "min": 4, "max": 400},
            {"key": "iters", "label": "Iterations (steady)", "kind": "int",
             "default": int(float(_cfd_study_get(doc, "CfdIters", "1000") or 1000)),
             "min": 50, "max": 200000},
            {"key": "nu", "label": "Kinematic viscosity nu (m2/s)", "kind": "float",
             "default": _cfd_study_nu(doc), "decimals": 9},
            {"key": "distro", "label": "WSL distro (blank = default)", "kind": "text", "default": ""},
            {"key": "env", "label": "OpenFOAM env (source)", "kind": "text", "default": cfd.DEFAULT_OF_ENV},
            {"key": "run", "label": "Mesh + solve now", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
            {"key": "pv", "label": "Open result in ParaView when done", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
        ]
        _cfd_show_step_panel(
            "Internal Flow from BCs",
            "Mesh the solid interior (blockMesh for a box, snappyHexMesh "
            "otherwise) and solve on OpenFOAM, then open the result in ParaView.",
            fields,
            lambda vals: _cfd_run_internal_flow(doc, solid, assigns, bb, vals0, vals))


def _cfd_run_and_report(script, distro, win_out):
    """Run a case script in WSL (blocking) and return a short convergence report
    - OpenFOAM's job status in-app, so the user can trust the result."""
    import subprocess
    try:
        argv = cfd.wsl_run_argv(script, distro)
        r = subprocess.run(argv, capture_output=True, timeout=1800)
        out = (r.stdout or b"").decode("utf-8", "replace")
        out += (r.stderr or b"").decode("utf-8", "replace")
    except Exception as e:
        return ("\n\nAuto-run could not start (%s). Run the command below in your "
                "WSL OpenFOAM terminal instead." % e)
    conv = cfd.parse_convergence(out)
    mesh_ok = "Mesh OK" in out
    if conv["converged"]:
        res = ", ".join("%s=%.1e" % (k, v) for k, v in sorted(conv["residuals"].items()))
        return ("\n\nSOLVED - converged in %d iterations (mesh: %s). Final "
                "residuals: %s. Results written to %s." %
                (conv["iterations"], "OK" if mesh_ok else "see log",
                 res or "n/a", os.path.join(win_out, "VTK")))
    if conv["iterations"]:
        return ("\n\nRan %d iterations (mesh: %s). It did not hit the early-stop "
                "tolerance - normal for internal flow, the result is still usable; "
                "raise iterations for a tighter solution. Results written to %s." %
                (conv["iterations"], "OK" if mesh_ok else "see log",
                 os.path.join(win_out, "VTK")))
    return ("\n\nThe run did not complete (mesh or solver error). Check the log "
            "in the case folder, or run the command below in your terminal.")


def _cfd_launch_paraview(name, distro=""):
    """Open a solved case in ParaView (installed in WSL, shown via WSLg): create a
    .foam file in the case and launch paraview on it, non-blocking. Returns True
    if the launch was dispatched."""
    try:
        import subprocess
        work = cfd.WORK_ROOT
        # nohup + setsid + disown fully detach ParaView so it survives the launcher
        # shell exiting; a short sleep lets WSLg bring the window up.
        script = (". %s >/dev/null 2>&1\n" % cfd.DEFAULT_OF_ENV
                  + 'D=%s/%s\n' % (work, name)
                  + '[ -d "$D" ] || exit 1\n'
                  + 'touch "$D/%s.foam" 2>/dev/null\n' % name
                  + 'export DISPLAY=${DISPLAY:-:0}\n'
                  + 'command -v paraview >/dev/null 2>&1 || exit 2\n'
                  + 'nohup setsid paraview "$D/%s.foam" '
                    '>/tmp/dynframe_pv.log 2>&1 < /dev/null &\n' % name
                  + 'disown 2>/dev/null || true\n'
                  + 'sleep 3\n')
        subprocess.Popen(cfd.wsl_run_argv(script, distro),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _cfd_windows_paraview():
    """A native Windows ParaView's path (a Windows path, C:\\...) if one is
    installed, else "". DynFrame opens results in native Windows ParaView when
    present - the only reliable interactive viewer here, since WSLg cannot show the
    WSL ParaView window (32x32 / off-screen). Without it, the result image is used."""
    import glob
    cands = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            cands += glob.glob(os.path.join(base, "ParaView*", "bin", "paraview.exe"))
    try:
        import shutil
        w = shutil.which("paraview")
        if w:
            cands.append(w)
    except Exception:
        pass
    for p in sorted(cands, reverse=True):          # newest version first
        if p and os.path.exists(p):
            return p                               # a Windows path (C:\...)
    return ""


_CFD_WATCHERS = []     # keep result watchers alive while they poll


def _cfd_foam_unc(name, distro=""):
    """The solved case's .foam as a Windows path (\\\\wsl.localhost\\...), creating
    the .foam if needed. "" on failure."""
    try:
        import subprocess
        script = ('D=%s/%s\n[ -d "$D" ] || exit 1\ntouch "$D/%s.foam" 2>/dev/null\n'
                  'wslpath -w "$D/%s.foam"\n' % (cfd.WORK_ROOT, name, name, name))
        r = subprocess.run(cfd.wsl_run_argv(script, distro),
                           capture_output=True, timeout=30)
        out = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        return out[-1].strip() if out else ""
    except Exception:
        return ""


def _cfd_open_result(name, distro, win_out):
    """Open the solved result FROM THE WINDOWS SIDE (the FreeCAD process): native
    Windows ParaView if installed - it survives, unlike a WSL-launched one, which
    is killed before its window appears - else the rendered velocity image.
    `win_out` is the Windows-side case folder (C:\\...\\<name>). Returns what opened."""
    import subprocess
    pv = _cfd_windows_paraview()                   # a Windows path, or ""
    if pv:
        foam = _cfd_foam_unc(name, distro)
        if foam:
            # Launch via Windows' own `start`, which detaches ParaView into a fully
            # independent process (the Windows shell owns it) - so it survives
            # FreeCAD closing and is never killed with the launcher. A plain child
            # or a DETACHED_PROCESS one is still inside FreeCAD's job object and
            # dies when FreeCAD exits; a WSL-launched one dies with the WSL script.
            comspec = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
            try:
                subprocess.Popen([comspec, "/c", "start", "", pv, foam],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True)
                return "paraview"
            except Exception:
                try:
                    subprocess.Popen([pv, foam])
                    return "paraview"
                except Exception:
                    pass
    img = os.path.join(win_out, "images", "U.png")
    try:
        if os.path.exists(img):
            os.startfile(img)                      # Windows default image viewer
            return "image"
    except Exception:
        pass
    return ""


class _CfdResultWatcher:
    """After a DETACHED run, poll (non-blocking, from the FreeCAD/Windows side) for
    the result, then open it in ParaView (or the image). Kept in _CFD_WATCHERS so
    the QTimer is not garbage-collected mid-run."""
    def __init__(self, name, distro, win_out):
        self._name = name; self._distro = distro; self._win_out = win_out
        self._ticks = 0
        try:
            os.remove(os.path.join(win_out, ".dynframe_done"))   # drop a stale marker
        except Exception:
            pass
        try:
            from PySide import QtCore
        except Exception:
            from PySide2 import QtCore
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(2500)
        _CFD_WATCHERS.append(self)

    def _poll(self):
        self._ticks += 1
        done = False
        try:
            done = os.path.exists(os.path.join(self._win_out, ".dynframe_done"))
        except Exception:
            done = False
        if done or self._ticks > 1200:             # ~50 min safety cap
            try:
                self._timer.stop()
            except Exception:
                pass
            if done:
                _cfd_open_result(self._name, self._distro, self._win_out)
            try:
                _CFD_WATCHERS.remove(self)
            except Exception:
                pass


def _cfd_list_tutorials(of_env=None, distro=""):
    """Enumerate the installed OpenFOAM tutorials as (category, relpath, abspath)
    by asking WSL. Empty list if none are found / WSL is unreachable."""
    import subprocess
    try:
        script = cfdgen.tutorials_find_script(of_env or cfd.DEFAULT_OF_ENV)
        r = subprocess.run(cfd.wsl_run_argv(script, distro),
                           capture_output=True, timeout=90)
        out = (r.stdout or b"").decode("utf-8", "replace")
    except Exception:
        return []
    cases = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line == "NO_TUTORIALS" or line.count("|") != 2:
            continue
        cat, rel, ab = line.split("|")
        if cat and rel and ab:
            cases.append((cat, rel, ab))
    return cases


class _CfdExamplesPanel:
    """Non-modal browser for the built-in OpenFOAM tutorials: pick a category and
    case, optionally change the time controls, Run (in the background) and the
    result opens in ParaView - a parameterisable example gallery, SimScale-style."""
    def __init__(self, cases):
        self._by_cat = {}
        for cat, rel, ab in cases:
            self._by_cat.setdefault(cat, []).append((rel, ab))
        self.form = self._build()

    def _build(self):
        w = QW.QWidget(); w.setObjectName("cfdPanel")
        w.setWindowTitle("OpenFOAM examples")
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "subtext": "#9aa7b4"})
        if cfdui is not None:
            try:
                w.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        lay = QW.QVBoxLayout(w)
        hdr = QW.QLabel("OpenFOAM examples")
        hdr.setStyleSheet("background:%s;color:#fff;font-weight:700;font-size:14px;"
                          "padding:7px 10px;" % pal["accent"])
        lay.addWidget(hdr)
        n = sum(len(v) for v in self._by_cat.values())
        tip = QW.QLabel("Pick a tutorial, change the time controls if you like, "
                        "then Run. It solves on OpenFOAM in the background and "
                        "opens in ParaView when done. %d cases available." % n)
        tip.setWordWrap(True)
        tip.setStyleSheet("color:%s;padding:4px 2px;" % pal["subtext"])
        lay.addWidget(tip)
        form = QW.QFormLayout()
        self._cat = QW.QComboBox(); self._cat.addItems(sorted(self._by_cat.keys()))
        try:                           # start on a fast, visual category, not XiFluid
            for pref in ("incompressibleFluid", "fluid", "incompressibleVoF"):
                if pref in self._by_cat:
                    self._cat.setCurrentText(pref); break
        except Exception:
            pass
        self._cat.currentIndexChanged.connect(self._fill_cases)
        form.addRow("Category", self._cat)
        self._case = QW.QComboBox()
        self._case.currentIndexChanged.connect(self._show_desc)
        form.addRow("Example", self._case)
        self._end = QW.QLineEdit(); self._end.setPlaceholderText("keep as shipped")
        form.addRow("End time / iterations", self._end)
        self._wri = QW.QLineEdit(); self._wri.setPlaceholderText("keep")
        form.addRow("Write interval", self._wri)
        self._dt = QW.QLineEdit(); self._dt.setPlaceholderText("keep")
        form.addRow("Time step (deltaT)", self._dt)
        self._distro = QW.QLineEdit(); self._distro.setPlaceholderText("default")
        form.addRow("WSL distro", self._distro)
        self._env = QW.QLineEdit(); self._env.setText(cfd.DEFAULT_OF_ENV)
        form.addRow("OpenFOAM env", self._env)
        lay.addLayout(form)
        self._desc = QW.QLabel(""); self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color:%s;padding:2px;" % pal["subtext"])
        lay.addWidget(self._desc)
        run = QW.QPushButton("Run now (mesh + solve + result image)")
        run.clicked.connect(self._run)
        lay.addWidget(run)
        self._status = QW.QLabel(""); self._status.setWordWrap(True)
        lay.addWidget(self._status)
        lay.addStretch(1)
        self._fill_cases()
        return w

    def _fill_cases(self, *a):
        self._case.clear()
        for rel, ab in self._by_cat.get(self._cat.currentText(), []):
            self._case.addItem(rel.split("/", 1)[-1] if "/" in rel else rel)
        self._show_desc()

    def _show_desc(self, *a):
        items = self._by_cat.get(self._cat.currentText(), [])
        i = self._case.currentIndex()
        if 0 <= i < len(items):
            self._desc.setText("Case path: %s" % items[i][0])

    def _run(self):
        items = self._by_cat.get(self._cat.currentText(), [])
        i = self._case.currentIndex()
        if i < 0 or i >= len(items):
            self._status.setText("Pick an example first."); return
        rel, ab = items[i]
        name = "ex_" + rel.replace("/", "_").replace(" ", "_")
        of_env = str(self._env.text() or cfd.DEFAULT_OF_ENV).strip()
        distro = str(self._distro.text() or "").strip()
        try:
            win_out = cfd.win_to_wsl(os.path.join(_cfd_outdir(), name), distro)
        except Exception:
            win_out = ""
        opts = {"of_env": of_env, "src": ab, "name": name, "win_out": win_out,
                "open_image": False,
                "end_time": self._end.text().strip(),
                "write_interval": self._wri.text().strip(),
                "delta_t": self._dt.text().strip()}
        try:
            script = cfdgen.build_tutorial_run_script(opts)
            import subprocess
            subprocess.Popen(cfd.wsl_run_argv(script, distro),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL)
            _CfdResultWatcher(name, distro, os.path.join(_cfd_outdir(), name))
        except Exception as e:
            self._status.setText("Could not start: %s" % e); return
        self._status.setText(
            "Running '%s' in the background - the result opens in ParaView (native "
            "Windows) when it finishes, or as an image if ParaView isn't installed "
            "(large cases take minutes). Progress: ~/dynframe_cfd/%s/log.dynframe"
            % (rel, name))

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Close)

    def accept(self):
        _close_task_dialog(); return True

    def reject(self):
        _close_task_dialog(); return True


def _cfd_open_template_as_study(doc, key, params):
    """Load a curated example as a fully EDITABLE CFD study: create the box
    geometry, build the SimScale-style tree, assign the boundary conditions to its
    faces and store the study settings. The user can then resize the box (Data
    panel), double-click BC nodes to change type/value/faces, edit Mesh/Numerics/
    Simulation control, and double-click Run - the same validated internal-flow
    solver. Non-box examples fall back to a message."""
    if cfdex is None or cfdtree is None or cfdbc is None:
        err("The CFD modules failed to load."); return
    spec = cfdex.example_study_spec(key, params)
    if spec is None:
        info("'Open as editable study' isn't available for this example yet (its "
             "geometry isn't a simple box). Use Run to solve it directly, or pick "
             "the cavity or channel template."); return
    doc.openTransaction("DynFrame: open CFD example as study")
    try:
        Lx, Ly, Lz = spec["dims"]
        box = doc.addObject("Part::Box", "CfdExample")
        box.Length = float(Lx); box.Width = float(Ly); box.Height = float(Lz)
        try:
            box.Label = spec.get("label", "CFD example")
        except Exception:
            pass
        doc.recompute()
        studies = cfdtree.study_types()
        study = next((s for s in studies
                      if "incompressible" in str(s.get("id", "")).lower()),
                     studies[0] if studies else {"id": "incompressibleFluid",
                                                 "title": "Incompressible flow"})
        container = build_cfd_tree(doc, study)
        _cfd_set_str(container, "CfdGeometry", box.Name)
        for k, v in spec.get("study", {}).items():
            _cfd_set_str(container, k, v)
        bb = box.Shape.BoundBox
        faces = box.Shape.Faces

        def _side(f):
            c = f.CenterOfMass
            d = {"xmin": abs(c.x - bb.XMin), "xmax": abs(c.x - bb.XMax),
                 "ymin": abs(c.y - bb.YMin), "ymax": abs(c.y - bb.YMax),
                 "zmin": abs(c.z - bb.ZMin), "zmax": abs(c.z - bb.ZMax)}
            return min(d, key=d.get)

        bcs = spec.get("bcs", {})
        groups = {}
        for i, f in enumerate(faces):
            s = _side(f)
            if s in bcs:
                groups.setdefault(bcs[s], []).append(i)
        for (bc_key, value), idxs in groups.items():
            b = cfdbc.bc_type(bc_key)
            if b is not None:
                _cfd_create_bc(doc, box, b, idxs, value)
        doc.commitTransaction(); doc.recompute()
    except Exception as e:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        err("Could not open the example as a study: %s" % e); return
    try:
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(box)
        _cfd_zoom_selection()
    except Exception:
        pass
    _cfd_report(
        "Editable study",
        "Loaded '%s' as an EDITABLE CFD study - change anything, then run.\n\n"
        "- Geometry: the box '%s'. Select it and edit Length / Width / Height in "
        "the Data panel (bottom-left) to resize, or replace it with your own "
        "imported CAD.\n"
        "- Boundary conditions: double-click a BC node under 'Boundary conditions' "
        "to change its type, value or the faces it is on.\n"
        "- Mesh / Numerics / Simulation control: double-click those tree nodes to "
        "edit resolution, turbulence model, scheme order, iterations, etc.\n\n"
        "When ready, double-click 'Run' (or the Run Flow from BCs toolbar button) "
        "to mesh + solve on OpenFOAM and get the result image."
        % (spec.get("label", key), getattr(box, "Label", box.Name)))


class _CfdGalleryPanel:
    """Curated, fully-parameterised CFD examples (SimScale-style templates): pick a
    case, set its *physical* parameters (speeds, viscosity, size, mesh, turbulence),
    then either Run it directly or open it as a fully editable study. Non-modal."""
    def __init__(self, catalog):
        self._catalog = catalog
        self._cur = None
        self._widgets = {}
        self.form = self._build()

    def _build(self):
        w = QW.QWidget(); w.setObjectName("cfdPanel")
        w.setWindowTitle("CFD examples")
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "subtext": "#9aa7b4"})
        if cfdui is not None:
            try:
                w.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        lay = QW.QVBoxLayout(w)
        hdr = QW.QLabel("CFD examples (templates)")
        hdr.setStyleSheet("background:%s;color:#fff;font-weight:700;font-size:14px;"
                          "padding:7px 10px;" % pal["accent"])
        lay.addWidget(hdr)
        top = QW.QFormLayout()
        self._pick = QW.QComboBox()
        self._pick.addItems([e["title"] for e in self._catalog])
        self._pick.currentIndexChanged.connect(self._load_params)
        top.addRow("Example", self._pick)
        lay.addLayout(top)
        self._help = QW.QLabel(""); self._help.setWordWrap(True)
        self._help.setStyleSheet("color:%s;padding:4px 2px;" % pal["subtext"])
        lay.addWidget(self._help)
        self._host = QW.QWidget()
        self._pform = QW.QFormLayout(self._host)
        self._pform.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._host)
        eng = QW.QFormLayout()
        self._distro = QW.QLineEdit(); self._distro.setPlaceholderText("default")
        eng.addRow("WSL distro", self._distro)
        self._env = QW.QLineEdit(); self._env.setText(cfd.DEFAULT_OF_ENV)
        eng.addRow("OpenFOAM env", self._env)
        lay.addLayout(eng)
        run = QW.QPushButton("Run now (mesh + solve + result image)")
        run.clicked.connect(self._run)
        lay.addWidget(run)
        edit = QW.QPushButton("Open as editable study (geometry, BCs, mesh, numerics)")
        edit.clicked.connect(self._open_study)
        lay.addWidget(edit)
        self._status = QW.QLabel(""); self._status.setWordWrap(True)
        lay.addWidget(self._status)
        lay.addStretch(1)
        self._load_params()
        return w

    def _mk(self, pp):
        if pp.get("kind") == "combo":
            c = QW.QComboBox(); c.addItems([str(o) for o in pp.get("options", [])])
            c.setCurrentText(str(pp.get("default")))
            return c
        e = QW.QLineEdit(); e.setText(str(pp.get("default")))
        return e

    def _load_params(self, *a):
        i = self._pick.currentIndex()
        if i < 0 or i >= len(self._catalog):
            return
        spec = self._catalog[i]; self._cur = spec
        self._help.setText(spec.get("help", ""))
        while self._pform.count():                 # clear old rows + widgets
            item = self._pform.takeAt(0)
            wd = item.widget()
            if wd is not None:
                wd.deleteLater()
        self._widgets = {}
        for pp in spec.get("params", []):
            widget = self._mk(pp)
            self._pform.addRow(pp.get("label", pp["key"]), widget)
            self._widgets[pp["key"]] = (pp, widget)

    def _collect(self):
        out = {}
        for key, (pp, widget) in self._widgets.items():
            if pp.get("kind") == "combo":
                out[key] = widget.currentText()
                continue
            txt = widget.text().strip()
            try:
                out[key] = int(txt) if pp.get("kind") == "int" else float(txt)
            except (TypeError, ValueError):
                out[key] = pp.get("default")
        return out

    def _run(self):
        if self._cur is None or cfdex is None:
            self._status.setText("Examples module not available."); return
        key = self._cur["key"]
        params = self._collect()
        name = "cfdex_" + key
        of_env = str(self._env.text() or cfd.DEFAULT_OF_ENV).strip()
        distro = str(self._distro.text() or "").strip()
        try:
            files = cfdex.build_example(key, params)
        except Exception as e:
            self._status.setText("Could not build the case: %s" % e); return
        outdir = _cfd_outdir()
        stage = os.path.join(outdir, name + "_src")
        try:
            for fn, txt in files.items():
                _write_lf(os.path.join(stage, fn), txt)
        except Exception as e:
            self._status.setText("Could not stage files: %s" % e); return
        win_out = os.path.join(outdir, name)
        try:
            script = cfdgen.build_example_run_script(
                {"of_env": of_env, "name": name, "stage_win": stage,
                 "win_out": win_out, "open_image": False})
            import subprocess
            subprocess.Popen(cfd.wsl_run_argv(script, distro),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL)
            _CfdResultWatcher(name, distro, win_out)
        except Exception as e:
            self._status.setText("Could not start: %s" % e); return
        self._status.setText(
            "Running '%s' on OpenFOAM - the result opens in ParaView (native "
            "Windows) when it finishes (usually seconds), or as an image if "
            "ParaView isn't installed. Change any parameter and Run again to "
            "compare. Log: ~/dynframe_cfd/%s/log.dynframe"
            % (self._cur["title"], name))

    def _open_study(self):
        if self._cur is None or cfdex is None:
            self._status.setText("Examples module not available."); return
        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument()
        _cfd_open_template_as_study(doc, self._cur["key"], self._collect())
        self._status.setText(
            "Opened '%s' as an editable study - see the Model tree. Resize the box, "
            "double-click the BC and Mesh/Numerics nodes to edit, then double-click "
            "Run." % self._cur["title"])

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Close)

    def accept(self):
        _close_task_dialog(); return True

    def reject(self):
        _close_task_dialog(); return True


class CfdGallery:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_gallery"),
                "MenuText": "CFD Examples (templates)",
                "ToolTip": "Curated, parameterised CFD examples - lid-driven "
                           "cavity, channel flow, backward-facing step - built and "
                           "solved on OpenFOAM and opened in ParaView. Change the "
                           "physical parameters (speed, viscosity, size, mesh, "
                           "turbulence) and re-run, SimScale-style.",
                "Accel": "C, G"}

    def IsActive(self):
        return cfd is not None and cfdgen is not None and cfdex is not None

    def Activated(self):
        if cfd is None or cfdgen is None or cfdex is None:
            err("The CFD example modules failed to load."); return
        catalog = cfdex.example_catalog()
        if _cfd_dock(lambda: _CfdGalleryPanel(catalog)):
            return
        info("Open CFD Examples from the FreeCAD GUI (it needs the Task panel). "
             "%d curated templates are available." % len(catalog))


class CfdExamples:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_examples"),
                "MenuText": "OpenFOAM Examples (all cases)",
                "ToolTip": "Browse every built-in OpenFOAM example/tutorial case, "
                           "change its time controls, run it on OpenFOAM and open "
                           "it in ParaView. For curated, richly-parameterised "
                           "cases use 'CFD Examples (templates)' instead.",
                "Accel": "C, E"}

    def IsActive(self):
        return cfd is not None and cfdgen is not None

    def Activated(self):
        if cfd is None or cfdgen is None:
            err("The CFD modules failed to load."); return
        cases = _cfd_list_tutorials(cfd.DEFAULT_OF_ENV, "")
        if not cases:
            info("No OpenFOAM tutorials were found. Is OpenFOAM installed in WSL "
                 "(expected $FOAM_TUTORIALS, e.g. /opt/openfoam14/tutorials)?")
            return
        if _cfd_dock(lambda: _CfdExamplesPanel(cases)):
            return
        info("Open the OpenFOAM Examples browser from the FreeCAD GUI (it needs "
             "the Task panel). %d tutorial cases are available." % len(cases))


def _cfd_flow_execute(obj, pts, facets, bb, Lm, vals):
    """Build + stage the incompressible-flow case from the collected values and
    report it. Shared by the modal form and the docked Task panel so both paths
    run exactly the same, validated pipeline (snappyHexMesh + kOmegaSST)."""
    name = (str(vals.get("name") or "flow1").strip().replace(" ", "_")) or "flow1"
    Ux = float(vals["U"]); nu = float(vals["nu"])
    I = max(0.0, float(vals["ti"]) / 100.0)
    dom = cfdgen.domain_from_bbox(
        bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax,
        up=float(vals["up"]), down=float(vals["down"]), side=float(vals["side"]),
        top=float(vals["top"]), ground=float(vals["ground"]))
    h = Lm / max(2, int(vals["ncb"]))
    nx, ny, nz = cfdgen.cell_counts(*dom, h=h)
    loc = cfdgen.location_in_mesh(*dom, bx0=bb.XMin)
    # freestream box: all far-field patches (incl. ground) are slip
    bm = cfdgen.block_mesh_dict(*dom, nx, ny, nz, ground_type="patch")
    sn = cfdgen.snappy_hex_mesh_dict(
        stl="body.stl", name="body", level_min=int(vals["lmin"]),
        level_max=int(vals["lmax"]), feature_level=int(vals["lmax"]),
        n_layers=int(vals["nlay"]), location=loc)
    sf = cfdgen.surface_features_dict("body.stl")
    stl = cfdgen.ascii_stl("body", pts, facets)
    wri = max(1, int(int(vals["iters"]) / 5))
    casefiles, k0, om0 = cfdgen.flow_case_files(
        Ux, nu=nu, intensity=I, L=Lm, end_iter=int(vals["iters"]),
        write_interval=wri)
    outdir = _cfd_outdir()
    stage = os.path.join(outdir, name + "_src")
    try:
        _write_lf(os.path.join(stage, "blockMeshDict"), bm)
        _write_lf(os.path.join(stage, "snappyHexMeshDict"), sn)
        _write_lf(os.path.join(stage, "surfaceFeaturesDict"), sf)
        _write_lf(os.path.join(stage, "body.stl"), stl)
        for fn, txt in casefiles.items():
            _write_lf(os.path.join(stage, fn), txt)
    except Exception as e:
        err("Could not write the CFD case files to %s:\n%s" % (stage, e)); return
    of_env = str(vals.get("env") or cfd.DEFAULT_OF_ENV).strip()
    distro = str(vals.get("distro") or "").strip()  # blank => WSL default distro
    win_out = os.path.join(outdir, name)
    fs = cfdgen.build_flow_script({"of_env": of_env, "name": name,
                                   "stage_win": stage, "win_out": win_out,
                                   "latest": True})
    fpath = os.path.join(outdir, "run_flow_%s.sh" % name)
    try:
        _write_lf(fpath, fs)
    except Exception as e:
        err("Could not write the flow script:\n%s" % e); return
    flow_cmd = "bash %s" % cfd.win_to_wsl(fpath, distro)
    _cfd_record(FreeCAD.ActiveDocument, name, [
        ("Analysis", "Incompressible flow (RANS kOmegaSST)"),
        ("Geometry", getattr(obj, "Label", "body")),
        ("Inlet speed (m/s)", "%g (+X)" % Ux),
        ("Inlet k / omega", "%.4g / %.4g" % (k0, om0)),
        ("Viscosity nu", "%g" % nu),
        ("Background cells", "%d x %d x %d" % (nx, ny, nz)),
        ("Mesh", "snappyHexMesh, level %d-%d, %d layers"
         % (int(vals["lmin"]), int(vals["lmax"]), int(vals["nlay"]))),
        ("Run (paste in WSL)", flow_cmd),
        ("Then open in ParaView", os.path.join(win_out, "VTK")),
        ("Flow script", fpath), ("Staged files", stage)])
    # draw the setup on the part (domain box + BC-coloured faces + inlet arrows)
    try:
        _draw_cfd_domain(FreeCAD.ActiveDocument,
                         tuple(c * 1000.0 for c in dom), Ux, name)
        FreeCAD.ActiveDocument.recompute()
    except Exception:
        pass
    launch = ""
    if vals.get("run") == "Yes":
        launch = "\n\nAuto-run: " + _try_launch_terminal(cfd.wsl_run_argv(fs, distro))
    info("CFD flow case '%s' on '%s' (engine: OpenFOAM incompressibleFluid, as "
         "SimScale runs).\n\nInlet %g m/s (+X), kOmegaSST turbulence "
         "(k=%.4g, omega=%.4g), mesh %d x %d x %d background + snappyHexMesh. "
         "In your WSL OpenFOAM terminal:\n\n  %s\n\nIt meshes, solves (%d "
         "iterations) and writes VTK to:\n  %s\n\nOpen in ParaView and colour "
         "by U (velocity) or p (pressure). It is a steady RANS solve - watch "
         "the residuals fall in log.foamRun. Details in the 'CFD_%s' sheet.%s" %
         (name, getattr(obj, "Label", "body"), Ux, k0, om0, nx, ny, nz,
          flow_cmd, int(vals["iters"]), os.path.join(win_out, "VTK"), name,
          launch))


# ── SimScale-style docked CFD setup panel (FreeCAD Task panel) ──
# The CFD section -> which setup step (QGroupBox) each field belongs to, so the
# flat `fields` spec renders as a SimScale-style stack of setup steps in the dock.
_CFD_FLOW_SECTIONS = ("Geometry", "Boundary conditions", "Fluid properties",
                      "Mesh & refinement", "Simulation control", "Run")
_CFD_FLOW_KEY_SECTION = {
    "_i": "Geometry", "name": "Geometry",
    "_legend": "Boundary conditions", "U": "Boundary conditions",
    "ti": "Boundary conditions",
    "nu": "Fluid properties",
    "ncb": "Mesh & refinement", "lmin": "Mesh & refinement",
    "lmax": "Mesh & refinement", "nlay": "Mesh & refinement",
    "up": "Mesh & refinement", "down": "Mesh & refinement",
    "side": "Mesh & refinement", "top": "Mesh & refinement",
    "ground": "Mesh & refinement",
    "iters": "Simulation control",
    "distro": "Run", "env": "Run", "run": "Run",
}


def _cfd_make_widget(f):
    """Create a Qt input widget + value getter from a field spec (same kinds as
    form_dialog). Returns (widget, getter_or_None); info rows have no getter."""
    kind = f.get("kind", "text")
    if kind == "info":
        return QW.QLabel(str(f.get("default", ""))), None
    if kind == "combo":
        w = QW.QComboBox()
        opts = [str(x) for x in f.get("options", [])]
        w.addItems(opts)
        dv = f.get("default")
        if dv is not None and str(dv) in opts:
            w.setCurrentIndex(opts.index(str(dv)))
        return w, (lambda w=w: w.currentText())
    if kind in ("float", "int"):
        w = QW.QDoubleSpinBox() if kind == "float" else QW.QSpinBox()
        w.setMinimum(f.get("min", -1e12)); w.setMaximum(f.get("max", 1e12))
        if kind == "float":
            w.setDecimals(f.get("decimals", 3))
        w.setValue(f.get("default", 0))
        return w, (lambda w=w: w.value())
    w = QW.QLineEdit(str(f.get("default", "")))
    return w, (lambda w=w: w.text())


class _CfdFlowTaskPanel:
    """A docked FreeCAD Task panel for the incompressible-flow setup - the
    SimScale-style left-dock experience (stacked setup steps, colour-coded BC
    legend, themed) instead of a floating modal. OK runs the same validated
    pipeline as the modal path via _cfd_flow_execute."""

    def __init__(self, obj, pts, facets, bb, Lm, fields):
        self._obj = obj; self._pts = pts; self._facets = facets
        self._bb = bb; self._Lm = Lm
        self._getters = {}
        self.form = self._build(fields)

    def _build(self, fields):
        root = QW.QWidget(); root.setObjectName("cfdPanel")
        root.setWindowTitle("CFD Flow")
        if cfdui is not None:
            try:
                root.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "surface": "#2b313a", "text": "#e6edf3",
                "subtext": "#9aa7b4", "bg": "#21262d", "border": "#3a424d"})
        outer = QW.QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        # title banner (inline-styled so FreeCAD's global theme can't override it)
        banner = QW.QLabel("CFD Flow \u2013 Incompressible")
        banner.setStyleSheet(
            "background:%s; color:#ffffff; font-size:15px; font-weight:700; "
            "padding:8px 10px;" % pal["accent"])
        outer.addWidget(banner)
        sub = QW.QLabel("Wind / air around a solid \u2013 auto-mesh (snappyHexMesh), "
                        "auto-BCs, kOmegaSST RANS, VTK for ParaView.")
        sub.setWordWrap(True)
        sub.setStyleSheet("background:%s; color:%s; padding:6px 10px;"
                          % (pal["bg"], pal["subtext"]))
        outer.addWidget(sub)
        forms = {}
        for i, sec in enumerate(_CFD_FLOW_SECTIONS, 1):
            hdr = QW.QLabel("%d \u00b7 %s" % (i, sec))
            hdr.setStyleSheet(
                "background:%s; color:#ffffff; font-weight:600; font-size:12px; "
                "padding:5px 10px; margin-top:6px;" % pal["accent"])
            outer.addWidget(hdr)
            cont = QW.QWidget()
            cont.setStyleSheet("background:%s;" % pal["surface"])
            fl = QW.QFormLayout(cont)
            fl.setContentsMargins(12, 8, 12, 10); fl.setSpacing(6)
            forms[sec] = fl
            outer.addWidget(cont)
        for f in fields:
            k = f.get("key"); kind = f.get("kind", "text")
            sec = _CFD_FLOW_KEY_SECTION.get(k, "Mesh & refinement")
            fl = forms.get(sec, forms[_CFD_FLOW_SECTIONS[0]])
            w, getter = _cfd_make_widget(f)
            if kind == "info":
                w.setWordWrap(True)
                fl.addRow(w)
            else:
                fl.addRow(f.get("label", k or ""), w)
            if getter is not None:
                self._getters[k] = getter
        outer.addStretch(1)
        return root

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Ok | QW.QDialogButtonBox.Cancel)

    def isAllowedAlterDocument(self):
        return True

    def _collect(self):
        vals = {}
        for k, g in self._getters.items():
            try:
                vals[k] = g()
            except Exception:
                pass
        return vals

    def accept(self):
        vals = self._collect()
        try:
            _cfd_flow_execute(self._obj, self._pts, self._facets,
                              self._bb, self._Lm, vals)
        finally:
            _close_task_dialog()
        return True

    def reject(self):
        _close_task_dialog()
        return True


def _close_task_dialog():
    try:
        FreeCADGui.Control.closeDialog()
    except Exception:
        pass


def _show_cfd_flow_panel(obj, pts, facets, bb, Lm, fields):
    """Show the docked CFD-flow Task panel. Returns True if shown, False when the
    Task-panel control is unavailable (headless / another dialog open) so the
    caller falls back to the modal form."""
    return _cfd_dock(lambda: _CfdFlowTaskPanel(obj, pts, facets, bb, Lm, fields))


class _CfdStepTaskPanel:
    """Generic docked Task panel for one CFD setup step - the SimScale / Autodesk-
    CFD inline left-dock experience (a themed panel in the Tasks tab you can leave
    open while you orbit, zoom and click in the 3D view) instead of a floating
    modal pop-up that blocks everything. Renders the same `fields` spec as
    form_dialog and calls on_accept(vals) when you click OK, so every setup step
    shares one validated path."""

    def __init__(self, title, subtitle, fields, on_accept):
        self._title = title or "CFD"
        self._subtitle = subtitle or ""
        self._fields = fields or []
        self._on_accept = on_accept
        self._getters = {}
        self.form = self._build()

    def _build(self):
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "surface": "#2b313a", "subtext": "#9aa7b4",
                "bg": "#21262d"})
        root = QW.QWidget(); root.setObjectName("cfdPanel")
        root.setWindowTitle(self._title)
        if cfdui is not None:
            try:
                root.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        outer = QW.QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        banner = QW.QLabel(self._title)
        banner.setStyleSheet("background:%s; color:#ffffff; font-size:15px; "
                             "font-weight:700; padding:8px 10px;" % pal["accent"])
        outer.addWidget(banner)
        if self._subtitle:
            sub = QW.QLabel(self._subtitle); sub.setWordWrap(True)
            sub.setStyleSheet("background:%s; color:%s; padding:6px 10px;"
                              % (pal["bg"], pal["subtext"]))
            outer.addWidget(sub)
        cont = QW.QWidget()
        cont.setStyleSheet("background:%s;" % pal["surface"])
        fl = QW.QFormLayout(cont)
        fl.setContentsMargins(12, 10, 12, 12); fl.setSpacing(6)
        for f in self._fields:
            k = f.get("key"); kind = f.get("kind", "text")
            w, getter = _cfd_make_widget(f)
            if kind == "info":
                try:
                    w.setWordWrap(True)
                except Exception:
                    pass
                fl.addRow(w)
            else:
                fl.addRow(f.get("label", k or ""), w)
            if getter is not None:
                self._getters[k] = getter
        outer.addWidget(cont)
        outer.addStretch(1)
        return root

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Ok | QW.QDialogButtonBox.Cancel)

    def isAllowedAlterDocument(self):
        return True

    def _collect(self):
        vals = {}
        for k, g in self._getters.items():
            try:
                vals[k] = g()
            except Exception:
                pass
        return vals

    def accept(self):
        vals = self._collect()
        _close_task_dialog()
        try:
            if self._on_accept is not None:
                self._on_accept(vals)
        except Exception as e:
            err("Could not apply this step: %s" % e)
        return True

    def reject(self):
        _close_task_dialog()
        return True


def _cfd_show_step_panel(title, subtitle, fields, on_accept):
    """Show one setup step as a docked Task panel (SimScale-style). Falls back to
    the themed modal form only when the Task-panel control is unavailable (headless
    / another dialog already open), so both paths run the SAME on_accept. Always
    returns True - the step is handled here."""
    if _cfd_dock(lambda: _CfdStepTaskPanel(title, subtitle, fields, on_accept)):
        return True
    vals = form_dialog(title, fields, **_cfd_dialog_kwargs(title, subtitle))
    if vals:
        on_accept(vals)
    return True


class _CfdResultPanel:
    """Read-only docked panel that shows a run report (SimScale 'job finished'
    feel) instead of a modal pop-up. Close when done."""
    def __init__(self, title, text):
        self._title = title or "Result"
        self._text = text or ""
        self.form = self._build()

    def _build(self):
        w = QW.QWidget(); w.setObjectName("cfdPanel")
        w.setWindowTitle(self._title)
        pal = (cfdui.PALETTE if cfdui is not None else
               {"accent": "#17a2b8", "subtext": "#9aa7b4"})
        if cfdui is not None:
            try:
                w.setStyleSheet(cfdui.stylesheet())
            except Exception:
                pass
        lay = QW.QVBoxLayout(w)
        hdr = QW.QLabel(self._title)
        hdr.setStyleSheet("background:%s;color:#fff;font-weight:700;font-size:14px;"
                          "padding:7px 10px;" % pal["accent"])
        lay.addWidget(hdr)
        box = QW.QTextEdit(); box.setReadOnly(True); box.setPlainText(self._text)
        try:
            box.setStyleSheet("border:none;")
        except Exception:
            pass
        lay.addWidget(box)
        return w

    def getStandardButtons(self):
        return int(QW.QDialogButtonBox.Close)

    def isAllowedAlterDocument(self):
        return False

    def accept(self):
        _close_task_dialog(); return True

    def reject(self):
        _close_task_dialog(); return True


def _cfd_report(title, text):
    """Show a run report in a non-modal docked Task panel (SimScale feel). Falls
    back to a modal message box only when the Task control is unavailable
    (headless / tests), so both paths surface the same text."""
    if _cfd_dock(lambda: _CfdResultPanel(title, text)):
        return
    info(text)


class CfdFlow:
    def GetResources(self):
        return {"Pixmap": _icon("cfd_extflow"),
                "MenuText": "CFD Flow: wind / air (incompressible)",
                "ToolTip": "Full incompressible-flow CFD on a selected solid, end "
                           "to end: auto-mesh with snappyHexMesh, generate the "
                           "boundary conditions + turbulence (kOmegaSST) to match, "
                           "solve with OpenFOAM's incompressibleFluid, and convert "
                           "to VTK for ParaView. Same engine as SimScale. +X is "
                           "the flow direction; set the inlet speed in the dialog.",
                "Accel": "C, W"}

    def IsActive(self):
        return (cfd is not None and cfdgen is not None
                and FreeCAD.ActiveDocument is not None)

    def Activated(self):
        if cfd is None or cfdgen is None:
            err("The CFD modules (dynframe_cfd / dynframe_cfd_gen) failed to load.")
            return
        try:
            sel = [o for o in FreeCADGui.Selection.getSelection()
                   if getattr(o, "Shape", None) is not None]
        except Exception:
            sel = []
        if not sel:
            info("Select the solid the air flows around (or through), then run "
                 "CFD Flow.")
            return
        obj = sel[0]
        try:
            shp = global_shape(obj)
            mat = FreeCAD.Matrix(); mat.scale(1e-3, 1e-3, 1e-3)
            shp_m = shp.transformGeometry(mat)
            bb = shp_m.BoundBox
            Lm = max(bb.XLength, bb.YLength, bb.ZLength, 1e-6)
            verts, facets = shp_m.tessellate(max(Lm / 400.0, 1e-5))
            pts = [(v.x, v.y, v.z) for v in verts]
        except Exception as e:
            err("Could not tessellate '%s': %s" % (getattr(obj, "Label", "?"), e))
            return
        fields = [
            {"key": "_i", "kind": "info", "default":
             "Incompressible-flow CFD on '%s' (body ~%.3g x %.3g x %.3g m). +X is "
             "the flow direction. DynFrame meshes with snappyHexMesh, writes the "
             "matching boundary conditions + kOmegaSST turbulence, solves with "
             "incompressibleFluid and converts to VTK. Same engine as SimScale." %
             (getattr(obj, "Label", "body"), bb.XLength, bb.YLength, bb.ZLength)},
            {"key": "_legend", "kind": "info", "html": True,
             "default": (cfdui.bc_legend_html() if cfdui else "")},
            {"key": "name", "label": "Case name", "kind": "text", "default": "flow1"},
            {"key": "U", "label": "Inlet air speed Ux (m/s)", "kind": "float",
             "default": 10.0, "decimals": 3},
            {"key": "ti", "label": "Turbulence intensity (%)", "kind": "float",
             "default": 5.0, "decimals": 2},
            {"key": "nu", "label": "Kinematic viscosity nu (m2/s)", "kind": "float",
             "default": 1.5e-5, "decimals": 9},
            {"key": "iters", "label": "Iterations (steady)", "kind": "int",
             "default": 1000, "min": 50, "max": 100000},
            {"key": "ncb", "label": "Background cells across body", "kind": "int",
             "default": 8, "min": 2, "max": 200},
            {"key": "lmin", "label": "Surface refinement level min", "kind": "int",
             "default": 2, "min": 0, "max": 8},
            {"key": "lmax", "label": "Surface refinement level max", "kind": "int",
             "default": 4, "min": 0, "max": 9},
            {"key": "nlay", "label": "Boundary layers on the body", "kind": "int",
             "default": 3, "min": 0, "max": 20},
            {"key": "up", "label": "Upstream margin (x L)", "kind": "float", "default": 3.0},
            {"key": "down", "label": "Downstream margin (x L)", "kind": "float", "default": 6.0},
            {"key": "side", "label": "Side margin (x L)", "kind": "float", "default": 3.0},
            {"key": "top", "label": "Top margin (x L)", "kind": "float", "default": 3.0},
            {"key": "ground", "label": "Below margin (x L)", "kind": "float", "default": 3.0},
            {"key": "distro", "label": "WSL distro (blank = your default)", "kind": "text", "default": ""},
            {"key": "env", "label": "OpenFOAM env (source)", "kind": "text", "default": cfd.DEFAULT_OF_ENV},
            {"key": "run", "label": "Try to run now", "kind": "combo",
             "options": ["No", "Yes"], "default": "No"},
        ]
        # SimScale-style docked setup panel (FreeCAD's native left dock, the way
        # SimScale docks its simulation setup); fall back to a modal form when
        # the Task-panel control is unavailable (e.g. headless).
        if _show_cfd_flow_panel(obj, pts, facets, bb, Lm, fields):
            return
        vals = form_dialog("CFD Flow: wind / air (incompressible)", fields,
                           **_cfd_dialog_kwargs(
                               "CFD Flow - Incompressible",
                               "Wind / air around a solid: auto-mesh, auto-BCs, "
                               "kOmegaSST RANS solve, VTK for ParaView."))
        if not vals:
            return
        _cfd_flow_execute(obj, pts, facets, bb, Lm, vals)


class Envelope:
    def GetResources(self):
        return {"Pixmap": _icon("envelope"), "MenuText": "Envelope (all combinations)",
                "ToolTip": "Solve every load combination and keep the worst N, My, "
                           "Mz and utilisation per member - the design envelope. The "
                           "envelope forces are stored so a following code check uses "
                           "them.", "Accel": "A, O"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        combos = _combos(doc)
        if not combos:
            info("No combinations defined. Create them with 'Load Combinations' "
                 "first, then run the envelope.")
            return
        bars = [o for o in doc.Objects if is_analysis_elem(o)]
        env = {}
        for (cn, cd) in combos:
            RunAnalysis().Activated(run_pick="Combo: " + cn, include_sw=True)
            for o in bars:
                if not hasattr(o, "ResN"):
                    continue
                e = env.setdefault(o.Name, {"label": str(o.Label),
                                            "sec": _elem_section(o), "Nc": 0.0,
                                            "Nt": 0.0, "My": 0.0, "Mz": 0.0, "util": 0.0})
                N = getattr(o, "ResN", 0.0)
                e["Nc"] = min(e["Nc"], N); e["Nt"] = max(e["Nt"], N)
                e["My"] = max(e["My"], getattr(o, "ResMy", 0.0))
                e["Mz"] = max(e["Mz"], getattr(o, "ResMz", 0.0))
                e["util"] = max(e["util"], getattr(o, "ResUtil", 0.0))
        if not env:
            info("No results - check that members have sections and loads.")
            return
        doc.openTransaction("DynFrame: envelope")
        worst = 0.0; wn = "-"
        for o in bars:
            e = env.get(o.Name)
            if e is None:
                continue
            # store the governing envelope forces so a code check uses them
            Ngov = e["Nc"] if abs(e["Nc"]) >= abs(e["Nt"]) else e["Nt"]
            _set(o, "App::PropertyFloat", "ResN", float(Ngov))
            _set(o, "App::PropertyFloat", "ResMy", float(e["My"]))
            _set(o, "App::PropertyFloat", "ResMz", float(e["Mz"]))
            _set(o, "App::PropertyFloat", "ResUtil", float(e["util"]))
            if e["util"] > worst:
                worst = e["util"]; wn = e["label"]
            try:
                uc = max(0.0, min(1.0, e["util"]))
                o.ViewObject.LineColor = (float(uc), float(1.0 - uc), 0.1)
                o.ViewObject.LineWidth = 4
            except Exception:
                pass
        try:
            sh = doc.getObject("Envelope") or doc.addObject("Spreadsheet::Sheet", "Envelope")
            sh.Label = "Envelope"; sh.clearAll()
            sh.set("A1", "ENVELOPE - worst across %d combination(s)" % len(combos))
            for c, h in zip("ABCDEFG", ["Member", "Section", "N comp (N)", "N tens (N)",
                                        "max|My| (N.mm)", "max|Mz| (N.mm)", "max Util"]):
                sh.set("%s2" % c, h)
            r = 3
            for nm, e in env.items():
                sh.set("A%d" % r, e["label"]); sh.set("B%d" % r, e["sec"])
                sh.set("C%d" % r, "%.1f" % e["Nc"]); sh.set("D%d" % r, "%.1f" % e["Nt"])
                sh.set("E%d" % r, "%.0f" % e["My"]); sh.set("F%d" % r, "%.0f" % e["Mz"])
                sh.set("G%d" % r, "%.2f" % e["util"]); r += 1
            _grp(doc, RES_GROUP).addObject(sh)
        except Exception as ex:
            FreeCAD.Console.PrintError("DynFrame: envelope table failed (%s)\n" % ex)
        doc.commitTransaction(); doc.recompute()
        info("Envelope complete over %d combination(s).\n\nWorst utilisation: %.2f "
             "(on %s)\n\nPer-member worst N / My / Mz / utilisation in the "
             "'Envelope' table; the envelope forces are now stored, so 'Steel Code "
             "Check' uses them. (The 3D view shows the last combination's result.)"
             % (len(combos), worst, wn))


def _frame_stiffness(doc):
    """Assemble the bare frame (bars only - no loads) into its global stiffness
    K plus the element data and fixed-DOF set, for repeated solves at many load
    positions (moving-load / influence analysis). Member releases, plates,
    springs and settlement are not included here - this is the clean live-load
    carrier model."""
    import numpy as np
    objs, _k = _analysis_objs(doc)
    nodes = []

    def nid(p, make=True):
        for i, q in enumerate(nodes):
            if q.distanceToPoint(p) <= 1.0:
                return i
        if not make:
            return -1
        nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

    elems = []
    for o in objs:
        sp = _section_props_from_name(_elem_section(o))
        if sp is None:
            continue
        A, Iy, Iz, J, c = sp
        s, e = _elem_ends(o)
        n1, n2 = nid(s), nid(e)
        if n1 == n2:
            continue
        E, G, Fy, rho = _material(_elem_material(o))
        T, L = _beam_T(nodes[n1], nodes[n2])
        kl = _beam_k_local(E, G, A, Iy, Iz, J, L)
        dofs = [6 * n1 + i for i in range(6)] + [6 * n2 + i for i in range(6)]
        elems.append({"o": o, "n1": n1, "n2": n2, "A": A, "Iy": Iy, "Iz": Iz,
                      "J": J, "c": c, "E": E, "G": G, "Fy": Fy,
                      "sec": _elem_section(o), "T": T, "L": L, "kl": kl,
                      "dofs": dofs})
    ndof = 6 * len(nodes)
    K = np.zeros((ndof, ndof))
    for el in elems:
        K[np.ix_(el["dofs"], el["dofs"])] += el["T"].T @ el["kl"] @ el["T"]
    fixed = set(); sup = []
    for o in doc.Objects:
        r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
        if r and at is not None:
            i = nid(FreeCAD.Vector(at), make=False)
            if i >= 0:
                sup.append(i)
                for k, ch in enumerate(str(r)):
                    if ch == "1":
                        fixed.add(6 * i + k)
    return nodes, elems, K, fixed, sup


def _storey_levels(zs, tol=1.0):
    """Distinct storey elevations (sorted) from a list of node Z coordinates,
    merging levels within `tol`."""
    levels = []
    for z in zs:
        if not any(abs(z - L) <= tol for L in levels):
            levels.append(float(z))
    levels.sort()
    return levels


def _response_spectrum(ts, ag, zeta, periods):
    """Elastic response spectrum of a ground-acceleration record ag(t) (in
    mm/s^2 at times ts) for the given damping ratio: for each natural period T
    a unit-mass SDOF (w=2pi/T) is integrated under -ag(t) by Newmark, and its
    peak relative displacement Sd and pseudo-acceleration Sa = w^2 Sd are
    returned. Lists (Sd, Sa) aligned with `periods` (all in mm, mm/s^2)."""
    import numpy as np
    ts = np.asarray(ts, float); ag = np.asarray(ag, float)
    t0, t1 = ts[0], ts[-1]
    rec_dt = (t1 - t0) / (len(ts) - 1) if len(ts) > 1 else 0.01
    beta = 0.25; gamma = 0.5
    Sd = []; Sa = []
    for T in periods:
        w = 2.0 * np.pi / T if T > 1e-9 else 1e9
        dt = min(rec_dt, T / 15.0)
        n = max(2, int(np.ceil((t1 - t0) / dt)))
        dt = (t1 - t0) / n
        grid = t0 + dt * np.arange(n + 1)
        a_g = np.interp(grid, ts, ag, left=0.0, right=0.0)
        c = 2.0 * zeta * w; k = w * w
        a0 = 1.0 / (beta * dt * dt); a1 = gamma / (beta * dt)
        a2 = 1.0 / (beta * dt); a3 = 1.0 / (2 * beta) - 1.0
        a4 = gamma / beta - 1.0; a5 = dt * (gamma / (2 * beta) - 1.0)
        khat = k + a0 + a1 * c
        q = 0.0; v = 0.0; acc = -a_g[0]           # m=1
        peak = 0.0
        for i in range(n):
            p1 = -a_g[i + 1] + (a0 * q + a2 * v + a3 * acc) \
                + c * (a1 * q + a4 * v + a5 * acc)
            q1 = p1 / khat
            acc1 = a0 * (q1 - q) - a2 * v - a3 * acc
            v1 = v + dt * ((1 - gamma) * acc + gamma * acc1)
            q, v, acc = q1, v1, acc1
            if abs(q) > peak:
                peak = abs(q)
        Sd.append(peak); Sa.append(w * w * peak)
    return Sd, Sa


def _frame_fine_MK(doc, nsub=4):
    """Assemble the frame's global stiffness K and consistent mass M on a mesh
    that subdivides each bar into `nsub` sub-elements (the coarse support nodes
    keep their indices), for modal / time-history dynamics. Returns
    (coarse_nodes, fine_nodes, K, M, fixed, sup). Mass density is converted to
    tonne/mm^3 (N-mm-tonne-s), so frequencies come out in Hz."""
    import numpy as np
    objs, _k = _analysis_objs(doc)
    nodes = []

    def nid(p, make=True):
        for i, q in enumerate(nodes):
            if q.distanceToPoint(p) <= 1.0:
                return i
        if not make:
            return -1
        nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

    bars = []
    for o in objs:
        sp = _section_props_from_name(_elem_section(o))
        if sp is None:
            continue
        A, Iy, Iz, J, c = sp
        s, e = _elem_ends(o)
        n1, n2 = nid(s), nid(e)
        if n1 == n2:
            continue
        E, G, Fy, rho = _material(_elem_material(o))
        bars.append({"n1": n1, "n2": n2, "A": A, "Iy": Iy, "Iz": Iz, "J": J,
                     "E": E, "G": G, "rho": rho})
    fixed = set(); sup = []
    for o in doc.Objects:
        r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
        if r and at is not None:
            i = nid(FreeCAD.Vector(at), make=False)
            if i >= 0:
                sup.append(i)
                for k, ch in enumerate(str(r)):
                    if ch == "1":
                        fixed.add(6 * i + k)
    fine = [FreeCAD.Vector(p) for p in nodes]

    def fid(p):
        for i, q in enumerate(fine):
            if q.distanceToPoint(p) <= 0.5:
                return i
        fine.append(FreeCAD.Vector(p)); return len(fine) - 1

    subel = []
    for b in bars:
        p1 = nodes[b["n1"]]; p2 = nodes[b["n2"]]; prev = b["n1"]
        for s in range(1, nsub + 1):
            pt = p1 + vscale(p2 - p1, s / float(nsub))
            cur = b["n2"] if s == nsub else fid(pt)
            subel.append((prev, cur, b)); prev = cur
    ndof = 6 * len(fine)
    K = np.zeros((ndof, ndof)); M = np.zeros((ndof, ndof))
    for (a, bidx, b) in subel:
        T, L = _beam_T(fine[a], fine[bidx])
        kl = _beam_k_local(b["E"], b["G"], b["A"], b["Iy"], b["Iz"], b["J"], L)
        ml = _beam_mass_local(b["rho"] * 1e-3, b["A"], b["J"], L)   # kg->tonne
        dofs = [6 * a + i for i in range(6)] + [6 * bidx + i for i in range(6)]
        ix = np.ix_(dofs, dofs)
        K[ix] += T.T @ kl @ T; M[ix] += T.T @ ml @ T
    return nodes, fine, K, M, fixed, sup


def _pt_samples(el, u, pts_local, NS=10):
    """Member force samples (N, Vy, Vz, Mx, My, Mz, Stress) along `el` under a
    set of point loads (local components, distance a from node i), from the
    nodal displacements u. Same free-body recovery as the main solver, point
    loads only. Returns (dict kind -> list[NS+1], end-force vector)."""
    import numpy as np
    L = el["L"]; dloc = el["T"] @ u[el["dofs"]]
    fef = np.zeros(12)
    for (px, py, pz, a) in pts_local:
        fef = fef + _fef_point_local(px, py, pz, L, a)
    fend = el["kl"] @ dloc - fef
    A = el["A"]; c = el["c"]; Imin = min(el["Iy"], el["Iz"])

    def crossed(ci, x):
        return sum((px, py, pz)[ci] * (1.0 if x >= a else 0.0)
                   for (px, py, pz, a) in pts_local)

    def free_m(ci, x):
        m = 0.0
        for (px, py, pz, a) in pts_local:
            P = (px, py, pz)[ci]
            m += P * ((L - a) * x / L if x <= a else a * (L - x) / L)
        return m

    out = {}
    for kind in DIAG_KINDS:
        vals = []
        for sidx in range(NS + 1):
            x = L * sidx / NS
            if kind == "N":
                v = -(fend[0] + crossed(0, x))
            elif kind == "Vy":
                v = fend[1] + crossed(1, x)
            elif kind == "Vz":
                v = fend[2] + crossed(2, x)
            elif kind == "Mx":
                v = -fend[3]
            elif kind == "My":
                v = fend[4] * (1 - x / L) - fend[10] * (x / L) - free_m(2, x)
            elif kind == "Mz":
                v = -fend[5] * (1 - x / L) + fend[11] * (x / L) - free_m(1, x)
            else:
                myx = fend[4] * (1 - x / L) - fend[10] * (x / L) - free_m(2, x)
                mzx = -fend[5] * (1 - x / L) + fend[11] * (x / L) - free_m(1, x)
                nx = -(fend[0] + crossed(0, x))
                mm = (myx * myx + mzx * mzx) ** 0.5
                v = abs(nx) / A + (mm * c / Imin if Imin > 1e-9 else 0.0)
            vals.append(v)
        out[kind] = vals
    return out, fend


class MovingLoad:
    _DIRS = {"-Z (gravity)": (0.0, 0.0, -1.0), "+Z": (0.0, 0.0, 1.0),
             "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
             "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}

    def GetResources(self):
        return {"Pixmap": _icon("moving"), "MenuText": "Moving Load Envelope",
                "ToolTip": "Step a point load along the selected lane members and "
                           "envelope the worst member forces at every position - a "
                           "bridge/crane influence analysis. Stores the envelope so "
                           "the Steel Code Check runs against it.", "Accel": "A, L"}

    def IsActive(self):
        return bool(selected_elems())

    def Activated(self):
        import numpy as np
        lane = [m for m in selected_elems() if is_bar(m)]
        if not lane:
            info("Select the lane members - the path the moving load travels "
                 "along (e.g. a bridge girder or crane runway) - then run it.")
            return
        doc = FreeCAD.ActiveDocument
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Moving Load Envelope (%d lane member(s))" % len(lane), [
            {"key": "_i", "kind": "info", "default":
             "A load pattern (one point load, or a train of equally-spaced axles) "
             "is stepped along the selected lane and the model solved at each "
             "position; the worst force at every section is kept (the influence "
             "envelope). Set axles > 1 for a vehicle/train (load = per axle). "
             "Member releases are not applied in this live-load carrier model. The "
             "envelope forces are stored, so a following Steel Code Check uses them."},
            {"key": "P", "label": "Load per axle P (N)", "kind": "float",
             "default": 100000.0},
            {"key": "dir", "label": "Direction", "kind": "combo",
             "options": list(self._DIRS.keys()), "default": "-Z (gravity)"},
            {"key": "naxle", "label": "Number of axles", "kind": "int",
             "default": 1, "min": 1, "max": 50},
            {"key": "spacing", "label": "Axle spacing (mm)", "kind": "float",
             "default": 1500.0},
            {"key": "nsta", "label": "Positions (lead-axle steps)", "kind": "int",
             "default": 41, "min": 2, "max": 400},
        ])
        if not vals:
            return
        Pmag = abs(float(vals["P"]))
        d = self._DIRS.get(vals["dir"], (0.0, 0.0, -1.0))
        Pvec = np.array(d, float) * Pmag
        NSTA = int(vals["nsta"])
        naxle = max(1, int(vals["naxle"])); spacing = abs(float(vals["spacing"]))

        nodes, elems, K, fixed, sup = _frame_stiffness(doc)
        if not elems:
            info("Could not build a frame model (check bar sections)."); return
        if not fixed:
            err("No supports defined. Add supports, then run the moving load."); return
        ndof = 6 * len(nodes); free = [i for i in range(ndof) if i not in fixed]
        try:
            Kinv = np.linalg.inv(K[np.ix_(free, free)])
        except Exception:
            err("The structure is unstable (a mechanism) with the supports given.")
            return
        by_name = {el["o"].Name: el for el in elems}
        laneels = [by_name[m.Name] for m in lane if m.Name in by_name]
        if not laneels:
            info("The selected lane members are not part of the analysis model."); return

        # order the lane along its dominant axis; record each member's start point
        pts = []
        for el in laneels:
            pts += [nodes[el["n1"]], nodes[el["n2"]]]
        far1 = pts[0]; far2 = pts[0]; best = -1.0
        for a in pts:
            for b in pts:
                dd = a.distanceToPoint(b)
                if dd > best:
                    best = dd; far1, far2 = a, b
        axis = far2 - far1
        axis = unit(axis) if axis.Length > 1e-9 else FreeCAD.Vector(1, 0, 0)

        def proj(p):
            return (p - far1).x * axis.x + (p - far1).y * axis.y + (p - far1).z * axis.z
        ordered = sorted(laneels, key=lambda el: 0.5 * (proj(nodes[el["n1"]])
                                                        + proj(nodes[el["n2"]])))
        seq = []   # (element, flip) flip=True means lane runs n2->n1
        for el in ordered:
            seq.append((el, proj(nodes[el["n1"]]) > proj(nodes[el["n2"]])))
        total = sum(el["L"] for el in ordered) or 1.0

        def station_arc(arc):           # arc length along lane -> (element, a-from-n1)
            target = max(0.0, min(total, arc)); cum = 0.0
            for (el, flip) in seq:
                if target <= cum + el["L"] + 1e-9:
                    lp = max(0.0, min(1.0, (target - cum) / el["L"]))
                    a = (1.0 - lp) * el["L"] if flip else lp * el["L"]
                    return el, a
                cum += el["L"]
            el, flip = seq[-1]
            return el, (0.0 if flip else el["L"])

        NS = 10
        sampabs = {id(el): {k: [0.0] * (NS + 1) for k in DIAG_KINDS} for el in elems}
        nrange = {id(el): [0.0, 0.0] for el in elems}      # [min N, max N] signed
        peak_my = 0.0; u_gov = np.zeros(ndof)
        # sweep the lead axle so the whole train passes across the lane
        sweep = total + (naxle - 1) * spacing
        for j in range(NSTA):
            lead = sweep * (j / float(NSTA - 1)) if NSTA > 1 else 0.0
            F = np.zeros(ndof); member_pts = {}
            for ax in range(naxle):
                arc = lead - ax * spacing
                if arc < -1e-6 or arc > total + 1e-6:
                    continue                       # this axle is off the lane
                el, a = station_arc(arc)
                Pl = el["T"][0:3, 0:3] @ Pvec
                plt = (float(Pl[0]), float(Pl[1]), float(Pl[2]), a)
                F[el["dofs"]] += el["T"].T @ _fef_point_local(plt[0], plt[1], plt[2],
                                                              el["L"], a)
                member_pts.setdefault(id(el), []).append(plt)
            if not member_pts:                     # no axle on the lane yet
                continue
            u = np.zeros(ndof); u[free] = Kinv @ F[free]
            for el in elems:
                ptl = member_pts.get(id(el), [])
                samp, fend = _pt_samples(el, u, ptl, NS)
                sa = sampabs[id(el)]
                for k in DIAG_KINDS:
                    row = samp[k]
                    for sidx in range(NS + 1):
                        av = abs(row[sidx])
                        if av > sa[k][sidx]:
                            sa[k][sidx] = av
                nn = -fend[0]
                nr = nrange[id(el)]
                nr[0] = min(nr[0], nn); nr[1] = max(nr[1], nn)
                mymax = max(abs(v) for v in samp["My"])
                if mymax > peak_my:
                    peak_my = mymax; u_gov = u.copy()

        # assemble the envelope result (abs-max per station) + peaks, store Res*
        comp_max = {k: 0.0 for k in DIAG_KINDS}
        for el in elems:
            el["samp"] = {k: list(sampabs[id(el)][k]) for k in DIAG_KINDS}
            for k in DIAG_KINDS:
                comp_max[k] = max(comp_max[k], max(el["samp"][k]))
            o = el["o"]; nr = nrange[id(el)]
            ngov = nr[0] if abs(nr[0]) >= abs(nr[1]) else nr[1]
            try:
                _set(o, "App::PropertyFloat", "ResN", float(ngov))
                _set(o, "App::PropertyFloat", "ResMy", float(max(el["samp"]["My"])))
                _set(o, "App::PropertyFloat", "ResMz", float(max(el["samp"]["Mz"])))
                _set(o, "App::PropertyFloat", "ResVy", float(max(el["samp"]["Vy"])))
                _set(o, "App::PropertyFloat", "ResVz", float(max(el["samp"]["Vz"])))
                _set(o, "App::PropertyFloat", "ResUtil",
                     float(max(el["samp"]["Stress"]) / el["Fy"]) if el["Fy"] > 0 else 0.0)
            except Exception:
                pass

        # render the moment envelope through the normal results path
        doc.openTransaction("DynFrame: moving load")
        for o in list(doc.Objects):
            if getattr(o, "DiagKind", None) is not None \
                    or o.Name.startswith(("Diagram_", "Result_", "DeformedShape",
                                          "Legend", "ResultPeak")):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        rg = _grp(doc, RES_GROUP)
        msize = _model_size([el["o"] for el in elems])
        _, maxoff = _deformed_points(nodes, u_gov,
                                     [(el["n1"], el["n2"]) for el in elems], 0.0)
        comp_max["Disp"] = maxoff
        dscale = (0.08 * msize / maxoff) if maxoff > 1e-9 else 1.0
        train = ("%d axle(s) x %.0f N @ %.0f mm" % (naxle, Pmag, spacing)
                 if naxle > 1 else "%.0f N" % Pmag)
        _store_analysis_state(doc, nodes, u_gov, elems, dscale, msize,
                              _tube_radius(msize),
                              "Moving load %s %s" % (vals["dir"], train), comp_max)
        doc.commitTransaction()
        _render_result(doc, "My", scale_mult=1.0)

        # envelope table
        try:
            sh = doc.getObject("MovingEnvelope") or \
                doc.addObject("Spreadsheet::Sheet", "MovingEnvelope")
            sh.Label = "MovingEnvelope"; sh.clearAll()
            sh.set("A1", "MOVING LOAD ENVELOPE - %s %s, %d positions"
                   % (train, vals["dir"], NSTA))
            for c, h in zip("ABCDEF", ["Member", "Section", "max|My| (N.mm)",
                                       "max|Mz| (N.mm)", "max|Vz| (N)", "N range (N)"]):
                sh.set("%s2" % c, h)
            r = 3
            for el in elems:
                o = el["o"]; nr = nrange[id(el)]
                row = [str(o.Label), el["sec"], "%.0f" % max(el["samp"]["My"]),
                       "%.0f" % max(el["samp"]["Mz"]), "%.0f" % max(el["samp"]["Vz"]),
                       "%.0f .. %.0f" % (nr[0], nr[1])]
                for c, v in zip("ABCDEF", row):
                    sh.set("%s%d" % (c, r), v)
                r += 1
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
        except Exception as ex:
            FreeCAD.Console.PrintError("DynFrame: moving env table failed (%s)\n" % ex)
        doc.recompute()
        info("Moving load envelope done: %s %s stepped over %d positions on a "
             "%d-member lane.\n\nPeak |My| anywhere = %.0f N.mm; showing the My "
             "envelope (worst moment at every section) with the deformed shape at "
             "the governing position. Per-member worst forces are in the "
             "'MovingEnvelope' table, and the envelope is stored so 'Steel Code "
             "Check' verifies against it."
             % (train, vals["dir"], NSTA, len(laneels), comp_max["My"]))


def _parse_motion(text, fmt="Auto", dt=0.02):
    """Parse a ground-motion file's text into (times, accels). Formats:
    'PEER .AT2' (a header line with NPTS=.. DT=.. then whitespace accel values,
    time = i*DT), 'CSV time,accel' (two numeric columns), 'CSV accel-only' (one
    column, time = i*dt), or 'Auto' to detect. Returns (times, accels) or None."""
    import re
    lines = text.splitlines(); low = text.lower()

    def floats(s):
        return [float(x) for x in
                re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', s)]
    is_at2 = ("npts" in low and "dt" in low)
    if fmt.startswith("PEER") or (fmt == "Auto" and is_at2):
        dtv = None; data_start = 0
        for n, ln in enumerate(lines):
            l2 = ln.lower()
            if "npts" in l2 and "dt" in l2:
                m = re.search(r'dt\s*=?\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', l2)
                if m:
                    dtv = float(m.group(1))
                data_start = n + 1; break
        if dtv is None:
            dtv = dt
        acc = []
        for ln in lines[data_start:]:
            acc += floats(ln)
        if not acc:
            return None
        return [i * dtv for i in range(len(acc))], acc
    rows = [floats(ln) for ln in lines]
    rows = [r for r in rows if r]
    if not rows:
        return None
    ncol = max(len(r) for r in rows)
    if fmt.startswith("CSV accel") or (fmt == "Auto" and ncol < 2):
        acc = [r[0] for r in rows]
        return [i * dt for i in range(len(acc))], acc
    ts = [r[0] for r in rows if len(r) >= 2]
    acc = [r[1] for r in rows if len(r) >= 2]
    if len(ts) < 2:
        return None
    return ts, acc


def _read_record(doc, name):
    """Read an acceleration (or force) time-series from a spreadsheet: column A
    = time (s), column B = value. A non-numeric first row (a header) is skipped;
    reading stops at the first empty time cell. Returns (times, values) or None.
    This is how a real earthquake record (e.g. El Centro) is driven in - paste
    the two columns into a sheet and name it."""
    sh = doc.getObject(name)
    if sh is None:
        for o in doc.Objects:
            if getattr(o, "TypeId", "") == "Spreadsheet::Sheet" \
                    and getattr(o, "Label", "") == name:
                sh = o; break
    if sh is None:
        return None

    def cell(addr):
        try:
            return sh.get(addr)
        except Exception:
            return None
    ts = []; vs = []; r = 1
    while r < 500000:
        a = cell("A%d" % r); b = cell("B%d" % r)
        if a is None and b is None:
            break
        try:
            ts.append(float(a)); vs.append(float(b))
        except Exception:
            pass                               # header / non-numeric -> skip
        r += 1
    if len(ts) < 2:
        return None
    return ts, vs


class ImportGroundMotion:
    def GetResources(self):
        return {"Pixmap": _icon("import"), "MenuText": "Import Ground Motion",
                "ToolTip": "Read an earthquake accelerogram (PEER .AT2, or a CSV of "
                           "time,accel or accel-only) from a file into a spreadsheet "
                           "(time | acceleration), ready for the Time-History "
                           "analysis.", "Accel": "A, J"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        vals = form_dialog("Import Ground Motion", [
            {"key": "_i", "kind": "info", "default":
             "Reads a ground-motion file into a spreadsheet (column A = time s, "
             "column B = acceleration) that the Time-History analysis can use. "
             "PEER .AT2 files carry their own time step; a CSV can be two columns "
             "(time, accel) or one column (accel) with the time step below."},
            {"key": "path", "label": "File path (blank = browse)", "kind": "text",
             "default": ""},
            {"key": "fmt", "label": "Format", "kind": "combo",
             "options": ["Auto", "PEER .AT2", "CSV time,accel", "CSV accel-only"],
             "default": "Auto"},
            {"key": "dt", "label": "Time step dt (accel-only CSV, s)",
             "kind": "float", "default": 0.02, "decimals": 5},
            {"key": "sheet", "label": "Target sheet name", "kind": "text",
             "default": "GroundMotion"},
        ])
        if not vals:
            return
        path = str(vals.get("path", "")).strip()
        if not path:
            try:
                from PySide import QtGui as _QtG
                path = _QtG.QFileDialog.getOpenFileName(_mw(),
                                                        "Open ground-motion file")[0]
            except Exception:
                path = ""
        if not path:
            info("No file chosen."); return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except Exception as e:
            err("Could not read '%s': %s" % (path, e)); return
        rec = _parse_motion(text, str(vals.get("fmt", "Auto")),
                            max(1e-5, float(vals.get("dt", 0.02))))
        if rec is None or len(rec[0]) < 2:
            err("Could not parse a time series from the file (try a specific "
                "format, or check the file has numeric columns)."); return
        ts, acc = rec
        name = str(vals.get("sheet", "GroundMotion")).strip() or "GroundMotion"
        doc.openTransaction("DynFrame: import ground motion")
        try:
            sh = doc.getObject(name) or doc.addObject("Spreadsheet::Sheet", name)
            sh.Label = name; sh.clearAll()
            sh.set("A1", "time (s)"); sh.set("B1", "accel")
            nmax = min(len(ts), 20000)
            for i in range(nmax):
                sh.set("A%d" % (i + 2), "%.6g" % ts[i])
                sh.set("B%d" % (i + 2), "%.6g" % acc[i])
            _grp(doc, RES_GROUP).addObject(sh)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Writing the sheet failed: %s" % e); return
        pga = max(abs(a) for a in acc)
        dtv = (ts[1] - ts[0]) if len(ts) > 1 else 0.0
        info("Imported %d points into sheet '%s'.\n\nDuration %.3f s, dt ~ %.4g s, "
             "peak |accel| = %.4g (in the file's units).\n\nRun Time-History, pick "
             "'Record (spreadsheet)' and this sheet (set the record unit to match "
             "the file - .AT2 files are in g)." %
             (len(ts), name, ts[-1], dtv, pga))


class GMSpectrum:
    def GetResources(self):
        return {"Pixmap": _icon("spectrum"), "MenuText": "Ground-Motion Spectrum",
                "ToolTip": "Elastic response spectrum (Sd, Sa) of a recorded "
                           "accelerogram in a spreadsheet: a unit SDOF is run over a "
                           "range of periods to get the peak response per period. "
                           "The classic Sa-vs-T plot for comparing a record to the "
                           "code spectrum.", "Accel": "A, Q"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        vals = form_dialog("Ground-Motion Response Spectrum", [
            {"key": "_i", "kind": "info", "default":
             "Reads an accelerogram from a spreadsheet (column A = time, column "
             "B = accel) and builds its elastic response spectrum: the peak SDOF "
             "response at each natural period. Sa = pseudo-acceleration, Sd = "
             "spectral displacement."},
            {"key": "sheet", "label": "Record sheet", "kind": "text",
             "default": "GroundMotion"},
            {"key": "unit", "label": "Record unit (accel)", "kind": "combo",
             "options": ["g", "m/s2", "mm/s2"], "default": "g"},
            {"key": "zeta", "label": "Damping ratio zeta", "kind": "float",
             "default": 0.05, "decimals": 4},
            {"key": "tmax", "label": "Max period T (s)", "kind": "float", "default": 4.0},
            {"key": "nt", "label": "Number of periods", "kind": "int",
             "default": 60, "min": 5, "max": 400},
        ])
        if not vals:
            return
        rec = _read_record(doc, str(vals.get("sheet", "GroundMotion")).strip())
        if rec is None:
            info("Record sheet '%s' not found (need column A = time, column B = "
                 "accel)." % vals.get("sheet", "GroundMotion")); return
        uf = {"g": 9810.0, "m/s2": 1000.0, "mm/s2": 1.0}.get(
            str(vals.get("unit", "g")), 9810.0)
        ts = rec[0]; ag = [a * uf for a in rec[1]]              # -> mm/s^2
        zeta = max(0.0, float(vals["zeta"])); tmax = max(0.1, float(vals["tmax"]))
        nt = max(5, int(vals["nt"]))
        periods = [0.04 + (tmax - 0.04) * i / (nt - 1) for i in range(nt)]
        Sd, Sa = _response_spectrum(ts, ag, zeta, periods)
        imax = max(range(nt), key=lambda i: Sa[i]); pga = max(abs(a) for a in ag)
        doc.openTransaction("DynFrame: ground-motion spectrum")
        try:
            sh = doc.getObject("GMSpectrum") or \
                doc.addObject("Spreadsheet::Sheet", "GMSpectrum")
            sh.Label = "GMSpectrum"; sh.clearAll()
            sh.set("A1", "RESPONSE SPECTRUM of '%s' (zeta=%.3f); PGA=%.4g g"
                   % (vals.get("sheet", "GroundMotion"), zeta, pga / 9810.0))
            for c, h in zip("ABCD", ["T (s)", "Sd (mm)", "Sa (mm/s2)", "Sa (g)"]):
                sh.set("%s2" % c, h)
            for i in range(nt):
                sh.set("A%d" % (i + 3), "%.4g" % periods[i])
                sh.set("B%d" % (i + 3), "%.5g" % Sd[i])
                sh.set("C%d" % (i + 3), "%.5g" % Sa[i])
                sh.set("D%d" % (i + 3), "%.4g" % (Sa[i] / 9810.0))
            _grp(doc, RES_GROUP).addObject(sh)
            doc.commitTransaction(); doc.recompute()
        except Exception as e:
            doc.abortTransaction(); err("Spectrum failed: %s" % e); return
        info("Response spectrum of '%s' (zeta = %.3f) built over %d periods to "
             "%.2f s.\n\nPGA = %.4g g. Peak Sa = %.4g g at T = %.3f s (Sd = "
             "%.3g mm).\n\nSee the 'GMSpectrum' table (T, Sd, Sa). Compare its "
             "shape to the EC8 design spectrum used in Response Spectrum." %
             (vals.get("sheet", "GroundMotion"), zeta, nt, tmax, pga / 9810.0,
              Sa[imax] / 9810.0, periods[imax], Sd[imax]))


class TimeHistory:
    _DIRS = {"+X": (1.0, 0.0, 0.0, 0), "-X": (-1.0, 0.0, 0.0, 0),
             "+Y": (0.0, 1.0, 0.0, 1), "-Y": (0.0, -1.0, 0.0, 1),
             "+Z": (0.0, 0.0, 1.0, 2), "-Z": (0.0, 0.0, -1.0, 2)}

    def GetResources(self):
        return {"Pixmap": _icon("timehist"), "MenuText": "Time-History (dynamic)",
                "ToolTip": "Transient dynamic response by Newmark-beta direct "
                           "integration: a nodal force or a ground acceleration "
                           "(seismic) with a step / harmonic / pulse time function, "
                           "Rayleigh damping. Reports the peak response, base shear "
                           "and the monitored-node time history.", "Accel": "A, H"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        sel_pts = _sel_support_points(doc)
        coarse, fine, K, M, fixed, sup = _frame_fine_MK(doc)
        if not fine or 6 * len(fine) == 0:
            info("No frame model found - build bars and supports first."); return
        if not fixed:
            err("No supports defined. Add supports, then run the time-history."); return
        ncoarse = len(coarse); ndof = 6 * len(fine)
        free = [i for i in range(ndof) if i not in fixed]
        Mf = M[np.ix_(free, free)]; Kf = K[np.ix_(free, free)]
        # natural frequencies (first two) for the Rayleigh damping anchors
        try:
            Lc = np.linalg.cholesky(Mf); Lci = np.linalg.inv(Lc)
            w2, _Y = np.linalg.eigh(0.5 * (Lci @ Kf @ Lci.T + (Lci @ Kf @ Lci.T).T))
            ws = sorted(float(x) ** 0.5 for x in w2 if x > 1e-9)
        except Exception:
            err("Dynamic solve failed - the structure may be a mechanism."); return
        if not ws:
            err("No positive vibration modes - check supports/mass."); return
        w1 = ws[0]; w2a = ws[1] if len(ws) > 1 else ws[0] * 3.0
        f1 = w1 / (2 * np.pi)
        vals = form_dialog("Time-History Analysis (Newmark-beta)", [
            {"key": "_i", "kind": "info", "default":
             "Transient response by Newmark-beta (average acceleration, "
             "unconditionally stable). First natural frequency f1 = %.3f Hz "
             "(T1 = %.4f s). Choose a nodal force (needs selected node vertices) "
             "or a ground acceleration, a time function, duration and time step."
             % (f1, 1.0 / f1 if f1 > 0 else 0.0)},
            {"key": "exc", "label": "Excitation", "kind": "combo",
             "options": ["Nodal force", "Ground acceleration (seismic)"],
             "default": "Nodal force"},
            {"key": "dir", "label": "Direction", "kind": "combo",
             "options": list(self._DIRS.keys()), "default": "+X"},
            {"key": "amp", "label": "Amplitude (force N, or accel in g)",
             "kind": "float", "default": 100000.0},
            {"key": "func", "label": "Time function", "kind": "combo",
             "options": ["Step", "Harmonic", "Half-sine pulse",
                         "Record (spreadsheet)"], "default": "Step"},
            {"key": "freq", "label": "Harmonic frequency (Hz)", "kind": "float",
             "default": max(0.1, f1)},
            {"key": "td", "label": "Pulse duration (s)", "kind": "float", "default": 0.1},
            {"key": "recsheet", "label": "Record sheet (time | value cols)",
             "kind": "text", "default": "GroundMotion"},
            {"key": "recunit", "label": "Record unit (accel)", "kind": "combo",
             "options": ["g", "m/s2", "mm/s2"], "default": "g"},
            {"key": "dur", "label": "Total duration (s)", "kind": "float",
             "default": max(1.0, 6.0 / f1 if f1 > 0 else 2.0)},
            {"key": "dt", "label": "Time step dt (s)", "kind": "float",
             "default": max(1e-4, 1.0 / (40.0 * max(f1, 0.5))), "decimals": 5},
            {"key": "zeta", "label": "Damping ratio zeta", "kind": "float",
             "default": 0.05, "decimals": 4},
            {"key": "method", "label": "Method", "kind": "combo",
             "options": ["Direct (Newmark)", "Modal superposition"],
             "default": "Direct (Newmark)"},
            {"key": "nmodes", "label": "Modes (modal method)", "kind": "int",
             "default": 6, "min": 1, "max": 100},
        ])
        if not vals:
            return
        modal = str(vals.get("method", "")).startswith("Modal")
        nmodes = max(1, int(vals.get("nmodes", 6)))
        dv = self._DIRS.get(vals["dir"], (1.0, 0.0, 0.0, 0))
        dvec = np.array(dv[:3], float); dirdof = dv[3]
        amp = float(vals["amp"]); seismic = vals["exc"].startswith("Ground")
        func = vals["func"]; fh = float(vals["freq"]); td = float(vals["td"])
        dur = float(vals["dur"]); dt = max(1e-5, float(vals["dt"]))
        zeta = max(0.0, float(vals["zeta"]))
        rec = None
        if func.startswith("Record"):
            rec = _read_record(doc, str(vals.get("recsheet", "GroundMotion")).strip())
            if rec is None:
                info("Record sheet '%s' not found, or it has fewer than 2 numeric "
                     "rows. Put the time series in a spreadsheet: column A = time "
                     "(s), column B = acceleration; name the sheet to match."
                     % vals.get("recsheet", "GroundMotion"))
                return
            dur = max(dur, rec[0][-1] + 3.0 / f1)   # run past the record for decay

        # load pattern p (full) and scalar time function g(t)
        p = np.zeros(ndof)
        if seismic:
            r = np.zeros(ndof)
            for i in range(len(fine)):
                r[6 * i + dirdof] = 1.0
            p = -(M @ r)                 # effective seismic force = -M r a_g(t)
            if func.startswith("Record"):
                _uf = {"g": 9810.0, "m/s2": 1000.0, "mm/s2": 1.0}.get(
                    str(vals.get("recunit", "g")), 9810.0)
            else:
                _uf = 9810.0             # built-in functions: amplitude is in g
            scale = amp * _uf            # -> mm/s^2
        else:
            if not sel_pts:
                info("Select the node vertices to load (nodal force), then run."); return
            hit = 0
            for q in sel_pts:
                idx = next((i for i in range(len(fine))
                            if fine[i].distanceToPoint(FreeCAD.Vector(q)) <= 1.0), -1)
                if idx >= 0:
                    for a in range(3):
                        p[6 * idx + a] += dvec[a]
                    hit += 1
            if hit == 0:
                info("The selected vertices are not frame nodes."); return
            scale = amp

        def gfun(t):
            if func == "Harmonic":
                return np.sin(2 * np.pi * fh * t)
            if func.startswith("Half"):
                return np.sin(np.pi * t / td) if 0.0 <= t <= td else 0.0
            return 1.0                    # Step

        # Rayleigh damping C = a*M + b*K anchored at the first two frequencies
        if w2a > w1 + 1e-9:
            a_ray = 2 * zeta * w1 * w2a / (w1 + w2a); b_ray = 2 * zeta / (w1 + w2a)
        else:
            a_ray = 2 * zeta * w1; b_ray = 0.0
        Cf = a_ray * Mf + b_ray * Kf
        pf = p[free]

        # pseudo-static response to pick the monitored (most responsive) node
        try:
            ust = np.linalg.solve(Kf, pf * scale)     # pseudo-static response
        except Exception:
            ust = np.zeros(len(free))
        ust_full = np.zeros(ndof); ust_full[free] = ust
        mon = max(range(ncoarse),
                  key=lambda i: abs(ust_full[6 * i + dirdof]))
        ust_mon = ust_full[6 * mon + dirdof]

        # Newmark-beta constants (average acceleration: beta=1/4, gamma=1/2)
        beta = 0.25; gamma = 0.5
        a0 = 1.0 / (beta * dt * dt); a1 = gamma / (beta * dt); a2 = 1.0 / (beta * dt)
        a3 = 1.0 / (2 * beta) - 1.0; a4 = gamma / beta - 1.0
        a5 = dt * (gamma / (2 * beta) - 1.0)
        Khat = Kf + a0 * Mf + a1 * Cf
        try:
            Khat_inv = np.linalg.inv(Khat)
        except Exception:
            err("Newmark factorisation failed (singular system)."); return

        nstep = max(1, int(round(dur / dt)))
        tgrid = np.array([i * dt for i in range(nstep + 1)])
        if rec is not None:                 # resample the record onto the time grid
            gseries = np.interp(tgrid, np.array(rec[0]), np.array(rec[1]),
                                left=0.0, right=0.0)
        else:
            gseries = np.array([gfun(float(t)) for t in tgrid])
        # coarse-element force envelope (reuse _frame_stiffness elements)
        _cn, celems, _Kc, _fx, _sp = _frame_stiffness(doc)
        sampabs = {id(el): {k: [0.0] * 11 for k in DIAG_KINDS} for el in celems}
        hist = [(0.0, 0.0)]; peak_abs = [0.0]; u_peak = [np.zeros(ndof)]
        peak_shear = [0.0]
        fullu = np.zeros(ndof); fulla = np.zeros(ndof)
        # storey levels + a representative (most responsive) node per level, for
        # the inter-storey drift envelope
        levels = _storey_levels([coarse[i].z for i in range(ncoarse)], 1.0)
        rep = {}
        for Lv in levels:
            cand = [i for i in range(ncoarse) if abs(coarse[i].z - Lv) <= 1.0]
            rep[Lv] = max(cand, key=lambda i: abs(ust_full[6 * i + dirdof])) \
                if cand else None
        drift_peak = [0.0] * max(0, len(levels) - 1)

        def record_step(t1, uf, af, gi):
            fullu[free] = uf; fulla[free] = af
            hist.append((t1, float(fullu[6 * mon + dirdof])))
            for kk in range(len(levels) - 1):
                a = rep[levels[kk]]; b = rep[levels[kk + 1]]
                if a is not None and b is not None:
                    dd = fullu[6 * b + dirdof] - fullu[6 * a + dirdof]
                    if abs(dd) > drift_peak[kk]:
                        drift_peak[kk] = abs(dd)
            res = max((fullu[6 * j] ** 2 + fullu[6 * j + 1] ** 2
                       + fullu[6 * j + 2] ** 2) for j in range(ncoarse)) ** 0.5
            if res > peak_abs[0]:
                peak_abs[0] = res; u_peak[0] = fullu.copy()
            R = K @ fullu + M @ fulla - p * scale * gi         # support reactions
            vb = sum(R[6 * s + dirdof] for s in sup)
            if abs(vb) > peak_shear[0]:
                peak_shear[0] = abs(vb)
            uc = fullu[:6 * ncoarse]
            for el in celems:
                samp, _fend = _pt_samples(el, uc, [], 10)
                sa = sampabs[id(el)]
                for k in DIAG_KINDS:
                    row = samp[k]
                    for sidx in range(11):
                        av = abs(row[sidx])
                        if av > sa[k][sidx]:
                            sa[k][sidx] = av

        if modal:
            # mode-superposition: project onto the lowest `nmodes` modes, integrate
            # each decoupled modal SDOF, and reconstruct the response each step
            A = Lci @ Kf @ Lci.T; A = 0.5 * (A + A.T)
            w2m, Ym = np.linalg.eigh(A)
            idx = [i for i in np.argsort(w2m) if w2m[i] > 1e-9][:nmodes]
            Phi = np.column_stack([Lci.T @ Ym[:, i] for i in idx])   # M-normalised
            wm = np.array([float(w2m[i]) ** 0.5 for i in idx])
            zm = a_ray / (2.0 * wm) + b_ray * wm / 2.0               # Rayleigh modal
            cm = 2.0 * zm * wm; km = wm * wm
            Lmod = Phi.T @ pf                                        # modal loads
            khat = km + a0 * 1.0 + a1 * cm
            q = np.zeros(len(idx)); qd = np.zeros(len(idx))
            qdd = Lmod * scale * float(gseries[0])                   # modal mass = 1
            for i in range(nstep):
                gi = float(gseries[i + 1])
                phat = Lmod * scale * gi + (a0 * q + a2 * qd + a3 * qdd) \
                    + cm * (a1 * q + a4 * qd + a5 * qdd)
                q1 = phat / khat
                qdd1 = a0 * (q1 - q) - a2 * qd - a3 * qdd
                qd1 = qd + dt * ((1 - gamma) * qdd + gamma * qdd1)
                q, qd, qdd = q1, qd1, qdd1
                record_step((i + 1) * dt, Phi @ q, Phi @ qdd, gi)
        else:
            Minv = np.linalg.inv(Mf)
            u = np.zeros(len(free)); v = np.zeros(len(free))
            acc = Minv @ (pf * scale * float(gseries[0]) - Cf @ v - Kf @ u)
            for i in range(nstep):
                gi = float(gseries[i + 1])
                phat = pf * scale * gi + Mf @ (a0 * u + a2 * v + a3 * acc) \
                    + Cf @ (a1 * u + a4 * v + a5 * acc)
                u1 = Khat_inv @ phat
                acc1 = a0 * (u1 - u) - a2 * v - a3 * acc
                v1 = v + dt * ((1 - gamma) * acc + gamma * acc1)
                u, v, acc = u1, v1, acc1
                record_step((i + 1) * dt, u, acc, gi)

        u_peak = u_peak[0]; peak_shear = peak_shear[0]
        peak_mon = max(abs(h[1]) for h in hist)
        daf = (peak_mon / abs(ust_mon)) if abs(ust_mon) > 1e-12 else 0.0

        # store the peak deformed state + member envelope, render the shape
        comp_max = {k: 0.0 for k in DIAG_KINDS}
        for el in celems:
            el["samp"] = {k: list(sampabs[id(el)][k]) for k in DIAG_KINDS}
            for k in DIAG_KINDS:
                comp_max[k] = max(comp_max[k], max(el["samp"][k]))
            try:
                o = el["o"]
                _set(o, "App::PropertyFloat", "ResMy", float(max(el["samp"]["My"])))
                _set(o, "App::PropertyFloat", "ResMz", float(max(el["samp"]["Mz"])))
                _set(o, "App::PropertyFloat", "ResVy", float(max(el["samp"]["Vy"])))
                _set(o, "App::PropertyFloat", "ResVz", float(max(el["samp"]["Vz"])))
                _set(o, "App::PropertyFloat", "ResN",
                     float(max(el["samp"]["N"], key=abs) if el["samp"]["N"] else 0.0))
            except Exception:
                pass
        doc.openTransaction("DynFrame: time-history")
        for o in list(doc.Objects):
            if getattr(o, "DiagKind", None) is not None \
                    or o.Name.startswith(("Diagram_", "Result_", "DeformedShape",
                                          "Legend", "ResultPeak")):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        rg = _grp(doc, RES_GROUP)
        msize = _model_size([el["o"] for el in celems]) if celems else 1000.0
        upc = u_peak[:6 * ncoarse]
        _, maxoff = _deformed_points(coarse, upc,
                                     [(el["n1"], el["n2"]) for el in celems], 0.0)
        comp_max["Disp"] = maxoff
        dscale = (0.08 * msize / maxoff) if maxoff > 1e-9 else 1.0
        _store_analysis_state(doc, coarse, upc, celems, dscale, msize,
                              _tube_radius(msize),
                              "Time-history %s %s" % (vals["dir"], vals["func"]),
                              comp_max)
        doc.commitTransaction()
        _render_result(doc, "Disp", scale_mult=1.0)

        # monitored-node response-history table (subsampled to <= 500 rows)
        try:
            sh = doc.getObject("ResponseHistory") or \
                doc.addObject("Spreadsheet::Sheet", "ResponseHistory")
            sh.Label = "ResponseHistory"; sh.clearAll()
            sh.set("A1", "TIME-HISTORY - node N%d, %s disp (mm); f1=%.3f Hz, zeta=%.3f"
                   % (mon + 1, vals["dir"], f1, zeta))
            sh.set("A2", "t (s)"); sh.set("B2", "u (mm)")
            step = max(1, len(hist) // 500); r = 3
            for (tt, uu) in hist[::step]:
                sh.set("A%d" % r, "%.5g" % tt); sh.set("B%d" % r, "%.6g" % uu); r += 1
            if rg is not None and sh not in rg.Group:
                rg.addObject(sh)
        except Exception as ex:
            FreeCAD.Console.PrintError("DynFrame: response table failed (%s)\n" % ex)
        # inter-storey drift envelope (if the frame has >= 2 storey levels)
        max_dr = 0.0
        if len(levels) >= 2:
            try:
                sd = doc.getObject("StoreyDrift") or \
                    doc.addObject("Spreadsheet::Sheet", "StoreyDrift")
                sd.Label = "StoreyDrift"; sd.clearAll()
                sd.set("A1", "INTER-STOREY DRIFT (peak over time, %s dir)" % vals["dir"])
                for c, h in zip("ABCDE", ["Storey", "z_bot (mm)", "z_top (mm)",
                                          "drift (mm)", "drift ratio"]):
                    sd.set("%s2" % c, h)
                r = 3
                for kk in range(len(levels) - 1):
                    hstorey = levels[kk + 1] - levels[kk]
                    ratio = drift_peak[kk] / hstorey if hstorey > 1e-9 else 0.0
                    max_dr = max(max_dr, ratio)
                    row = [str(kk + 1), "%.1f" % levels[kk], "%.1f" % levels[kk + 1],
                           "%.4g" % drift_peak[kk],
                           "%.5f (1/%.0f)" % (ratio, (1.0 / ratio) if ratio > 1e-9 else 0.0)]
                    for c, v in zip("ABCDE", row):
                        sd.set("%s%d" % (c, r), v)
                    r += 1
                if rg is not None and sd not in rg.Group:
                    rg.addObject(sd)
            except Exception as ex:
                FreeCAD.Console.PrintError("DynFrame: drift table failed (%s)\n" % ex)
        doc.recompute()
        if func.startswith("Record"):
            src = "record '%s' (%s)" % (vals.get("recsheet", "GroundMotion"),
                                        vals.get("recunit", "g"))
        else:
            src = vals["func"]
        base = ("ground accel" if seismic else "nodal force %.0f N" % amp)
        meth = "modal (%d modes)" % nmodes if modal else "direct Newmark"
        drift_note = ("\nMax inter-storey drift ratio = %.5f (1/%.0f) - see the "
                      "'StoreyDrift' table." % (max_dr, (1.0 / max_dr) if max_dr > 1e-9
                                                else 0.0)) if len(levels) >= 2 else ""
        info("Time-history complete (%s): %s, %s, %s over %.3g s "
             "(dt=%.4g s, %d steps).\n\nf1 = %.3f Hz (T1 = %.4f s), Rayleigh "
             "zeta = %.3f.\nPeak response at node N%d = %.4g mm (dyn. amplification "
             "%.2f x the static).\nPeak base shear = %.0f N.%s\n\nShowing the deformed "
             "shape at peak response; the monitored-node time history is in the "
             "'ResponseHistory' table and the member-force envelope is stored for "
             "the code check." % (meth, base, src, vals["dir"], dur, dt, nstep,
                                  f1, 1.0 / f1 if f1 > 0 else 0.0, zeta, mon + 1,
                                  peak_mon, daf, peak_shear, drift_note))


def _auto_combos(doc):
    cases = _cases(doc)
    dead = [n for n, nat in cases if nat == "Dead"]
    var = [n for n, nat in cases if nat in ("Live", "Wind", "Snow")]
    uls = " + ".join(["1.35*%s" % d for d in dead] + ["1.5*%s" % q for q in var])
    sls = " + ".join(["1.0*%s" % c for c in (dead + var)])
    pairs = _combos(doc); have = {p[0] for p in pairs}
    if uls and "ULS1" not in have:
        pairs.append(("ULS1", uls))
    if sls and "SLS1" not in have:
        pairs.append(("SLS1", sls))
    _set_combos(doc, pairs)
    return uls, sls


_PANEL = None
_RESPANEL = None


# ── Results Viewer backend (second interface: analyse & view results) ──
# Results are rendered lazily: the solve stores the per-bar force samples and
# the deformed state, and ONE result is drawn at a time (on demand) by
# _render_result. That keeps the object count down, lets the deformation scale
# and the tube/solid-beam choice re-render instantly, and guarantees the
# colour gradient along each bar.
_SOLID_BEAMS = False        # Results Viewer "Solid beams" toggle


def _store_analysis_state(doc, nodes, u, elems, dscale, msize, radius, run_name,
                          comp_max):
    """Persist the solved state the Results Viewer needs to render any result
    on demand (per-bar force samples, sections, peaks) and to re-draw / animate
    the deformed shape at any exaggeration, without re-solving."""
    import json
    st = doc.getObject("AnalysisState")
    if st is None:
        st = doc.addObject("App::DocumentObjectGroup", "AnalysisState")
    st.Label = "AnalysisState"
    _set(st, "App::PropertyString", "StNodes",
         json.dumps([[n.x, n.y, n.z] for n in nodes]))
    _set(st, "App::PropertyString", "StU", json.dumps([float(x) for x in u]))
    _set(st, "App::PropertyString", "StElems",
         json.dumps([[el["n1"], el["n2"]] for el in elems]))
    _set(st, "App::PropertyFloat", "StScale", float(dscale))
    _set(st, "App::PropertyFloat", "StMsize", float(msize))
    _set(st, "App::PropertyFloat", "StRadius", float(radius))
    _set(st, "App::PropertyString", "StRun", str(run_name))
    _set(st, "App::PropertyString", "StSamp", json.dumps(
        [{k: [float(v) for v in el["samp"][k]] for k in DIAG_KINDS}
         for el in elems]))
    _set(st, "App::PropertyString", "StSections",
         json.dumps([str(el.get("sec", "")) for el in elems]))
    _set(st, "App::PropertyString", "StCompMax",
         json.dumps({k: float(comp_max.get(k, 0.0)) for k in ["Disp"] + DIAG_KINDS}))
    try:
        st.ViewObject.Visibility = False
    except Exception:
        pass


def _deformed_points(nodes, u, elpairs, scale, NS=10):
    """Per-bar deformed station points (cubic Hermite from the nodal
    displacements) at the given exaggeration, plus the true |u| per station and
    the peak |u|. Shared by the displacement contour and the animation frames."""
    import numpy as np
    perbar = []; maxd = 0.0
    for (n1, n2) in elpairs:
        T, L = _beam_T(nodes[n1], nodes[n2]); R3 = T[0:3, 0:3]
        lx = FreeCAD.Vector(*[float(R3[0][j]) for j in range(3)])
        ly = FreeCAD.Vector(*[float(R3[1][j]) for j in range(3)])
        lz = FreeCAD.Vector(*[float(R3[2][j]) for j in range(3)])
        dg = np.concatenate([u[6 * n1:6 * n1 + 6], u[6 * n2:6 * n2 + 6]])
        dl = T @ dg
        bpt = nodes[n1]; pts = []; disp = []
        for s in range(NS + 1):
            xi = s / float(NS); x = L * xi
            h1 = 1 - 3 * xi ** 2 + 2 * xi ** 3; h2 = L * (xi - 2 * xi ** 2 + xi ** 3)
            h3 = 3 * xi ** 2 - 2 * xi ** 3; h4 = L * (-xi ** 2 + xi ** 3)
            ux = dl[0] + (dl[6] - dl[0]) * xi
            uy = h1 * dl[1] + h2 * dl[5] + h3 * dl[7] + h4 * dl[11]
            uz = h1 * dl[2] - h2 * dl[4] + h3 * dl[8] - h4 * dl[10]
            off = vscale(lx, ux) + vscale(ly, uy) + vscale(lz, uz)
            pts.append(bpt + vscale(lx, x) + vscale(off, scale))
            disp.append(off.Length); maxd = max(maxd, off.Length)
        perbar.append((pts, disp))
    return perbar, maxd


def _load_state(doc):
    """(nodes, u, elpairs, base_scale, msize, radius) from the stored solved
    state, or None if there is no analysis yet."""
    import json
    import numpy as np
    st = doc.getObject("AnalysisState")
    if st is None:
        return None
    return ([FreeCAD.Vector(*p) for p in json.loads(st.StNodes)],
            np.array(json.loads(st.StU)), json.loads(st.StElems),
            st.StScale, st.StMsize, st.StRadius)


def _load_state_full(doc):
    """The full solved state for on-demand result rendering: adds the per-bar
    force samples, section names and per-result peaks to _load_state."""
    import json
    base = _load_state(doc)
    if base is None:
        return None
    st = doc.getObject("AnalysisState")
    try:
        samp = json.loads(getattr(st, "StSamp", "[]"))
        sections = json.loads(getattr(st, "StSections", "[]"))
        compmax = json.loads(getattr(st, "StCompMax", "{}"))
    except Exception:
        samp, sections, compmax = [], [], {}
    return base + (samp, sections, compmax)


def _render_result(doc, kind, scale_mult=1.0, solid=None):
    """Draw ONE result (kind = 'Disp' or a force component) on demand from the
    stored state, as the coloured contour - tubes, or (solid=True) the members'
    real swept profiles. Replaces whatever result was shown. Returns True/False."""
    state = _load_state_full(doc)
    if state is None:
        return False
    nodes, u, elpairs, base, msize, radius, samp, sections, compmax = state
    if solid is None:
        solid = _SOLID_BEAMS
    kind = kind if kind in (["Disp"] + DIAG_KINDS) else "Disp"
    if kind == "Disp":
        scale = base * max(float(scale_mult), 0.0)
        perbar0, _ = _deformed_points(nodes, u, elpairs, scale)
        perbar = perbar0
        vmax = float(compmax.get("Disp", 0.0))
        title = "Displacement (mm)"; label = "Displacement (mm) x%.0f" % scale
    else:
        perbar0, _ = _deformed_points(nodes, u, elpairs, 0.0)      # undeformed stations
        perbar = []
        for bi, (pts, _d) in enumerate(perbar0):
            vals = samp[bi].get(kind, []) if bi < len(samp) else []
            perbar.append((pts, [abs(v) for v in vals]))
        vmax = float(compmax.get(kind, 0.0))
        title = RESULT_LABELS.get(kind, kind); label = "%s result" % kind
    # clear the previously shown result (contour, legend, peak label) and hide
    # any mode/buckling/seismic shape
    for o in list(doc.Objects):
        nm = o.Name; dk = getattr(o, "DiagKind", None)
        if nm.startswith("Diagram_") or dk == "_legend" or nm.startswith("ResultPeak"):
            try:
                doc.removeObject(nm)
            except Exception:
                pass
    for o in doc.Objects:
        dk = getattr(o, "DiagKind", None)
        if dk and dk.startswith("_") and dk not in ("_legend", "_anim"):
            try:
                o.ViewObject.Visibility = False
            except Exception:
                pass
    rg = _grp(doc, RES_GROUP); dg = _grp(doc, DIA_GROUP)
    grp = rg if kind == "Disp" else dg
    dirs = [unit(nodes[b] - nodes[a]) for (a, b) in elpairs]
    ob = _result_tube(doc, grp, "Diagram_%s" % kind, kind, perbar, radius, vmax,
                      True, sections=sections, dirs=dirs, solid=solid)
    if ob is not None:
        ob.Label = label
    objs = [o for o in doc.Objects if is_analysis_elem(o)]
    _color_bar(doc, dg, 0.0, vmax, title, objs, msize)
    doc.recompute()
    _apply_result_colors(doc)
    return True


def _draw_deformed(doc, scale_mult=1.0):
    """Render the displacement contour at `scale_mult` x the auto exaggeration."""
    return _render_result(doc, "Disp", scale_mult=scale_mult)


def _make_anim_frames(doc, amp=1.0, nframes=12):
    """Pre-build the deformed-shape animation as `nframes` hidden frames, each a
    set of colour-band WIRE objects (coloured by |u|, so the animation shows the
    same gradient as the static contour). Playing just toggles visibility - no
    per-frame rebuild. Returns a list of frames, each a list of band objects."""
    import math
    full = _load_state_full(doc)
    if full is None:
        return []
    nodes, u, elpairs, base, msize, radius, samp, sections, compmax = full
    vmax = float(compmax.get("Disp", 0.0))
    _clear_anim_frames(doc)
    grp = _grp(doc, RES_GROUP)
    frames = []
    for i in range(nframes):
        m = amp * 0.5 * (1.0 - math.cos(2.0 * math.pi * i / nframes))
        perbar, _ = _deformed_points(nodes, u, elpairs, base * m)
        bands = [[] for _ in range(_NBAND)]
        for (pts, disp) in perbar:
            for j in range(len(pts) - 1):
                a = pts[j]; b = pts[j + 1]
                if (b - a).Length < 1e-6:
                    continue
                t = (0.5 * (disp[j] + disp[j + 1]) / vmax) if vmax > 1e-12 else 0.0
                try:
                    seg = Part.makePolygon([FreeCAD.Vector(a), FreeCAD.Vector(b)])
                except Exception:
                    continue
                bands[min(_NBAND - 1, max(0, int(t * _NBAND)))].append(seg)
        fobs = []
        for k, segs in enumerate(bands):
            if not segs:
                continue
            ob = doc.addObject("Part::Feature", "AnimF%d_b%d" % (i, k))
            ob.Shape = Part.makeCompound(segs)
            _set(ob, "App::PropertyString", "DiagKind", "_anim")
            try:
                ob.ViewObject.Visibility = False
                ob.ViewObject.LineWidth = 6
                ob.ViewObject.LineColor = _ramp((k + 0.5) / _NBAND)
            except Exception:
                pass
            grp.addObject(ob)
            fobs.append(ob)
        if fobs:
            frames.append(fobs)
    doc.recompute()          # one-time; animation then only toggles visibility
    return frames


def _clear_anim_frames(doc):
    for o in list(doc.Objects):
        if getattr(o, "DiagKind", None) == "_anim":
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass


def _shown_range(doc):
    """(title, vmin, vmax) of the result currently visible in the 3D view, for
    the Results Viewer legend - read from the shown tube's stored range."""
    for o in doc.Objects:
        if not hasattr(o, "CompMax"):
            continue
        try:
            if o.ViewObject.Visibility:
                k = getattr(o, "DiagKind", "")
                title = RESULT_LABELS.get(k, o.Label or str(k))
                return (title, float(getattr(o, "CompMin", 0.0)),
                        float(getattr(o, "CompMax", 0.0)))
        except Exception:
            pass
    return None


def _result_list(doc):
    """Available results as (label, key, kind) where kind is 'diag' (a static
    result rendered on demand by _render_result) or 'obj' (a Mode/Buckling/
    Seismic shape toggled directly). Static results come from the stored peaks
    (StCompMax), since they are no longer pre-built as objects."""
    import json
    out = []
    st = doc.getObject("AnalysisState")
    compmax = {}
    if st is not None:
        try:
            compmax = json.loads(getattr(st, "StCompMax", "{}"))
        except Exception:
            compmax = {}
    for k in RESULT_ORDER:
        if k == "Disp" and st is not None:
            out.append((RESULT_LABELS[k], k, "diag"))
        elif float(compmax.get(k, 0.0)) > 1e-9:
            out.append((RESULT_LABELS[k], k, "diag"))
    # mode / buckling / seismic / plate shapes are drawn as colour-band objects
    # sharing one DiagKind each; list each kind once and toggle it by DiagKind
    seen = set()
    for o in doc.Objects:
        dk = getattr(o, "DiagKind", None)
        if dk and (dk in ("_mode", "_buckling", "_seismic")
                   or dk.startswith("_plate")) and dk not in seen:
            seen.add(dk)
            out.append((o.Label or dk.strip("_").title(), dk, "obj"))
    return out


def _result_summary(doc):
    """Human-readable summary of the key maxima from the current results, read
    from the per-bar stored forces and the solved state (Inventor-style probe)."""
    import json
    bars = [o for o in doc.Objects if is_analysis_elem(o) and hasattr(o, "ResN")]
    has_plate = any(hasattr(o, "ShellVM") for o in doc.Objects)
    if not bars and not has_plate and doc.getObject("AnalysisState") is None:
        return "No results yet. Solve first (Calculate)."
    def peak(attr):
        best = 0.0; who = "-"
        for o in bars:
            v = abs(getattr(o, attr, 0.0))
            if v >= best:
                best = v; who = str(o.Label)
        return best, who
    lines = []
    st = doc.getObject("AnalysisState")
    if st is not None:
        try:
            u = json.loads(st.StU)
            md = 0.0; mn = "-"
            for i in range(len(u) // 6):
                m = (u[6 * i] ** 2 + u[6 * i + 1] ** 2 + u[6 * i + 2] ** 2) ** 0.5
                if m > md:
                    md = m; mn = "N%d" % (i + 1)
            # true peak includes bending between nodes (a beam bows mid-span),
            # which the nodal max understates - report it from the stored peak
            cm = {}
            try:
                cm = json.loads(getattr(st, "StCompMax", "{}"))
            except Exception:
                cm = {}
            dmax = max(md, float(cm.get("Disp", 0.0)))
            lines.append("Run: %s" % getattr(st, "StRun", "-"))
            lines.append("Max displacement:  %.4g mm  (peak along members)" % dmax)
            lines.append("Max nodal displacement:  %.4g mm  (%s)" % (md, mn))
        except Exception:
            pass
    for attr, lab, unit in (("ResN", "Axial N", "N"), ("ResMy", "Moment My", "N.mm"),
                            ("ResMz", "Moment Mz", "N.mm"), ("ResVy", "Shear Vy", "N"),
                            ("ResVz", "Shear Vz", "N")):
        v, who = peak(attr)
        if v > 1e-9:
            lines.append("Max |%s|:  %.4g %s  (%s)" % (lab, v, unit, who))
    uv, uw = peak("ResUtil")
    if uv > 1e-9:
        lines.append("Max utilisation:  %.2f  (%s)  ->  %s"
                     % (uv, uw, "OK" if uv <= 1.0 else "OVER-STRESSED"))
    # plate/shell peaks (von Mises + bending moments), if any plates were solved
    plates = [o for o in doc.Objects if hasattr(o, "ShellVM")]
    if plates:
        def ppk(attr):
            return max((abs(float(getattr(o, attr, 0.0))) for o in plates), default=0.0)
        vmx = ppk("ShellVM")
        if vmx > 1e-9:
            lines.append("Plate max von Mises:  %.4g MPa" % vmx)
        mx, my, mxy = ppk("ShellMx"), ppk("ShellMy"), ppk("ShellMxy")
        if max(mx, my, mxy) > 1e-9:
            lines.append("Plate max |Mx| %.4g | |My| %.4g | |Mxy| %.4g  N.mm/mm"
                         % (mx, my, mxy))
        wxb, wyb = ppk("ShellWAxb"), ppk("ShellWAyb")
        wxt, wyt = ppk("ShellWAxt"), ppk("ShellWAyt")
        if max(wxb, wyb, wxt, wyt) > 1e-9:
            lines.append("Wood-Armer design M - bottom x/y %.4g / %.4g, "
                         "top x/y %.4g / %.4g  N.mm/mm" % (wxb, wyb, wxt, wyt))
    cc = doc.getObject("CodeCheck")
    if cc is not None:
        lines.append("Code check: see 'CodeCheck' table (class, chi_LT, U).")
    return "\n".join(lines) if lines else "Results present."


def _results_panel_class():
    """Second interface: an Inventor-style results browser (result list +
    contour + readable value legend + min/max probe + deformation scale +
    animation). Built lazily so importing the module never needs Qt."""
    from PySide import QtCore

    class _RampBar(QW.QWidget):
        """A 2D colour-ramp legend painted in the panel (readable regardless of
        the 3D view angle), with numeric value ticks - the Inventor result
        legend."""
        def __init__(self):
            super(_RampBar, self).__init__()
            self._title = "Result"; self._vmin = 0.0; self._vmax = 0.0
            self.setMinimumHeight(190); self.setMinimumWidth(150)

        def set_range(self, title, vmin, vmax):
            self._title = title; self._vmin = vmin; self._vmax = vmax
            self.update()

        def paintEvent(self, ev):
            p = QtGui.QPainter(self)
            try:
                w = self.width(); h = self.height()
                bx, bw, top, bot = 10, 30, 26, h - 14
                bh = max(bot - top, 1)
                grad = QtGui.QLinearGradient(0, top, 0, bot)
                for i in range(13):
                    t = i / 12.0
                    r, g, b = _ramp(1.0 - t)
                    grad.setColorAt(t, QtGui.QColor(int(r * 255), int(g * 255), int(b * 255)))
                p.fillRect(QtCore.QRectF(bx, top, bw, bh), QtGui.QBrush(grad))
                p.setPen(QtGui.QColor(110, 110, 110))
                p.drawRect(QtCore.QRectF(bx, top, bw, bh))
                tc = self.palette().windowText().color()
                p.setPen(tc)
                f = p.font(); f.setBold(True); p.setFont(f)
                p.drawText(QtCore.QRectF(0, 2, w, 18), int(QtCore.Qt.AlignLeft),
                           self._title)
                f.setBold(False); p.setFont(f)
                if self._vmax <= self._vmin:
                    p.drawText(QtCore.QRectF(bx + bw + 8, top, w, 18),
                               int(QtCore.Qt.AlignLeft), "(no result shown)")
                    return
                for i in range(7):
                    frac = i / 6.0
                    val = self._vmax - (self._vmax - self._vmin) * frac
                    yy = top + bh * frac
                    p.drawLine(QtCore.QPointF(bx + bw, yy),
                               QtCore.QPointF(bx + bw + 5, yy))
                    p.drawText(QtCore.QRectF(bx + bw + 9, yy - 9,
                               w - (bx + bw + 9), 18),
                               int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter),
                               "%.4g" % val)
            finally:
                p.end()

    class ResultsViewerPanel(QW.QDialog):
        def __init__(self):
            super(ResultsViewerPanel, self).__init__(_mw())
            self.setWindowTitle("DynFrame - Results Viewer")
            self.setModal(False)
            self._timer = None
            self._frames = []
            self._fi = 0
            self._loops = 0
            self._build()
            self._refresh()

        def _doc(self):
            return FreeCAD.ActiveDocument

        def _btn(self, text, slot):
            b = QW.QPushButton(text); b.clicked.connect(slot); return b

        def _build(self):
            lay = QW.QVBoxLayout(self)
            self.hdr = QW.QLabel("Results"); self.hdr.setWordWrap(True)
            lay.addWidget(self.hdr)

            row = QW.QHBoxLayout()
            g = QW.QGroupBox("Result"); gl = QW.QVBoxLayout(g)
            self.list = QW.QListWidget()
            self.list.setMinimumHeight(190)
            self.list.currentRowChanged.connect(self._show_selected)
            gl.addWidget(self.list)
            row.addWidget(g, 1)
            lg = QW.QGroupBox("Legend"); lgl = QW.QVBoxLayout(lg)
            self.legend = _RampBar(); lgl.addWidget(self.legend)
            row.addWidget(lg)
            lay.addLayout(row)

            g = QW.QGroupBox("Deformation scale (displacement contour)")
            gl = QW.QVBoxLayout(g)
            r = QW.QHBoxLayout()
            r.addWidget(QW.QLabel("x auto"))
            self.scale = QW.QDoubleSpinBox()
            self.scale.setRange(0.0, 1.0e6); self.scale.setDecimals(2)
            self.scale.setValue(1.0); self.scale.setSingleStep(0.5)
            r.addWidget(self.scale, 1)
            r.addWidget(self._btn("Apply", self._apply_scale))
            self.animbtn = self._btn("Animate", self._toggle_anim)
            self.animbtn.setCheckable(True)
            r.addWidget(self.animbtn)
            gl.addLayout(r)
            cr = QW.QHBoxLayout()
            self.showmodel = QW.QCheckBox("Show undeformed model")
            self.showmodel.setChecked(True)
            self.showmodel.stateChanged.connect(self._toggle_model)
            cr.addWidget(self.showmodel)
            self.solidbeams = QW.QCheckBox("Solid beams (real section)")
            self.solidbeams.setChecked(bool(_SOLID_BEAMS))
            self.solidbeams.stateChanged.connect(self._toggle_solid)
            cr.addWidget(self.solidbeams)
            gl.addLayout(cr)
            lay.addWidget(g)

            g = QW.QGroupBox("Summary (max values)"); gl = QW.QVBoxLayout(g)
            self.summary = QW.QLabel("-"); self.summary.setWordWrap(True)
            self.summary.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            gl.addWidget(self.summary)
            lay.addWidget(g)

            r = QW.QHBoxLayout()
            r.addWidget(self._btn("Fit view", self._fit))
            r.addWidget(self._btn("Refresh", self._refresh))
            lay.addLayout(r)

        def _update_legend(self):
            doc = self._doc()
            if doc is None:
                return
            rng = _shown_range(doc)
            if rng is not None:
                self.legend.set_range(*rng)
            else:
                self.legend.set_range("Result", 0.0, 0.0)

        def _refresh(self, *a):
            doc = self._doc()
            if doc is None:
                self.hdr.setText("No active document."); return
            self._results = _result_list(doc)
            cur = self.list.currentRow()
            self.list.blockSignals(True)
            self.list.clear()
            for (label, key, knd) in self._results:
                self.list.addItem(label)
            self.list.blockSignals(False)
            if self._results:
                self.list.setCurrentRow(cur if 0 <= cur < len(self._results) else 0)
            self.hdr.setText("%d result(s) available. Click one to show it as a "
                             "thick coloured contour; the legend and the max-value "
                             "summary update to match." % len(self._results))
            self.summary.setText(_result_summary(doc))
            self._update_legend()

        def _show_selected(self, row):
            doc = self._doc()
            if doc is None or not (0 <= row < len(self._results)):
                return
            self._stop_anim()
            label, key, knd = self._results[row]
            self._cur = (key, knd)
            if knd == "diag":
                sc = self.scale.value() if key == "Disp" else 1.0
                _render_result(doc, key, scale_mult=sc)
            else:
                # a mode / buckling / seismic / plate shape (band objects share
                # one DiagKind): show every object of that kind, hide other
                # results; refresh the legend from the shown range
                for o in doc.Objects:
                    k = getattr(o, "DiagKind", None)
                    if not k or k in ("_legend", "_anim"):
                        continue
                    try:
                        o.ViewObject.Visibility = (k == key)
                    except Exception:
                        pass
                objs = [o for o in doc.Objects if is_analysis_elem(o)]
                vm = 0.0; vmn = 0.0
                for o in doc.Objects:
                    if getattr(o, "DiagKind", None) == key:
                        vm = float(getattr(o, "CompMax", 0.0))
                        vmn = float(getattr(o, "CompMin", 0.0)); break
                _color_bar(doc, _grp(doc, DIA_GROUP), vmn, vm,
                           label, objs, _model_size(objs))
                doc.recompute()
            self.summary.setText(_result_summary(doc))
            self._update_legend()

        def _toggle_model(self, *a):
            doc = self._doc()
            if doc is None:
                return
            vis = self.showmodel.isChecked()
            for o in doc.Objects:
                if is_analysis_elem(o):
                    try:
                        o.ViewObject.Visibility = vis
                    except Exception:
                        pass

        def _toggle_solid(self, *a):
            global _SOLID_BEAMS
            _SOLID_BEAMS = self.solidbeams.isChecked()
            # re-render the current result with the new style
            self._show_selected(self.list.currentRow())

        def _apply_scale(self):
            doc = self._doc()
            if doc is None:
                return
            self._stop_anim()
            if not _draw_deformed(doc, self.scale.value()):
                info("No solved state found. Run Calculate first.")
                return
            self._update_legend(); self._fit()

        # ---- animation: pre-built wire frames, toggled by visibility only, so
        # a frame costs nothing and the Stop click always registers ----
        def _toggle_anim(self):
            doc = self._doc()
            if self.animbtn.isChecked():
                if doc is None or doc.getObject("AnalysisState") is None:
                    self.animbtn.setChecked(False)
                    info("No solved state found. Run Calculate first."); return
                self._frames = _make_anim_frames(doc, max(self.scale.value(), 0.1), 12)
                if not self._frames:
                    self.animbtn.setChecked(False); return
                sd = doc.getObject("Diagram_Disp")
                if sd is not None:
                    try:
                        sd.ViewObject.Visibility = False
                    except Exception:
                        pass
                self._fi = 0; self._loops = 0
                self.animbtn.setText("Stop")
                self._timer = QtCore.QTimer(self)
                self._timer.timeout.connect(self._anim_step)
                self._timer.start(90)
            else:
                self._stop_anim()

        def _anim_step(self):
            frames = self._frames
            if not frames:
                self._stop_anim(); return
            for j, fobs in enumerate(frames):       # each frame is a list of bands
                vis = (j == self._fi)
                for ob in fobs:
                    try:
                        ob.ViewObject.Visibility = vis
                    except Exception:
                        pass
            self._fi += 1
            if self._fi >= len(frames):
                self._fi = 0; self._loops += 1
                if self._loops >= 8:          # auto-stop after a few loops
                    self._stop_anim()

        def _stop_anim(self):
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._timer = None
            try:
                self.animbtn.setChecked(False); self.animbtn.setText("Animate")
            except Exception:
                pass
            doc = self._doc()
            if doc is not None and self._frames:
                _clear_anim_frames(doc)
                _draw_deformed(doc, self.scale.value())
                self._update_legend()
            self._frames = []

        def closeEvent(self, ev):
            self._stop_anim()
            try:
                super(ResultsViewerPanel, self).closeEvent(ev)
            except Exception:
                ev.accept()

        def _fit(self):
            try:
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass

    return ResultsViewerPanel


def _panel_class():
    """Build the panel class lazily so importing the module never needs Qt."""
    class FrameAnalysisPanel(QW.QDialog):
        def __init__(self):
            super(FrameAnalysisPanel, self).__init__(_mw())
            self.setWindowTitle("DynFrame - Frame Analysis")
            self.setModal(False)
            self._build()
            self._refresh()

        def _doc(self):
            return FreeCAD.ActiveDocument

        def _box(self, title):
            g = QW.QGroupBox(title)
            return g, QW.QVBoxLayout(g)

        def _btn(self, text, slot):
            b = QW.QPushButton(text); b.clicked.connect(slot); return b

        def _build(self):
            lay = QW.QVBoxLayout(self)
            self.info = QW.QLabel("-"); self.info.setWordWrap(True)
            lay.addWidget(self.info)

            g, gl = self._box("1. Structure (line model)")
            r = QW.QHBoxLayout()
            r.addWidget(self._btn("Grid…", self._grid))
            r.addWidget(self._btn("Bars from lines", self._addbars))
            r.addWidget(self._btn("Bars from members", self._frommembers))
            gl.addLayout(r)
            r2 = QW.QHBoxLayout()
            r2.addWidget(self._btn("Edit node/bar tables", self._edittables))
            r2.addWidget(self._btn("Build from tables", self._buildtables))
            gl.addLayout(r2)
            lay.addWidget(g)

            g, gl = self._box("2. Load case")
            r = QW.QHBoxLayout()
            self.case = QW.QComboBox(); r.addWidget(self.case, 1)
            r.addWidget(self._btn("New case…", self._newcase))
            gl.addLayout(r)
            lay.addWidget(g)

            g, gl = self._box("3. Support (select node vertices, then Apply)")
            r = QW.QHBoxLayout()
            self.sup = QW.QComboBox(); self.sup.addItems(list(SUPPORT_TYPES.keys()))
            r.addWidget(self.sup, 1); r.addWidget(self._btn("Apply", self._support))
            gl.addLayout(r)
            lay.addWidget(g)

            g, gl = self._box("4. Load (select nodes or bars, then Apply)")
            self.ltype = QW.QComboBox()
            self.ltype.addItems(["Nodal force (on selected nodes)",
                                 "Line load (on selected bars)"])
            gl.addWidget(self.ltype)
            grid = QW.QGridLayout()
            self.fx = QW.QDoubleSpinBox(); self.fy = QW.QDoubleSpinBox()
            self.fz = QW.QDoubleSpinBox(); self.w = QW.QDoubleSpinBox()
            for sb, df in ((self.fx, 0.0), (self.fy, 0.0), (self.fz, -1000.0), (self.w, -5.0)):
                sb.setRange(-1e12, 1e12); sb.setDecimals(2); sb.setValue(df)
            grid.addWidget(QW.QLabel("Fx (N)"), 0, 0); grid.addWidget(self.fx, 0, 1)
            grid.addWidget(QW.QLabel("Fy (N)"), 0, 2); grid.addWidget(self.fy, 0, 3)
            grid.addWidget(QW.QLabel("Fz (N)"), 1, 0); grid.addWidget(self.fz, 1, 1)
            grid.addWidget(QW.QLabel("w (N/mm,Z)"), 1, 2); grid.addWidget(self.w, 1, 3)
            gl.addLayout(grid)
            gl.addWidget(self._btn("Apply load", self._load))
            lay.addWidget(g)

            g, gl = self._box("5. Combinations")
            gl.addWidget(self._btn("Auto ULS + SLS (EN 1990)", self._autocombo))
            lay.addWidget(g)

            g, gl = self._box("6. Solve")
            r = QW.QHBoxLayout()
            self.run = QW.QComboBox(); r.addWidget(self.run, 1)
            self.sw = QW.QCheckBox("Self-weight"); self.sw.setChecked(True)
            r.addWidget(self.sw)
            self.po = QW.QCheckBox("P-Δ"); r.addWidget(self.po)
            r.addWidget(self._btn("Calculate", self._calc))
            r.addWidget(self._btn("Modal", self._modal))
            r.addWidget(self._btn("Buckling", self._buckling))
            r.addWidget(self._btn("Seismic", self._seismic))
            gl.addLayout(r)
            r2 = QW.QHBoxLayout()
            r2.addWidget(self._btn("Envelope (all combos)", self._envelope))
            r2.addWidget(self._btn("Steel code check (EC3)", self._codecheck))
            gl.addLayout(r2)
            lay.addWidget(g)

            g, gl = self._box("7. Result shown")
            r = QW.QHBoxLayout()
            self.res = QW.QComboBox(); self.res.addItems([RESULT_LABELS[k] for k in RESULT_ORDER])
            r.addWidget(self.res, 1); r.addWidget(self._btn("Show", self._show))
            gl.addLayout(r)
            gl.addWidget(self._btn("Open Results Viewer (contours, scale, animate)…",
                                   self._resviewer))
            lay.addWidget(g)

            lay.addWidget(self._btn("Refresh", self._refresh))

        # ---- handlers ----
        def _refresh(self, *a):
            doc = self._doc()
            if doc is None:
                self.info.setText("No active document."); return
            bars = len([o for o in doc.Objects if is_analysis_elem(o)])
            sups = len([o for o in doc.Objects if getattr(o, "Restrain", None)])
            lds = len([o for o in doc.Objects if getattr(o, "LoadType", None)])
            cs = [c[0] for c in _cases(doc)]
            cbs = [c[0] for c in _combos(doc)]
            self.info.setText("Bars/members: %d   Supports: %d   Loads: %d   "
                              "Cases: %d   Combos: %d" % (bars, sups, lds, len(cs), len(cbs)))
            cur = self.case.currentText()
            self.case.clear(); self.case.addItems(cs)
            if cur in cs:
                self.case.setCurrentIndex(cs.index(cur))
            elif cs:
                self.case.setCurrentIndex(len(cs) - 1)
            self.run.clear()
            self.run.addItems(["All loads"] + ["Case: %s" % c for c in cs]
                              + ["Combo: %s" % c for c in cbs])

        def _grid(self):
            GridGen().Activated(); self._refresh()

        def _addbars(self):
            AddBars().Activated(); self._refresh()

        def _frommembers(self):
            BarsFromMembers().Activated(); self._refresh()

        def _edittables(self):
            EditTables().Activated(); self._refresh()

        def _buildtables(self):
            BuildFromTables().Activated(); self._refresh()

        def _newcase(self):
            NewLoadCase().Activated(); self._refresh()

        def _support(self):
            doc = self._doc(); pts = _sel_support_points(doc)
            if not pts:
                info("Select one or more node vertices (or a solid member's end "
                     "face) in the 3D view first."); return
            doc.openTransaction("DynFrame: support")
            _apply_support(doc, self.sup.currentText(), pts)
            doc.commitTransaction(); doc.recompute(); self._refresh()

        def _load(self):
            doc = self._doc(); case = self.case.currentText() or "DL1"
            if self.ltype.currentIndex() == 0:
                pts = _sel_support_points(doc)
                if not pts:
                    info("Select node vertices (or a solid member's end face) "
                         "in the 3D view first."); return
                fvec = FreeCAD.Vector(self.fx.value(), self.fy.value(), self.fz.value())
                if fvec.Length < 1e-9:
                    info("Load is zero."); return
                doc.openTransaction("DynFrame: nodal load")
                _apply_nodal(doc, case, fvec, pts); doc.commitTransaction()
            else:
                elems = selected_elems()
                if not elems:
                    info("Select bars (lines) in the 3D view first."); return
                doc.openTransaction("DynFrame: line load")
                _apply_line(doc, case, FreeCAD.Vector(0, 0, self.w.value()), elems)
                doc.commitTransaction()
            doc.recompute(); self._refresh()

        def _autocombo(self):
            uls, sls = _auto_combos(self._doc()); self._doc().recompute()
            info("ULS1 = %s\nSLS1 = %s" % (uls or "-", sls or "-")); self._refresh()

        def _calc(self):
            RunAnalysis().Activated(run_pick=self.run.currentText(),
                                    include_sw=self.sw.isChecked(),
                                    second_order=self.po.isChecked())
            self._refresh()

        def _modal(self):
            ModalAnalysis().Activated(); self._refresh()

        def _buckling(self):
            BucklingAnalysis().Activated(); self._refresh()

        def _seismic(self):
            ResponseSpectrum().Activated(); self._refresh()

        def _codecheck(self):
            CodeCheck().Activated(); self._refresh()

        def _envelope(self):
            Envelope().Activated(); self._refresh()

        def _show(self):
            lab = self.res.currentText()
            kind = RESULT_ORDER[[RESULT_LABELS[k] for k in RESULT_ORDER].index(lab)]
            ShowDiagram().Activated(kind=kind)

        def _resviewer(self):
            ResultsViewer().Activated()

    return FrameAnalysisPanel


class Manager:
    def GetResources(self):
        return {"Pixmap": _icon("panel"), "MenuText": "Frame Analysis Panel",
                "ToolTip": "Open the single Frame Analysis panel - build the model, "
                           "supports, loads, cases, combinations, solve and switch "
                           "results, all in one window.", "Accel": "A, P"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        global _PANEL
        try:
            cls = _panel_class()
            _PANEL = cls()
            _PANEL.show(); _PANEL.raise_()
        except Exception as e:
            import traceback
            FreeCAD.Console.PrintError("DynFrame: panel failed\n" + traceback.format_exc())
            err("Could not open the panel (%s).\n\nUse the individual DynFrame "
                "toolbar commands instead." % e)


class ResultsViewer:
    def GetResources(self):
        return {"Pixmap": _icon("results"), "MenuText": "Results Viewer",
                "ToolTip": "Open the Results Viewer - a second, Inventor-style panel "
                           "to analyse and view results: pick a result (displacement, "
                           "forces, stress, mode / buckling / seismic shapes) to show "
                           "it as a coloured contour with a value legend, read the "
                           "max values, and scale or animate the deformed shape.",
                "Accel": "A, V"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        global _RESPANEL
        try:
            cls = _results_panel_class()
            _RESPANEL = cls()
            _RESPANEL.show(); _RESPANEL.raise_()
        except Exception as e:
            import traceback
            FreeCAD.Console.PrintError("DynFrame: results viewer failed\n"
                                       + traceback.format_exc())
            err("Could not open the Results Viewer (%s).\n\nUse 'Show Result / "
                "Diagram' from the toolbar instead." % e)


def _parse_spacings(s):
    """'5000,5000,5000' or Robot-style '3@5000' or '3@5000,2@4000' -> list of
    bay/storey lengths."""
    out = []
    for tok in str(s).replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "@" in tok:
            n, v = tok.split("@", 1)
            try:
                d = float(v)
                if d > 1e-6:
                    out += [d] * int(float(n))
            except Exception:
                pass
        else:
            try:
                d = float(tok)
                if d > 1e-6:                 # drop zero / blank / negative bays
                    out.append(d)
            except Exception:
                pass
    return out


def _cumulative(spac):
    pos = [0.0]
    for d in spac:
        pos.append(pos[-1] + d)
    return pos


class GridGen:
    def GetResources(self):
        return {"Pixmap": _icon("grid"), "MenuText": "Generate Grid Structure",
                "ToolTip": "Create a rectangular 3D grid of bars (columns + beams) "
                           "from bay spacings and storey heights - for sheds, portal "
                           "frames and multi-storey / high-rise frames. Accepts "
                           "Robot-style '3@5000' (3 bays of 5000).", "Accel": "A, R"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        vals = form_dialog("Generate Grid Structure", [
            {"key": "_i", "kind": "info", "default":
             "Spacings = comma-separated bay lengths (mm).\n"
             "  Unequal bays:  5000,4000,6000\n"
             "  Equal bays:    3@5000  (= 5000,5000,5000)\n"
             "  Mix:           3@5000,4000\n"
             "Leave Y EMPTY for a flat 2D frame (one plane)."},
            {"key": "x", "label": "X bay spacings", "kind": "text", "default": "5000,4000,5000"},
            {"key": "y", "label": "Y bay spacings", "kind": "text", "default": "4000"},
            {"key": "z", "label": "Storey heights", "kind": "text", "default": "3500,3500"},
            {"key": "sec", "label": "Section", "kind": "section"},
            {"key": "mat", "label": "Material", "kind": "combo",
             "options": list(MATERIALS.keys()), "default": DEFAULT_MAT},
            {"key": "cols", "label": "Columns", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
            {"key": "fbeam", "label": "Floor beams (every storey)", "kind": "combo",
             "options": ["Yes", "No"], "default": "Yes"},
            {"key": "gbeam", "label": "Ground beams (z = 0)", "kind": "combo",
             "options": ["No", "Yes"], "default": "No"},
        ])
        if not vals:
            return
        X = _cumulative(_parse_spacings(vals["x"]) or [5000.0])
        Y = _cumulative(_parse_spacings(vals["y"]) or [4000.0])
        Z = _cumulative(_parse_spacings(vals["z"]) or [3500.0])
        sec = vals["sec"] or "IPE 200"
        mat = vals["mat"]
        want_cols = vals["cols"] == "Yes"
        want_floor = vals["fbeam"] == "Yes"
        want_ground = vals["gbeam"] == "Yes"
        if not profiles.builder_for(sec):
            warn("Section '%s' not found in the library." % sec)
            return

        def V(ix, iy, iz):
            return FreeCAD.Vector(X[ix], Y[iy], Z[iz])

        doc.openTransaction("DynFrame: grid structure")
        grp = _grp(doc, STR_GROUP)
        n = 0
        # columns
        if want_cols:
            for ix in range(len(X)):
                for iy in range(len(Y)):
                    for iz in range(len(Z) - 1):
                        _make_bar(doc, V(ix, iy, iz), V(ix, iy, iz + 1), sec, mat, grp); n += 1
        # beams at chosen z-levels
        levels = []
        if want_ground:
            levels.append(0)
        if want_floor:
            levels += list(range(1, len(Z)))
        for iz in sorted(set(levels)):
            for iy in range(len(Y)):                      # X-direction beams
                for ix in range(len(X) - 1):
                    _make_bar(doc, V(ix, iy, iz), V(ix + 1, iy, iz), sec, mat, grp); n += 1
            for ix in range(len(X)):                      # Y-direction beams
                for iy in range(len(Y) - 1):
                    _make_bar(doc, V(ix, iy, iz), V(ix, iy + 1, iz), sec, mat, grp); n += 1
        doc.commitTransaction()
        doc.recompute()
        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Generated a %dx%d bay, %d-storey grid: %d bars (%s, %s).\n\nAdd "
             "supports at the base nodes, loads, then Calculate." %
             (len(X) - 1, len(Y) - 1, len(Z) - 1, n, sec, mat))


def _color_bar(doc, grp, vmin, vmax, title, objs, msize):
    """A colour-ramp bar with numeric value labels (min..max), placed at the
    model corner - the result legend. Rebuilt whenever the shown result
    changes, so the numbers always match the visible contour/diagram."""
    # remove any previous legend + its labels
    for o in list(doc.Objects):
        if o.Name.startswith("Legend") or getattr(o, "DiagKind", None) == "_legend":
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass
    try:
        bb = None
        for o in objs:
            try:
                b = o.Shape.BoundBox
            except Exception:
                continue
            bb = b if bb is None else bb.united(b)
        if bb is None:
            return
        x0 = bb.XMax + msize * 0.08; y0 = bb.YMin; z0 = bb.ZMin
        h = msize * 0.6; w = msize * 0.075; nseg = 12
        # one object per band with a plain ShapeColor (reliable gradient)
        for s in range(nseg):
            z1 = z0 + h * s / nseg; z2 = z0 + h * (s + 1) / nseg
            f = _polyface([FreeCAD.Vector(x0, y0, z1), FreeCAD.Vector(x0 + w, y0, z1),
                           FreeCAD.Vector(x0 + w, y0, z2), FreeCAD.Vector(x0, y0, z2)])
            if f is None:
                continue
            lg = doc.addObject("Part::Feature", "Legend_b%d" % s)
            lg.Shape = f
            lg.Label = "Legend: " + title
            _set(lg, "App::PropertyString", "DiagKind", "_legend")
            try:
                lg.ViewObject.ShapeColor = _ramp(s / float(nseg - 1))
            except Exception:
                pass
            grp.addObject(lg)
        fs = max(12.0, msize * 0.045)
        nlab = 6
        for i in range(nlab + 1):
            frac = i / float(nlab); val = vmin + (vmax - vmin) * frac
            _label_text(doc, grp, "%.4g" % val,
                        FreeCAD.Vector(x0 + w + msize * 0.02, y0, z0 + h * frac - fs * 0.5),
                        "_legend", fontsize=fs)
        _label_text(doc, grp, title,
                    FreeCAD.Vector(x0, y0, z0 + h + msize * 0.05), "_legend",
                    fontsize=max(13.0, msize * 0.05))
    except Exception:
        pass


def _label_text(doc, grp, text, point, kind, fontsize=12.0):
    """Add a Draft text annotation (graceful if Draft is unavailable or its API
    differs between FreeCAD versions)."""
    try:
        import Draft
    except Exception:
        return None
    pt = FreeCAD.Vector(point)
    t = None
    for call in (
        lambda: Draft.make_text([text], FreeCAD.Placement(pt, FreeCAD.Rotation())),
        lambda: Draft.make_text([text], pt),
        lambda: Draft.makeText([text], pt),
    ):
        try:
            t = call()
        except Exception:
            t = None
        if t is not None:
            break
    if t is None:
        return None
    try:
        if not hasattr(t, "DiagKind"):
            t.addProperty("App::PropertyString", "DiagKind", "DynFrame", "DiagKind")
        t.DiagKind = kind
    except Exception:
        pass
    try:
        t.ViewObject.FontSize = fontsize
    except Exception:
        pass
    if grp is not None:
        try:
            grp.addObject(t)
        except Exception:
            pass
    return t


def _polyline(pts):
    """Part.makePolygon over points with consecutive near-duplicates removed
    (a zero value at a support makes the baseline and first sample coincide,
    which makePolygon rejects). Returns a wire or None."""
    clean = []
    for p in pts:
        if not clean or (p - clean[-1]).Length > 1e-7:
            clean.append(p)
    if len(clean) < 2:
        return None
    try:
        return Part.makePolygon(clean)
    except Exception:
        return None


def _polyface(pts):
    clean = []
    for p in pts:
        if not clean or (p - clean[-1]).Length > 1e-7:
            clean.append(p)
    if len(clean) < 3:
        return None
    try:
        return Part.Face(Part.makePolygon(clean + [clean[0]]))
    except Exception:
        return None


# Per-face colours of result objects, kept so they can be RE-APPLIED after a
# doc.recompute(): FreeCAD resets ViewObject.DiffuseColor to a single colour
# when a touched object is recomputed, which is what made every bar show one
# flat colour instead of the gradient. _apply_result_colors() restores them.
_RESULT_COLORS = {}


def _apply_result_colors(doc):
    """Re-apply the stored per-face colours to result objects and force a
    shaded (edge-free) display, so the gradient survives recompute and is not
    hidden behind wireframe edge rings."""
    for name in list(_RESULT_COLORS.keys()):
        o = doc.getObject(name)
        if o is None:
            _RESULT_COLORS.pop(name, None)
            continue
        colors = _RESULT_COLORS[name]
        try:
            if len(colors) == len(o.Shape.Faces):
                o.ViewObject.DiffuseColor = colors
        except Exception:
            pass
        try:
            o.ViewObject.DisplayMode = "Shaded"
        except Exception:
            pass


_PROFILE_FACE_CACHE = {}


def _profile_face(sec):
    """Cached cross-section face (centred, in the local XY plane) for a section
    name, used to sweep solid beams for the result contour."""
    if sec in _PROFILE_FACE_CACHE:
        return _PROFILE_FACE_CACHE[sec]
    f = None
    try:
        f = build_face(sec, "Center", 0.0, 0.0)
    except Exception:
        f = None
    _PROFILE_FACE_CACHE[sec] = f
    return f


def _segment_solid(face, a, b):
    """A short solid beam: the section `face` swept from point a to point b,
    oriented along a->b (so results can be shown on the real beam shape, the
    Inventor look). None on failure (caller falls back to a tube)."""
    try:
        d = b - a; L = d.Length
        if L < 1e-6:
            return None
        seg = face.extrude(FreeCAD.Vector(0, 0, L))
        seg.Placement = orient_placement(a, d, 0.0)
        return seg
    except Exception:
        return None


_NBAND = 16


def _emit_bands(doc, grp, name, kind, vmax, bands, visible, line, lw=6):
    """Create one object per non-empty colour band. `line=True` makes thick
    coloured WIRE objects (LineColor); these render reliably everywhere (the
    way the animation wires do), which is what makes the gradient actually
    show. `line=False` makes solid objects coloured with ShapeColor."""
    first = None
    for k, segs in enumerate(bands):
        if not segs:
            continue
        ob = doc.addObject("Part::Feature", "%s_b%d" % (name, k))
        ob.Shape = Part.makeCompound(segs)
        ob.Label = "%s result" % kind
        _set(ob, "App::PropertyString", "DiagKind", kind)
        _set(ob, "App::PropertyFloat", "CompMax", float(vmax))
        _set(ob, "App::PropertyFloat", "CompMin", 0.0)
        col = _ramp((k + 0.5) / _NBAND)
        try:
            ob.ViewObject.Visibility = bool(visible)
            if line:
                ob.ViewObject.LineColor = col
                ob.ViewObject.LineWidth = lw
                try:
                    ob.ViewObject.PointColor = col
                except Exception:
                    pass
            else:
                ob.ViewObject.ShapeColor = col
                ob.ViewObject.LineColor = col
        except Exception:
            pass
        if grp is not None:
            grp.addObject(ob)
        if first is None:
            first = ob
    return first


def _result_tube(doc, grp, name, kind, perbar, radius, vmax, visible,
                 sections=None, dirs=None, solid=False):
    """Render a result as the structure coloured blue->red by |value|, binned
    into colour bands (one object per band) so the colour varies ALONG every
    bar. Default: thick coloured WIRES (LineColor) - these render reliably on
    every machine, which is what makes the gradient show. With solid=True it
    draws solid tubes / the members' real swept profiles (the Inventor look),
    for users whose display shows shaded solids. `perbar` is a list of
    (points, values) per bar."""
    bands = [[] for _ in range(_NBAND)]
    for bi, (pts, vals) in enumerate(perbar):
        face = None
        if solid and sections is not None and bi < len(sections):
            face = _profile_face(sections[bi])
        for i in range(len(pts) - 1):
            a = pts[i]; b = pts[i + 1]; v = b - a; ln = v.Length
            if ln < 1e-6:
                continue
            t = (0.5 * (abs(vals[i]) + abs(vals[i + 1])) / vmax) if vmax > 1e-12 else 0.0
            k = min(_NBAND - 1, max(0, int(t * _NBAND)))
            if solid:
                seg = _segment_solid(face, a, b) if face is not None else None
                if seg is None:
                    try:
                        seg = Part.makeCylinder(radius, ln, a, unit(v))
                    except Exception:
                        continue
            else:
                try:
                    seg = Part.makePolygon([FreeCAD.Vector(a), FreeCAD.Vector(b)])
                except Exception:
                    continue
            bands[k].append(seg)
    return _emit_bands(doc, grp, name, kind, vmax, bands, visible,
                       line=(not solid), lw=max(5, int(radius > 0) * 6))


def _build_plate_stress(doc, grp, shells, vmmax, visible=False):
    """Plate/shell von Mises stress contour: each triangle binned into a colour
    band and drawn with a plain ShapeColor (one object per band), so the stress
    gradient across the plate reliably shows."""
    for o in list(doc.Objects):
        if o.Name.startswith("PlateStress"):
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass
    NBAND = 16
    bands = [[] for _ in range(NBAND)]
    for sh in shells:
        pervm = sh.get("pervm", [])
        for k, (ni, pts) in enumerate(sh["tris"]):
            try:
                f = Part.Face(Part.makePolygon(
                    [FreeCAD.Vector(pts[0]), FreeCAD.Vector(pts[1]),
                     FreeCAD.Vector(pts[2]), FreeCAD.Vector(pts[0])]))
            except Exception:
                continue
            vm = pervm[k] if k < len(pervm) else 0.0
            t = (vm / vmmax) if vmmax > 1e-12 else 0.0
            bands[min(NBAND - 1, max(0, int(t * NBAND)))].append(f)
    first = None
    for k, fs in enumerate(bands):
        if not fs:
            continue
        ob = doc.addObject("Part::Feature", "PlateStress_b%d" % k)
        ob.Shape = Part.makeCompound(fs)
        ob.Label = "Plate stress (von Mises, MPa)"
        _set(ob, "App::PropertyString", "DiagKind", "_plate")
        _set(ob, "App::PropertyFloat", "CompMax", float(vmmax))
        _set(ob, "App::PropertyFloat", "CompMin", 0.0)
        col = _ramp((k + 0.5) / NBAND)
        try:
            ob.ViewObject.Visibility = bool(visible)
            ob.ViewObject.ShapeColor = col
            ob.ViewObject.LineColor = col           # coloured edges as a fallback
            ob.ViewObject.LineWidth = 2
        except Exception:
            pass
        if grp is not None:
            grp.addObject(ob)
        if first is None:
            first = ob
    return first


def _build_plate_field(doc, grp, shells, comp, vmin, vmax, label, visible=False):
    """Generic plate scalar-field contour for one per-triangle component
    (key 'per'+comp): each triangle binned into a colour band over [vmin, vmax]
    and drawn with a plain ShapeColor, one object per band (reliable gradient).
    Used for the signed bending moments Mx/My/Mxy, the principal moments M1/M2
    and the one-signed Wood-Armer reinforcement moments."""
    dk = "_plate" + comp; key = "per" + comp
    for o in list(doc.Objects):
        if o.Name.startswith("Plate" + comp + "_b"):
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass
    NBAND = 16
    bands = [[] for _ in range(NBAND)]
    span = (vmax - vmin) or 1.0
    for sh in shells:
        vals = sh.get(key, [])
        for k, (ni, pts) in enumerate(sh["tris"]):
            try:
                f = Part.Face(Part.makePolygon(
                    [FreeCAD.Vector(pts[0]), FreeCAD.Vector(pts[1]),
                     FreeCAD.Vector(pts[2]), FreeCAD.Vector(pts[0])]))
            except Exception:
                continue
            v = vals[k] if k < len(vals) else 0.0
            t = (v - vmin) / span
            bands[min(NBAND - 1, max(0, int(t * NBAND)))].append(f)
    first = None
    for k, fs in enumerate(bands):
        if not fs:
            continue
        ob = doc.addObject("Part::Feature", "Plate%s_b%d" % (comp, k))
        ob.Shape = Part.makeCompound(fs)
        ob.Label = label
        _set(ob, "App::PropertyString", "DiagKind", dk)
        _set(ob, "App::PropertyFloat", "CompMax", float(vmax))
        _set(ob, "App::PropertyFloat", "CompMin", float(vmin))
        col = _ramp((k + 0.5) / NBAND)
        try:
            ob.ViewObject.Visibility = bool(visible)
            ob.ViewObject.ShapeColor = col
            ob.ViewObject.LineColor = col
            ob.ViewObject.LineWidth = 2
        except Exception:
            pass
        if grp is not None:
            grp.addObject(ob)
        if first is None:
            first = ob
    return first


# plate contour fields, in Results-Viewer order: (component key, signed?, label)
PLATE_FIELDS = [
    ("Mx",   True,  "Plate Mx - bending (N.mm/mm)"),
    ("My",   True,  "Plate My - bending (N.mm/mm)"),
    ("Mxy",  True,  "Plate Mxy - twisting (N.mm/mm)"),
    ("M1",   True,  "Plate M1 - principal max (N.mm/mm)"),
    ("M2",   True,  "Plate M2 - principal min (N.mm/mm)"),
    ("WAxb", False, "Plate Wood-Armer bottom X (N.mm/mm)"),
    ("WAyb", False, "Plate Wood-Armer bottom Y (N.mm/mm)"),
    ("WAxt", False, "Plate Wood-Armer top X (N.mm/mm)"),
    ("WAyt", False, "Plate Wood-Armer top Y (N.mm/mm)"),
]


def _build_plate_trajectories(doc, grp, shells, peak1, peak2, visible=False):
    """Principal-moment trajectory plots: at each plate triangle a short line
    along the major (M1) and minor (M2) principal moment directions, length
    scaled by the moment magnitude. Two wire objects (M1 red, M2 blue) - the
    'flow of forces' in a slab, which bottom/top reinforcement should follow."""
    import math
    import numpy as np
    for (fam, dk, comp, col, peak) in (
            (1, "_plateT1", "M1", (0.85, 0.15, 0.1), peak1),
            (2, "_plateT2", "M2", (0.1, 0.3, 0.85), peak2)):
        for o in list(doc.Objects):
            if o.Name.startswith("PlateTraj%d" % fam):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        segs = []
        for sh in shells:
            Ex = sh.get("Ex"); Ey = sh.get("Ey")
            if Ex is None:
                continue
            for (cen, mxx, myy, mxy, m1, m2, clen) in sh.get("traj", []):
                th = _principal_angle(mxx, myy, mxy) + (math.pi / 2 if fam == 2 else 0.0)
                dire = math.cos(th) * Ex + math.sin(th) * Ey
                mag = abs(m1 if fam == 1 else m2)
                frac = (mag / peak) if peak > 1e-12 else 0.0
                half = 0.45 * clen * max(0.12, min(1.0, 0.15 + 0.85 * frac))
                dv = FreeCAD.Vector(float(dire[0]), float(dire[1]), float(dire[2]))
                try:
                    segs.append(Part.makeLine(FreeCAD.Vector(cen - vscale(dv, half)),
                                              FreeCAD.Vector(cen + vscale(dv, half))))
                except Exception:
                    pass
        if not segs:
            continue
        ob = doc.addObject("Part::Feature", "PlateTraj%d" % fam)
        try:
            ob.Shape = Part.makeCompound(segs)
        except Exception:
            continue
        ob.Label = "Plate %s trajectories (N.mm/mm)" % comp
        _set(ob, "App::PropertyString", "DiagKind", dk)
        _set(ob, "App::PropertyFloat", "CompMax", float(peak))
        _set(ob, "App::PropertyFloat", "CompMin", 0.0)
        try:
            ob.ViewObject.Visibility = bool(visible)
            ob.ViewObject.LineColor = col
            ob.ViewObject.LineWidth = 3
        except Exception:
            pass
        if grp is not None:
            grp.addObject(ob)


def _build_plate_fields(doc, grp, shells, mom_peak, visible=False):
    """Build every plate moment / principal / Wood-Armer contour (hidden),
    each scaled to its own peak: signed fields over -peak..+peak, one-signed
    Wood-Armer fields over 0..peak (bottom) or -peak..0 (top)."""
    for (comp, signed, label) in PLATE_FIELDS:
        pk = float(mom_peak.get(comp, 0.0))
        if signed:
            vmin, vmax = -pk, pk
        elif comp.endswith("t"):          # top: hogging, values <= 0
            vmin, vmax = -pk, 0.0
        else:                             # bottom: sagging, values >= 0
            vmin, vmax = 0.0, pk
        _build_plate_field(doc, grp, shells, comp, vmin, vmax, label, visible=visible)


class RebuildFromSketch:
    def GetResources(self):
        return {"Pixmap": _icon("rebuild"), "MenuText": "Rebuild Members from Sketch",
                "ToolTip": "Re-fit members to their source sketch edges after you "
                           "move the sketch. Regenerates members (per-member "
                           "miters/trims are reset).", "Accel": "F, U"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        sel = [m for m in selected_members() if is_member(m) and getattr(m, "MemberSource", "")]
        members = sel or [o for o in doc.Objects if is_member(o) and getattr(o, "MemberSource", "")]
        if not members:
            info("No members are linked to a sketch.\n\nMembers created with "
                 "Insert Frame Members (by selecting sketch/edge geometry) remember "
                 "their source and can be rebuilt here.")
            return
        rebuilt = skipped = 0
        doc.openTransaction("DynFrame: rebuild from sketch")
        for m in members:
            src = doc.getObject(getattr(m, "MemberSource", ""))
            idx = int(getattr(m, "MemberSourceIndex", 0) or 0)
            if src is None or getattr(src, "Shape", None) is None or idx < 1:
                skipped += 1
                continue
            try:
                g = global_shape(src)
                e = g.Edges[idx - 1]
                a = FreeCAD.Vector(e.Vertexes[0].Point)
                b = FreeCAD.Vector(e.Vertexes[-1].Point)
            except Exception:
                skipped += 1
                continue
            if rebuild_member(m, a, b, getattr(m, "MemberProfile", ""),
                              float(getattr(m, "MemberTwist", 0.0)),
                              getattr(m, "MemberAlign", "Center"),
                              float(getattr(m, "MemberOffX", 0.0)),
                              float(getattr(m, "MemberOffY", 0.0))):
                rebuilt += 1
            else:
                skipped += 1
        doc.commitTransaction()
        doc.recompute()
        info("Rebuilt %d member(s) from their sketch%s.\n\nNote: this regenerates "
             "members from the current sketch geometry, so any per-member miters, "
             "trims or holes are reset — re-apply them after." %
             (rebuilt, "" if skipped == 0 else " (%d skipped)" % skipped))


# ── register ─────────────────────────────────────────────────────
def _add(name, cls):
    try:
        FreeCADGui.addCommand(name, cls())
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: add %s failed (%s)\n" % (name, e))


_add("DynFrame_InsertMembers", InsertMembers)
_add("DynFrame_RebuildFromSketch", RebuildFromSketch)
_add("DynFrame_ChangeProfile", ChangeProfile)
_add("DynFrame_LengthenShorten", LengthenShorten)
_add("DynFrame_TrimButt", TrimButt)
_add("DynFrame_Miter", Miter)
_add("DynFrame_MirrorMembers", MirrorMembers)
_add("DynFrame_RectPattern", RectPattern)
_add("DynFrame_CircPattern", CircPattern)
_add("DynFrame_BOM", BOM)
_add("DynFrame_Manager", Manager)
_add("DynFrame_GridGen", GridGen)
_add("DynFrame_AddBars", AddBars)
_add("DynFrame_BarsFromMembers", BarsFromMembers)
_add("DynFrame_EditTables", EditTables)
_add("DynFrame_BuildFromTables", BuildFromTables)
_add("DynFrame_NewLoadCase", NewLoadCase)
_add("DynFrame_DefineSupport", DefineSupport)
_add("DynFrame_AddNodalLoad", AddNodalLoad)
_add("DynFrame_AddMemberLoad", AddMemberLoad)
_add("DynFrame_AddSettlement", AddSettlement)
_add("DynFrame_AddPlate", AddPlate)
_add("DynFrame_AddPlateLoad", AddPlateLoad)
_add("DynFrame_AddWindLoad", AddWindLoad)
_add("DynFrame_AddImperfection", AddImperfection)
_add("DynFrame_Combinations", Combinations)
_add("DynFrame_MemberReleases", MemberReleases)
_add("DynFrame_MemberType", MemberType)
_add("DynFrame_PlateReinfEC2", PlateReinfEC2)
_add("DynFrame_PunchingEC2", PunchingEC2)
_add("DynFrame_RcBeamEC2", RcBeamEC2)
_add("DynFrame_RcColumnEC2", RcColumnEC2)
_add("DynFrame_PadFootingEC2", PadFootingEC2)
_add("DynFrame_TimberEC5", TimberEC5)
_add("DynFrame_BasePlateEC3", BasePlateEC3)
_add("DynFrame_BoltedConnEC3", BoltedConnEC3)
_add("DynFrame_FilletWeldEC3", FilletWeldEC3)
_add("DynFrame_MasonryEC6", MasonryEC6)
_add("DynFrame_CombinedFootingEC2", CombinedFootingEC2)
_add("DynFrame_AiscSteel", AiscSteel)
_add("DynFrame_AluminiumEC9", AluminiumEC9)
_add("DynFrame_PlasticCollapse", PlasticCollapse)
_add("DynFrame_TorsionCheckEC3", TorsionCheckEC3)
_add("DynFrame_Pushover", Pushover)
_add("DynFrame_DeflectionCheck", DeflectionCheck)
_add("DynFrame_WallThermal", WallThermal)
_add("DynFrame_ThermalBridge2D", ThermalBridge2D)
_add("DynFrame_FireThermal", FireThermal)
_add("DynFrame_CfdStudy", CfdStudy)
_add("DynFrame_CfdAssignBC", CfdAssignBC)
_add("DynFrame_CfdFlowInternal", CfdFlowInternal)
_add("DynFrame_CfdCase", CfdCase)
_add("DynFrame_CfdDomain", CfdDomain)
_add("DynFrame_CfdMeshFromCad", CfdMeshFromCad)
_add("DynFrame_CfdFlow", CfdFlow)
_add("DynFrame_CfdView", CfdView)
_add("DynFrame_CfdGallery", CfdGallery)
_add("DynFrame_CfdExamples", CfdExamples)
_add("DynFrame_RunAnalysis", RunAnalysis)
_add("DynFrame_ModalAnalysis", ModalAnalysis)
_add("DynFrame_BucklingAnalysis", BucklingAnalysis)
_add("DynFrame_ResponseSpectrum", ResponseSpectrum)
_add("DynFrame_Envelope", Envelope)
_add("DynFrame_MovingLoad", MovingLoad)
_add("DynFrame_ImportGroundMotion", ImportGroundMotion)
_add("DynFrame_GMSpectrum", GMSpectrum)
_add("DynFrame_TimeHistory", TimeHistory)
_add("DynFrame_CodeCheck", CodeCheck)
_add("DynFrame_ShowDiagram", ShowDiagram)
_add("DynFrame_ResultsViewer", ResultsViewer)
_add("DynFrame_ClearAnalysis", ClearAnalysis)
_add("DynFrame_TrimToFace", TrimToFace)
_add("DynFrame_ExtendToFace", ExtendToFace)
_add("DynFrame_CutList", CutList)
_add("DynFrame_Hole", HoleFeature)
_add("DynFrame_QuickFillet", QuickFillet)
_add("DynFrame_ExportStep", ExportStep)
_add("DynFrame_ExportStl", ExportStl)
_add("DynFrame_Skeleton3D", Skeleton3D)
_add("DynFrame_ConstrainedSketch", ConstrainedSketch)
_add("DynFrame_InventorNav", InventorNav)
