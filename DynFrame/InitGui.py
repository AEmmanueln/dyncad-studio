# -*- coding: utf-8 -*-
"""DynFrame workbench registration (GUI).

IMPORTANT: FreeCAD exec's this file with separate globals/locals, so
module-level names (imports, variables) are NOT visible inside the class
body or its methods. Therefore:
  * the class body uses only literal attributes (no module variables);
  * every method imports what it needs locally;
  * the icon path is computed inside __init__ (local imports, no __file__).
Breaking these rules makes the workbench fail to register at startup with
errors like "name '_ICON' is not defined" — even though it works when the
file is exec'd by hand in a single namespace.
"""

import FreeCAD
import FreeCADGui


class DynFrameWorkbench(FreeCADGui.Workbench):
    MenuText = "DynFrame"
    ToolTip = "Inventor-style Frame Generator, modeling helpers and export tools"

    def __init__(self):
        import os
        try:
            import FreeCAD
            icon = os.path.join(FreeCAD.getUserAppDataDir(),
                                "Mod", "DynFrame", "icons", "dynframe.svg")
            if os.path.exists(icon):
                self.__class__.Icon = icon
        except Exception:
            pass

    def Initialize(self):
        import FreeCAD
        try:
            import dynframe_commands  # noqa: F401  (registers DynFrame_* commands)
        except Exception:
            import traceback
            FreeCAD.Console.PrintError("DynFrame: commands failed to load\n"
                                       + traceback.format_exc())
            return

        frame = ["DynFrame_InsertMembers", "DynFrame_ChangeProfile",
                 "DynFrame_LengthenShorten", "DynFrame_ExtendToFace",
                 "DynFrame_TrimButt", "DynFrame_Miter", "DynFrame_TrimToFace",
                 "DynFrame_CutList"]
        skel = ["DynFrame_Skeleton3D"]
        model = ["DynFrame_Hole", "DynFrame_QuickFillet"]
        io = ["DynFrame_ExportStep", "DynFrame_ExportStl"]
        setup = ["DynFrame_InventorNav"]

        self.appendToolbar("DynFrame · Frame", frame)
        self.appendToolbar("DynFrame · Skeleton", skel)
        self.appendToolbar("DynFrame · Model", model)
        self.appendToolbar("DynFrame · Export", io)
        self.appendMenu("DynFrame", frame + skel + model + io + setup)
        FreeCAD.Console.PrintMessage("DynFrame workbench loaded\n")

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(DynFrameWorkbench())
