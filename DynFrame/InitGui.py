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

        frame = ["DynFrame_InsertMembers", "DynFrame_RebuildFromSketch",
                 "DynFrame_ChangeProfile", "DynFrame_LengthenShorten",
                 "DynFrame_ExtendToFace", "DynFrame_TrimButt", "DynFrame_Miter",
                 "DynFrame_TrimToFace"]
        pattern = ["DynFrame_MirrorMembers", "DynFrame_RectPattern",
                   "DynFrame_CircPattern"]
        skel = ["DynFrame_Skeleton3D", "DynFrame_ConstrainedSketch"]
        model = ["DynFrame_Hole", "DynFrame_QuickFillet"]
        report = ["DynFrame_CutList", "DynFrame_BOM"]
        panel = ["DynFrame_Manager", "DynFrame_ResultsViewer"]
        structure = ["DynFrame_GridGen", "DynFrame_AddBars",
                     "DynFrame_BarsFromMembers", "DynFrame_EditTables",
                     "DynFrame_BuildFromTables", "DynFrame_AddPlate"]
        loads = ["DynFrame_NewLoadCase", "DynFrame_DefineSupport",
                 "DynFrame_AddNodalLoad", "DynFrame_AddMemberLoad",
                 "DynFrame_AddPlateLoad", "DynFrame_MemberReleases",
                 "DynFrame_Combinations"]
        results = ["DynFrame_RunAnalysis", "DynFrame_ModalAnalysis",
                   "DynFrame_BucklingAnalysis", "DynFrame_ResponseSpectrum",
                   "DynFrame_Envelope", "DynFrame_CodeCheck",
                   "DynFrame_ShowDiagram", "DynFrame_ClearAnalysis"]
        analysis = panel + structure + loads + results
        io = ["DynFrame_ExportStep", "DynFrame_ExportStl"]
        setup = ["DynFrame_InventorNav"]

        self.appendToolbar("DynFrame · Frame", frame)
        self.appendToolbar("DynFrame · Pattern", pattern)
        self.appendToolbar("DynFrame · Skeleton", skel)
        self.appendToolbar("DynFrame · Model", model)
        self.appendToolbar("DynFrame · Report", report)
        self.appendToolbar("DynFrame · Analysis Panel", panel)
        self.appendToolbar("DynFrame · Structure", structure)
        self.appendToolbar("DynFrame · Loads", loads)
        self.appendToolbar("DynFrame · Results", results)
        self.appendToolbar("DynFrame · Export", io)
        self.appendMenu(["DynFrame", "Analysis (Structure)"], structure)
        self.appendMenu(["DynFrame", "Analysis (Loads)"], loads)
        self.appendMenu(["DynFrame", "Analysis (Results)"], results)
        self.appendMenu("DynFrame", frame + pattern + skel + model + report
                        + analysis + io + setup)
        FreeCAD.Console.PrintMessage("DynFrame workbench loaded\n")

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(DynFrameWorkbench())
