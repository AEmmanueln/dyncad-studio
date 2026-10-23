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


def _section_props(obj):
    face = build_face(getattr(obj, "MemberProfile", ""), "Center", 0.0, 0.0)
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


def _fea_solve(nodes, members, fixed, loads):
    import numpy as np
    nn = len(nodes); ndof = 6 * nn
    K = np.zeros((ndof, ndof)); F = np.zeros(ndof)
    edata = []
    for (n1, n2, A, Iy, Iz, J) in members:
        T, L = _beam_T(nodes[n1], nodes[n2])
        kl = _beam_k_local(E_STEEL, G_STEEL, A, Iy, Iz, J, L)
        kg = T.T @ kl @ T
        dofs = [6 * n1 + i for i in range(6)] + [6 * n2 + i for i in range(6)]
        ix = np.ix_(dofs, dofs)
        K[ix] += kg
        edata.append((dofs, T, kl))
    for d, v in loads.items():
        F[d] += v
    free = [d for d in range(ndof) if d not in fixed]
    u = np.zeros(ndof)
    try:
        u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    except Exception:
        return None
    R = K @ u - F
    mend = [kl @ (T @ u[dofs]) for (dofs, T, kl) in edata]
    return u, R, mend


class FrameAnalysis:
    def GetResources(self):
        return {"Pixmap": _icon("analysis"), "MenuText": "Frame Analysis (static)",
                "ToolTip": "Linear-static 3D frame analysis: supports at the base "
                           "(or selected vertices), self-weight + a vertical load; "
                           "reports deflection, reactions, member stress and colours "
                           "the frame by utilisation.", "Accel": "F, A"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        members = [o for o in doc.Objects if is_member(o)]
        if len(members) < 1:
            info("No frame members found. Build a frame first.")
            return
        # pre-selected vertices define supports
        sel_pts = []
        for so in FreeCADGui.Selection.getSelectionEx():
            for sub in getattr(so, "SubObjects", []) or []:
                if getattr(sub, "ShapeType", "") == "Vertex":
                    sel_pts.append(FreeCAD.Vector(sub.Point))

        # build nodes (merge coincident) + elements with section properties
        nodes = []

        def nid(p):
            for i, q in enumerate(nodes):
                if q.distanceToPoint(p) <= 1.0:
                    return i
            nodes.append(FreeCAD.Vector(p)); return len(nodes) - 1

        elems = []
        sect = []
        for m in members:
            sp = _section_props(m)
            if sp is None:
                continue
            A, Iy, Iz, J, c = sp
            s, e = skeleton(m)
            n1, n2 = nid(s), nid(e)
            if n1 == n2:
                continue
            elems.append((n1, n2, A, Iy, Iz, J))
            sect.append((m, A, c, min(Iy, Iz)))
        if not elems:
            info("Could not build an analysis model from the members.")
            return

        # supports: selected vertices, else all nodes at the lowest Z
        if sel_pts:
            supp = set(nid(p) for p in sel_pts)
        else:
            zmin = min(n.z for n in nodes)
            supp = set(i for i, n in enumerate(nodes) if abs(n.z - zmin) <= 1.0)
        if not supp:
            warn("No supports found. Select base vertices to fix, then re-run.")
            return
        fixed = set()
        for i in supp:
            for k in range(6):
                fixed.add(6 * i + k)

        # loads
        sw, ok = get_item("Frame Analysis", "Include self-weight?", ["Yes", "No"], 0)
        if not ok:
            return
        pl, ok = get_double("Frame Analysis",
                            "Extra vertical load at each non-support node (N, downward):",
                            1000.0, 0.0, 1e9)
        if not ok:
            return
        loads = {}
        if sw == "Yes":
            for (n1, n2, A, Iy, Iz, J) in elems:
                L = nodes[n1].distanceToPoint(nodes[n2])
                w = A * L * RHO_STEEL * GRAV      # N, total member weight
                loads[6 * n1 + 2] = loads.get(6 * n1 + 2, 0.0) - w / 2.0
                loads[6 * n2 + 2] = loads.get(6 * n2 + 2, 0.0) - w / 2.0
        for i in range(len(nodes)):
            if i not in supp:
                loads[6 * i + 2] = loads.get(6 * i + 2, 0.0) - pl

        res = _fea_solve(nodes, elems, fixed, loads)
        if res is None:
            err("The model is unstable (singular) — it needs more supports. "
                "Select base vertices to fix and re-run.")
            return
        u, R, mend = res
        import numpy as np

        # results
        maxd = 0.0
        for i in range(len(nodes)):
            d = (u[6 * i] ** 2 + u[6 * i + 1] ** 2 + u[6 * i + 2] ** 2) ** 0.5
            maxd = max(maxd, d)
        rx = sum(R[6 * i] for i in supp); ry = sum(R[6 * i + 1] for i in supp); rz = sum(R[6 * i + 2] for i in supp)

        rows = []
        max_util = 0.0
        doc.openTransaction("DynFrame: analysis colour")
        for k, (m, A, c, Imin) in enumerate(sect):
            fl = mend[k]
            N = max(abs(fl[0]), abs(fl[6]))
            M = max(abs(fl[4]), abs(fl[5]), abs(fl[10]), abs(fl[11]))
            sigma = N / A + (M * c / Imin if Imin > 1e-9 else 0.0)
            util = sigma / FY_STEEL
            max_util = max(max_util, util)
            rows.append((m.Label, N, M, sigma, util))
            try:
                uc = max(0.0, min(1.0, util))
                m.ViewObject.ShapeColor = (float(uc), float(1.0 - uc), 0.2)
            except Exception:
                pass
        doc.commitTransaction()

        try:
            sheet = doc.getObject("Analysis") or doc.addObject("Spreadsheet::Sheet", "Analysis")
            sheet.clearAll()
            sheet.set("A1", "DynFrame Frame Analysis (linear static, steel)")
            sheet.set("A3", "Member"); sheet.set("B3", "Axial N (N)"); sheet.set("C3", "Moment (N.mm)")
            sheet.set("D3", "Stress (MPa)"); sheet.set("E3", "Utilisation")
            r = 4
            for label, N, M, sg, ut in rows:
                sheet.set("A%d" % r, str(label)); sheet.set("B%d" % r, "%.1f" % N)
                sheet.set("C%d" % r, "%.1f" % M); sheet.set("D%d" % r, "%.1f" % sg)
                sheet.set("E%d" % r, "%.2f" % ut); r += 1
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: analysis sheet failed (%s)\n" % e)

        info("Frame Analysis (linear static)\n\n"
             "Nodes: %d   Members: %d   Supports: %d\n"
             "Max displacement: %.3f mm\n"
             "Max stress: %.1f MPa   Max utilisation: %.2f  (vs %.0f MPa yield)\n"
             "Total reaction: Rz = %.0f N  (Rx=%.0f, Ry=%.0f)\n\n"
             "Members are coloured green->red by utilisation; full table in the "
             "'Analysis' spreadsheet.\n\nNote: linear static only (no modal, "
             "buckling, seismic or code checks yet)." %
             (len(nodes), len(elems), len(supp), maxd,
              max_util * FY_STEEL, max_util, FY_STEEL, rz, rx, ry))


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
_add("DynFrame_FrameAnalysis", FrameAnalysis)
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
