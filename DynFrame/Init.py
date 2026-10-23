# -*- coding: utf-8 -*-
"""DynFrame non-GUI init (runs in both FreeCAD and FreeCADCmd).

Writes a startup marker so we can confirm, from a clean restart, that
FreeCAD reached this folder and whether InitGui.py ran afterwards.
"""

import os

try:
    _DIR = os.path.dirname(__file__)
except Exception:
    import FreeCAD as _fc
    _DIR = os.path.join(_fc.getUserAppDataDir(), "Mod", "DynFrame")

try:
    import time
    import FreeCAD
    with open(os.path.join(_DIR, "_load.log"), "a") as _f:
        _f.write("%s  Init.py ran (GuiUp=%s)\n"
                 % (time.ctime(), getattr(FreeCAD, "GuiUp", "?")))
except Exception:
    pass
