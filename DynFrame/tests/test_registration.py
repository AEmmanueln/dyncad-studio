"""Registration test: exec InitGui.py the way FreeCAD does (separate
globals/locals, no __file__) and confirm the workbench registers and every
DynFrame command is added. Run:  python3 DynFrame/tests/test_registration.py"""
import sys, types, os
DF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DF)

# minimal mocks so dynframe_commands import works in Initialize()
for name in ["Part"]:
    m=types.ModuleType(name); sys.modules[name]=m
class _Any:
    def __init__(s,*a,**k): pass
    def __getattr__(s,k): return _Any()
    def __call__(s,*a,**k): return _Any()
    def __mul__(s,o): return _Any()
    def __add__(s,o): return _Any()
    def __sub__(s,o): return _Any()
sys.modules["Part"].__dict__.update({k:_Any() for k in ["makePolygon","Face","Wire","makeCircle","makeBox","export"]})

FreeCAD=types.ModuleType("FreeCAD")
FreeCAD.getUserAppDataDir=lambda: os.path.join(os.getcwd(),"DynFrame")+os.sep+".."+os.sep  # dummy
FreeCAD.Vector=_Any; FreeCAD.Rotation=_Any; FreeCAD.Placement=_Any; FreeCAD.Matrix=_Any
class _C:
    def PrintMessage(s,*a): pass
    def PrintError(s,*a): print("PrintError:",a)
FreeCAD.Console=_C(); FreeCAD.ActiveDocument=None; FreeCAD.ParamGet=lambda s:_Any(); FreeCAD.newDocument=lambda *a:None
sys.modules["FreeCAD"]=FreeCAD

_CMDS={}
class Workbench:
    def appendToolbar(self,n,c): pass
    def appendMenu(self,n,c): pass
_registered=[]
FreeCADGui=types.ModuleType("FreeCADGui")
FreeCADGui.Workbench=Workbench
FreeCADGui.addWorkbench=lambda wb:_registered.append(wb)
FreeCADGui.addCommand=lambda n,c:_CMDS.__setitem__(n,c)
FreeCADGui.getMainWindow=lambda:None
FreeCADGui.Selection=_Any(); FreeCADGui.activeDocument=lambda:None; FreeCADGui.SendMsgToActiveView=lambda m:None
FreeCADGui.activateWorkbench=lambda n:None; FreeCADGui.runCommand=lambda n:None
sys.modules["FreeCADGui"]=FreeCADGui

PySide=types.ModuleType("PySide"); QtGui=types.ModuleType("PySide.QtGui"); QtWidgets=types.ModuleType("PySide.QtWidgets")
for mm in (QtGui,QtWidgets):
    mm.QMessageBox=_Any(); mm.QInputDialog=_Any(); mm.QFileDialog=_Any()
PySide.QtGui=QtGui; PySide.QtWidgets=QtWidgets
sys.modules["PySide"]=PySide; sys.modules["PySide.QtGui"]=QtGui; sys.modules["PySide.QtWidgets"]=QtWidgets

# ---- THE REAL TEST: exec InitGui.py the way FreeCAD does: SEPARATE globals/locals, no __file__ ----
path=os.path.join(DF,"InitGui.py")
src=open(path,encoding="utf-8").read()
g={}; l={}   # separate dicts, __file__ absent -> replicates FreeCAD startup
try:
    exec(compile(src, path, "exec"), g, l)
    print("exec with SEPARATE globals/locals: OK (no NameError)")
except Exception as e:
    import traceback; traceback.print_exc(); print("FAILED"); sys.exit(1)

print("addWorkbench called:", len(_registered)==1)
wb=_registered[0]
print("workbench MenuText:", wb.MenuText)
# now exercise Initialize() under the same instance (methods do local imports)
wb.Initialize()
print("Initialize() ran; commands registered:", len(_CMDS))
assert len(_registered)==1 and len(_CMDS)>=12
print("PASS: InitGui registers and initializes under FreeCAD-style exec")
