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


def form_dialog(title, fields):
    """One modal form instead of a chain of pop-ups. `fields` is a list of
    dicts: {key, label, kind, default, options, min, max, decimals}. kind is
    one of 'text', 'float', 'int', 'combo', 'section', 'info'. Returns a
    {key: value} dict, or None if cancelled. 'section' is a profile picker
    (family + size combos). 'info' is a read-only label row."""
    d = QW.QDialog(_mw())
    d.setWindowTitle(title)
    outer = QW.QVBoxLayout(d)
    form = QW.QFormLayout()
    widgets = {}
    fam_combo = {}
    for f in fields:
        k = f.get("key"); kind = f.get("kind", "text"); lab = f.get("label", k or "")
        if kind == "info":
            w = QW.QLabel(str(f.get("default", "")))
            w.setWordWrap(True)
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
        return {"Pixmap": _icon("member"), "MenuText": "Change Profile / Align",
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
        return {"Pixmap": _icon("trim"), "MenuText": "Trim to Face / Plane",
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
        return {"Pixmap": _icon("lengthen"), "MenuText": "Lengthen / Shorten to Face",
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
        return {"Pixmap": _icon("export"), "MenuText": "Export each body to STL",
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
        return {"Pixmap": _icon("cutlist"), "MenuText": "Bill of Materials",
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


def _section_props_from_name(name):
    """Section properties (A, Iy, Iz, J, c) from a profile name in the library.
    Works for both solid members and line bars (the analysis entity carries a
    section name, never a swept solid)."""
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


# ── materials (name -> E, G, Fy, density) in N/mm^2 and kg/mm^3 ──────
MATERIALS = {
    "Steel S235": (210000.0, 80769.0, 235.0, 7.85e-6),
    "Steel S275": (210000.0, 80769.0, 275.0, 7.85e-6),
    "Steel S355": (210000.0, 80769.0, 355.0, 7.85e-6),
    "Stainless 304": (193000.0, 74000.0, 215.0, 7.90e-6),
    "Aluminium 6061-T6": (70000.0, 26000.0, 240.0, 2.70e-6),
}
DEFAULT_MAT = "Steel S235"


def _material(name):
    """Return (E, G, Fy, rho) for a material name, defaulting to steel."""
    return MATERIALS.get(name, MATERIALS[DEFAULT_MAT])


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


def _grp(doc, label):
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label == label:
            return o
    g = doc.addObject("App::DocumentObjectGroup", label.replace(" ", ""))
    g.Label = label
    return g


def _meta(doc):
    o = doc.getObject(META_NAME)
    if o is None:
        o = doc.addObject("App::DocumentObjectGroup", META_NAME)
        o.Label = "Analysis Setup"
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
        return {"Pixmap": _icon("bar"), "MenuText": "Bars from Members",
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
        return {"Pixmap": _icon("table"), "MenuText": "Build from Tables",
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


def _apply_nodal(doc, case, fvec, pts):
    grp = _grp(doc, LOAD_GROUP)
    objs, _k = _analysis_objs(doc)
    ln = _model_size(objs) * 0.15 + 100.0
    fvec = FreeCAD.Vector(fvec)
    dirn = unit(fvec)
    for p in pts:
        p = FreeCAD.Vector(p)
        tail = p - vscale(dirn, ln)
        shaft = Part.makeLine(FreeCAD.Vector(tail), FreeCAD.Vector(p))
        head = Part.makeCone(ln * 0.12, 0.0, ln * 0.25,
                             p - vscale(dirn, ln * 0.25), dirn)
        o = doc.addObject("Part::Feature", "NodalLoad")
        o.Shape = Part.makeCompound([shaft, head])
        o.Label = "%s: (%.0f,%.0f,%.0f)N" % (case, fvec.x, fvec.y, fvec.z)
        _set(o, "App::PropertyString", "LoadType", "Nodal")
        _set(o, "App::PropertyString", "LoadCase", case)
        _set(o, "App::PropertyVector", "LoadVec", fvec)
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


class DefineSupport:
    def GetResources(self):
        return {"Pixmap": _icon("support"), "MenuText": "Define Support",
                "ToolTip": "Select joint vertices (bar node points), then apply a "
                           "support (Fixed / Pinned / Roller). Blue cone. Supports "
                           "are global (shared by every case).", "Accel": "A, S"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        pts = _sel_vertices()
        if not pts:
            info("Select one or more joint vertices (a bar end point), then run "
                 "Define Support.")
            return
        t, ok = get_item("Define Support", "Support type:",
                         list(SUPPORT_TYPES.keys()), 0)
        if not ok:
            return
        doc = FreeCAD.ActiveDocument
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
        pts = _sel_vertices()
        if not pts:
            info("Select one or more joint vertices, then add a nodal load.")
            return
        doc = FreeCAD.ActiveDocument
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Add Nodal Load (%d node(s))" % len(pts), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "fx", "label": "Fx (N)", "kind": "float", "default": 0.0},
            {"key": "fy", "label": "Fy (N)", "kind": "float", "default": 0.0},
            {"key": "fz", "label": "Fz (N, + up / - down)", "kind": "float", "default": -1000.0},
        ])
        if not vals:
            return
        fvec = FreeCAD.Vector(vals["fx"], vals["fy"], vals["fz"])
        if fvec.Length < 1e-9:
            warn("Load is zero - nothing added.")
            return
        doc.openTransaction("DynFrame: nodal load")
        _apply_nodal(doc, vals["case"], fvec, pts)
        doc.commitTransaction()
        doc.recompute()
        info("Nodal load added to case '%s' on %d node(s)." % (vals["case"], len(pts)))


class AddMemberLoad:
    def GetResources(self):
        return {"Pixmap": _icon("load"), "MenuText": "Add Bar Load",
                "ToolTip": "Select bars (lines) or members, then enter case + uniform "
                           "distributed load (N/mm along global Z) in one dialog.",
                "Accel": "A, M"}

    def IsActive(self):
        return bool(selected_elems())

    def Activated(self):
        elems = selected_elems()
        if not elems:
            info("Select one or more bars (lines) or members, then add a "
                 "distributed load.")
            return
        doc = FreeCAD.ActiveDocument
        cs = [c[0] for c in _cases(doc)]
        vals = form_dialog("Add Bar Load (%d bar(s))" % len(elems), [
            {"key": "case", "label": "Load case", "kind": "combo",
             "options": cs, "default": cs[-1]},
            {"key": "w", "label": "w (N/mm, global Z, + up / - down)",
             "kind": "float", "default": -5.0},
        ])
        if not vals or abs(vals["w"]) < 1e-12:
            return
        doc.openTransaction("DynFrame: bar load")
        _apply_line(doc, vals["case"], FreeCAD.Vector(0, 0, vals["w"]), elems)
        doc.commitTransaction()
        doc.recompute()
        info("Distributed load %.3g N/mm (Z) added to case '%s' on %d bar(s)."
             % (vals["w"], vals["case"], len(elems)))


class Combinations:
    def GetResources(self):
        return {"Pixmap": _icon("combo"), "MenuText": "Load Combinations",
                "ToolTip": "Generate simplified EN 1990 ULS (1.35G + 1.5Q) and SLS "
                           "(G + Q) combinations from the load cases, or add your own.",
                "Accel": "A, B"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        cases = _cases(doc)
        mode, ok = get_item("Load Combinations", "Action:",
                            ["Auto ULS + SLS (EN 1990)", "Add a custom combination",
                             "Clear all combinations"], 0)
        if not ok:
            return
        if mode.startswith("Clear"):
            _set_combos(doc, [])
            doc.recompute(); info("All combinations cleared."); return
        if mode.startswith("Auto"):
            dead = [n for n, nat in cases if nat == "Dead"]
            var = [n for n, nat in cases if nat in ("Live", "Wind", "Snow")]
            if not dead and not var:
                info("Define some load cases first (New Load Case)."); return
            uls = " + ".join(["1.35*%s" % d for d in dead] + ["1.5*%s" % q for q in var])
            sls = " + ".join(["1.0*%s" % c for c in (dead + var)])
            pairs = _combos(doc); have = {p[0] for p in pairs}
            if uls and "ULS1" not in have:
                pairs.append(("ULS1", uls))
            if sls and "SLS1" not in have:
                pairs.append(("SLS1", sls))
            _set_combos(doc, pairs); doc.recompute()
            info("Combinations generated:\n\nULS1 = %s\nSLS1 = %s\n\n(Simplified "
                 "EN 1990. Edit the 'Combinations' spreadsheet or add custom ones.)"
                 % (uls or "-", sls or "-"))
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


class RunAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("analysis"), "MenuText": "Calculate",
                "ToolTip": "Linear-static solve on the bar line model for a chosen "
                           "load case or combination. Produces reactions, deformed "
                           "shape, gradient N/V/M diagrams and result tables.",
                "Accel": "A, C"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self, run_pick=None, include_sw=None):
        import numpy as np
        doc = FreeCAD.ActiveDocument
        objs, kind = _analysis_objs(doc)
        if not objs:
            info("No bars or members found. Build a line model first (Add Bars, "
                 "Bars from Members, or Node/Bar Tables + Build from Tables).")
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
                          "sec": sec, "w": FreeCAD.Vector(0, 0, 0)})
        if not elems:
            info("Could not build an analysis model (check that bars have valid "
                 "section names).")
            return
        by_obj = {el["o"].Name: el for el in elems}

        fixed = set(); sup_nodes = []
        for o in doc.Objects:
            r = getattr(o, "Restrain", None); at = getattr(o, "AtNode", None)
            if r and at is not None:
                i = nid(FreeCAD.Vector(at), make=False)
                if i >= 0:
                    sup_nodes.append(i)
                    for k, ch in enumerate(r):
                        if ch == "1":
                            fixed.add(6 * i + k)
        if not fixed:
            err("No supports defined.\n\nSelect base node vertices and run "
                "'Define Support' (e.g. Fixed or Pinned), then Calculate.")
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
            if getattr(o, "LoadType", None) == "Member":
                f = factors.get(getattr(o, "LoadCase", ""), 0.0)
                el = by_obj.get(getattr(o, "OnMember", ""))
                if f and el is not None:
                    el["w"] = el["w"] + vscale(FreeCAD.Vector(getattr(o, "LoadVec")), f)
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
            K[np.ix_(dofs, dofs)] += T.T @ kl @ T
            w = el["w"]
            wl = T[0:3, 0:3] @ np.array([w.x, w.y, w.z])
            el["wx"], el["wy"], el["wz"] = float(wl[0]), float(wl[1]), float(wl[2])
            if w.Length > 1e-12:
                fl = _fef_udl(w, T[0:3, 0:3], L); el["fef"] = fl; F[dofs] += T.T @ fl
            else:
                el["fef"] = np.zeros(12)
        for o in doc.Objects:
            if getattr(o, "LoadType", None) == "Nodal":
                f = factors.get(getattr(o, "LoadCase", ""), 0.0)
                at = getattr(o, "AtNode", None)
                if f and at is not None:
                    i = nid(FreeCAD.Vector(at), make=False)
                    if i >= 0:
                        v = FreeCAD.Vector(getattr(o, "LoadVec"))
                        F[6 * i] += v.x * f; F[6 * i + 1] += v.y * f; F[6 * i + 2] += v.z * f

        free = [d for d in range(ndof) if d not in fixed]
        u = np.zeros(ndof)
        try:
            u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
        except Exception:
            err("The structure is a mechanism (unstable) with the supports given. "
                "Add more supports (or restrain more directions), then Calculate.")
            return
        Rreac = K @ u - F
        msize = _model_size(objs)
        maxd = max((u[6 * i] ** 2 + u[6 * i + 1] ** 2 + u[6 * i + 2] ** 2) ** 0.5
                   for i in range(len(nodes)))

        NS = 10
        comp_max = {k: 0.0 for k in DIAG_KINDS}
        comp_max["Disp"] = 0.0
        max_util = 0.0
        for el in elems:
            dloc = el["T"] @ u[el["dofs"]]; el["dloc"] = dloc
            fend = el["kl"] @ dloc - el["fef"]; el["fend"] = fend
            L = el["L"]; wy, wz, wx = el["wy"], el["wz"], el["wx"]
            A = el["A"]; c = el["c"]; Imin = min(el["Iy"], el["Iz"]); Fy = el["Fy"]

            def val(kind, x, fend=fend, L=L, wx=wx, wy=wy, wz=wz, A=A, c=c,
                    Imin=Imin):
                if kind == "N":
                    return -(fend[0] + wx * x)
                if kind == "Vy":
                    return fend[1] + wy * x
                if kind == "Vz":
                    return fend[2] + wz * x
                if kind == "Mx":
                    return -fend[3]
                if kind == "My":
                    return fend[4] * (1 - x / L) - fend[10] * (x / L) - wz * x * (L - x) / 2.0
                if kind == "Mz":
                    return -fend[5] * (1 - x / L) + fend[11] * (x / L) - wy * x * (L - x) / 2.0
                # Stress: axial + biaxial bending magnitude at x
                myx = fend[4] * (1 - x / L) - fend[10] * (x / L) - wz * x * (L - x) / 2.0
                mzx = -fend[5] * (1 - x / L) + fend[11] * (x / L) - wy * x * (L - x) / 2.0
                nx = -(fend[0] + wx * x)
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

        # ---- build visuals: colour the STRUCTURE by each result (thick tubes) ----
        # Every result (Displacement, N, Vy, Vz, Mx, My, Mz, Stress) is drawn as
        # the structure rendered in thick tube segments coloured blue->red by the
        # value along each bar - the Inventor/Robot contour look, visible from any
        # angle. Displacement uses the deformed shape; the rest use the real model.
        doc.openTransaction("DynFrame: results")
        for o in list(doc.Objects):
            if getattr(o, "DiagKind", None) is not None \
                    or o.Name.startswith(("Diagram_", "Result_", "DeformedShape",
                                          "Legend", "MomentDiagram")):
                try:
                    doc.removeObject(o.Name)
                except Exception:
                    pass
        rg = _grp(doc, RES_GROUP); dg = _grp(doc, DIA_GROUP)

        # deformed geometry + displacement magnitude per bar (cubic shape fns)
        maxoff = 0.0
        for el in elems:
            T = el["T"]; L = el["L"]; d = el["dloc"]; R3 = T[0:3, 0:3]
            lx = FreeCAD.Vector(*[float(R3[0][j]) for j in range(3)])
            ly = FreeCAD.Vector(*[float(R3[1][j]) for j in range(3)])
            lz = FreeCAD.Vector(*[float(R3[2][j]) for j in range(3)])
            base = nodes[el["n1"]]; statpts = []; offs = []; disp = []
            for s in range(NS + 1):
                xi = s / float(NS); x = L * xi
                n1 = 1 - 3 * xi ** 2 + 2 * xi ** 3; n2 = L * (xi - 2 * xi ** 2 + xi ** 3)
                n3 = 3 * xi ** 2 - 2 * xi ** 3; n4 = L * (-xi ** 2 + xi ** 3)
                ux = d[0] + (d[6] - d[0]) * xi
                uy = n1 * d[1] + n2 * d[5] + n3 * d[7] + n4 * d[11]
                uz = n1 * d[2] - n2 * d[4] + n3 * d[8] - n4 * d[10]
                off = vscale(lx, ux) + vscale(ly, uy) + vscale(lz, uz)
                statpts.append(base + vscale(lx, x)); offs.append(off); disp.append(off.Length)
                maxoff = max(maxoff, off.Length)
            el["statpts"] = statpts; el["offs"] = offs; el["disp"] = disp
            comp_max["Disp"] = max(comp_max["Disp"], max(disp))
        dscale = (0.08 * msize / maxoff) if maxoff > 1e-9 else 1.0
        for el in elems:
            el["defpts"] = [el["statpts"][s] + vscale(el["offs"][s], dscale)
                            for s in range(NS + 1)]

        radius = max(msize * 0.007, 2.0)
        default_kind = "Disp"
        for kind in ["Disp"] + DIAG_KINDS:
            cmax = comp_max[kind]
            if cmax < 1e-12:
                continue
            perbar = []
            for el in elems:
                if kind == "Disp":
                    perbar.append((el["defpts"], el["disp"]))
                else:
                    perbar.append((el["statpts"], [abs(v) for v in el["samp"][kind]]))
            grp = rg if kind == "Disp" else dg
            ob = _result_tube(doc, grp, "Diagram_%s" % kind, kind, perbar,
                              radius, cmax, kind == default_kind)
            if ob is None:
                continue
            ob.Label = ("Displacement (mm) x%.0f" % dscale) if kind == "Disp" \
                else "%s result" % kind
            # label the global peak of this result
            pk = 0.0; pkp = None
            for el in elems:
                vals = el["disp"] if kind == "Disp" else el["samp"][kind]
                pts = el["defpts"] if kind == "Disp" else el["statpts"]
                for s in range(NS + 1):
                    if abs(vals[s]) >= abs(pk):
                        pk = vals[s]; pkp = pts[s]
            if pkp is not None and abs(pk) > 1e-9:
                t = _label_text(doc, grp, "%s max %.4g" % (kind, pk),
                                pkp + FreeCAD.Vector(0, 0, radius * 2.5), kind,
                                fontsize=max(8.0, msize * 0.03))
                if t is not None:
                    try:
                        t.ViewObject.Visibility = (kind == default_kind)
                    except Exception:
                        pass
        _color_bar(doc, dg, 0.0, comp_max["Disp"], "Displacement (mm)", objs, msize)
        doc.commitTransaction()

        self._tables(doc, nodes, sup_nodes, Rreac, u, elems, run_name, rg, kind)

        try:
            FreeCADGui.activeDocument().activeView().viewAxonometric()
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        info("Analysis complete - %s  (line model, %d bars).\n\n"
             "Nodes %d | Restrained DOFs %d\n"
             "Max displacement:  %.3f mm\n"
             "Max |My| %.0f | Max |Mz| %.0f | Max |N| %.0f  N(.mm)\n"
             "Max utilisation:  %.2f  (stress / yield)\n\n"
             "Showing the DISPLACEMENT contour (deformed shape coloured blue->red "
             "by |u|, with a value colour bar). Use 'Show Force Diagram' to switch "
             "to N, Vy, Vz, Mx, My, Mz or Stress - the colour bar updates to that "
             "result. Tables: Reactions, Displacements, BarForces, plus your Nodes/"
             "Bars.\n\nLinear static only; modal / buckling / seismic / code-checks "
             "are later phases." %
             (run_name, len(elems), len(nodes), len(fixed), maxd,
              comp_max["My"], comp_max["Mz"], comp_max["N"], max_util))

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
                 "Mz": "Mz - bending minor (N.mm)", "Stress": "Stress - combined (MPa)"}
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
        diobjs = {getattr(o, "DiagKind"): o for o in doc.Objects
                  if getattr(o, "DiagKind", None) and not getattr(o, "DiagKind").startswith("_")}
        if not diobjs:
            info("No results yet. Run Calculate first."); return
        order = [k for k in RESULT_ORDER if k in diobjs]
        if kind is not None:
            sel = kind if kind in diobjs else None
        else:
            pick, ok = get_item("Show Result / Diagram", "Result:",
                                [RESULT_LABELS[k] for k in order] + ["(hide all)"], 0)
            if not ok:
                return
            if pick.startswith("(hide"):
                sel = None
            else:
                sel = order[[RESULT_LABELS[k] for k in order].index(pick)]
        for o in doc.Objects:
            k = getattr(o, "DiagKind", None)
            if not k or k.startswith("_"):
                continue
            try:
                o.ViewObject.Visibility = (k == sel)
            except Exception:
                pass
        # update the colour bar to the selected result's range
        if sel is not None:
            ob = diobjs[sel]
            vmax = float(getattr(ob, "CompMax", 1.0) or 1.0)
            vmin = float(getattr(ob, "CompMin", 0.0) or 0.0)
            objs, _k = _analysis_objs(doc)
            _color_bar(doc, _grp(doc, DIA_GROUP), vmin, vmax,
                       RESULT_LABELS[sel], objs, _model_size(objs))
        doc.recompute()


class ClearAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("analysis"), "MenuText": "Clear Results",
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
                      "ModalFrequencies", "CodeCheck")
        all_sheets = res_sheets + ("LoadCases", "Combinations", "AnalysisResults")
        to_del = []
        for o in list(doc.Objects):
            nm = o.Name
            is_res = (getattr(o, "DiagKind", None) is not None
                      or nm.startswith(("Diagram_", "DeformedShape", "Legend",
                                        "MomentDiagram", "Mode"))
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
                          max(msize * 0.007, 2.0), dmax, True)
        if ob is not None:
            ob.Label = "Mode 1  (%.3f Hz)" % freqs[0]
        doc.commitTransaction(); doc.recompute()
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
            r.addWidget(self._btn("Calculate", self._calc))
            r.addWidget(self._btn("Modal", self._modal))
            gl.addLayout(r)
            lay.addWidget(g)

            g, gl = self._box("7. Result shown")
            r = QW.QHBoxLayout()
            self.res = QW.QComboBox(); self.res.addItems([RESULT_LABELS[k] for k in RESULT_ORDER])
            r.addWidget(self.res, 1); r.addWidget(self._btn("Show", self._show))
            gl.addLayout(r)
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
            doc = self._doc(); pts = _sel_vertices()
            if not pts:
                info("Select one or more node vertices in the 3D view first."); return
            doc.openTransaction("DynFrame: support")
            _apply_support(doc, self.sup.currentText(), pts)
            doc.commitTransaction(); doc.recompute(); self._refresh()

        def _load(self):
            doc = self._doc(); case = self.case.currentText() or "DL1"
            if self.ltype.currentIndex() == 0:
                pts = _sel_vertices()
                if not pts:
                    info("Select node vertices in the 3D view first."); return
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
                                    include_sw=self.sw.isChecked())
            self._refresh()

        def _modal(self):
            ModalAnalysis().Activated(); self._refresh()

        def _show(self):
            lab = self.res.currentText()
            kind = RESULT_ORDER[[RESULT_LABELS[k] for k in RESULT_ORDER].index(lab)]
            ShowDiagram().Activated(kind=kind)

    return FrameAnalysisPanel


class Manager:
    def GetResources(self):
        return {"Pixmap": _icon("analysis"), "MenuText": "Frame Analysis Panel",
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
        x0 = bb.XMax + msize * 0.06; y0 = bb.YMin; z0 = bb.ZMin
        h = msize * 0.5; w = msize * 0.045; nseg = 10
        faces = []; colors = []
        for s in range(nseg):
            z1 = z0 + h * s / nseg; z2 = z0 + h * (s + 1) / nseg
            f = _polyface([FreeCAD.Vector(x0, y0, z1), FreeCAD.Vector(x0 + w, y0, z1),
                           FreeCAD.Vector(x0 + w, y0, z2), FreeCAD.Vector(x0, y0, z2)])
            if f is not None:
                faces.append(f); colors.append(_ramp(s / float(nseg - 1)) + (0.0,))
        if not faces:
            return
        lg = doc.addObject("Part::Feature", "Legend")
        lg.Shape = Part.makeCompound(faces)
        lg.Label = "Legend: " + title
        _set(lg, "App::PropertyString", "DiagKind", "_legend")
        try:
            if len(colors) == len(lg.Shape.Faces):
                lg.ViewObject.DiffuseColor = colors
        except Exception:
            pass
        grp.addObject(lg)
        fs = max(8.0, msize * 0.03)
        nlab = 5
        for i in range(nlab + 1):
            frac = i / float(nlab); val = vmin + (vmax - vmin) * frac
            _label_text(doc, grp, "%.4g" % val,
                        FreeCAD.Vector(x0 + w + msize * 0.012, y0, z0 + h * frac - fs * 0.5),
                        "_legend", fontsize=fs)
        _label_text(doc, grp, title,
                    FreeCAD.Vector(x0, y0, z0 + h + msize * 0.035), "_legend",
                    fontsize=max(9.0, msize * 0.035))
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


def _result_tube(doc, grp, name, kind, perbar, radius, vmax, visible):
    """Render a result as the structure drawn in thick tube segments coloured
    blue->red by |value| along each bar (per-face DiffuseColor, with a solid
    fallback). `perbar` is a list of (points, values) per bar. Thick tubes read
    clearly from any angle - the Inventor/Robot contour look."""
    cyls = []
    colors = []
    for (pts, vals) in perbar:
        for i in range(len(pts) - 1):
            a = pts[i]; b = pts[i + 1]; v = b - a; ln = v.Length
            if ln < 1e-6:
                continue
            try:
                cyl = Part.makeCylinder(radius, ln, a, unit(v))
            except Exception:
                continue
            try:
                nf = len(cyl.Faces)
            except Exception:
                nf = 3
            cyls.append(cyl)
            t = (0.5 * (abs(vals[i]) + abs(vals[i + 1])) / vmax) if vmax > 1e-12 else 0.0
            colors += [_ramp(t) + (0.0,)] * nf
    if not cyls:
        return None
    ob = doc.addObject("Part::Feature", name)
    ob.Shape = Part.makeCompound(cyls)
    ob.Label = "%s result" % kind
    _set(ob, "App::PropertyString", "DiagKind", kind)
    _set(ob, "App::PropertyFloat", "CompMax", float(vmax))
    _set(ob, "App::PropertyFloat", "CompMin", 0.0)
    try:
        ob.ViewObject.Visibility = bool(visible)
        if len(colors) == len(ob.Shape.Faces):
            ob.ViewObject.DiffuseColor = colors
        else:
            ob.ViewObject.ShapeColor = (0.2, 0.6, 0.95)
    except Exception:
        pass
    if grp is not None:
        grp.addObject(ob)
    return ob


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
_add("DynFrame_Combinations", Combinations)
_add("DynFrame_RunAnalysis", RunAnalysis)
_add("DynFrame_ModalAnalysis", ModalAnalysis)
_add("DynFrame_ShowDiagram", ShowDiagram)
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
