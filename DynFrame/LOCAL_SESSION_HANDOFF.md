# DynFrame CFD — handoff to a local Claude Code session

You are a Claude Code session running **on the user's own Windows PC**
(`DESKTOP-CTS5QOH`), which has **FreeCAD 1.1, OpenFOAM 14 in WSL, and ParaView**
installed. A previous cloud session built the work below but could not run or
test any of it (no FreeCAD/OpenFOAM in the cloud). **Your job is to actually run,
test, validate and extend it on this machine** — the thing the cloud session
couldn't do.

Read this, then confirm the current state works before building anything new.

## The goal

A **local, SimScale-class CFD workbench inside FreeCAD** (the DynFrame
workbench) that drives the user's OpenFOAM for **all** OpenFOAM physics, with a
visual, interactive setup in the FreeCAD 3D view and results in ParaView. Free
and FreeCAD-based (no cloud, no paid tools). The engine is OpenFOAM; ParaView is
the viewer; DynFrame is the GUI/driver. "Same case → same results as SimScale,"
because SimScale also runs OpenFOAM.

## Where the code is

- Repo branch: **`claude/sleepy-ramanujan-96b3y6`** (develop here; the user's
  rule is to stay on this branch).
- Installed workbench on this PC:
  `%APPDATA%\FreeCAD\Mod\DynFrame\` (what FreeCAD loads).
- The one-line updater in `DynFrame/README.md` ("Install / update straight from
  the FreeCAD Python console") copies the branch into that Mod folder.

## What is already built (all committed on the branch)

Pure, unit-tested generators (no FreeCAD imports):
- `DynFrame/dynframe_cfd.py` — WSL/Windows path translation, `foamDictionary`
  command builder, the 20-module OpenFOAM catalog, run/view script builders,
  `wsl_run_argv` (blank distro ⇒ default distro).
- `DynFrame/dynframe_cfd_gen.py` — mesh-from-CAD (blockMesh + snappyHexMesh +
  surfaceFeatures dicts, ASCII-STL writer), the incompressible-flow case
  generator (U/p/k/omega/nut fields + kOmegaSST + fvSchemes/fvSolution/
  controlDict), the mesh+solve scripts, and the domain-preview face→BC colours.

FreeCAD commands in `DynFrame/dynframe_commands.py` (toolbar **DynFrame · CFD**):
- **CfdDomain** — draws the flow domain as a transparent box with BC-coloured
  faces + inlet arrows in the 3D view (visual preview; this one rendered OK).
- **CfdMeshFromCad** — snappyHexMesh a selected solid.
- **CfdFlow** — end-to-end incompressible flow: auto-mesh + auto-BCs + solve +
  VTK, and draws the domain preview.
- **CfdCase** — run any of the 20 OpenFOAM modules from its own tutorial.
- **CfdView** — convert a case's latest results to VTK for ParaView.

Docs: `DynFrame/CFD_with_OpenFOAM.md` (§0 = the CFD commands),
`DynFrame/OpenFOAM14_solver_catalog.md`, and the README CFD section.

## FIRST: confirm the baseline actually runs (do this before anything new)

1. **Unit tests** (pure Python, numpy only):
   ```
   python3 DynFrame/tests/validate.py
   python3 DynFrame/tests/test_registration.py
   ```
   Both should print pass lines (61 commands registered).

2. **FreeCAD loads the workbench headlessly** — run FreeCAD's console binary
   (`FreeCADCmd` / `freecadcmd` / `FreeCADCmd.exe`) and exec `InitGui.py` the way
   `test_registration.py` does, or just import `dynframe_commands`. Fix any
   import/registration error you find.

3. **The generated flow case actually meshes + solves** — the real test the
   cloud session could not do:
   - In FreeCAD, select a solid (a Part **Cube** is fine) → **CFD Flow** → set an
     inlet speed → it writes `~/dynframe_cfd/run_flow_<name>.sh` (staged under
     the Windows `dynframe_cfd` folder) and prints a `bash /mnt/c/.../*.sh`
     one-liner.
   - Run that script in the **WSL OpenFOAM 14** shell
     (`. /opt/openfoam14/etc/bashrc`). Watch `blockMesh → snappyHexMesh →
     checkMesh → foamRun → foamToVTK`.
   - **This is where real bugs will surface** (dict syntax for OF-14, patch-name
     mismatches, snappy settings, locationInMesh, `physicalProperties` form).
     Fix them in `dynframe_cfd_gen.py` until `checkMesh` says `Mesh OK` and
     `foamRun` converges and writes a result. Re-run the unit tests after each
     change.

## Known issues to expect

- **WSL distro name:** this PC's distro is NOT literally "Ubuntu" (auto-run hit
  `WSL_E_DISTRO_NOT_FOUND`). Find it with `wsl -l -v`; the CFD dialogs now
  default the distro field to blank (⇒ default distro). Consider
  `wsl --set-default <name>` so auto-run works.
- `constant/physicalProperties` nu form is the most likely OF-14 syntax quirk —
  verify against a real `incompressibleFluid` tutorial on this machine
  (`ls $FOAM_TUTORIALS/incompressibleFluid`).
- snappyHexMesh patch for the body is named `body` (from the STL solid name) and
  the generated `0/` fields expect patches `inlet/outlet/sides/top/ground/body` —
  keep them consistent if you change the mesh.

## Then: build the SimScale-style workbench up, in tested increments

Each feature small enough to run + verify on this machine before the next:
interactive BC assignment, mesh-refinement regions (draw + write
`refinementRegions`), the physics panels for the other OpenFOAM modules
(heat/HVAC buoyant `fluid`, VoF, combustion…), convergence monitoring from
`log.foamRun`, and drawing the mesh/result back into the FreeCAD viewport.

## Project rules (keep these)

- Stay on branch `claude/sleepy-ramanujan-96b3y6`; commit with clear messages;
  push when a piece works.
- Never call any feature a "wizard".
- Validate everything you can to a known answer; never ship a case as "working"
  until it has actually meshed + solved on this machine.
- Keep it free / FreeCAD-based; don't add paid or cloud dependencies.
