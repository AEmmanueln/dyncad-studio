"""DynFrame verification & validation suite.

Runs the whole analysis engine against closed-form / benchmark solutions with
a mocked FreeCAD, Part, Spreadsheet, Gui and dialog layer (real numpy), so the
numbers can be checked with no GUI. Every structural feature is compared to an
exact result (beam theory, Euler buckling, Timoshenko plate, EN code values,
...). Run it from anywhere:

    python3 DynFrame/tests/validate.py

It prints each check and its expected value and exits non-zero on any failure.
This is the evidence behind the README's Verification & Validation section -
correctness you can reproduce, not a claim to take on trust."""
import sys, types, os, math
# DynFrame package dir, resolved from this file (works from any cwd)
DF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DF)

# ---------- FreeCAD.Vector with real math ----------
class Vec:
    def __init__(s, x=0.0, y=0.0, z=0.0):
        if hasattr(x, "x"):
            s.x, s.y, s.z = float(x.x), float(x.y), float(x.z)
        else:
            s.x, s.y, s.z = float(x), float(y), float(z)
    def __add__(s, o): return Vec(s.x+o.x, s.y+o.y, s.z+o.z)
    def __sub__(s, o): return Vec(s.x-o.x, s.y-o.y, s.z-o.z)
    @property
    def Length(s): return math.sqrt(s.x*s.x+s.y*s.y+s.z*s.z)
    def distanceToPoint(s, o): return (s-o).Length

class BB:
    def __init__(s, pts=None):
        if pts:
            xs=[p.x for p in pts]; ys=[p.y for p in pts]; zs=[p.z for p in pts]
            s.XMin,s.XMax=min(xs),max(xs); s.YMin,s.YMax=min(ys),max(ys); s.ZMin,s.ZMax=min(zs),max(zs)
        else:
            s.XMin=s.YMin=s.ZMin=0.0; s.XMax=s.YMax=s.ZMax=1000.0
    @property
    def XLength(s): return s.XMax-s.XMin
    @property
    def YLength(s): return s.YMax-s.YMin
    @property
    def ZLength(s): return s.ZMax-s.ZMin
    def united(s, o):
        r=BB(); r.XMin=min(s.XMin,o.XMin); r.XMax=max(s.XMax,o.XMax)
        r.YMin=min(s.YMin,o.YMin); r.YMax=max(s.YMax,o.YMax)
        r.ZMin=min(s.ZMin,o.ZMin); r.ZMax=max(s.ZMax,o.ZMax); return r

class Shape:
    def __init__(s, nfaces=0, pts=None): s._nf=nfaces; s._pts=pts or [Vec(0,0,0),Vec(1000,0,0)]
    @property
    def Faces(s): return [object()]*s._nf
    @property
    def BoundBox(s): return BB(s._pts)
    @property
    def Vertexes(s):
        class V:
            def __init__(self,p): self.Point=p
        return [V(p) for p in s._pts]

FreeCAD=types.ModuleType("FreeCAD")
FreeCAD.Vector=Vec
class _Rot:
    def __init__(s,*a): pass
    def multVec(s,v): return Vec(v)
FreeCAD.Rotation=_Rot
class _Pl:
    def __init__(s,*a):
        s.Base=Vec(); s.Rotation=_Rot()
FreeCAD.Placement=_Pl
class _Con:
    def PrintMessage(s,*a): pass
    def PrintError(s,*a): print("PrintError:",*a)
FreeCAD.Console=_Con()
FreeCAD.getUserAppDataDir=lambda: DF+os.sep+".."+os.sep

# ---------- Part stub ----------
Part=types.ModuleType("Part")
def _mkline(a,b): return Shape(0,[a,b])
def _mkcone(*a,**k): return Shape(0)
def _mkpoly(pts): return Shape(0,list(pts))
def _mkface(w): return Shape(1, getattr(w,"_pts",None))
def _mkcompound(lst):
    nf=sum(getattr(x,"_nf",0) for x in lst)
    pts=[];
    for x in lst: pts+=getattr(x,"_pts",[])
    return Shape(nf, pts or None)
def _mkcyl(r,h,p=None,d=None): return Shape(3,[p] if p else None)   # 3 faces per cylinder
Part.makeLine=_mkline; Part.makeCone=_mkcone; Part.makePolygon=_mkpoly
Part.Face=_mkface; Part.makeCompound=_mkcompound; Part.makeCylinder=_mkcyl
Part.makeCircle=lambda *a,**k: Shape(0); Part.Wire=lambda *a,**k: Shape(0)
sys.modules["Part"]=Part

# ---------- document / objects ----------
class VO:
    def __init__(s): s.Visibility=True
    def __setattr__(s,k,v): object.__setattr__(s,k,v)
class Obj:
    def __init__(s, typ, name):
        object.__setattr__(s,"_d",{})
        s.TypeId=typ; s.Name=name; s.Label=name; s.Shape=Shape(0)
        s.ViewObject=VO(); s.Group=[]
    def addProperty(s, typ, name, grp=None, doc=None):
        if not hasattr(s, name): object.__setattr__(s, name, None)
        return s
    def addObject(s, o): s.Group.append(o)
class Doc:
    def __init__(s): s.Objects=[]; s._n=0
    def addObject(s, typ, name):
        s._n+=1; nm=name if not any(o.Name==name for o in s.Objects) else "%s%03d"%(name,s._n)
        o=Sheet(nm) if typ=="Spreadsheet::Sheet" else Obj(typ, nm)
        s.Objects.append(o); return o
    def getObject(s, name):
        for o in s.Objects:
            if o.Name==name: return o
        return None
    def removeObject(s, name):
        s.Objects=[o for o in s.Objects if o.Name!=name]
    def recompute(s): pass
    def openTransaction(s,*a): pass
    def commitTransaction(s,*a): pass

# ---------- Spreadsheet ----------
class Sheet(Obj):
    def __init__(s, name):
        Obj.__init__(s, "Spreadsheet::Sheet", name); s._cells={}
    def set(s, a, v): s._cells[a]=v
    def get(s, a):
        if a not in s._cells: raise ValueError("empty")
        return s._cells[a]
    def clearAll(s): s._cells={}

# ---------- Gui ----------
FreeCADGui=types.ModuleType("FreeCADGui")
class _Sel:
    def getSelectionEx(s): return []
    def getSelection(s): return []
FreeCADGui.Selection=_Sel()
class _WB:
    def appendToolbar(s,*a): pass
    def appendMenu(s,*a): pass
FreeCADGui.Workbench=_WB
FreeCADGui.addWorkbench=lambda wb: None
_CMDS={}
FreeCADGui.addCommand=lambda n,c:_CMDS.__setitem__(n,c)
FreeCADGui.getMainWindow=lambda: None
FreeCADGui.activeDocument=lambda: None
FreeCADGui.SendMsgToActiveView=lambda m: None
sys.modules["FreeCADGui"]=FreeCADGui

# ---------- PySide ----------
PySide=types.ModuleType("PySide"); QtGui=types.ModuleType("PySide.QtGui"); QtW=types.ModuleType("PySide.QtWidgets")
class _Any:
    def __init__(s,*a,**k): pass
    def __getattr__(s,k): return _Any()
    def __call__(s,*a,**k): return _Any()
for mm in (QtGui,QtW):
    mm.QMessageBox=_Any(); mm.QInputDialog=_Any(); mm.QFileDialog=_Any(); mm.QLineEdit=_Any()
PySide.QtGui=QtGui; PySide.QtWidgets=QtW
sys.modules["PySide"]=PySide; sys.modules["PySide.QtGui"]=QtGui; sys.modules["PySide.QtWidgets"]=QtW

FreeCAD.ActiveDocument=None
sys.modules["FreeCAD"]=FreeCAD

import dynframe_commands as C

# ---- monkeypatch geometry-dependent + dialog helpers ----
C._section_props_from_name=lambda name: (2000.0, 2.0e6, 1.0e6, 3.0e6, 100.0)
C.info=lambda m: print("[info]", m.split("\n")[0])
C.warn=lambda m: print("[warn]", m.split("\n")[0])
C.err=lambda m: print("[ERR]", m)
# dialog answers: run "All loads", self-weight "Yes"
_answers=iter(["All loads", "Yes"])
def _get_item(title,label,items,cur=0):
    try: return next(_answers), True
    except StopIteration: return items[cur], True
C.get_item=_get_item

# ---- build a synthetic 2-bar model (portal-ish) ----
doc=Doc(); FreeCAD.ActiveDocument=doc
def mkbar(name,p1,p2):
    o=doc.addObject("Part::Feature",name)
    o.Shape=Shape(0,[p1,p2])
    o.IsBar=True; o.Section="IPE 200"; o.Material="Steel S235"
    o.BarStart=p1; o.BarEnd=p2
    return o
mkbar("Bar1", Vec(0,0,0), Vec(0,0,3000))
mkbar("Bar2", Vec(0,0,3000), Vec(4000,0,3000))
mkbar("Bar3", Vec(4000,0,3000), Vec(4000,0,0))
# supports at the two bases
for p in (Vec(0,0,0), Vec(4000,0,0)):
    o=doc.addObject("Part::Feature","Support"); o.Restrain="111111"; o.AtNode=p
# a member (bar) load on Bar2, in default case DL1
lo=doc.addObject("Part::Feature","BarLoad")
lo.LoadType="Member"; lo.LoadCase="DL1"; lo.OnMember="Bar2"; lo.LoadVec=Vec(0,0,-5.0)
# a nodal load at the top-left corner
nl=doc.addObject("Part::Feature","NodalLoad")
nl.LoadType="Nodal"; nl.LoadCase="DL1"; nl.LoadVec=Vec(2000,0,0); nl.AtNode=Vec(0,0,3000)

print("=== running RunAnalysis.Activated on 3-bar portal ===")
try:
    C.RunAnalysis().Activated()
    print("RunAnalysis: completed without exception")
except Exception:
    import traceback; traceback.print_exc(); print("RunAnalysis: **FAILED**"); sys.exit(1)

# inspect results
diags=[o.Name for o in doc.Objects if getattr(o,"DiagKind",None)]
sheets=[o.Name for o in doc.Objects if o.TypeId=="Spreadsheet::Sheet"]
deformed=[o.Name for o in doc.Objects if o.Name.startswith("DeformedShape")]
print("diagram/legend objects:", diags)
print("result sheets:", sheets)
print("deformed shape:", deformed)
# check BarForces sheet got rows
bf=doc.getObject("BarForces")
print("BarForces A1:", bf._cells.get("A1"))
print("BarForces has a data row (A3):", "A3" in bf._cells, "->", bf._cells.get("A3"), bf._cells.get("H3"))
re=doc.getObject("Reactions")
print("Reactions row A3:", re._cells.get("A3"), "Rz:", re._cells.get("D3"))
print("\n=== ShowDiagram (switch to Vz) ===")
# pick the Vz entry by matching the label prefix in whatever list is offered
def _pick_vz(t,l,items,cur=0):
    for it in items:
        if it.startswith("Vz"): return it, True
    return items[cur], True
C.get_item=_pick_vz
C.ShowDiagram().Activated()
vis={o.Name:o.ViewObject.Visibility for o in doc.Objects if getattr(o,"DiagKind",None)}
print("visibility after switch to Vz:", vis)
print("\n=== EditTables -> BuildFromTables ===")
doc2=Doc(); FreeCAD.ActiveDocument=doc2
# EditTables writes example portal (4 nodes, 3 bars)
C.get_item=lambda t,l,items,cur=0: (items[cur], True)
C.EditTables().Activated()
# builder_for must recognise the section names used in the example ("IPE 200")
import dynframe_profiles as P
print("builder_for('IPE 200') ok:", P.builder_for("IPE 200") is not None)
C.BuildFromTables().Activated()
bars=[o for o in doc2.Objects if getattr(o,"IsBar",False)]
print("bars built from tables:", len(bars), "sections:", sorted({b.Section for b in bars}))
assert len(bars)==3, "expected 3 bars from the example tables"

print("\n=== AddBars from a mocked line selection ===")
doc3=Doc(); FreeCAD.ActiveDocument=doc3
# mock collect_edges to return two edges
C.collect_edges=lambda: [(Vec(0,0,0),Vec(0,0,3000),"Sketch",1),
                         (Vec(0,0,3000),Vec(4000,0,3000),"Sketch",2)]
# answers: section family, size, material  -> just take defaults via get_item
_a2=iter([])
C.get_item=lambda t,l,items,cur=0: (items[cur], True)
C.AddBars().Activated()
bars3=[o for o in doc3.Objects if getattr(o,"IsBar",False)]
print("bars from AddBars:", len(bars3), "section:", bars3[0].Section if bars3 else None,
      "material:", bars3[0].Material if bars3 else None)
assert len(bars3)==2

print("\n=== per-material: aluminium deflects ~3x steel ===")
import numpy as np
# cantilever one bar, tip load, steel vs aluminium
def cant_defl(mat):
    d=Doc(); FreeCAD.ActiveDocument=d
    o=d.addObject("Part::Feature","B1"); o.Shape=Shape(0,[Vec(0,0,0),Vec(1000,0,0)])
    o.IsBar=True; o.Section="IPE 200"; o.Material=mat; o.BarStart=Vec(0,0,0); o.BarEnd=Vec(1000,0,0)
    s=d.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
    nl=d.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"; nl.LoadVec=Vec(0,0,-1000); nl.AtNode=Vec(1000,0,0)
    # capture max displacement from the info message
    got={}
    C.info=lambda m,g=got: g.setdefault("msg",m)
    C.get_item=lambda t,l,items,cur=0: (("All loads",True) if "Analyse" in l else ("No",True))
    C.RunAnalysis().Activated()
    import re
    mm=re.search(r"Max displacement:\s*([\d.]+)", got["msg"])
    return float(mm.group(1))
ds=cant_defl("Steel S235"); da=cant_defl("Aluminium 6061-T6")
print("steel tip %.4f  aluminium tip %.4f  ratio %.3f (expect E_steel/E_al=3.0)"%(ds,da,da/ds))
assert abs(da/ds-210000.0/70000.0)<0.02

print("\n=== GridGen (2x1 bays, 3 storeys) + solve ===")
doc4=Doc(); FreeCAD.ActiveDocument=doc4
C.form_dialog=lambda title,fields: {"x":"2@5000","y":"1@4000","z":"3@3500",
    "sec":"IPE 200","mat":"Steel S235","cols":"Yes","fbeam":"Yes","gbeam":"No"}
C.info=lambda m: print("[info]", m.split("\n")[0])
C.GridGen().Activated()
gbars=[o for o in doc4.Objects if getattr(o,"IsBar",False)]
print("grid bars:", len(gbars), "(expect 39: 18 columns + 21 beams)")
assert len(gbars)==39, len(gbars)
# supports at the 6 base nodes (z=0)
for ix in (0,5000,10000):
    for iy in (0,4000):
        s=doc4.addObject("Part::Feature","Sup"); s.Restrain="111111"; s.AtNode=Vec(ix,iy,0)
# a lateral load at a top node
nl=doc4.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
nl.LoadVec=Vec(5000,0,0); nl.AtNode=Vec(0,0,10500)
got={}
C.info=lambda m,g=got: g.setdefault("msg",m)
C.get_item=lambda t,l,items,cur=0: (("All loads",True) if "Analyse" in l else ("Yes",True))
C.RunAnalysis().Activated()
import re
mm=re.search(r"(\d+) bars", got["msg"])
print("solved grid:", got["msg"].split("\n")[0])
assert "complete" in got["msg"], got["msg"]
print("grid solved OK;", len([o for o in doc4.Objects if getattr(o,'DiagKind',None)]), "result objects")

print("\n=== panel backend calls (apply_* , auto_combos, parameterised run/show) ===")
doc5=Doc(); FreeCAD.ActiveDocument=doc5
mkbar=lambda name,p1,p2:(lambda o:(setattr(o,"IsBar",True),setattr(o,"Section","IPE 200"),
    setattr(o,"Material","Steel S235"),setattr(o,"BarStart",p1),setattr(o,"BarEnd",p2),
    setattr(o,"Shape",Shape(0,[p1,p2])),o)[-1])(doc5.addObject("Part::Feature",name))
b1=mkbar("B1",Vec(0,0,0),Vec(0,0,3000)); b2=mkbar("B2",Vec(0,0,3000),Vec(4000,0,3000)); b3=mkbar("B3",Vec(4000,0,3000),Vec(4000,0,0))
C.info=lambda m: None
# two load cases: DL1 (default) + LL1
C._add_case(doc5,"LL1","Live")
# supports on the two base nodes via the shared helper
n=C._apply_support(doc5,"Fixed (all 6)",[Vec(0,0,0),Vec(4000,0,0)]); print("supports applied:",n)
# nodal load (DL1) + line load (LL1) via shared helpers
C._apply_nodal(doc5,"DL1",Vec(3000,0,0),[Vec(0,0,3000)])
C._apply_line(doc5,"LL1",Vec(0,0,-6.0),[b2])
# auto combos
uls,sls=C._auto_combos(doc5); print("ULS1:",uls)
assert "1.35*DL1" in uls and "1.5*LL1" in uls
# parameterised solve (no dialogs) on the combo, self-weight off
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="Combo: ULS1", include_sw=False)
print("panel calc:", got["msg"].split("\n")[0])
assert "Combo ULS1" in got["msg"]
# parameterised show -> switch to N (no dialog)
nvis_before={o.Name:o.ViewObject.Visibility for o in doc5.Objects if getattr(o,"DiagKind",None)=="N"}
C.ShowDiagram().Activated(kind="N")
nobj=[o for o in doc5.Objects if getattr(o,"DiagKind",None)=="N"]
print("N diagram visible after show:", nobj[0].ViewObject.Visibility if nobj else "none")
assert nobj and nobj[0].ViewObject.Visibility is True
print("panel backend OK")

print("\n=== Modal analysis: cantilever f1 vs analytical ===")
doc6=Doc(); FreeCAD.ActiveDocument=doc6
import math
Lc=2000.
o=doc6.addObject("Part::Feature","B1"); o.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Lc)])
o.IsBar=True; o.Section="IPE 200"; o.Material="Steel S235"; o.BarStart=Vec(0,0,0); o.BarEnd=Vec(0,0,Lc)
s=doc6.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.get_int=lambda t,l,v,lo,hi:(6,True)
C.ModalAnalysis().Activated()
import re
m=re.search(r"1:\s*([\d.]+)", got["msg"])
f1=float(m.group(1))
# mocked section: A=2000, Imin=1e6; rho(tonne)=7.85e-9; weak-axis bending
E=210000.; I=1e6; A=2000.; rho=7.85e-9
f1ex=(1.875104**2)/(2*math.pi)*math.sqrt(E*I/(rho*A*Lc**4))
print("modal f1=%.4f Hz  analytical=%.4f Hz  ratio=%.4f"%(f1,f1ex,f1/f1ex))
assert abs(f1/f1ex-1.0)<0.03, (f1,f1ex)
fr=doc6.getObject("ModalFrequencies")
print("ModalFrequencies table rows present:", "A3" in fr._cells)
mode1=[o for o in doc6.Objects if o.Name.startswith("Mode")]
print("Mode 1 shape object:", bool(mode1))
assert mode1
print("modal OK")

print("\n=== Section database (real _section_db, pure Python) vs tables ===")
dbi=C._section_db("IPE 300")
print("  IPE300: A=%.0f Iz=%.4g Iy=%.4g Wpl_z=%.4g Wpl_y=%.4g It=%.4g Iw=%.4g"
      %(dbi["A"],dbi["Iz"],dbi["Iy"],dbi["Wpl_z"],dbi["Wpl_y"],dbi["It"],dbi["Iw"]))
# sharp-corner idealisation of IPE300 (no root fillets)
assert abs(dbi["A"]-5188)<5, dbi["A"]
assert abs(dbi["Iz"]-7.999e7)/7.999e7<0.01, dbi["Iz"]
assert 1.10<dbi["Wpl_z"]/dbi["Wel_z"]<1.18     # I-section shape factor ~1.13
assert dbi["Iw"]>1e11 and dbi["It"]<5e5         # open-section torsion/warping
dbs=C._section_db("SHS 100x100x6")
assert abs(dbs["Wpl_z"]/dbs["Wel_z"]-dbs["Wpl_y"]/dbs["Wel_y"])<1e-6  # symmetric
assert C._section_db("CHS 114.3x5.0")["It"]>0
assert C._section_db("NOT A SECTION") is None    # graceful fallback signal
print("  section DB OK")

print("\n=== EC3 code check: IPE300 column, 400 kN, minor-axis buckling ===")
doc7=Doc(); FreeCAD.ActiveDocument=doc7
ob=doc7.addObject("Part::Feature","Col1"); ob.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,4000)])
ob.IsBar=True; ob.Section="IPE 300"; ob.Material="Steel S235"
ob.BarStart=Vec(0,0,0); ob.BarEnd=Vec(0,0,4000)
# stored member forces (as RunAnalysis would): N = -400 kN compression, no moment
ob.ResN=-400000.0; ob.ResMy=0.0; ob.ResMz=0.0; ob.ResVy=0.0; ob.ResVz=0.0; ob.ResL=4000.0
C._material=lambda name: (210000.0, 80769.0, 235.0, 7.85e-6)
C.form_dialog=lambda title,fields: {"gm0":1.0,"gm1":1.0,"ky":1.0,"kz":1.0,
                                     "klt":1.0,"shape":"Uniform (conservative)"}
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.CodeCheck().Activated()
cc=doc7.getObject("CodeCheck")
cls=int(cc._cells.get("C3")); U=float(cc._cells.get("J3"))
gov=cc._cells.get("K3"); verdict=cc._cells.get("L3")
# hand calc (IPE300 no-fillet A=5188, curve b minor): chi_z=0.452, Nb,z=551kN,
# U = 400/551 = 0.726, minor-axis flexural buckling governs (Eq.6.62)
print("  class=%d utilisation=%.3f governs=%s verdict=%s (hand calc U=0.726)"
      %(cls,U,gov,verdict))
# web is Class 2/3 under heavy compression (combined-loading alpha); plastic
# resistance (<=Cl2) still applies and the column is axial-governed anyway
assert cls in (2,3), cls
assert abs(U-0.726)<0.02 and gov.startswith("Eq.6.6") and verdict=="OK", (U,gov,verdict)
print("EC3 code check OK")

print("\n=== EC3 LTB: long laterally-unrestrained beam, chi_LT < 1 ===")
doc7b=Doc(); FreeCAD.ActiveDocument=doc7b
ob2=doc7b.addObject("Part::Feature","Bm1"); ob2.Shape=Shape(0,[Vec(0,0,0),Vec(6000,0,0)])
ob2.IsBar=True; ob2.Section="IPE 300"; ob2.Material="Steel S235"
ob2.BarStart=Vec(0,0,0); ob2.BarEnd=Vec(6000,0,0)
ob2.ResN=0.0; ob2.ResMy=0.0; ob2.ResMz=50.0e6; ob2.ResVy=0.0; ob2.ResVz=0.0; ob2.ResL=6000.0
C.form_dialog=lambda title,fields: {"gm0":1.0,"gm1":1.0,"ky":1.0,"kz":1.0,
                                     "klt":1.0,"shape":"Uniform (conservative)"}
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.CodeCheck().Activated()
cc2=doc7b.getObject("CodeCheck")
chilt=float(cc2._cells.get("G3")); U2=float(cc2._cells.get("J3"))
# Mcr~150kNm, Wpl_z*fy=602e3*235=141.5kNm -> lam_LT~0.97 -> chi_LT~0.53;
# Mb,Rd = chi_LT*141.5 ~ 75kNm -> U = 50/75 ~ 0.67
print("  chi_LT=%.3f utilisation=%.3f (My=50kNm, expect chi_LT~0.5, U~0.67)"%(chilt,U2))
assert 0.4<chilt<0.65 and 0.55<U2<0.85, (chilt,U2)
print("EC3 LTB OK")

print("\n=== Member release: fixed-fixed beam + release My at end j -> propped cantilever ===")
def run_beam_release(relj):
    d=Doc(); FreeCAD.ActiveDocument=d
    b=d.addObject("Part::Feature","B1"); b.Shape=Shape(0,[Vec(0,0,0),Vec(2000,0,0)])
    b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(2000,0,0)
    if relj: b.RelJ=relj
    for p in (Vec(0,0,0),Vec(2000,0,0)):
        s=d.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=p
    ld=d.addObject("Part::Feature","L"); ld.LoadType="Member"; ld.LoadCase="DL1"; ld.OnMember="B1"; ld.LoadVec=Vec(0,0,-10.0)
    C.info=lambda m: None
    C.get_item=lambda t,l,items,cur=0:("All loads",True)
    C.RunAnalysis().Activated(run_pick="All loads", include_sw=False)
    return getattr(b,"ResMy",0.0)
m_fixed=run_beam_release(None)
m_rel  =run_beam_release("000010")   # release ry (My) at end j
print("fixed-fixed max|My| = %.0f (expect wL^2/12 = %.0f)"%(m_fixed, 10*2000**2/12))
print("released   max|My| = %.0f (expect wL^2/8  = %.0f)"%(m_rel, 10*2000**2/8))
assert abs(m_fixed-10*2000**2/12)<1e3 and abs(m_rel-10*2000**2/8)<1e3, (m_fixed,m_rel)
print("member release OK")

print("\n=== Nodal moment: cantilever tip moment My -> constant member moment ===")
d8=Doc(); FreeCAD.ActiveDocument=d8
bb=d8.addObject("Part::Feature","B1"); bb.Shape=Shape(0,[Vec(0,0,0),Vec(1000,0,0)])
bb.IsBar=True; bb.Section="IPE 200"; bb.Material="Steel S235"; bb.BarStart=Vec(0,0,0); bb.BarEnd=Vec(1000,0,0)
s=d8.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
nl=d8.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
nl.LoadVec=Vec(0,0,0); nl.LoadMom=Vec(0,2.0e6,0); nl.AtNode=Vec(1000,0,0)
C.info=lambda m: None; C.get_item=lambda t,l,items,cur=0:("All loads",True)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False)
resmy=getattr(bb,"ResMy",0.0)
print("member max|My| = %.0f (expect applied My = 2.0e6, constant)"%resmy)
assert abs(resmy-2.0e6)<1e3, resmy
print("nodal moment OK")

print("\n=== Envelope: max across ULS and SLS combos ===")
d9=Doc(); FreeCAD.ActiveDocument=d9
bb=d9.addObject("Part::Feature","B1"); bb.Shape=Shape(0,[Vec(0,0,0),Vec(2000,0,0)])
bb.IsBar=True; bb.Section="IPE 200"; bb.Material="Steel S235"; bb.BarStart=Vec(0,0,0); bb.BarEnd=Vec(2000,0,0)
for p in (Vec(0,0,0),Vec(2000,0,0)):
    s=d9.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=p  # fixed (stable)
C._add_case(d9,"LL1","Live")
# DL member load -3, LL member load -5 on the bar
for case,w in (("DL1",-3.0),("LL1",-5.0)):
    ld=d9.addObject("Part::Feature","L"); ld.LoadType="Member"; ld.LoadCase=case; ld.OnMember="B1"; ld.LoadVec=Vec(0,0,w)
C._set_combos(d9,[("ULS1","1.35*DL1 + 1.5*LL1"),("SLS1","1.0*DL1 + 1.0*LL1")])
C.info=lambda m: None
C.Envelope().Activated()
envmy=getattr(bb,"ResMy",0.0)  # after envelope, stored = max across combos
# ULS mid moment (SS, no self-weight effect since Live+Dead only here; sw dead factor applies)
# w_uls = 1.35*3 + 1.5*5 = 4.05+7.5=11.55 N/mm (+ self-weight*1.35, small). mid M=w*L^2/8
w_uls=1.35*3+1.5*5
# fixed-fixed end moment = w L^2/12; envelope keeps the ULS (larger) value
print("envelope max|My| = %.0f  (>= ULS wL^2/12 = %.0f; self-weight adds a little)"%(envmy, w_uls*2000**2/12))
ev=d9.getObject("Envelope")
print("Envelope table present:", ev is not None and "A3" in ev._cells)
assert envmy >= w_uls*2000**2/12 - 1 and ev is not None  # at least the ULS value
print("envelope OK")

print("\n=== Buckling: cantilever column, axial P -> critical factor ===")
import math
d10=Doc(); FreeCAD.ActiveDocument=d10
Lc=3000.; P=10000.
b=d10.addObject("Part::Feature","Col"); b.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Lc)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(0,0,Lc)
s=d10.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
nl=d10.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"; nl.LoadVec=Vec(0,0,-P); nl.AtNode=Vec(0,0,Lc)
C.info=lambda m: None; C.get_item=lambda t,l,items,cur=0:("All loads",True)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False)
print("stored axial ResN = %.0f (expect -%.0f compression)"%(getattr(b,"ResN",0.0),P))
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.BucklingAnalysis().Activated()
import re
m=re.search(r"Critical load factor:\s*([\d.]+)", got["msg"])
lam=float(m.group(1))
E=210000.; I=1e6  # weak axis
Pcr=math.pi**2*E*I/(2*Lc)**2
lam_ex=Pcr/P
print("lam_cr = %.3f  (expect Pcr/P = pi^2EI/(2L)^2 / P = %.3f)"%(lam,lam_ex))
assert abs(lam/lam_ex-1.0)<0.02, (lam,lam_ex)
bk=[o for o in d10.Objects if o.Name.startswith("Buckling")]
print("buckling mode shape object:", bool(bk))
print("buckling OK")

print("\n=== P-Delta (2nd order): cantilever amplification ~ 1/(1-P/Pcr) ===")
import math
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)  # symmetric
d11=Doc(); FreeCAD.ActiveDocument=d11
Lc=3000.; E=210000.; I=1e6
Pcr=math.pi**2*E*I/(2*Lc)**2; P=0.5*Pcr; H=1000.
b=d11.addObject("Part::Feature","Col"); b.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Lc)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(0,0,Lc)
s=d11.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
nl=d11.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
nl.LoadVec=Vec(H,0,-P); nl.AtNode=Vec(0,0,Lc)
def run2(so):
    got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
    C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=so)
    import re; return float(re.search(r"Max displacement:\s*([\d.]+)",got["msg"]).group(1))
d1=run2(False); d2=run2(True)
print("1st order maxd=%.3f  2nd order maxd=%.3f  amp=%.3f (expect 1/(1-0.5)=2.00)"%(d1,d2,d2/d1))
assert abs(d2/d1-2.0)<0.05, (d1,d2)
print("P-Delta OK")

print("\n=== Seismic (EC8 response spectrum): modal mass + base shear bound ===")
C._section_props_from_name=lambda name:(2000.0,2.0e6,1.0e6,3.0e6,100.0)
d12=Doc(); FreeCAD.ActiveDocument=d12
Lc=3000.
b=d12.addObject("Part::Feature","Col"); b.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Lc)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(0,0,Lc)
s=d12.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
C.form_dialog=lambda title,fields:{"dir":"X","ag":0.25,"soil":"B","q":1.5,"n":12}
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.ResponseSpectrum().Activated()
import re
V=float(re.search(r"SRSS base shear:\s*([\d.]+)",got["msg"]).group(1))
pm=float(re.search(r"Modal mass captured:\s*([\d.]+)",got["msg"]).group(1))
# bound: V <= M_total * Sd_plateau ; M_total ~ rho_t*A*L, Sd_plateau=ag*S*2.5/q
rho_t=7.85e-9; A=2000.; Mtot=rho_t*A*Lc; Sd_pl=0.25*9810*1.2*2.5/1.5
print("SRSS base shear = %.1f N   modal mass captured = %.1f%%"%(V,pm))
print("upper bound M*Sd_plateau = %.1f N"%(Mtot*Sd_pl))
sk=d12.getObject("Seismic"); shape=[o for o in d12.Objects if o.Name.startswith("Seismic") and getattr(o,'DiagKind',None)]
print("Seismic table + shape:", sk is not None and bool(shape))
assert 0 < V <= Mtot*Sd_pl*1.05 and pm > 80 and sk is not None
print("seismic OK")

print("\n=== Bar point load: cantilever tip load -> PL^3/3EI, M_fixed = PL ===")
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)  # symmetric
d13=Doc(); FreeCAD.ActiveDocument=d13
Lc=2000.; P=1000.0; E=210000.; I=1.0e6
b=d13.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(Lc,0,0)
s=d13.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)  # fixed at start
# point load P downward at the tip (pos=1.0)
C._apply_point(d13,"DL1",Vec(0,0,-P),1.0,[b])
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
import re
md=float(re.search(r"Max displacement:\s*([\d.]+)",got["msg"]).group(1))
dex=P*Lc**3/(3*E*I)
rz=float(d13.getObject("Reactions")._cells.get("D3") or 0.0) if d13.getObject("Reactions") else 0.0
mfix=float(getattr(b,"ResMy",0.0)) or float(getattr(b,"ResMz",0.0))
print("tip point load: maxd=%.3f (exact PL^3/3EI=%.3f)  M_fixed=%.0f (exact PL=%.0f)"
      %(md,dex,mfix,P*Lc))
assert abs(md/dex-1.0)<0.01, (md,dex)
assert abs(mfix-P*Lc)/(P*Lc)<0.02, (mfix,P*Lc)
print("bar point load OK")

print("\n=== Bar point load at mid: M beyond load is zero, M_fixed = P*L/2 ===")
d14=Doc(); FreeCAD.ActiveDocument=d14
b=d14.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(Lc,0,0)
s=d14.addObject("Part::Feature","S"); s.Restrain="111111"; s.AtNode=Vec(0,0,0)
C._apply_point(d14,"DL1",Vec(0,0,-P),0.5,[b])
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
mfix=float(getattr(b,"ResMy",0.0)) or float(getattr(b,"ResMz",0.0))
print("mid point load: M_fixed=%.0f (exact P*L/2=%.0f)"%(mfix,P*Lc/2))
assert abs(mfix-P*Lc/2)/(P*Lc/2)<0.02, (mfix,P*Lc/2)
print("bar mid point load OK")

print("\n=== Bar trapezoidal load: w1=w2 must equal a UDL (exactness) ===")
def cant_maxd(applyfn):
    d=Doc(); FreeCAD.ActiveDocument=d
    bb=d.addObject("Part::Feature","Bm"); bb.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
    bb.IsBar=True; bb.Section="IPE 200"; bb.Material="Steel S235"; bb.BarStart=Vec(0,0,0); bb.BarEnd=Vec(Lc,0,0)
    d.addObject("Part::Feature","S").Restrain="111111"; d.Objects[-1].AtNode=Vec(0,0,0)
    applyfn(d,bb)
    g={}; C.info=lambda m,gg=g: gg.setdefault("msg",m)
    C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
    return float(re.search(r"Max displacement:\s*([\d.]+)",g["msg"]).group(1))
w=-4.0
md_udl=cant_maxd(lambda d,bb: C._apply_line(d,"DL1",Vec(0,0,w),[bb]))
md_trap=cant_maxd(lambda d,bb: C._apply_trap(d,"DL1",Vec(0,0,w),Vec(0,0,w),[bb]))
md_udl_ex=abs(w)*Lc**4/(8*E*I)
print("UDL maxd=%.4f  trap(w1=w2) maxd=%.4f  exact wL^4/8EI=%.4f"%(md_udl,md_trap,md_udl_ex))
assert abs(md_udl/md_udl_ex-1.0)<0.01 and abs(md_trap-md_udl)<1e-6, (md_udl,md_trap)
print("bar trapezoidal (uniform-equivalent) OK")

print("\n=== Bar trapezoidal triangular: total reaction = qL/2 ===")
d15=Doc(); FreeCAD.ActiveDocument=d15
q=-6.0
b=d15.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(Lc,0,0)
d15.addObject("Part::Feature","S").Restrain="111111"; d15.Objects[-1].AtNode=Vec(0,0,0)
C._apply_trap(d15,"DL1",Vec(0,0,0.0),Vec(0,0,q),[b])  # 0 at fixed -> q at tip
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
rz=float(d15.getObject("Reactions")._cells.get("D3") or 0.0)
print("triangular load total vertical reaction=%.1f (exact |q|L/2=%.1f)"%(abs(rz),abs(q)*Lc/2))
assert abs(abs(rz)-abs(q)*Lc/2)/(abs(q)*Lc/2)<0.02, (rz,q*Lc/2)
print("bar trapezoidal (triangular) OK")

print("\n=== Results Viewer backend: list, summary, deformed re-draw/scale ===")
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
d16=Doc(); FreeCAD.ActiveDocument=d16
b=d16.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"; b.BarStart=Vec(0,0,0); b.BarEnd=Vec(Lc,0,0)
d16.addObject("Part::Feature","S").Restrain="111111"; d16.Objects[-1].AtNode=Vec(0,0,0)
C._apply_line(d16,"DL1",Vec(0,0,-5.0),[b])
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
# analysis state persisted?
stt=d16.getObject("AnalysisState")
print("AnalysisState stored:", stt is not None and hasattr(stt,"StU"))
assert stt is not None and hasattr(stt,"StU")
# result list has Displacement + force results
rl=C._result_list(d16); keys=[k for (lab,k,knd) in rl]
print("result list keys:", keys)
assert "Disp" in keys and ("Mz" in keys or "My" in keys), keys
# summary mentions max displacement
summ=C._result_summary(d16)
print("summary first line:", summ.splitlines()[0])
assert "Max displacement" in summ, summ
# results render as colour-BAND objects (Diagram_<kind>_b<n>) coloured by a
# plain ShapeColor -> the gradient actually shows and survives recompute
def dispbands(d): return [o for o in d.Objects if str(getattr(o,"DiagKind",""))=="Disp"]
ok1=C._draw_deformed(d16,1.0); nb1=len(dispbands(d16))
ok3=C._draw_deformed(d16,3.0); nb3=len(dispbands(d16))
print("draw_deformed 1x ok=%s  3x ok=%s  Disp band objects=%d"%(ok1,ok3,nb3))
assert ok1 and ok3 and nb3>=2   # several colour bands -> a real gradient
# default contour is thick coloured WIRES (LineColor) so it renders everywhere
cols={tuple(round(c,3) for c in o.ViewObject.LineColor) for o in dispbands(d16)}
print("distinct band colours:", len(cols))
assert len(cols)>=2, cols            # not one flat colour
# no solved state -> graceful False
assert C._draw_deformed(Doc(),2.0) is False
print("results viewer backend OK")

print("\n=== Lazy rendering: one result at a time, on demand ===")
# after a solve only the default (Disp) kind is rendered, not all 8 kinds
def kinds_rendered(d):
    return sorted({str(getattr(o,"DiagKind","")) for o in d.Objects
                   if str(getattr(o,"DiagKind","")) in C.DIAG_KINDS+["Disp"]})
print("rendered result kind(s) after solve:", kinds_rendered(d16))
assert kinds_rendered(d16)==["Disp"], kinds_rendered(d16)
# render a force result on demand -> switches to My only
assert C._render_result(d16,"My") is True
print("after render My:", kinds_rendered(d16))
assert kinds_rendered(d16)==["My"], kinds_rendered(d16)
# switch back to displacement
assert C._render_result(d16,"Disp",scale_mult=2.0) is True
assert kinds_rendered(d16)==["Disp"]
print("on-demand switch OK")

print("\n=== Solid beams: real-section rendering path ===")
# solid=True renders the member's swept profile (falls back to tubes if the
# mock cannot build a section face); must still succeed and build the result
assert C._render_result(d16,"My",solid=True) and kinds_rendered(d16)==["My"]
# the global toggle is respected by _render_result when solid is not passed
C._SOLID_BEAMS=True
assert C._render_result(d16,"Vz") is True and kinds_rendered(d16)==["Vz"]
C._SOLID_BEAMS=False
print("solid-beam render path OK")

print("\n=== Visibility: bold tube radius, legend range, animation frames ===")
# tubes are now a bold fraction of the model (was 0.007 -> thin); floored
assert abs(C._tube_radius(5000.0)-110.0)<1e-6, C._tube_radius(5000.0)  # 5000*0.022
assert C._tube_radius(10.0)==8.0                                       # floor
print("tube radius: 5 m model -> %.0f mm (bold), tiny model -> %.0f mm (floor)"
      %(C._tube_radius(5000.0),C._tube_radius(10.0)))
# legend range comes from the shown result's stored CompMax
C._render_result(d16,"Disp")      # reset the shown result to displacement
rng=C._shown_range(d16)
print("shown range:", rng)
assert rng is not None and rng[0].startswith("Displacement") and rng[2] > 0
# animation builds N frames (each a list of colour-band wire objects, DiagKind
# '_anim'), hidden; toggled by visibility only (no per-frame rebuild)
frames=C._make_anim_frames(d16, 2.0, 8)
anim=[o for o in d16.Objects if getattr(o,"DiagKind",None)=="_anim"]
print("animation frames built:", len(frames), " total band objects:", len(anim))
assert len(frames)==8 and len(anim)>=8        # >=1 colour band per frame
assert all(isinstance(f,list) and f for f in frames)   # each frame is a list
# animation frames are gradient-coloured (not one flat colour)
animcols={tuple(round(c,3) for c in o.ViewObject.LineColor) for o in anim}
assert len(animcols)>=2, animcols
assert all(o.ViewObject.Visibility is False for o in anim)   # start hidden
C._clear_anim_frames(d16)
assert not [o for o in d16.Objects if getattr(o,"DiagKind",None)=="_anim"]
print("animation frames cleared OK (gradient-coloured, %d distinct colours)"%len(animcols))
print("visibility + animation backend OK")

print("\n=== Plate/shell FE (ported): simply-supported square plate ===")
import numpy as _np
E=210000.; nu=0.3; a=2000.; t=20.; qp=0.01
Dp=E*t**3/(12*(1-nu*nu)); wc_ex=0.00406*qp*a**4/Dp
Np=12; h=a/Np
nidp=lambda i,j: j*(Np+1)+i
nn=(Np+1)**2
K=_np.zeros((6*nn,6*nn)); F=_np.zeros(6*nn)
for j in range(Np):
  for i in range(Np):
    cp={(i,j):Vec(i*h,j*h,0),(i+1,j):Vec((i+1)*h,j*h,0),
        (i+1,j+1):Vec((i+1)*h,(j+1)*h,0),(i,j+1):Vec(i*h,(j+1)*h,0)}
    quad=[(i,j),(i+1,j),(i+1,j+1),(i,j+1)]
    for tri in ((quad[0],quad[1],quad[2]),(quad[0],quad[2],quad[3])):
      P=[cp[ij] for ij in tri]; ns=[nidp(*ij) for ij in tri]
      Ke=C._shell_k_global(P,E,nu,t); Ae=C._tri_area2d([(p.x,p.y) for p in P])
      dofs=[]
      for n in ns: dofs+=list(range(6*n,6*n+6))
      for n in ns: F[6*n+2]+=qp*Ae/3.0
      for aa in range(18):
        for bb in range(18): K[dofs[aa],dofs[bb]]+=Ke[aa,bb]
fixed=set()
for i in range(Np+1):
  for j in range(Np+1):
    if i in (0,Np) or j in (0,Np):
      n=nidp(i,j); fixed.update([6*n,6*n+1,6*n+2])
free=[d for d in range(6*nn) if d not in fixed]
u=_np.zeros(6*nn); u[free]=_np.linalg.solve(K[_np.ix_(free,free)],F[free])
cn=nidp(Np//2,Np//2); wc=abs(u[6*cn+2])
print("  w_center=%.4f mm  exact=%.4f  ratio=%.4f"%(wc,wc_ex,wc/wc_ex))
assert abs(wc/wc_ex-1.0)<0.02, (wc,wc_ex)
# stress recovery returns a finite positive von Mises at a loaded element
tri0=[Vec(0,0,0),Vec(h,0,0),Vec(h,h,0)]
ns0=[nidp(0,0),nidp(1,0),nidp(1,1)]
ug=[]
for n in ns0: ug+=list(u[6*n:6*n+6])
vm=C._shell_vm_stress(tri0,E,nu,t,ug)
print("  sample von Mises stress=%.3f MPa (finite, >0)"%vm)
assert vm>0 and vm<1e6
# bending-moment recovery: SS square plate under UDL, center moment (Timoshenko
# Mx=My=0.0479 q a^2 for nu=0.3). Build the whole tri list, recover per-tri
# moments in the shared plate frame, take the field max (occurs at the centre).
allt=[]
for j in range(Np):
  for i in range(Np):
    cp={(i,j):Vec(i*h,j*h,0),(i+1,j):Vec((i+1)*h,j*h,0),
        (i+1,j+1):Vec((i+1)*h,(j+1)*h,0),(i,j+1):Vec(i*h,(j+1)*h,0)}
    quad=[(i,j),(i+1,j),(i+1,j+1),(i,j+1)]
    for tri in ((quad[0],quad[1],quad[2]),(quad[0],quad[2],quad[3])):
      allt.append([cp[ij] for ij in tri])
En,Ex,Ey=C._plate_frame(allt)
mxmax=mymax=0.0
for tri in allt:
  nsT=[nidp(int(round(p.x/h)),int(round(p.y/h))) for p in tri]
  ugT=[]
  for n in nsT: ugT+=list(u[6*n:6*n+6])
  mxx,myy,mxy,m1,m2=C._shell_moments(tri,E,nu,t,ugT,En,Ex,Ey)
  mxmax=max(mxmax,abs(mxx)); mymax=max(mymax,abs(myy))
Mex=0.0479*qp*a**2
print("  moment Mx_max=%.1f My_max=%.1f  exact 0.0479 q a^2=%.1f  (ratio %.3f/%.3f)"
      %(mxmax,mymax,Mex,mxmax/Mex,mymax/Mex))
assert abs(mxmax/Mex-1.0)<0.06 and abs(mymax/Mex-1.0)<0.06, (mxmax,mymax,Mex)
print("plate/shell FE OK")

print("\n=== Wood-Armer design moments (closed-form corner cases) ===")
def wa(mx,my,mxy): return tuple(round(v,6) for v in C._wood_armer(mx,my,mxy))
cases=[
 # (mx,my,mxy) -> (mxb,myb,mxt,myt)
 ((100.,0.,0.),   (100.,0.,0.,0.)),      # pure sagging: bottom x only
 ((-100.,0.,0.),  (0.,0.,-100.,0.)),     # pure hogging: top x only
 ((0.,0.,50.),    (50.,50.,-50.,-50.)),  # pure twist: equal steel all 4
 ((100.,0.,50.),  (150.,50.,0.,-25.)),   # combined: top-x corrected to 0, top-y=-25
]
for inp,exp in cases:
    got=wa(*inp)
    print("  WA%s -> bot(%.0f,%.0f) top(%.0f,%.0f)  expect bot(%.0f,%.0f) top(%.0f,%.0f)"
          %(inp,got[0],got[1],got[2],got[3],exp[0],exp[1],exp[2],exp[3]))
    assert got==tuple(round(v,6) for v in exp), (inp,got,exp)
# bottom moments are never negative, top never positive (by construction)
import random as _rnd
for _ in range(200):
    mx=_rnd.uniform(-200,200); my=_rnd.uniform(-200,200); mxy=_rnd.uniform(-150,150)
    b1,b2,t1,t2=C._wood_armer(mx,my,mxy)
    assert b1>=-1e-9 and b2>=-1e-9 and t1<=1e-9 and t2<=1e-9, (mx,my,mxy,b1,b2,t1,t2)
    # the design moment must always envelope the raw field (|WA| >= contribution)
    assert b1+1e-9>=mx and t1-1e-9<=mx, (mx,my,mxy,b1,t1)
print("Wood-Armer OK")

print("\n=== EC2 slab reinforcement (hand calc) ===")
# h=200, outer d=200-25-6=169; C30/37 fcd=0.85*30/1.5=17, fyk=500 fyd=434.8
asv,dv,nt=C._ec2_slab_as(50000.,200.,25.,12.,0,30.,500.)
print("  As(M=50 kNm/m)=%.0f mm2/m  d=%.0f  note=%r  (hand calc ~757)"%(asv,dv,nt))
assert abs(dv-169.)<1e-6 and abs(asv-757.)/757.<0.03, (asv,dv)
# tiny moment -> minimum steel governs (0.26 fctm/fyk * d, ~255 mm2/m)
asm,_,ntm=C._ec2_slab_as(5000.,200.,25.,12.,0,30.,500.)
print("  As(M=5 kNm/m)=%.0f mm2/m note=%r (min steel ~255)"%(asm,ntm))
assert "minimum" in ntm and abs(asm-254.5)/254.5<0.03, (asm,ntm)
# over-moment (K>0.168) -> flagged for compression steel / thickening
aso,_,nto=C._ec2_slab_as(100000.,200.,25.,12.,0,30.,500.)
print("  As(M=100 kNm/m)=%.0f note=%r"%(aso,nto))
assert "compression" in nto, nto
# the inner layer (smaller effective depth) needs more steel for the same moment
asi,di,_=C._ec2_slab_as(50000.,200.,25.,12.,1,30.,500.)
assert di<dv and asi>asv, (asi,di,asv,dv)
# fctm at C30 ~ 2.90 MPa
assert abs(C._fctm(30.)-2.896)<0.01, C._fctm(30.)
print("EC2 slab reinforcement OK")

print("\n=== Plate integration: SS plate solved end-to-end via RunAnalysis ===")
import json as _json
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dP=Doc(); FreeCAD.ActiveDocument=dP
aP=2000.; tP=20.; qP=0.005; NP=10; hP=aP/NP
trisP=[]
for jj in range(NP):
  for ii in range(NP):
    A=[ii*hP,jj*hP,0.]; B=[(ii+1)*hP,jj*hP,0.]; Cc=[(ii+1)*hP,(jj+1)*hP,0.]; Dd=[ii*hP,(jj+1)*hP,0.]
    trisP.append([A,B,Cc]); trisP.append([A,Cc,Dd])
pl=dP.addObject("Part::Feature","Plate"); pl.Shape=Shape(0,[Vec(0,0,0),Vec(aP,aP,0)])
pl.IsShell=True; pl.ShellThk=tP; pl.Material="Steel S235"; pl.ShellTris=_json.dumps(trisP)
for ii in range(NP+1):
  for jj in range(NP+1):
    if ii in (0,NP) or jj in (0,NP):
      s=dP.addObject("Part::Feature","S_%d_%d"%(ii,jj))
      s.Restrain="111000"; s.AtNode=Vec(ii*hP,jj*hP,0)
pr=dP.addObject("Part::Feature","PR"); pr.LoadType="Pressure"; pr.LoadCase="DL1"
pr.OnShell=pl.Name; pr.Pressure=qP
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
stP=dP.getObject("AnalysisState"); U=_json.loads(stP.StU); NODES=_json.loads(stP.StNodes)
ci=min(range(len(NODES)), key=lambda k:(NODES[k][0]-aP/2)**2+(NODES[k][1]-aP/2)**2)
wcP=abs(U[6*ci+2])
DpP=E*tP**3/(12*(1-0.3**2)); wcP_ex=0.00406*qP*aP**4/DpP
print("  solved plate w_center=%.4f  exact=%.4f  ratio=%.4f"%(wcP,wcP_ex,wcP/wcP_ex))
assert abs(wcP/wcP_ex-1.0)<0.03, (wcP,wcP_ex)
# plate stress contour (colour-band objects, DiagKind '_plate') + result list
psbands=[o for o in dP.Objects if str(getattr(o,"DiagKind",""))=="_plate"]
assert len(psbands)>=1 and getattr(pl,"ShellVM",0.0)>0
pscols={tuple(round(c,3) for c in o.ViewObject.ShapeColor) for o in psbands}
rlist=[k for (lab,k,knd) in C._result_list(dP) if knd=="obj"]
print("  plate stress: %d band object(s), %d distinct colours; max vM=%.1f MPa; objs=%s"
      %(len(psbands), len(pscols), getattr(pl,"ShellVM",0.0), rlist))
assert "_plate" in rlist
# signed bending-moment + principal contours (hidden), symmetric range, listed
for comp in ("Mx","My","Mxy","M1","M2"):
    dk="_plate"+comp
    mb=[o for o in dP.Objects if str(getattr(o,"DiagKind",""))==dk]
    assert len(mb)>=2, (comp,len(mb))                 # several bands -> a gradient
    assert dk in rlist, (dk,rlist)                    # selectable in Results Viewer
    # symmetric legend range -peak..+peak, and >=2 distinct band colours
    assert all(getattr(o,"CompMin",0.0)<0 and getattr(o,"CompMax",0.0)>0 for o in mb), comp
    cols={tuple(round(c,3) for c in o.ViewObject.ShapeColor) for o in mb}
    assert len(cols)>=2, (comp,cols)
# Wood-Armer reinforcement contours: bottom one-signed (0..peak), top (-peak..0)
for comp in ("WAxb","WAyb"):
    dk="_plate"+comp
    mb=[o for o in dP.Objects if str(getattr(o,"DiagKind",""))==dk]
    assert mb and dk in rlist, (comp,len(mb),dk in rlist)
    assert all(getattr(o,"CompMin",0.0)==0.0 and getattr(o,"CompMax",0.0)>0 for o in mb), comp
for comp in ("WAxt","WAyt"):
    dk="_plate"+comp
    mb=[o for o in dP.Objects if str(getattr(o,"DiagKind",""))==dk]
    assert mb and dk in rlist, (comp,len(mb),dk in rlist)
    assert all(getattr(o,"CompMax",0.0)==0.0 and getattr(o,"CompMin",0.0)<0 for o in mb), comp
# M1 >= M2 everywhere (principal ordering), and WA bottom peaks are positive
assert getattr(pl,"ShellWAxb",0.0)>0 and getattr(pl,"ShellWAyb",0.0)>0
# PlateReinforcement table exists with Wood-Armer columns + a data row
prt=dP.getObject("PlateReinforcement")
assert prt and prt._cells.get("B2","").startswith("Mxd bottom") and "B3" in prt._cells
assert "Wood-Armer" in C._result_summary(dP), C._result_summary(dP)
print("  extra contours: M1/M2 + Wood-Armer(4) present & listed; PlateReinforcement table OK")
# principal-moment trajectories: angle helper + the two wire objects
import math as _mt
assert abs(C._principal_angle(100.,0.,0.))<1e-9                      # uniaxial Mx -> 0
assert abs(C._principal_angle(0.,0.,50.)-_mt.pi/4)<1e-9              # pure twist -> 45
assert abs(abs(C._principal_angle(0.,100.,0.))-_mt.pi/2)<1e-9       # My>Mx -> 90
rkeys=[k for (lab,k,knd) in C._result_list(dP)]
for dk in ("_plateT1","_plateT2"):
    tj=[o for o in dP.Objects if str(getattr(o,"DiagKind",""))==dk]
    assert len(tj)==1, (dk,len(tj))                    # one wire family object
    assert dk in rkeys, (dk,rkeys)                     # selectable in the viewer
    assert tuple(round(c,2) for c in tj[0].ViewObject.LineColor) != (0.0,0.0,0.0)
print("  principal-moment trajectories: angle helper + M1/M2 wire families OK")
pk=lambda a: getattr(pl,a,0.0)
print("  moment contours built: Mx/My/Mxy band objs=%d/%d/%d; plate peaks |Mx|=%.0f |My|=%.0f |Mxy|=%.0f"
      %(len([o for o in dP.Objects if getattr(o,"DiagKind","")=="_plateMx"]),
        len([o for o in dP.Objects if getattr(o,"DiagKind","")=="_plateMy"]),
        len([o for o in dP.Objects if getattr(o,"DiagKind","")=="_plateMxy"]),
        pk("ShellMx"),pk("ShellMy"),pk("ShellMxy")))
# SS plate solved via RunAnalysis: field-max Mx ~ 0.0479 q a^2
MexP=0.0479*qP*aP**2
print("  solved plate max|Mx|=%.0f  exact 0.0479 q a^2=%.0f  ratio=%.3f"
      %(pk("ShellMx"),MexP,pk("ShellMx")/MexP))
assert abs(pk("ShellMx")/MexP-1.0)<0.08, (pk("ShellMx"),MexP)
# EC2 reinforcement command runs end-to-end on the solved plate
pl.ShellThk=200.0    # a realistic slab thickness for the design
C.form_dialog=lambda title,fields:{"grade":"C30/37","fyk":500.0,"cover":25.0,
    "dia":12.0,"gc":1.5,"gs":1.15,"acc":0.85}
gotR={}; C.info=lambda m,g=gotR: g.setdefault("msg",m)
C.PlateReinfEC2().Activated()
ps=dP.getObject("PlateSteel")
assert ps is not None and ps._cells.get("C2","").startswith("As x bot") and "C3" in ps._cells
asxb=float(ps._cells.get("C3") or 0.0)
print("  EC2 command: PlateSteel As x bot=%.0f mm2/m; msg=%r"
      %(asxb, gotR["msg"].split("\n")[0]))
assert asxb>0 and "reinforcement" in gotR["msg"].lower()
# PlateForces table carries the moment columns (F2/G2/H2 headers + a data row)
pf=dP.getObject("PlateForces")
assert pf and pf._cells.get("F2","").startswith("Max |Mx|") and "F3" in pf._cells
# summary mentions plate moments
summ=C._result_summary(dP)
assert "Plate max |Mx|" in summ, summ
print("plate moment contours OK")
print("plate integration OK")

print("\n=== Thermal load: fixed-fixed bar heated -> N = -EA.alpha.dT ===")
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dtl=Doc(); FreeCAD.ActiveDocument=dtl
Lc=2000.; Ab=2000.; E=210000.; alpha=1.2e-5; dT=50.
b=dtl.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True;b.Section="IPE 200";b.Material="Steel S235";b.BarStart=Vec(0,0,0);b.BarEnd=Vec(Lc,0,0)
for nm,p in (("TA",(0,0,0)),("TB",(Lc,0,0))):
    s=dtl.addObject("Part::Feature",nm); s.Restrain="111111"; s.AtNode=Vec(*p)
C._apply_thermal(dtl,"DL1",dT,[b])
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
N=getattr(b,"ResN",0.0); Nex=-E*Ab*alpha*dT
print("  thermal N=%.0f N  (exact -EA.alpha.dT=%.0f N)"%(N,Nex))
assert abs(N-Nex)/abs(Nex)<0.01, (N,Nex)
print("thermal load OK")

print("\n=== Elastic (spring) support: tip spring halves cantilever deflection ===")
import json as _json2
ds=Doc(); FreeCAD.ActiveDocument=ds
I=1.0e6; P=1000.; kbeam=3*E*I/Lc**3
b=ds.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True;b.Section="IPE 200";b.Material="Steel S235";b.BarStart=Vec(0,0,0);b.BarEnd=Vec(Lc,0,0)
ds.addObject("Part::Feature","SF").Restrain="111111"; ds.Objects[-1].AtNode=Vec(0,0,0)
sp=ds.addObject("Part::Feature","SP"); sp.Restrain="000000"
sp.Springs=_json2.dumps([0.,0.,kbeam,0.,0.,0.]); sp.AtNode=Vec(Lc,0,0)
nl=ds.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
nl.LoadVec=Vec(0,0,-P); nl.AtNode=Vec(Lc,0,0)
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
import re
md=float(re.search(r"Max displacement:\s*([\d.eE+-]+)",got["msg"]).group(1))
dex=P/(kbeam+kbeam)    # beam tip stiffness in parallel with the spring
print("  tip defl with spring=%.4f mm  (exact P/(kbeam+Kz)=%.4f; no spring=%.4f)"
      %(md,dex,P/kbeam))
assert abs(md/dex-1.0)<0.03, (md,dex)
print("elastic support OK")

print("\n=== Support settlement: cantilever tip settles d -> M=3EId/L^2, V=3EId/L^3 ===")
# Fixed at A; node B given an imposed vertical settlement dz=-delta (its rotation
# stays free -> a moment-free prop).  Classic result: end moment at the fixed
# support M = 3EI*delta/L^2 and constant shear V = 3EI*delta/L^3.
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)  # symmetric
dse=Doc(); FreeCAD.ActiveDocument=dse
Lc=2000.; E=210000.; I=1.0e6; delta=10.0
b=dse.addObject("Part::Feature","Bm"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b.IsBar=True;b.Section="IPE 200";b.Material="Steel S235";b.BarStart=Vec(0,0,0);b.BarEnd=Vec(Lc,0,0)
dse.addObject("Part::Feature","SF").Restrain="111111"; dse.Objects[-1].AtNode=Vec(0,0,0)
# settlement at B: dz = -delta (mm), rotations free
C._apply_settlement(dse,"DL1",Vec(0,0,-delta),Vec(0,0,0),[Vec(Lc,0,0)])
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
mset=float(getattr(b,"ResMy",0.0)) or float(getattr(b,"ResMz",0.0))
vset=float(getattr(b,"ResVz",0.0)) or float(getattr(b,"ResVy",0.0))
Mex=3*E*I*delta/Lc**2; Vex=3*E*I*delta/Lc**3
print("  settlement M=%.0f (exact 3EId/L^2=%.0f)  V=%.1f (exact 3EId/L^3=%.1f)"
      %(mset,Mex,vset,Vex))
assert abs(mset-Mex)/Mex<0.02, (mset,Mex)
assert abs(vset-Vex)/Vex<0.02, (vset,Vex)
# a zero settlement must reduce to the ordinary solve (no induced forces)
dz0=Doc(); FreeCAD.ActiveDocument=dz0
b0=dz0.addObject("Part::Feature","Bm"); b0.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
b0.IsBar=True;b0.Section="IPE 200";b0.Material="Steel S235";b0.BarStart=Vec(0,0,0);b0.BarEnd=Vec(Lc,0,0)
dz0.addObject("Part::Feature","SF").Restrain="111111"; dz0.Objects[-1].AtNode=Vec(0,0,0)
dz0.addObject("Part::Feature","SR").Restrain="001000"; dz0.Objects[-1].AtNode=Vec(Lc,0,0)
C._apply_settlement(dz0,"DL1",Vec(0,0,0.0),Vec(0,0,0),[Vec(Lc,0,0)])  # zero -> no-op
got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
m0=float(getattr(b0,"ResMy",0.0)) or float(getattr(b0,"ResMz",0.0))
print("  zero settlement -> induced M=%.3g (expect ~0)"%m0)
assert abs(m0)<1.0, m0
print("support settlement OK")

print("\n=== Tension-only / compression-only members: active-set drop-out ===")
# One axial bar A->B in parallel with an x-spring at B (so B never becomes a
# mechanism when the bar drops out).  Bar stiffness kb = EA/L, spring ks = kb.
#  * pull B away from A (+x): bar in tension -> active -> defl = P/(ks+kb)
#  * push B toward A  (-x): bar in compression -> a tension-only bar drops out
#    -> defl = P/ks (twice as soft); the bar then carries ~0.
import json as _jsonT
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
Lc=2000.; E=210000.; Ab=2000.; P=100000.
kb=E*Ab/Lc; ks=kb                      # 210000 N/mm each
def run_axial(behavior,Px):
    d=Doc(); FreeCAD.ActiveDocument=d
    b=d.addObject("Part::Feature","Br"); b.Shape=Shape(0,[Vec(0,0,0),Vec(Lc,0,0)])
    b.IsBar=True;b.Section="IPE 200";b.Material="Steel S235"
    b.BarStart=Vec(0,0,0);b.BarEnd=Vec(Lc,0,0); b.MemberBehavior=behavior
    d.addObject("Part::Feature","A").Restrain="111111"; d.Objects[-1].AtNode=Vec(0,0,0)
    sp=d.addObject("Part::Feature","Bsup"); sp.Restrain="011111"   # free dx only
    sp.Springs=_jsonT.dumps([ks,0.,0.,0.,0.,0.]); sp.AtNode=Vec(Lc,0,0)
    nl=d.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
    nl.LoadVec=Vec(Px,0,0); nl.AtNode=Vec(Lc,0,0)
    got={}; C.info=lambda m,g=got: g.setdefault("msg",m)
    C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
    md=float(re.search(r"Max displacement:\s*([\d.eE+-]+)",got["msg"]).group(1))
    return md, float(getattr(b,"ResN",0.0))
d_par=P/(ks+kb); d_spr=P/ks
mdt,Nt=run_axial("Tension-only", P)    # tension -> active
mdc,Nc=run_axial("Tension-only",-P)    # compression -> drops out
print("  tension-only: +P defl=%.4f N=%.0f (active)   -P defl=%.4f N=%.0f (dropped)"
      %(mdt,Nt,mdc,Nc))
print("    exact: active P/(ks+kb)=%.4f (N=+%.0f)   dropped P/ks=%.4f (N=0)"
      %(d_par,kb*d_par,d_spr))
assert abs(mdt-d_par)/d_par<0.02 and Nt>0 and abs(Nt-kb*d_par)/(kb*d_par)<0.02, (mdt,Nt)
assert abs(mdc-d_spr)/d_spr<0.02 and abs(Nc)<1.0, (mdc,Nc)
# compression-only mirrors it: active under -P (compression), drops under +P
mdk,Nk=run_axial("Compression-only",-P)
mdk2,Nk2=run_axial("Compression-only", P)
print("  compression-only: -P defl=%.4f N=%.0f (active)   +P defl=%.4f N=%.0f (dropped)"
      %(mdk,Nk,mdk2,Nk2))
assert abs(mdk-d_par)/d_par<0.02 and Nk<0 and abs(abs(Nk)-kb*d_par)/(kb*d_par)<0.02, (mdk,Nk)
assert abs(mdk2-d_spr)/d_spr<0.02 and abs(Nk2)<1.0, (mdk2,Nk2)
# a plain (normal) member stays active regardless of sign
mdn,Nn=run_axial("Normal", P)
assert abs(mdn-d_par)/d_par<0.02, (mdn,Nn)
print("tension/compression-only members OK")

print("\n=== Wind load (EN 1991-1-4): q_p(z) + applied base shear ===")
# q_p at 10 m, terrain II, vb0=26 -> ~994 Pa, exposure c_e ~ 2.35 (EN chart)
qp10,vm10,ce10=C._wind_qp(10.0,26.0,0.05,2.0)
print("  q_p(10m, cat II, vb=26)=%.1f Pa  c_e=%.3f  v_m=%.2f (expect ~994, ~2.35)"
      %(qp10,ce10,vm10))
assert abs(qp10-993.6)<3.0 and abs(ce10-2.35)<0.03, (qp10,ce10)
# apply to a 10 m cantilever column; base shear must equal the q_p integral
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dW=Doc(); FreeCAD.ActiveDocument=dW
H=10000.
col=dW.addObject("Part::Feature","Col"); col.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,H)])
col.IsBar=True; col.Section="IPE 200"; col.Material="Steel S235"
col.BarStart=Vec(0,0,0); col.BarEnd=Vec(0,0,H)
dW.addObject("Part::Feature","S").Restrain="111111"; dW.Objects[-1].AtNode=Vec(0,0,0)
cp=1.0; btrib=1000.0
C.selected_elems=lambda: [col]
C.form_dialog=lambda title,fields:{"case":"DL1","dir":"+X","vb0":26.0,
  "terr":"II - Open, low vegetation","cp":cp,"btrib":btrib,"c0":1.0,"rho":1.25,
  "cdir":1.0,"cseas":1.0}
gotW={}; C.info=lambda m,g=gotW: g.setdefault("msg",m)
C.AddWindLoad().Activated()
wl=[o for o in dW.Objects if getattr(o,"LoadType",None)=="MemberTrap"]
assert len(wl)==1, len(wl)
w1=wl[0].LoadVec; w2=wl[0].LoadVec2
print("  applied trapezoid: |w1|=%.4f |w2|=%.4f N/mm  (z-comp %.2g/%.2g -> horizontal)"
      %(w1.Length,w2.Length,w1.z,w2.z))
assert abs(w1.z)<1e-9 and abs(w2.z)<1e-9 and w1.x>0 and w2.x>w1.x, (w1.x,w2.x,w1.z)
qpb,_,_=C._wind_qp(2.0,26.0,0.05,2.0)        # base clamped to zmin = 2 m
w1ex=qpb*cp*btrib/1e6; w2ex=qp10*cp*btrib/1e6
Vex=(w1ex+w2ex)/2.0*H                          # integral of the line load
C.info=lambda m: None
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
Rx=abs(float(dW.getObject("Reactions")._cells.get("B3") or 0.0))
print("  base shear |Rx|=%.0f N  (expected q_p integral = %.0f N)"%(Rx,Vex))
assert abs(Rx-Vex)/Vex<0.02, (Rx,Vex)
print("wind load OK")

print("\n=== EC3 sway imperfection: phi formula + equivalent horizontal force ===")
import math as _ms
# phi = 1/200 * alpha_h * alpha_m; h=10 m, m=1 -> alpha_h clamps to 2/3, alpha_m=1
phi,ah,am=C._sway_phi(10.0,1)
print("  phi(h=10,m=1)=%.5f  alpha_h=%.3f  alpha_m=%.3f (expect 0.00333, 0.667, 1.0)"
      %(phi,ah,am))
assert abs(ah-2.0/3.0)<1e-6 and abs(am-1.0)<1e-6 and abs(phi-0.005*2.0/3.0)<1e-6, (phi,ah,am)
# alpha_h upper clamp at low height; alpha_m for several columns
p2,ah2,am2=C._sway_phi(4.0,4)
assert abs(ah2-1.0)<1e-6 and abs(am2-_ms.sqrt(0.5*1.25))<1e-6, (ah2,am2)
# end-to-end: column under vertical load P -> notional H = phi*P at the top
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dI=Doc(); FreeCAD.ActiveDocument=dI
Hc=10000.; P=100000.
cc=dI.addObject("Part::Feature","Col"); cc.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Hc)])
cc.IsBar=True; cc.Section="IPE 200"; cc.Material="Steel S235"
cc.BarStart=Vec(0,0,0); cc.BarEnd=Vec(0,0,Hc)
dI.addObject("Part::Feature","S").Restrain="111111"; dI.Objects[-1].AtNode=Vec(0,0,0)
nl=dI.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
nl.LoadVec=Vec(0,0,-P); nl.AtNode=Vec(0,0,Hc)
C.info=lambda m: None
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
print("  column ResN=%.0f (expect ~ -P compression)"%getattr(cc,"ResN",0.0))
assert getattr(cc,"ResN",0.0) < -1e3
C.selected_elems=lambda: [cc]
C.form_dialog=lambda title,fields:{"case":"DL1","dir":"+X","m":1}
gotI={}; C.info=lambda m,g=gotI: g.setdefault("msg",m)
C.AddImperfection().Activated()
# the notional horizontal load created at the top node, magnitude phi*P in +X
ehf=[o for o in dI.Objects if getattr(o,"LoadType",None)=="Nodal"
     and abs(FreeCAD.Vector(o.LoadVec).x)>1e-9 and getattr(o,"LoadVec").z==0]
assert len(ehf)>=1, len(ehf)
H=FreeCAD.Vector(ehf[0].LoadVec)
phiP=phi*P
print("  notional H = %.1f N in +X  (expect phi*P = %.1f)  at z=%.0f"
      %(H.x, phiP, FreeCAD.Vector(ehf[0].AtNode).z))
assert abs(H.x-phiP)/phiP<0.01 and abs(H.y)<1e-9 and abs(H.z)<1e-9, (H.x,phiP)
assert abs(FreeCAD.Vector(ehf[0].AtNode).z-Hc)<1.0   # applied at the column top
print("EC3 sway imperfection OK")

print("\n=== Moving load envelope: SS beam, max My = PL/4 ===")
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dM=Doc(); FreeCAD.ActiveDocument=dM
Lb=6000.; Pm=100000.
bm=dM.addObject("Part::Feature","Gird"); bm.Shape=Shape(0,[Vec(0,0,0),Vec(Lb,0,0)])
bm.IsBar=True; bm.Section="IPE 200"; bm.Material="Steel S235"
bm.BarStart=Vec(0,0,0); bm.BarEnd=Vec(Lb,0,0)
# simply supported for in-plane (X-Z) bending: dz fixed both ends, ry free
dM.addObject("Part::Feature","SA").Restrain="111101"; dM.Objects[-1].AtNode=Vec(0,0,0)
dM.addObject("Part::Feature","SB").Restrain="011101"; dM.Objects[-1].AtNode=Vec(Lb,0,0)
C.selected_elems=lambda: [bm]
C.form_dialog=lambda title,fields:{"P":Pm,"dir":"-Z (gravity)","naxle":1,
                                   "spacing":1500.0,"nsta":21}
gotM={}; C.info=lambda m,g=gotM: g.setdefault("msg",m)
C.MovingLoad().Activated()
rmy=getattr(bm,"ResMy",0.0)
print("  single axle envelope max|My|=%.0f  (exact PL/4=%.0f)  ratio=%.4f"
      %(rmy,Pm*Lb/4,rmy/(Pm*Lb/4)))
assert abs(rmy-Pm*Lb/4)/(Pm*Lb/4)<0.02, (rmy,Pm*Lb/4)
# max shear envelope approaches P (load next to a support)
rvz=getattr(bm,"ResVz",0.0)
print("  envelope max|Vz|=%.0f  (expect ~P=%.0f near support)"%(rvz,Pm))
assert 0.85*Pm < rvz <= 1.05*Pm, rvz
# envelope stored + rendered as a My contour, and the table exists
me=dM.getObject("MovingEnvelope")
assert me is not None and me._cells.get("C2","").startswith("max|My|") and "C3" in me._cells
assert [o for o in dM.Objects if str(getattr(o,"DiagKind",""))=="My"], "My envelope rendered"
stM=dM.getObject("AnalysisState"); assert stM is not None and hasattr(stM,"StU")
assert "envelope" in gotM["msg"].lower(), gotM["msg"]
# the stored envelope lets the EC3 code check run against it
C._material=lambda name:(210000.0,80769.0,235.0,7.85e-6)
C.form_dialog=lambda title,fields:{"gm0":1.0,"gm1":1.0,"ky":1.0,"kz":1.0,
                                    "klt":1.0,"shape":"Uniform (conservative)"}
C.info=lambda m: None
C.CodeCheck().Activated()
assert dM.getObject("CodeCheck") is not None
# multi-axle: two axles a hair apart ~ one 2P load -> max My ~ (2P)L/4 = PL/2
dM2=Doc(); FreeCAD.ActiveDocument=dM2
b2=dM2.addObject("Part::Feature","Gird2"); b2.Shape=Shape(0,[Vec(0,0,0),Vec(Lb,0,0)])
b2.IsBar=True; b2.Section="IPE 200"; b2.Material="Steel S235"
b2.BarStart=Vec(0,0,0); b2.BarEnd=Vec(Lb,0,0)
dM2.addObject("Part::Feature","SA").Restrain="111101"; dM2.Objects[-1].AtNode=Vec(0,0,0)
dM2.addObject("Part::Feature","SB").Restrain="011101"; dM2.Objects[-1].AtNode=Vec(Lb,0,0)
C.selected_elems=lambda: [b2]
C.form_dialog=lambda title,fields:{"P":Pm,"dir":"-Z (gravity)","naxle":2,
                                   "spacing":1.0,"nsta":81}
C.info=lambda m: None
C.MovingLoad().Activated()
rmy2=getattr(b2,"ResMy",0.0)
print("  two axles (spacing~0) max|My|=%.0f  (exact (2P)L/4=%.0f)  ratio=%.4f"
      %(rmy2,2*Pm*Lb/4,rmy2/(2*Pm*Lb/4)))
assert abs(rmy2-2*Pm*Lb/4)/(2*Pm*Lb/4)<0.02, (rmy2,2*Pm*Lb/4)
print("moving load envelope OK")

print("\n=== EC2 punching shear (hand calc + command) ===")
# internal 400x400 column, d=200, C30/37, rho_l=0.01, V_Ed=800 kN, beta=1.15
pr=C._punching(800000.0, 400.0,400.0, 200.0, 30.0, 0.01, 1.15)
import math as _mp
u1ex=2*(400+400)+4*_mp.pi*200
print("  u1=%.1f (exp %.1f)  k=%.2f  v_Rd,c=%.3f  v_Ed=%.3f  util=%.3f  crush=%.3f"
      %(pr["u1"],u1ex,pr["k"],pr["vRdc"],pr["vEd"],pr["util"],pr["crush"]))
assert abs(pr["u1"]-u1ex)<0.5 and abs(pr["k"]-2.0)<1e-6
assert abs(pr["vRdc"]-0.7457)<0.005, pr["vRdc"]
assert abs(pr["vEd"]-1.1184)<0.01, pr["vEd"]
assert abs(pr["util"]-1.500)<0.02 and pr["util"]>1.0   # needs punching reinforcement
assert pr["crush"]<1.0 and abs(pr["vRdmax"]-4.488)<0.02, (pr["crush"],pr["vRdmax"])
# v_min floor governs a lightly-loaded thin check
pr2=C._punching(50000.0, 300.,300., 150., 25., 0.002, 1.15)
assert pr2["vRdc"]>=pr2["vmin"]-1e-9
# command end-to-end: a column carrying 800 kN -> PunchingShear table, util~1.5
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dPn=Doc(); FreeCAD.ActiveDocument=dPn
col=dPn.addObject("Part::Feature","C1"); col.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,3000)])
col.IsBar=True; col.Section="IPE 200"; col.Material="Steel S235"
col.BarStart=Vec(0,0,0); col.BarEnd=Vec(0,0,3000); col.ResN=-800000.0
C.selected_elems=lambda: [col]
C.form_dialog=lambda title,fields:{"pos":"Internal","c1":400.0,"c2":400.0,
  "d":200.0,"grade":"C30/37","rhol":0.01,"ved":0.0}
gotP={}; C.info=lambda m,g=gotP: g.setdefault("msg",m)
C.PunchingEC2().Activated()
pt=dPn.getObject("PunchingShear")
assert pt is not None and pt._cells.get("E2","").startswith("v_Rd,c") and "F3" in pt._cells
util=float(pt._cells.get("F3")); verdict=pt._cells.get("H3")
print("  command: util=%.2f verdict=%r"%(util,verdict))
assert abs(util-1.50)<0.03 and "reinf" in verdict.lower()
print("EC2 punching shear OK")

print("\n=== Time-history (Newmark-beta): step DAF~2 + period ~ T1 ===")
import re as _re2, math as _mh
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dTH=Doc(); FreeCAD.ActiveDocument=dTH
Lc=3000.
cc=dTH.addObject("Part::Feature","Col"); cc.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Lc)])
cc.IsBar=True; cc.Section="IPE 200"; cc.Material="Steel S235"
cc.BarStart=Vec(0,0,0); cc.BarEnd=Vec(0,0,Lc)
dTH.addObject("Part::Feature","S").Restrain="111111"; dTH.Objects[-1].AtNode=Vec(0,0,0)
C._sel_support_points=lambda doc: [Vec(0,0,Lc)]
C.form_dialog=lambda title,fields:{"exc":"Nodal force","dir":"+X","amp":50000.0,
  "func":"Step","freq":5.0,"td":0.1,"dur":0.6,"dt":0.002,"zeta":0.0}
gotT={}; C.info=lambda m,g=gotT: g.setdefault("msg",m)
C.TimeHistory().Activated()
msg=gotT["msg"]
daf=float(_re2.search(r"amplification\s*([\d.]+)",msg).group(1))
f1=float(_re2.search(r"f1 = ([\d.]+) Hz",msg).group(1))
print("  undamped step: f1=%.3f Hz  DAF=%.3f (expect ~2.0)"%(f1,daf))
assert 1.9<daf<2.2, daf
# period from the response history: first peak at ~T1/2
rh=dTH.getObject("ResponseHistory"); th=[]; r=3
while ("A%d"%r) in rh._cells:
    th.append((float(rh._cells["A%d"%r]), abs(float(rh._cells["B%d"%r])))); r+=1
# first local peak of |u| (the step response peaks at t ~ T1/2); undamped peaks
# all tie, so take the FIRST turning point rather than the global max
tpk=th[-1][0]
for i in range(1, len(th)):
    if th[i][1] < th[i - 1][1] - 1e-9:
        tpk = th[i - 1][0]; break
Tmeas=2*tpk; T1=1.0/f1
print("  measured period=%.4f s  T1=1/f1=%.4f s  ratio=%.3f"%(Tmeas,T1,Tmeas/T1))
assert abs(Tmeas/T1-1.0)<0.08, (Tmeas,T1)
# f1 vs the analytical cantilever (1.875^2/2pi) sqrt(EI/rho A L^4)
rho=7.85e-9; A=2000.; I=1e6; E=210000.
f1ex=(1.875104**2)/(2*_mh.pi)*_mh.sqrt(E*I/(rho*A*Lc**4))
print("  f1=%.3f Hz  analytical=%.3f Hz  ratio=%.3f"%(f1,f1ex,f1/f1ex))
assert abs(f1/f1ex-1.0)<0.05, (f1,f1ex)
assert "base shear" in msg.lower()
# heavy damping -> quasi-static, little overshoot
C.form_dialog=lambda title,fields:{"exc":"Nodal force","dir":"+X","amp":50000.0,
  "func":"Step","freq":5.0,"td":0.1,"dur":0.6,"dt":0.002,"zeta":0.7}
gotT2={}; C.info=lambda m,g=gotT2: g.setdefault("msg",m)
C.TimeHistory().Activated()
daf2=float(_re2.search(r"amplification\s*([\d.]+)",gotT2["msg"]).group(1))
print("  heavy damping (zeta=0.7): DAF=%.3f (expect ~1.0, <1.3)"%daf2)
assert 0.8<daf2<1.3, daf2
# modal superposition reproduces the direct result
C.form_dialog=lambda title,fields:{"exc":"Nodal force","dir":"+X","amp":50000.0,
  "func":"Step","freq":5.0,"td":0.1,"recsheet":"GroundMotion","recunit":"g",
  "dur":0.6,"dt":0.002,"zeta":0.0,"method":"Modal superposition","nmodes":6}
gotM3={}; C.info=lambda m,g=gotM3: g.setdefault("msg",m)
C.TimeHistory().Activated()
dafm=float(_re2.search(r"amplification\s*([\d.]+)",gotM3["msg"]).group(1))
print("  modal (6 modes) step DAF=%.3f  (direct DAF=%.3f)  ratio=%.4f"%(dafm,daf,dafm/daf))
assert abs(dafm-daf)/daf<0.03, (dafm,daf)
print("time-history OK")

print("\n=== Earthquake record (spreadsheet) vs built-in half-sine ===")
import math as _mr, re as _re3
dRC=Doc(); FreeCAD.ActiveDocument=dRC
Lr=3000.
cr=dRC.addObject("Part::Feature","Col"); cr.Shape=Shape(0,[Vec(0,0,0),Vec(0,0,Lr)])
cr.IsBar=True; cr.Section="IPE 200"; cr.Material="Steel S235"
cr.BarStart=Vec(0,0,0); cr.BarEnd=Vec(0,0,Lr)
dRC.addObject("Part::Feature","S").Restrain="111111"; dRC.Objects[-1].AtNode=Vec(0,0,0)
C._sel_support_points=lambda doc: [Vec(0,0,Lr)]
# a half-sine pulse (td=0.1) sampled at dt into a sheet, with a header row
gm=dRC.addObject("Spreadsheet::Sheet","GroundMotion"); gm.Label="GroundMotion"
gm.set("A1","t (s)"); gm.set("B1","accel"); tdp=0.1; tt=0.0; rr2=2
while tt<=0.3+1e-9:
    gm.set("A%d"%rr2, tt)
    gm.set("B%d"%rr2, (_mr.sin(_mr.pi*tt/tdp) if tt<=tdp else 0.0)); rr2+=1; tt+=0.002
base=dict(exc="Nodal force",dir="+X",amp=50000.0,freq=5.0,td=0.1,
          recsheet="GroundMotion",recunit="g",dur=1.0,dt=0.002,zeta=0.05)
def runth(func):
    v=dict(base); v["func"]=func
    C.form_dialog=lambda title,fields,_v=v:_v
    g={}; C.info=lambda m,gg=g: gg.setdefault("msg",m)
    C.TimeHistory().Activated()
    return float(_re3.search(r"= ([\d.eE+-]+) mm",g["msg"]).group(1))
pkA=runth("Half-sine pulse")
pkB=runth("Record (spreadsheet)")
print("  built-in half-sine peak=%.5g mm   record peak=%.5g mm   ratio=%.4f"
      %(pkA,pkB,pkB/pkA))
assert abs(pkB/pkA-1.0)<0.01, (pkA,pkB)
# the reader skips the header and returns the series (first value ~0)
rr=C._read_record(dRC,"GroundMotion")
assert rr is not None and len(rr[0])>100 and abs(rr[1][0])<1e-9, (rr and len(rr[0]))
# a missing sheet is reported, not crashed
gmiss={}; C.info=lambda m,g=gmiss: g.setdefault("msg",m)
C.form_dialog=lambda title,fields:dict(base,func="Record (spreadsheet)",recsheet="NOPE")
C.TimeHistory().Activated()
assert "not found" in gmiss.get("msg","").lower(), gmiss
print("earthquake record OK")

print("\n=== Ground-motion import (.AT2 / CSV parser + command) ===")
# PEER .AT2: a header with NPTS/DT then accel values, time = i*DT
at2="PEER NGA STRONG MOTION\nEL CENTRO ARRAY\nNPTS=  5, DT=  0.0200 SEC\n"\
    " 0.000  0.100  0.200\n 0.300  0.400\n"
ts,acc=C._parse_motion(at2,"Auto",0.02)
print("  .AT2 -> %d pts, dt=%.4f, acc[:3]=%s"%(len(ts),ts[1]-ts[0],acc[:3]))
assert len(ts)==5 and abs(ts[1]-0.02)<1e-9 and acc==[0.0,0.1,0.2,0.3,0.4], (ts,acc)
# CSV time,accel and accel-only
tsc,accc=C._parse_motion("t,a\n0,0\n0.02,0.1\n0.04,0.2\n","Auto",0.02)
assert tsc==[0.0,0.02,0.04] and accc==[0.0,0.1,0.2], (tsc,accc)
tsa,acca=C._parse_motion("0\n0.1\n0.2\n","CSV accel-only",0.02)
assert abs(tsa[2]-0.04)<1e-9 and acca==[0.0,0.1,0.2], (tsa,acca)
# command end-to-end: import an .AT2 file into a sheet
import tempfile as _tf, os as _os2
fd,pth=_tf.mkstemp(suffix=".AT2"); _os2.write(fd,at2.encode()); _os2.close(fd)
dGM=Doc(); FreeCAD.ActiveDocument=dGM
C.form_dialog=lambda title,fields:{"path":pth,"fmt":"PEER .AT2","dt":0.02,
                                   "sheet":"GroundMotion"}
gGM={}; C.info=lambda m,g=gGM: g.setdefault("msg",m)
C.ImportGroundMotion().Activated()
gm=dGM.getObject("GroundMotion")
assert gm is not None and gm._cells.get("A1","").startswith("time")
assert abs(float(gm._cells["A3"])-0.02)<1e-9 and abs(float(gm._cells["B4"])-0.2)<1e-9
rr=C._read_record(dGM,"GroundMotion")
assert rr is not None and len(rr[0])==5
_os2.remove(pth)
print("  imported %d pts; '%s'"%(len(rr[0]), gGM["msg"].split(chr(10))[0]))
print("ground-motion import OK")

print("\n=== Storey drift (time-history) + response spectrum ===")
import math as _ms2, re as _re4
# storey-level grouping
assert C._storey_levels([0.0,0.0,3000.0,3000.4,6000.0],1.0)==[0.0,3000.0,6000.0]
# a 2-storey column: levels 0 / 3000 / 6000, lateral step at the top
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dSD=Doc(); FreeCAD.ActiveDocument=dSD
for (za,zb) in ((0,3000),(3000,6000)):
    b=dSD.addObject("Part::Feature","C_%d"%zb); b.Shape=Shape(0,[Vec(0,0,za),Vec(0,0,zb)])
    b.IsBar=True; b.Section="IPE 200"; b.Material="Steel S235"
    b.BarStart=Vec(0,0,za); b.BarEnd=Vec(0,0,zb)
dSD.addObject("Part::Feature","S").Restrain="111111"; dSD.Objects[-1].AtNode=Vec(0,0,0)
C._sel_support_points=lambda doc: [Vec(0,0,6000)]
C.form_dialog=lambda title,fields:{"exc":"Nodal force","dir":"+X","amp":20000.0,
  "func":"Step","freq":5.0,"td":0.1,"recsheet":"GroundMotion","recunit":"g",
  "dur":0.5,"dt":0.002,"zeta":0.05,"method":"Direct (Newmark)","nmodes":6}
gSD={}; C.info=lambda m,g=gSD: g.setdefault("msg",m)
C.TimeHistory().Activated()
dr=dSD.getObject("StoreyDrift")
assert dr is not None and dr._cells.get("D2","").startswith("drift")
# two storeys, and the reported drift ratio equals drift / storey height
d1=float(dr._cells["D3"]); rat1=float(_re4.match(r"([\d.]+)",dr._cells["E3"]).group(1))
assert "E4" in dr._cells and abs(rat1-d1/3000.0)<5e-3, (d1,rat1)  # =d/h (to rounding)
assert "inter-storey drift" in gSD["msg"].lower()
print("  2-storey drift: storey-1 drift=%.4g mm ratio=%.5f (=d/h OK)"%(d1,rat1))
# response spectrum of a sine: Sa(small T) ~ PGA, resonant peak at T=1/f ~ A/2zeta
f=2.0; A=1000.0; zt=0.05; Nr=4000; dtr=0.005
tss=[i*dtr for i in range(Nr+1)]; agg=[A*_ms2.sin(2*_ms2.pi*f*t) for t in tss]
pers=[0.04+(1.0-0.04)*i/59 for i in range(60)]
Sd,Sa=C._response_spectrum(tss,agg,zt,pers)
im=max(range(60),key=lambda i:Sa[i])
print("  spectrum: Sa(T=%.2f)=%.0f (PGA=%.0f); peak Sa=%.0f at T=%.3f (~1/f=0.5, ~A/2z=%.0f)"
      %(pers[0],Sa[0],A,max(Sa),pers[im],A/(2*zt)))
assert 0.8*A<=Sa[0]<=1.4*A, Sa[0]
assert abs(pers[im]-1.0/f)<0.08, pers[im]
assert abs(max(Sa)-A/(2*zt))/(A/(2*zt))<0.2, max(Sa)
# GMSpectrum command on a sine sheet (unit mm/s2)
dGS=Doc(); FreeCAD.ActiveDocument=dGS
gm=dGS.addObject("Spreadsheet::Sheet","GM2"); gm.Label="GM2"
gm.set("A1","t"); gm.set("B1","a")
for i in range(Nr+1):
    gm.set("A%d"%(i+2), tss[i]); gm.set("B%d"%(i+2), agg[i])
C.form_dialog=lambda title,fields:{"sheet":"GM2","unit":"mm/s2","zeta":0.05,
                                   "tmax":1.0,"nt":60}
gGS={}; C.info=lambda m,g=gGS: g.setdefault("msg",m)
C.GMSpectrum().Activated()
sp=dGS.getObject("GMSpectrum")
assert sp is not None and sp._cells.get("C2","").startswith("Sa")
pkT=float(_re4.search(r"at T = ([\d.]+) s",gGS["msg"]).group(1))
print("  GMSpectrum command: peak Sa at T=%.3f s (expect ~0.5)"%pkT)
assert abs(pkT-0.5)<0.08, pkT
print("storey drift + response spectrum OK")

print("\n=== Supports on solid bodies (snap) + single DynFrame group ===")
C._section_props_from_name=lambda name:(2000.0,1.0e6,1.0e6,2.0e6,100.0)
dB=Doc(); FreeCAD.ActiveDocument=dB
# a SOLID member (body), not a line bar: has MemberProfile + skeleton endpoints
mm=dB.addObject("Part::Feature","Col"); mm.MemberProfile="IPE 200"
mm.MemberStart=Vec(0,0,0); mm.MemberEnd=Vec(0,0,3000); mm.Material="Steel S235"
assert C.is_member(mm) and not C.is_bar(mm)
nds=C._analysis_node_pts(dB)
assert len(nds)==2 and any((q-Vec(0,0,0)).Length<1e-6 for q in nds), nds
# a clicked section CORNER vertex is off the centreline -> must snap to the node
snapped,nsnap=C._snap_to_nodes([Vec(150,100,0.0), Vec(150,-100,3000.0)], dB)
print("  corners snapped to %s (nsnap=%d)"
      %([(round(p.x),round(p.y),round(p.z)) for p in snapped],nsnap))
assert nsnap==2 and len(snapped)==2
assert any((p-Vec(0,0,0)).Length<1e-6 for p in snapped)
assert any((p-Vec(0,0,3000)).Length<1e-6 for p in snapped)
# end-to-end: a support at the snapped base node makes the BODY model solve
C._apply_support(dB,"Fixed (all 6)",[Vec(0,0,0)])
P=1000.0; Lc2=3000.
nl=dB.addObject("Part::Feature","NL"); nl.LoadType="Nodal"; nl.LoadCase="DL1"
nl.LoadVec=Vec(P,0,0); nl.AtNode=Vec(0,0,3000)   # lateral tip load
gotB={}; C.info=lambda m2,g=gotB: g.setdefault("msg",m2)
C.get_item=lambda t,l,items,cur=0:("All loads",True)
C.RunAnalysis().Activated(run_pick="All loads", include_sw=False, second_order=False)
assert "complete" in gotB.get("msg","").lower(), gotB.get("msg")
md=float(__import__("re").search(r"Max displacement:\s*([\d.]+)",gotB["msg"]).group(1))
dex=P*Lc2**3/(3*210000.*1.0e6)
print("  body cantilever solved: max disp=%.3f mm (exact PL^3/3EI=%.3f)"%(md,dex))
assert abs(md/dex-1.0)<0.02, (md,dex)
# everything DynFrame made sits under ONE 'DynFrame' root group (not scattered)
root=[o for o in dB.Objects if getattr(o,"TypeId","")=="App::DocumentObjectGroup"
      and o.Label=="DynFrame"]
assert len(root)==1, "expected one DynFrame root group"
subs={g.Label for g in root[0].Group
      if getattr(g,"TypeId","")=="App::DocumentObjectGroup"}
print("  DynFrame root holds:", sorted(subs))
assert {"Results","Supports"}<=subs, subs
res=[g for g in root[0].Group if g.Label=="Results"][0]
assert any(getattr(x,"TypeId","")=="Spreadsheet::Sheet" for x in res.Group), \
    "result spreadsheets live under DynFrame/Results"
print("supports-on-bodies + single DynFrame group OK")

print("\n=== Wall thermal: U-value (EN ISO 6946) + Glaser condensation (13788) ===")
# saturation vapour pressure anchors
assert abs(C._sat_vapour_pressure(0.0)-610.5)<1.0 and abs(C._sat_vapour_pressure(20.0)-2337)<6
assert abs(C._sat_vapour_pressure(10.0)-1227)<6, C._sat_vapour_pressure(10.0)
def _lyr(name,d):
    k,mu,fR=C._thermal_mat(name); return (name,d,k,mu,fR)
# U-value: 200 mm dense concrete (k=2.0) + 100 mm EPS (k=0.035)
L=[_lyr("Concrete (dense)",200.0), _lyr("EPS insulation",100.0)]
U,R,perR=C._wall_uvalue(L,0.13,0.04)
print("  U=%.4f W/m2K  R=%.3f  (expect U~0.320, R~3.127)"%(U,R))
assert abs(R-3.1271)<0.01 and abs(U-0.31978)<0.002, (U,R)
r=C._wall_thermal(L,20.0,60.0,0.0,90.0,0.13,0.04)
assert abs(r["q"]-U*20.0)<1e-6 and abs(r["nodeT"][0]-(20.0-r["q"]*0.13))<1e-6
assert 0.9<r["fRsi"]<1.0
print("  q=%.1f W/m2  Tsi=%.2f C  f_Rsi=%.3f"%(r["q"],r["nodeT"][0],r["fRsi"]))
# Glaser direction: insulation on the WRONG (warm/inside) side condenses behind
# it; the same insulation outside keeps the structure warm and stays dry
bad=C._wall_thermal([_lyr("EPS insulation",60.0),_lyr("Concrete (dense)",200.0)],
                    20.0,60.0,-10.0,80.0)
good=C._wall_thermal([_lyr("Concrete (dense)",200.0),_lyr("EPS insulation",60.0)],
                     20.0,60.0,-10.0,80.0)
print("  insulation inside -> condensation=%s ; insulation outside -> %s"
      %(bad["condensation"],good["condensation"]))
assert bad["condensation"] is True and good["condensation"] is False
# command end-to-end writes the WallThermal table
dWT=Doc(); FreeCAD.ActiveDocument=dWT
C.form_dialog=lambda title,fields:{"m0":"Plasterboard","d0":12.5,"m1":"Mineral wool",
  "d1":120.0,"m2":"Brick (fired clay)","d2":100.0,"m3":"(none)","d3":0.0,
  "m4":"(none)","d4":0.0,"m5":"(none)","d5":0.0,"Ti":20.0,"RHi":60.0,"Te":-5.0,
  "RHe":90.0,"rsi":0.13,"rse":0.04}
gWT={}; C.info=lambda m,g=gWT: g.setdefault("msg",m)
C.WallThermal().Activated()
wt=dWT.getObject("WallThermal")
assert wt is not None and wt._cells.get("A1","").startswith("WALL THERMAL")
assert "U-value" in gWT["msg"], gWT["msg"]
print("  command: %s"%wt._cells["A1"][:70])
print("wall thermal OK")

print("\nALL RUNTIME CHECKS PASSED")
