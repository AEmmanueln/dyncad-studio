# -*- coding: utf-8 -*-
"""One-shot CfdOF setup for an existing blueCFD + ParaView install.

Run it from the FreeCAD Python console (View > Panels > Python console):

    exec(open(FreeCAD.getUserAppDataDir()+"/Mod/DynFrame/tools/cfdof_setup.py").read())

What it does automatically:
  * finds blueCFD-Core (OpenFOAM) and ParaView under Program Files,
  * writes CfdOF's OpenFOAM / ParaView / Gmsh preference paths,
  * runs CfdOF's dependency checker and prints the report.

What it CANNOT do (no stable headless API, and they compile for minutes):
  * install cfMesh and HiSA. The script opens the CfdOF preferences page so you
    click 'Install cfMesh' and 'Install HiSA' once; CfdOF then downloads and
    builds them for you (no coding). Re-run the checker afterwards.

If auto-detect misses your install, set OPENFOAM_DIR / PARAVIEW below (use
forward slashes) and run it again.
"""
import FreeCAD
import glob
import os

# ---- optional manual override (use forward slashes); "AUTO" = detect ----
OPENFOAM_DIR = "AUTO"   # e.g. "C:/Program Files/blueCFD-Core-2024/OpenFOAM-v2012"
PARAVIEW = "AUTO"       # e.g. "C:/Program Files/blueCFD-Core-2024/ParaView-5.9.1/bin/paraview.exe"
GMSH = "AUTO"           # optional


def _hits(patterns):
    out = []
    for pat in patterns:
        out += glob.glob(pat)
    return sorted(set(out))


def _first(patterns):
    h = _hits(patterns)
    return h[-1] if h else ""


# candidate OpenFOAM install dirs (blueCFD first, then ESI/.org layouts)
of_candidates = ([OPENFOAM_DIR] if OPENFOAM_DIR != "AUTO" else []) + _hits([
    "C:/Program Files*/blueCFD-Core-*/OpenFOAM-*",
    "C:/Program Files*/blueCFD-Core-*",
    "C:/Program Files*/ESI-OpenCFD/OpenFOAM/*/*",
    "C:/Program Files*/ESI-OpenCFD/OpenFOAM/*",
    "/opt/openfoam*", "/usr/lib/openfoam/openfoam*",
])
if PARAVIEW == "AUTO":
    PARAVIEW = _first([
        "C:/Program Files*/blueCFD-Core-*/ParaView*/bin/paraview.exe",
        "C:/Program Files*/ParaView*/bin/paraview.exe",
        "/usr/bin/paraview", "/opt/paraview*/bin/paraview",
    ])
if GMSH == "AUTO":
    GMSH = _first([
        "C:/Program Files*/blueCFD-Core-*/**/gmsh.exe",
        "C:/Program Files*/gmsh*/gmsh.exe", "C:/Program Files*/*/gmsh.exe",
        "/usr/bin/gmsh",
    ])

prefs = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CfdOF")

# pick the OpenFOAM dir that CfdOF accepts (setFoamDir validates it)
chosen_of = ""
try:
    from CfdOF import CfdTools
except Exception as exc:
    CfdTools = None
    print("!! Could not import CfdOF - install it first: Tools > Addon Manager "
          "> CfdOF > Install, restart FreeCAD, then run this again. (%s)" % exc)

if CfdTools is not None:
    for cand in of_candidates:
        if not cand or not os.path.isdir(cand):
            continue
        try:
            CfdTools.setFoamDir(cand)       # writes the pref AND validates
            chosen_of = cand
            break
        except Exception:
            continue
    if not chosen_of and of_candidates:
        # nothing validated; still store the best guess so the checker can report
        prefs.SetString("InstallationPath", of_candidates[0])
        chosen_of = of_candidates[0] + "  (unvalidated - check the report below)"

if PARAVIEW:
    prefs.SetString("ParaviewPath", PARAVIEW)
if GMSH:
    prefs.SetString("GmshPath", GMSH)

print("=== CfdOF paths ===")
print("  OpenFOAM :", chosen_of or "NOT FOUND - set OPENFOAM_DIR and re-run")
print("  ParaView :", PARAVIEW or "NOT FOUND - set PARAVIEW and re-run")
print("  Gmsh     :", GMSH or "(optional) not found")

if CfdTools is not None:
    print("\n=== Dependency checker ===")
    try:
        report = CfdTools.checkCfdDependencies()
    except TypeError:
        try:
            report = CfdTools.checkCfdDependencies(lambda s: None)
        except Exception as exc:
            report = "checker call failed: %s" % exc
    except Exception as exc:
        report = "checker call failed: %s" % exc
    print(report if report else "(no problems reported)")

print("\n=== cfMesh + HiSA ===")
print("These download-and-compile; CfdOF installs them from its Preferences "
      "page (no coding). Opening Preferences now - open the CfdOF group and "
      "click 'Install cfMesh' and 'Install HiSA', then 'Run dependency "
      "checker' until every line is OK.")
try:
    import FreeCADGui
    FreeCADGui.runCommand("Std_DlgPreferences")
except Exception:
    print("(Open  Edit > Preferences > CfdOF  manually.)")
