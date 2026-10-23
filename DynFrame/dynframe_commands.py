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
    out = []
    for so in FreeCADGui.Selection.getSelectionEx():
        subs = list(getattr(so, "SubObjects", []) or [])
        if subs:
            for s in subs:
                _edges_of(s, out)
        else:
            obj = so.Object
            if getattr(obj, "Shape", None) is not None:
                try:
                    _edges_of(global_shape(obj), out)
                except Exception:
                    _edges_of(obj.Shape, out)
    uniq = []
    for a, b in out:
        if not any((a.distanceToPoint(c) < 1e-4 and b.distanceToPoint(d) < 1e-4) or
                   (a.distanceToPoint(d) < 1e-4 and b.distanceToPoint(c) < 1e-4)
                   for c, d in uniq):
            uniq.append((a, b))
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
        for p1, p2 in edges:
            m = make_member(doc, res["size"], p1, p2, res["twist"], res["align"],
                            res["offx"], res["offy"])
            if m:
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
        s1, e1 = skeleton(m1)
        s2, e2 = skeleton(m2)
        cand = [(s1, e1, s2, e2), (s1, e1, e2, s2), (e1, s1, s2, e2), (e1, s1, e2, s2)]
        c1, f1, c2, f2 = min(cand, key=lambda p: p[0].distanceToPoint(p[2]))
        gap = c1.distanceToPoint(c2)
        if gap > 5.0:
            warn("Those members don't meet at a corner (ends are %.1f mm apart)." % gap)
            return
        C = c1
        d1 = unit(f1 - c1)
        d2 = unit(f2 - c2)
        n = d1 - d2
        if n.Length < 1e-4:
            warn("Members are collinear — nothing to miter.")
            return
        n = unit(n)
        L1 = s1.distanceToPoint(e1)
        L2 = s2.distanceToPoint(e2)
        S = max(L1, L2, 100.0) * 4.0 + 200.0
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: miter")
        try:
            g1 = global_shape(m1).cut(_halfspace_box(C, vscale(n, -1.0), S))
            g2 = global_shape(m2).cut(_halfspace_box(C, n, S))
            if g1.Volume < TOL or g2.Volume < TOL:
                doc.abortTransaction()
                warn("Miter produced an empty result — check the two members "
                     "share a corner.")
                return
            m1.Shape, m1.Placement = g1, FreeCAD.Placement()
            m2.Shape, m2.Placement = g2, FreeCAD.Placement()
            doc.commitTransaction()
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            err("Miter failed:\n%s" % e)


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
        try:
            FreeCADGui.activateWorkbench("DraftWorkbench")
        except Exception as e:
            err("Could not open the Draft workbench:\n%s" % e)
            return
        started = False
        for cmd in ("Draft_Wire", "Draft_Polyline", "Draft_Line"):
            try:
                FreeCADGui.runCommand(cmd, 0)
                started = True
                break
            except Exception:
                continue
        info("You're now in the Draft workbench.\n\n"
             "Draw the 3D skeleton with the **Polyline** tool "
             "(Drafting menu -> Polyline, or the polyline toolbar icon)%s:\n"
             "  - click points in 3D (type X/Y/Z for exact points),\n"
             "  - set the working plane or use snaps for other planes,\n"
             "  - double-click or Esc to finish.\n\n"
             "Then switch back to DynFrame, select the polyline(s), and run "
             "Insert Frame Members."
             % (" (it may already be active)" if started else ""))


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


# ── register ─────────────────────────────────────────────────────
def _add(name, cls):
    try:
        FreeCADGui.addCommand(name, cls())
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: add %s failed (%s)\n" % (name, e))


_add("DynFrame_InsertMembers", InsertMembers)
_add("DynFrame_ChangeProfile", ChangeProfile)
_add("DynFrame_LengthenShorten", LengthenShorten)
_add("DynFrame_TrimButt", TrimButt)
_add("DynFrame_Miter", Miter)
_add("DynFrame_TrimToFace", TrimToFace)
_add("DynFrame_CutList", CutList)
_add("DynFrame_QuickFillet", QuickFillet)
_add("DynFrame_ExportStep", ExportStep)
_add("DynFrame_ExportStl", ExportStl)
_add("DynFrame_Skeleton3D", Skeleton3D)
_add("DynFrame_InventorNav", InventorNav)
