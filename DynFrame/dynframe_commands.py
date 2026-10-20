# -*- coding: utf-8 -*-
"""DynFrame commands: Frame Generator, trim/miter, cut list, export,
quick fillet and an Inventor navigation preset.

Design notes
------------
* A "member" is a Part::Feature whose Shape is a profile face extruded
  along its local +Z, placed so +Z points down the selected edge. Its
  cut length and profile name are stored as properties (used by the
  cut list).
* Selections are read via Gui.Selection; sub-selected edges come back in
  GLOBAL coordinates, which is what we need. Whole-object selections are
  transformed by the object's Placement so their edges are global too.
"""

import os
import math

import FreeCAD
import FreeCADGui
import Part

import dynframe_profiles as profiles

# ── Qt helpers (binding-agnostic through FreeCAD's PySide shim) ──
from PySide import QtGui
try:
    from PySide import QtWidgets as QW
except Exception:  # older FreeCAD maps widgets into QtGui
    QW = QtGui

_ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
TOL = 1e-6


def _icon(name):
    p = os.path.join(_ICON_DIR, name + ".svg")
    return p if os.path.exists(p) else os.path.join(_ICON_DIR, "dynframe.svg")


def _mw():
    try:
        return FreeCADGui.getMainWindow()
    except Exception:
        return None


def info(msg):
    QW.QMessageBox.information(_mw(), "DynFrame", msg)


def warn(msg):
    QW.QMessageBox.warning(_mw(), "DynFrame", msg)


def err(msg):
    QW.QMessageBox.critical(_mw(), "DynFrame", msg)


def get_item(title, label, items):
    return QW.QInputDialog.getItem(_mw(), title, label, items, 0, False)


def get_double(title, label, value, lo, hi, decimals=2):
    return QW.QInputDialog.getDouble(_mw(), title, label, value, lo, hi, decimals)


def save_filename(title, filt):
    res = QW.QFileDialog.getSaveFileName(_mw(), title, "", filt)
    return res[0] if isinstance(res, (tuple, list)) else res


def existing_dir(title):
    return QW.QFileDialog.getExistingDirectory(_mw(), title, "")


# ── Geometry helpers ─────────────────────────────────────────────
def _edge_endpoints(edge, out):
    try:
        if len(edge.Vertexes) >= 2:
            p1 = edge.Vertexes[0].Point
            p2 = edge.Vertexes[-1].Point
            if p1.distanceToPoint(p2) > TOL:
                out.append((FreeCAD.Vector(p1), FreeCAD.Vector(p2)))
    except Exception:
        pass


def _edges_from_shape(shp, out):
    try:
        if shp.ShapeType == "Edge":
            _edge_endpoints(shp, out)
        else:
            for e in shp.Edges:
                _edge_endpoints(e, out)
    except Exception:
        pass


def collect_edges():
    """Return a list of (p1, p2) global endpoint pairs for straight edges
    in the current selection (sub-selected edges, or all edges of a whole
    selected object such as a sketch)."""
    out = []
    for so in FreeCADGui.Selection.getSelectionEx():
        subs = list(getattr(so, "SubObjects", []) or [])
        if subs:
            for sub in subs:
                _edges_from_shape(sub, out)
        else:
            obj = so.Object
            if hasattr(obj, "Shape") and obj.Shape is not None:
                try:
                    gshape = obj.Shape.copy()
                    gshape.Placement = obj.Placement.multiply(gshape.Placement)
                except Exception:
                    gshape = obj.Shape
                _edges_from_shape(gshape, out)
    return out


def get_or_make_group(doc, name):
    for o in doc.Objects:
        if o.Name == name and o.TypeId == "App::DocumentObjectGroup":
            return o
    grp = doc.addObject("App::DocumentObjectGroup", name)
    return grp


def make_member(doc, face, p1, p2, profname, twist_deg):
    """Extrude `face` from p1 to p2; return the new Part::Feature."""
    d = p2.sub(p1)
    L = d.Length
    if L < TOL:
        return None
    dirn = FreeCAD.Vector(d)
    dirn.normalize()
    try:
        solid = face.extrude(FreeCAD.Vector(0, 0, L))
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: extrude failed (%s)\n" % e)
        return None

    rot = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), dirn)
    if abs(twist_deg) > 1e-9:
        rot = rot.multiply(FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), twist_deg))

    obj = doc.addObject("Part::Feature", "Member")
    obj.Shape = solid
    obj.Placement = FreeCAD.Placement(p1, rot)
    try:
        obj.addProperty("App::PropertyString", "MemberProfile", "DynFrame",
                        "Structural section").MemberProfile = profname
        obj.addProperty("App::PropertyLength", "MemberLength", "DynFrame",
                        "Cut length").MemberLength = L
    except Exception:
        pass
    obj.Label = "%s (%.1f mm)" % (profname, L)
    return obj


def _member_axis(obj):
    """Return (corner_a, corner_b, length) in global coords for a member."""
    L = float(getattr(obj, "MemberLength", 0.0) or 0.0)
    if L <= 0:
        # fall back to bounding box longest dimension
        bb = obj.Shape.BoundBox
        L = max(bb.XLength, bb.YLength, bb.ZLength)
    base = obj.Placement.Base
    axis = obj.Placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
    axis.normalize()
    return FreeCAD.Vector(base), base.add(axis.multiply(L)), L


# ── Commands ─────────────────────────────────────────────────────
class InsertMembers:
    def GetResources(self):
        return {"Pixmap": _icon("member"),
                "MenuText": "Insert Frame Members",
                "ToolTip": "Create structural members along the selected "
                           "sketch lines or edges (choose a profile).",
                "Accel": "F, M"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        edges = collect_edges()
        if not edges:
            info("Select one or more straight edges or sketch lines first,\n"
                 "then run Insert Frame Members.")
            return
        plist = profiles.build_profiles()
        names = [p[0] for p in plist]
        item, ok = get_item("Frame Generator", "Structural profile:", names)
        if not ok:
            return
        builder = dict(plist)[item]
        twist, _ = get_double("Frame Generator",
                              "Rotation about member axis (deg):", 0.0, -360.0, 360.0)
        try:
            face = builder()
        except Exception as e:
            err("Could not build profile '%s':\n%s" % (item, e))
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: insert members")
        grp = get_or_make_group(doc, "Frame")
        n = 0
        for (p1, p2) in edges:
            m = make_member(doc, face, p1, p2, item, twist)
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


class TrimButt:
    def GetResources(self):
        return {"Pixmap": _icon("trim"),
                "MenuText": "Trim Members (Butt Joint)",
                "ToolTip": "Cut the FIRST selected member against the others "
                           "to form clean butt joints.",
                "Accel": "F, T"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx()]
        members = [o for o in sel if hasattr(o, "Shape") and o.Shape]
        if len(members) < 2:
            info("Select the member to trim FIRST, then the member(s) it "
                 "butts against (at least two total).")
            return
        target, tools = members[0], members[1:]
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: trim butt")
        try:
            result = target.Shape.copy()
            result.Placement = target.Placement.multiply(result.Placement)
            for t in tools:
                ts = t.Shape.copy()
                ts.Placement = t.Placement.multiply(ts.Placement)
                result = result.cut(ts)
            target.Shape = result
            target.Placement = FreeCAD.Placement()  # geometry now global
            doc.commitTransaction()
            doc.recompute()
            FreeCAD.Console.PrintMessage("DynFrame: trimmed %s\n" % target.Label)
        except Exception as e:
            doc.abortTransaction()
            err("Trim failed:\n%s" % e)


class Miter:
    def GetResources(self):
        return {"Pixmap": _icon("miter"),
                "MenuText": "Miter Two Members (experimental)",
                "ToolTip": "Trim two members that meet at a corner on their "
                           "angle bisector. Experimental — verify the result.",
                "Accel": "F, I"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx()]
        members = [o for o in sel if hasattr(o, "Shape") and o.Shape]
        if len(members) != 2:
            info("Select exactly two members that share a corner.")
            return
        m1, m2 = members
        a1, b1, L1 = _member_axis(m1)
        a2, b2, L2 = _member_axis(m2)
        # find the shared corner (closest pair of endpoints)
        pairs = [(a1, a2), (a1, b2), (b1, a2), (b1, b2)]
        corner_pair = min(pairs, key=lambda pr: pr[0].distanceToPoint(pr[1]))
        if corner_pair[0].distanceToPoint(corner_pair[1]) > 1.0:
            warn("Those members do not appear to share a corner "
                 "(endpoints are > 1 mm apart).")
            return
        C = corner_pair[0]
        far1 = b1 if corner_pair[0].isEqual(a1, 1e-3) else a1
        far2 = b2 if corner_pair[1].isEqual(a2, 1e-3) else a2
        d1 = far1.sub(C); d1.normalize()
        d2 = far2.sub(C); d2.normalize()
        normal = d1.sub(d2)            # miter-plane normal (points to d1 side)
        if normal.Length < 1e-6:
            warn("Members are collinear — nothing to miter.")
            return
        normal.normalize()
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: miter")
        try:
            self._cut_halfspace(m1, C, normal.multiply(-1.0))  # remove d2 side of m1
            self._cut_halfspace(m2, C, normal)                 # remove d1 side of m2
            doc.commitTransaction()
            doc.recompute()
            FreeCAD.Console.PrintMessage("DynFrame: mitered %s / %s\n"
                                         % (m1.Label, m2.Label))
        except Exception as e:
            doc.abortTransaction()
            err("Miter failed:\n%s" % e)

    def _cut_halfspace(self, member, point, remove_dir):
        """Cut away the part of `member` lying on the +remove_dir side of the
        plane through `point` with normal `remove_dir`."""
        gshape = member.Shape.copy()
        gshape.Placement = member.Placement.multiply(gshape.Placement)
        bb = gshape.BoundBox
        S = max(bb.XLength, bb.YLength, bb.ZLength) * 3.0 + 10.0
        rd = FreeCAD.Vector(remove_dir); rd.normalize()
        box = Part.makeBox(S, S, S, FreeCAD.Vector(-S / 2.0, -S / 2.0, 0))
        rot = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), rd)
        box.Placement = FreeCAD.Placement(FreeCAD.Vector(point), rot)
        member.Shape = gshape.cut(box)
        member.Placement = FreeCAD.Placement()


class CutList:
    def GetResources(self):
        return {"Pixmap": _icon("cutlist"),
                "MenuText": "Generate Cut List",
                "ToolTip": "Tabulate every frame member (profile + length) "
                           "into a spreadsheet, with optional CSV export.",
                "Accel": "F, C"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        members = [o for o in doc.Objects if hasattr(o, "MemberProfile")]
        if not members:
            info("No frame members found. Create some with Insert Frame "
                 "Members first.")
            return
        rows = []
        summary = {}
        for m in members:
            prof = getattr(m, "MemberProfile", "?")
            length = float(getattr(m, "MemberLength", 0.0) or 0.0)
            rows.append((m.Label, prof, length))
            key = prof
            agg = summary.setdefault(key, [0, 0.0])
            agg[0] += 1
            agg[1] += length

        # Spreadsheet
        try:
            sheet = doc.getObject("CutList") or doc.addObject("Spreadsheet::Sheet", "CutList")
            sheet.clearAll()
            sheet.set("A1", "DynFrame Cut List")
            sheet.set("A3", "Label"); sheet.set("B3", "Profile"); sheet.set("C3", "Length (mm)")
            r = 4
            for (label, prof, length) in rows:
                sheet.set("A%d" % r, str(label))
                sheet.set("B%d" % r, str(prof))
                sheet.set("C%d" % r, "%.2f" % length)
                r += 1
            r += 1
            sheet.set("A%d" % r, "SUMMARY"); sheet.set("B%d" % r, "Qty"); sheet.set("C%d" % r, "Total (mm)")
            r += 1
            for prof, (qty, total) in sorted(summary.items()):
                sheet.set("A%d" % r, str(prof))
                sheet.set("B%d" % r, str(qty))
                sheet.set("C%d" % r, "%.2f" % total)
                r += 1
            doc.recompute()
        except Exception as e:
            FreeCAD.Console.PrintError("DynFrame: spreadsheet failed (%s)\n" % e)

        # Optional CSV
        fn = save_filename("Export cut list as CSV", "CSV files (*.csv)")
        if fn:
            if not fn.lower().endswith(".csv"):
                fn += ".csv"
            try:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("Label,Profile,Length_mm\n")
                    for (label, prof, length) in rows:
                        f.write('"%s","%s",%.2f\n' % (label, prof, length))
                    f.write("\nProfile,Qty,Total_mm\n")
                    for prof, (qty, total) in sorted(summary.items()):
                        f.write('"%s",%d,%.2f\n' % (prof, qty, total))
                info("Cut list written to:\n%s\n\nSpreadsheet 'CutList' also "
                     "added to the document." % fn)
            except Exception as e:
                err("Could not write CSV:\n%s" % e)
        else:
            info("Spreadsheet 'CutList' added to the document.")


class QuickFillet:
    def GetResources(self):
        return {"Pixmap": _icon("fillet"),
                "MenuText": "Quick Fillet (selected edges)",
                "ToolTip": "Fillet the selected solid edges by a radius.",
                "Accel": "M, F"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        sel = FreeCADGui.Selection.getSelectionEx()
        base = None
        idxs = []
        for so in sel:
            for name in getattr(so, "SubElementNames", []) or []:
                if name.startswith("Edge"):
                    base = so.Object
                    try:
                        idxs.append(int(name[4:]))
                    except Exception:
                        pass
        if base is None or not idxs:
            info("Select one or more edges of a single solid, then run "
                 "Quick Fillet.")
            return
        r, ok = get_double("Quick Fillet", "Radius (mm):", 2.0, 0.01, 1e6)
        if not ok:
            return
        try:
            edges = [base.Shape.Edges[i - 1] for i in idxs]
            filleted = base.Shape.makeFillet(r, edges)
        except Exception as e:
            err("Fillet failed (edges may be unfilletable):\n%s" % e)
            return
        doc = FreeCAD.ActiveDocument
        doc.openTransaction("DynFrame: quick fillet")
        obj = doc.addObject("Part::Feature", base.Label + "_Fillet")
        obj.Shape = filleted
        obj.Placement = base.Placement
        try:
            base.ViewObject.Visibility = False
        except Exception:
            pass
        doc.commitTransaction()
        doc.recompute()


class ExportStep:
    def GetResources(self):
        return {"Pixmap": _icon("export"),
                "MenuText": "Export to STEP",
                "ToolTip": "Export the selected objects (or all solids) to a "
                           "single STEP file.",
                "Accel": "E, S"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx()]
        objs = [o for o in sel if hasattr(o, "Shape") and o.Shape]
        if not objs:
            objs = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape
                    and o.TypeId not in ("App::DocumentObjectGroup",)]
        if not objs:
            info("Nothing with geometry to export.")
            return
        fn = save_filename("Export STEP", "STEP files (*.step *.stp)")
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
        return {"Pixmap": _icon("export"),
                "MenuText": "Export each body to STL",
                "ToolTip": "Export the selected objects (or all solids) to "
                           "individual STL files in a chosen folder.",
                "Accel": "E, L"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx()]
        objs = [o for o in sel if hasattr(o, "Shape") and o.Shape]
        if not objs:
            objs = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape
                    and o.TypeId not in ("App::DocumentObjectGroup",)]
        if not objs:
            info("Nothing with geometry to export.")
            return
        folder = existing_dir("Choose a folder for the STL files")
        if not folder:
            return
        n = 0
        for o in objs:
            try:
                safe = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in o.Label)
                shp = o.Shape.copy()
                shp.Placement = o.Placement.multiply(shp.Placement)
                shp.exportStl(os.path.join(folder, safe + ".stl"))
                n += 1
            except Exception as e:
                FreeCAD.Console.PrintError("DynFrame: STL export of %s failed (%s)\n"
                                           % (o.Label, e))
        info("Exported %d STL file(s) to:\n%s" % (n, folder))


class InventorNav:
    def GetResources(self):
        return {"Pixmap": _icon("nav"),
                "MenuText": "Use Inventor Navigation",
                "ToolTip": "Switch the 3D navigation style to the Inventor "
                           "preset (orbit/pan/zoom like Autodesk Inventor)."}

    def IsActive(self):
        return True

    def Activated(self):
        try:
            grp = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
            grp.SetString("NavigationStyle", "Gui::InventorNavigationStyle")
            info("Navigation style set to Inventor.\n\nIf an existing 3D view "
                 "does not update immediately, close and reopen it, or "
                 "restart FreeCAD.")
        except Exception as e:
            err("Could not set navigation style:\n%s" % e)


# ── Register all commands ────────────────────────────────────────
def _add(name, cls):
    try:
        FreeCADGui.addCommand(name, cls())
    except Exception as e:
        FreeCAD.Console.PrintError("DynFrame: could not add %s (%s)\n" % (name, e))


_add("DynFrame_InsertMembers", InsertMembers)
_add("DynFrame_TrimButt", TrimButt)
_add("DynFrame_Miter", Miter)
_add("DynFrame_CutList", CutList)
_add("DynFrame_QuickFillet", QuickFillet)
_add("DynFrame_ExportStep", ExportStep)
_add("DynFrame_ExportStl", ExportStl)
_add("DynFrame_InventorNav", InventorNav)
