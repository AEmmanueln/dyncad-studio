# -*- coding: utf-8 -*-
"""DynFrame workbench registration (GUI).

Note: this file must not rely on __file__ at import time — FreeCAD's
startup loader does not always define it when it execs InitGui.py, and a
failure here makes the whole workbench silently disappear. We resolve the
module directory defensively instead.
"""

import os
import FreeCAD
import FreeCADGui

try:
    _DIR = os.path.dirname(__file__)
except Exception:
    _DIR = os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "DynFrame")
_ICON = os.path.join(_DIR, "icons", "dynframe.svg")


class DynFrameWorkbench(FreeCADGui.Workbench):
    MenuText = "DynFrame"
    ToolTip = "Inventor-style Frame Generator, modeling helpers and export tools"
    Icon = _ICON

    def Initialize(self):
        try:
            import dynframe_commands  # registers all DynFrame_* commands
        except Exception:
            import traceback
            FreeCAD.Console.PrintError("DynFrame: commands failed to load\n"
                                       + traceback.format_exc())
            return

        frame = ["DynFrame_InsertMembers", "DynFrame_ChangeProfile",
                 "DynFrame_LengthenShorten", "DynFrame_TrimButt",
                 "DynFrame_Miter", "DynFrame_TrimToFace", "DynFrame_CutList"]
        skel = ["DynFrame_Skeleton3D"]
        model = ["DynFrame_QuickFillet"]
        io = ["DynFrame_ExportStep", "DynFrame_ExportStl"]
        setup = ["DynFrame_InventorNav"]

        try:
            self.appendToolbar("DynFrame · Frame", frame)
            self.appendToolbar("DynFrame · Skeleton", skel)
            self.appendToolbar("DynFrame · Model", model)
            self.appendToolbar("DynFrame · Export", io)
            self.appendMenu("DynFrame", frame + skel + model + io + setup)
        except Exception:
            import traceback
            FreeCAD.Console.PrintError("DynFrame: toolbar/menu setup failed\n"
                                       + traceback.format_exc())
        FreeCAD.Console.PrintMessage("DynFrame workbench loaded\n")

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


try:
    FreeCADGui.addWorkbench(DynFrameWorkbench())
except Exception:
    import traceback
    FreeCAD.Console.PrintError("DynFrame: addWorkbench failed at startup\n"
                               + traceback.format_exc())
