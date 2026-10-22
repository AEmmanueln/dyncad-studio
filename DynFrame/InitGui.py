# -*- coding: utf-8 -*-
"""DynFrame workbench registration (GUI)."""

import os
import FreeCAD
import FreeCADGui


class DynFrameWorkbench(FreeCADGui.Workbench):
    MenuText = "DynFrame"
    ToolTip = "Inventor-style Frame Generator, modeling helpers and export tools"

    def __init__(self):
        self.__class__.Icon = os.path.join(os.path.dirname(__file__),
                                            "icons", "dynframe.svg")

    def Initialize(self):
        # Importing the module registers all DynFrame_* commands.
        import dynframe_commands  # noqa: F401

        frame = ["DynFrame_InsertMembers", "DynFrame_ChangeProfile",
                 "DynFrame_LengthenShorten", "DynFrame_TrimButt",
                 "DynFrame_Miter", "DynFrame_TrimToFace", "DynFrame_CutList"]
        skel = ["DynFrame_Skeleton3D"]
        model = ["DynFrame_QuickFillet"]
        io = ["DynFrame_ExportStep", "DynFrame_ExportStl"]
        setup = ["DynFrame_InventorNav"]

        self.appendToolbar("DynFrame · Frame", frame)
        self.appendToolbar("DynFrame · Skeleton", skel)
        self.appendToolbar("DynFrame · Model", model)
        self.appendToolbar("DynFrame · Export", io)
        self.appendMenu("DynFrame", frame + skel + model + io + setup)
        FreeCAD.Console.PrintMessage("DynFrame workbench loaded\n")

    def Activated(self):
        FreeCAD.Console.PrintMessage("DynFrame workbench activated\n")

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(DynFrameWorkbench())
