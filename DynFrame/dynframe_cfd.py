# -*- coding: utf-8 -*-
"""DynFrame CFD - drive OpenFOAM (the engine behind SimScale) from FreeCAD.

Pure Python: no FreeCAD, PySide or numpy imports, so every line here is unit
-testable with the rest of the DynFrame validation suite. This module contains
the logic worth validating - path translation, OpenFOAM parameter editing, and
the shell scripts that set up / run / post-process a case. The FreeCAD command
layer (dynframe_commands.py) only collects parameters in a dialog and executes
what this module builds.

Honest scope - read this, it is the whole point
------------------------------------------------
*SimScale's "CFD" analysis runs OpenFOAM under the hood.* So the engine here is
the same engine SimScale uses, and for the **same case** (same mesh, same
boundary conditions, same turbulence model, same numerical schemes) the results
are the same - that is not marketing, it is the same source code solving the
same equations. What DynFrame automates is the *driving* of that engine from
FreeCAD, for **every** OpenFOAM solver module, not just the flow+heat that CfdOF
exposes:

  pick a physics module  ->  copy OpenFOAM's own validated tutorial for it
  ->  set the universal run controls (end time, time step, output) and the
      material/BC values that are safe to set generically
  ->  run (foamRun / foamMultiRun)  ->  convert to VTK  ->  view in ParaView.

What is *not* claimed: one-click conversion of an arbitrary CAD part into a
meshed, boundary-tagged case. That step is inherently geometry-specific (it is
what SimScale's geometry GUI, and CfdOF's mesher for flow, exist to do), and no
honest tool pretends otherwise. For the advanced modules the reliable no-code
route is exactly this one: adapt the module's validated tutorial. This file
makes that route a FreeCAD action instead of a terminal session.

DynFrame does not run OpenFOAM itself; it builds the scripts and hands them to
the user's OpenFOAM install (WSL Ubuntu, or native Linux).
"""

import base64

# ---- defaults (overridable from the dialog) ----------------------------------
DEFAULT_DISTRO = "Ubuntu"
DEFAULT_OF_ENV = "/opt/openfoam14/etc/bashrc"
WORK_ROOT = "~/dynframe_cfd"          # where cases are built, on the Linux side


# ---- Windows <-> WSL path translation ----------------------------------------
def win_to_wsl(path, distro=DEFAULT_DISTRO):
    """Translate a Windows path to the path WSL/Linux sees.

    C:\\Users\\X\\a            -> /mnt/c/Users/X/a
    \\\\wsl.localhost\\Ubuntu\\home\\x -> /home/x   (strip the UNC + distro)
    /home/x (already Linux)   -> unchanged
    """
    if not path:
        return path
    p = str(path).replace("\\", "/")
    low = p.lower()
    for pre in ("//wsl.localhost/", "//wsl$/"):
        if low.startswith(pre):
            rest = p[len(pre):]                 # "<distro>/home/x/..."
            parts = rest.split("/", 1)
            return "/" + (parts[1] if len(parts) > 1 else "")
    if len(p) >= 2 and p[1] == ":":             # drive-letter path
        return "/mnt/" + p[0].lower() + p[2:]
    return p


def wsl_to_win(path, distro=DEFAULT_DISTRO):
    """Translate a Linux/WSL path back to a Windows path.

    /mnt/c/Users/X -> C:\\Users\\X
    /home/x        -> \\\\wsl.localhost\\<distro>\\home\\x   (UNC into the distro)
    """
    if not path:
        return path
    p = str(path)
    if p.startswith("/mnt/") and len(p) > 6 and p[6] == "/":
        return p[5].upper() + ":" + p[6:].replace("/", "\\")
    return "\\\\wsl.localhost\\" + distro + p.replace("/", "\\")


# ---- shell quoting + native OpenFOAM dictionary editing ----------------------
def shq(s):
    """POSIX single-quote so a value with spaces/parens survives the shell."""
    return "'" + str(s).replace("'", "'\\''") + "'"


def foam_set_cmd(dict_file, entry, value):
    """A `foamDictionary` command that sets one entry of an OpenFOAM case file.

    `entry` is '/'-scoped like OpenFOAM wants, e.g. 'boundaryField/inlet/value'
    or just 'endTime'. foamDictionary is OpenFOAM's own dictionary tool, so the
    format is parsed and written correctly (far safer than sed). The caller
    wraps this non-fatally so a key absent from the chosen case is a warning,
    not a failed run.
    """
    return "foamDictionary -entry %s -set %s %s" % (
        shq(entry), shq(value), shq(dict_file))


# ---- the capability catalog: every OpenFOAM 14 solver module -----------------
# Each entry: id, title, module (solver written in controlDict / run by foamRun),
# tutorial (parent dir under $FOAM_TUTORIALS to pull a template from), multiRegion
# (choose foamMultiRun + expect fluid/solid regions), solve (False = mesh/ref only),
# use (plain-English applications). This is the list the dialog shows, so the user
# can launch ANY module, not only the four worked examples in the guide.
CATALOG = [
    # ---- flow ----
    {"id": "incompressibleFluid", "title": "Incompressible flow (RANS/LES)",
     "module": "incompressibleFluid", "tutorial": "incompressibleFluid",
     "multiRegion": False, "solve": True,
     "use": "wind, ventilation, ducts, pumps, low-speed external aero"},
    {"id": "isothermalFluid", "title": "Compressible flow, fixed temperature",
     "module": "isothermalFluid", "tutorial": "isothermalFluid",
     "multiRegion": False, "solve": True,
     "use": "low-speed compressible flow where heating is ignored"},
    {"id": "fluid", "title": "Compressible flow + heat + buoyancy (HVAC)",
     "module": "fluid", "tutorial": "fluid",
     "multiRegion": False, "solve": True,
     "use": "natural/forced convection, heated rooms, stacks, HVAC with temperature"},
    {"id": "potentialFoam", "title": "Potential flow (inviscid, fast)",
     "module": "potentialFoam", "tutorial": "potentialFoam",
     "multiRegion": False, "solve": True,
     "use": "quick first field / initialiser for the flow solvers"},
    {"id": "shockFluid", "title": "Compressible flow with shocks",
     "module": "shockFluid", "tutorial": "shockFluid",
     "multiRegion": False, "solve": True,
     "use": "supersonic nozzles, shock tubes, blast (density-based)"},
    # ---- heat / multi-region ----
    {"id": "multiRegion", "title": "Conjugate heat transfer (fluid + solid)",
     "module": "foamMultiRun", "tutorial": "multiRegion/CHT",
     "multiRegion": True, "solve": True,
     "use": "CHT: walls/insulation with the air side, heat exchangers, electronics cooling"},
    {"id": "solidDisplacement", "title": "Solid stress incl. thermal stress",
     "module": "solidDisplacement", "tutorial": "solidDisplacement",
     "multiRegion": False, "solve": True,
     "use": "thermal stress in a part, simple solid mechanics (frames: use DynFrame)"},
    # ---- multiphase ----
    {"id": "incompressibleVoF", "title": "Free surface, 2 phases (VOF)",
     "module": "incompressibleVoF", "tutorial": "incompressibleVoF",
     "multiRegion": False, "solve": True,
     "use": "water waves, dam break, tank sloshing, weirs, drainage"},
    {"id": "compressibleVoF", "title": "Free surface, compressible (VOF)",
     "module": "compressibleVoF", "tutorial": "compressibleVoF",
     "multiRegion": False, "solve": True,
     "use": "cavitation, water-hammer with a free surface"},
    {"id": "incompressibleMultiphaseVoF", "title": "3+ phases, incompressible (VOF)",
     "module": "incompressibleMultiphaseVoF", "tutorial": "incompressibleMultiphaseVoF",
     "multiRegion": False, "solve": True,
     "use": "oil-water-air, layered immiscible fluids"},
    {"id": "compressibleMultiphaseVoF", "title": "3+ phases, compressible (VOF)",
     "module": "compressibleMultiphaseVoF", "tutorial": "compressibleMultiphaseVoF",
     "multiRegion": False, "solve": True,
     "use": "multiple compressible immiscible phases"},
    {"id": "multiphaseEuler", "title": "Euler-Euler multiphase + boiling",
     "module": "multiphaseEuler", "tutorial": "multiphaseEuler",
     "multiRegion": False, "solve": True,
     "use": "bubble columns, fluidised beds, aeration, gas-liquid reactors, boiling"},
    {"id": "incompressibleDriftFlux", "title": "Settling / sedimentation (drift-flux)",
     "module": "incompressibleDriftFlux", "tutorial": "incompressibleDriftFlux",
     "multiRegion": False, "solve": True,
     "use": "clarifiers, settling tanks, slurries"},
    {"id": "incompressibleDenseParticleFluid", "title": "Dense particle-laden flow (DPM/MPPIC)",
     "module": "incompressibleDenseParticleFluid", "tutorial": "incompressibleDenseParticleFluid",
     "multiRegion": False, "solve": True,
     "use": "fluidised beds, pneumatic conveying, cyclones, dense sprays"},
    {"id": "film", "title": "Liquid film on surfaces",
     "module": "film", "tutorial": "film",
     "multiRegion": True, "solve": True,
     "use": "rain films, cooling/lubricating films, condensation, fire-suppression films"},
    {"id": "isothermalFilm", "title": "Liquid film, isothermal",
     "module": "isothermalFilm", "tutorial": "isothermalFilm",
     "multiRegion": True, "solve": True,
     "use": "thin liquid films without heat transfer"},
    # ---- combustion / reacting ----
    {"id": "multicomponentFluid", "title": "Reacting flow + combustion (finite-rate)",
     "module": "multicomponentFluid", "tutorial": "multicomponentFluid",
     "multiRegion": False, "solve": True,
     "use": "non-premixed combustion, furnaces, burners, NOx/CO, chemical reactors"},
    {"id": "XiFluid", "title": "Premixed / partially-premixed combustion",
     "module": "XiFluid", "tutorial": "XiFluid",
     "multiRegion": False, "solve": True,
     "use": "premixed flames, SI engines, gas explosions (PDR)"},
    # ---- mesh / motion / reference ----
    {"id": "movingMesh", "title": "Moving / dynamic mesh flow",
     "module": "incompressibleFluid", "tutorial": "movingMesh",
     "multiRegion": False, "solve": True,
     "use": "moving valves, pistons, deforming domains, basic FSI"},
    {"id": "mesh", "title": "Meshing only (blockMesh / snappyHexMesh)",
     "module": "", "tutorial": "mesh",
     "multiRegion": False, "solve": False,
     "use": "build a mesh (box, STL-based, boundary layers) - no solve"},
]

CATALOG_BY_ID = {c["id"]: c for c in CATALOG}


# ---- universal run controls (present in every case's controlDict) ------------
# These keys exist in every OpenFOAM controlDict, so setting them is safe for any
# module. Each: key (dialog), label, default, the dict file + entry, and a Python
# format for the value. Applied non-fatally.
CONTROLS = [
    {"key": "endTime", "label": "End time", "default": 100.0,
     "file": "system/controlDict", "entry": "endTime", "fmt": "{:g}"},
    {"key": "deltaT", "label": "Time step (deltaT)", "default": 1.0, "decimals": 6,
     "file": "system/controlDict", "entry": "deltaT", "fmt": "{:g}"},
    {"key": "writeInterval", "label": "Write interval", "default": 10.0,
     "file": "system/controlDict", "entry": "writeInterval", "fmt": "{:g}"},
]


def control_edits(values):
    """Turn a {key: number} dict (from the dialog) into (file, entry, value_str)
    edits for the universal controlDict settings. Only keys present and > 0 (for
    deltaT/writeInterval) or given (endTime) are emitted."""
    edits = []
    for c in CONTROLS:
        if c["key"] not in values:
            continue
        v = values[c["key"]]
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if c["key"] in ("deltaT", "writeInterval") and fv <= 0:
            continue
        edits.append((c["file"], c["entry"], c["fmt"].format(fv)))
    return edits


def inlet_velocity_edit(ux, uy=0.0, uz=0.0, patch="inlet", field="U"):
    """Optional convenience edit: set a uniform inlet velocity. Only valid if the
    chosen case actually has a patch of this name; applied non-fatally so a name
    mismatch is a warning, not a failure."""
    return ("0/%s" % field, "boundaryField/%s/value" % patch,
            "uniform (%g %g %g)" % (float(ux), float(uy), float(uz)))


# ---- script builders ---------------------------------------------------------
def build_case_script(opts):
    """Bash that sets up and runs a case. opts:
        of_env (str), module (str), multiRegion (bool), solve (bool),
        tutorial (str, parent under $FOAM_TUTORIALS), case (str or None,
        explicit case name), name (str, working-case name), edits (list of
        (file, entry, value_str)).
    Prefers the tutorial's own ./Allrun (it does the right mesh/field steps for
    that physics); falls back to blockMesh + the solver. Parameter edits are
    applied after copy and before the run, each non-fatally."""
    of_env = opts.get("of_env", DEFAULT_OF_ENV)
    module = opts.get("module", "")
    multi = bool(opts.get("multiRegion", False))
    solve = opts.get("solve", True)
    tutorial = opts["tutorial"]
    case = opts.get("case")
    name = opts.get("name", "case1")
    edits = opts.get("edits", []) or []
    solver = "foamMultiRun" if multi else "foamRun"

    L = []
    L.append("# DynFrame CFD - generated run script (engine: OpenFOAM)")
    L.append(". %s" % of_env)
    L.append('echo "OpenFOAM: $WM_PROJECT_VERSION   tutorials: $FOAM_TUTORIALS"')
    # resolve the template case directory
    if case:
        L.append('SRC="$FOAM_TUTORIALS/%s/%s"' % (tutorial, case))
    else:
        L.append('SRC=$(ls -d "$FOAM_TUTORIALS/%s"/*/ 2>/dev/null | head -1)' % tutorial)
    L.append('if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then '
             'echo "ERROR: no tutorial case found under %s - run: ls $FOAM_TUTORIALS/%s"; '
             'exit 1; fi' % (tutorial, tutorial))
    L.append('echo "Template: $SRC"')
    L.append('mkdir -p %s' % WORK_ROOT)
    L.append('DST=%s/%s' % (WORK_ROOT, name))
    L.append('rm -rf "$DST" && cp -r "$SRC" "$DST" && cd "$DST" || exit 1')
    L.append('echo "Case: $DST"')
    # parameter edits (non-fatal: a key the case lacks is a warning only)
    for (f, entry, val) in edits:
        L.append("%s || echo \"WARN: could not set %s in %s (not in this case)\""
                 % (foam_set_cmd(f, entry, val), entry, f))
    if not solve:
        L.append('echo "Mesh-only module: building mesh"; '
                 'blockMesh 2>&1 | tee log.blockMesh; '
                 '[ -f system/snappyHexMeshDict ] && snappyHexMesh -overwrite 2>&1 | tee log.snappy')
        L.append('echo "=== MESH DONE: $DST ==="')
        return "\n".join(L)
    # run: prefer the tutorial's own Allrun, else a generic mesh+solve
    L.append('if [ -x ./Allrun ]; then')
    L.append('  echo "Running the case Allrun (meshes + solves)..."')
    L.append('  ./Allrun 2>&1 | tee log.Allrun')
    L.append('else')
    L.append('  echo "No Allrun; running blockMesh + %s"' % solver)
    L.append('  blockMesh 2>&1 | tee log.blockMesh')
    L.append('  %s 2>&1 | tee log.run' % solver)
    L.append('fi')
    L.append('echo "=== DONE: $DST ==="')
    return "\n".join(L)


def build_view_script(opts):
    """Bash that converts the latest results to VTK (auto-discovering fluid/solid
    regions) and copies the VTK tree to a Windows-visible folder for ParaView.
    opts: of_env, name, win_out (Windows dir to receive VTK), latest (bool)."""
    of_env = opts.get("of_env", DEFAULT_OF_ENV)
    name = opts.get("name", "case1")
    win_out = opts["win_out"]
    latest = opts.get("latest", True)
    wsl_out = win_to_wsl(win_out)
    lt = " -latestTime" if latest else ""

    L = []
    L.append("# DynFrame CFD - generated post-process / view script")
    L.append(". %s" % of_env)
    L.append('cd %s/%s || { echo "ERROR: case %s not found"; exit 1; }' % (WORK_ROOT, name, name))
    L.append('rm -rf VTK')
    # discover mesh regions (multi-region cases have constant/<region>/polyMesh)
    L.append('REGIONS=$(for d in constant/*/polyMesh; do [ -d "$d" ] && '
             'basename "$(dirname "$d")"; done)')
    L.append('if [ -z "$REGIONS" ]; then')
    L.append('  echo "single-region -> foamToVTK"; foamToVTK%s 2>&1 | tail -3' % lt)
    L.append('else')
    L.append('  for r in $REGIONS; do echo "converting region: $r"; '
             'foamToVTK -region "$r"%s 2>&1 | tail -2; done' % lt)
    L.append('fi')
    # copy VTK to the Windows side
    L.append('OUT=%s' % shq(wsl_out))
    L.append('mkdir -p "$OUT"')
    L.append('rm -rf "$OUT/VTK"')
    L.append('if [ -d VTK ]; then cp -r VTK "$OUT/" && echo "=== VTK copied to: %s ==="; '
             'else echo "ERROR: no VTK produced (did the case run?)"; fi' % win_out)
    L.append('find "$OUT/VTK" -name "*.vtk" 2>/dev/null | sed "s#$OUT/##" | head -40')
    return "\n".join(L)


# ---- WSL invocation ----------------------------------------------------------
def wsl_run_argv(script, distro=DEFAULT_DISTRO, login=True):
    """argv for subprocess to run a bash script inside WSL. The script is passed
    base64-encoded to sidestep every quoting pitfall of nesting a multi-line
    script inside `wsl.exe bash -c "..."`."""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    inner = "echo %s | base64 -d | bash" % b64
    flags = "-lc" if login else "-c"
    return ["wsl.exe", "-d", distro, "bash", flags, inner]


def decode_wsl_argv(argv):
    """Inverse of wsl_run_argv (for tests): recover the script text from the argv
    the runner would execute."""
    inner = argv[-1]
    b64 = inner.split("echo ", 1)[1].split(" |", 1)[0]
    return base64.b64decode(b64.encode("ascii")).decode("utf-8")


def native_run_argv(script, login=True):
    """Same, for a native Linux OpenFOAM (no WSL wrapper)."""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    inner = "echo %s | base64 -d | bash" % b64
    return ["bash", "-lc" if login else "-c", inner]
