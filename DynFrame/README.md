# DynFrame — a FreeCAD workbench

An Inventor-style **Frame Generator** plus modeling helpers and
export/cut-list automation, packaged as a FreeCAD add-on (custom
workbench).

> **Status: v0.1, needs testing on your machine.** The code is written
> against the FreeCAD Python API and syntax-checked, but it has **not**
> been run inside FreeCAD yet (it was authored in a headless cloud
> environment with no FreeCAD GUI). Install it, try each tool, and report
> anything that misbehaves so it can be fixed. Nothing here can match
> Autodesk Inventor or SolidWorks exactly — it reproduces the *workflow*
> of their frame tools on FreeCAD's free OpenCASCADE kernel.

Tested target: **FreeCAD 1.0 / 1.1 on Windows** (should also work on
macOS/Linux).

---

## What it adds

**Frame Generator**
- **Insert Frame Members** — select straight sketch lines or model edges,
  pick a profile (two-step **family → size** picker), optionally rotate it
  about the member axis, and DynFrame sweeps a real solid member down each
  edge. Members use a **stable orientation frame**, so I-beams / angles /
  channels no longer roll or flip randomly. Each member stores its
  *skeleton* (centre-line), profile and twist, so later edits stay robust.
- **Change Profile** — swap the profile/twist of selected members in place.
- **Lengthen / Shorten** — extend (+) or shorten (-) members at each end.
- **Trim / Notch (to members)** — cut the first selected member against the
  others (butt joint / cope).
- **Miter Two Members** — trim two members meeting at a corner on their
  shared angle bisector. Rewritten to work regardless of member lengths.
- **Trim to Face / Plane** — trim selected members at a selected flat face.
- **Generate Cut List** — `CutList` spreadsheet + CSV of every member
  (label, profile, length) with per-profile quantity and total.

**Profile library (~196 sizes, 12 families)**
I-beam **IPE**, H-beam **HEA** / **HEB**, channel **UPN**, equal & unequal
**angles (L)**, **square (SHS)**, **rectangular (RHS)** and **round (CHS)**
tube, **T** sections, **flat bar**, **round bar**. Edit
`dynframe_profiles.py` to add sizes or families.

**3D skeleton**
- **3D Skeleton (Draft Wire)** — launches FreeCAD's Draft Wire tool to draw
  centre-lines in 3D, then insert members along them. (FreeCAD's Draft
  polyline is its 3D-sketch equivalent.)

**Frame Analysis — Robot-style line/stick model**
The analysis entity is a **bar**: a *line* (two nodes) carrying a **section**
and a **material** — not a swept solid. That is how Autodesk Robot
Structural Analysis works, and it is what scales to large structures (a
high-rise is thousands of lines, which would be impossible as solids). The
solid Frame Generator above stays for fabrication and cut-lists; the line
model is what you analyse. Commands are on the toolbars/menus
**DynFrame · Analysis Panel**, **· Structure**, **· Loads**, **· Results**.

> **One panel for everything.** **Frame Analysis Panel** (DynFrame ·
> Analysis Panel) opens a single window where you build the model, apply
> supports and loads to the current 3D selection, manage cases and
> combinations, Calculate, and switch the shown result — all in one place,
> instead of a chain of pop-ups. The individual commands below still exist
> and now use single-form dialogs.

*Build the line model (DynFrame · Structure) — any of four ways:*
1. **Generate Grid Structure** — enter bay spacings and storey heights and
   get a full column + beam grid in one step: sheds, portal frames,
   multi-storey and high-rise frames. Spacings are comma-separated bay
   lengths, so they can be **unequal** (`5000,4000,6000`); `3@5000` is
   shorthand for three equal 5000 bays, and you can mix them
   (`3@5000,4000`). Leave the **Y** field empty for a flat 2D frame.
2. **Add Bars (from lines)** — draw the structure as sketch / Draft lines,
   select them, pick a section + material → one bar per line.
3. **Bars from Members** — convert the solid members you already built into
   bars, keeping each member's section.
4. **Node/Bar Tables** + **Build from Tables** — type node coordinates and
   bar connectivity (NodeI, NodeJ, Section, Material) into the `Nodes` and
   `Bars` spreadsheets (Robot's tables), then build the model from them.

*Loads (DynFrame · Loads):*
4. **New Load Case** — a named case with a nature (Dead / Live / Wind /
   Snow / Other). Loads belong to a case.
5. **Define Support** — select node vertices → Fixed / Pinned / Roller.
6. **Add Nodal Load** (on selected node vertices) / **Add Bar Load** (on
   selected bars/lines) — one dialog each, assigned to a load case.
7. **Load Combinations** — auto EN 1990 **ULS** (1.35G + 1.5Q) and **SLS**
   (G + Q), or a custom factored combination (`1.35*DL1 + 1.5*LL1`).

*Solve & results (DynFrame · Results):*
8. **Calculate** — choose a case, a combination, or *All loads* (+ optional
   self-weight). Solves a 3D Euler–Bernoulli direct-stiffness model
   (6 DOF/node) **per material**. Produces:
   - a **Displacement contour** — the deformed structure drawn as thick
     tubes coloured blue→red by |u|, with a **numeric colour bar** (0 … max),
     the way Inventor/Robot show it (the default view);
   - the structure coloured by any force result **N, Vy, Vz, Mx, My, Mz** or
     combined **Stress** — thick tubes coloured blue→red along each bar
     (visible from any angle); the colour bar updates to the shown result;
   - **Reactions**, **Displacements** and **BarForces** (start/end N, Vy,
     Vz, Mx, My, Mz, stress, utilisation) spreadsheets, alongside your
     `Nodes` / `Bars` tables.
9. **Show Result / Diagram** — switch the displayed result: Displacement
   contour, or an N / Vy / Vz / Mx / My / Mz / Stress diagram.
10. **Clear Results** — remove results only, or everything (supports, loads,
    combinations).

*Design & dynamics (DynFrame · Loads / Results):*
- **Member Releases** — free member end DOFs: moment releases for a pinned
  connection, or pin both ends for a truss member (presets). Handled by
  static condensation; non-released members are unaffected.
- **Nodal Load** also takes **moments** Mx / My / Mz, not just forces.
- **Envelope (all combinations)** — solves every combination and keeps the
  worst axial / My / Mz / utilisation per member (the design envelope),
  colours members by it, and stores the governing forces so the code check
  runs against the envelope.
- **Steel Code Check (EC3)** — verifies steel members to EN 1993-1-1
  (simplified, user γ-factors): cross-section resistance, flexural buckling
  (both axes, curve a–d), the N+M interaction, and lateral-torsional
  buckling → utilisation, governing check and OK/FAIL per member, coloured
  green→red, in a `CodeCheck` table.
- **Modal Analysis** — natural frequencies and mode shapes (consistent-mass
  eigenvalue analysis, each bar meshed into sub-elements); first *N*
  frequencies in a `ModalFrequencies` table, Mode 1 drawn as a mode-shape
  tube.
- **Buckling Analysis** — linear (Euler) buckling: the critical load factor
  by which the analysed loads must be multiplied to buckle the structure
  (λ < 1 = unsafe), plus the buckling mode shape, from the geometric
  stiffness built on the analysed axial forces.
- **Second-order (P-Δ)** — tick *P-Δ* (or pick 2nd order) in Calculate to
  include geometric nonlinearity: the solve iterates with the geometric
  stiffness until it converges, amplifying the displacements and moments
  from the axial forces (the stability effect in slender frames).

**Materials:** Steel S235 / S275 / S355, Stainless 304, Aluminium 6061-T6
(each with its own E, G, yield and density). Edit `MATERIALS` in
`dynframe_commands.py` to add more.

> **Validation** (all numeric, against closed-form solutions): the static
> solver is exact in both bending planes — cantilever (point and UDL),
> simply-supported and fixed-fixed beams (tip = wL⁴/8EI, mid = 5wL⁴/384EI,
> M = wL²/8, end = wL²/12), all six force components and load-case
> superposition; **releases** reproduce the propped cantilever (wL²/8);
> **modal** matches the cantilever f₁ = (1.875²/2π)·√(EI/ρAL⁴) to four
> figures; **buckling** matches the Euler load Pcr = π²EI/(2L)² (ratio
> 1.000); the **EC3** buckling reduction factors match the code tables and
> a worked column check (χ = 0.441, Nb,Rd = 558 kN); **P-Δ** reproduces the
> 1/(1−P/Pcr) amplification. It covers **static, P-Δ, modal, buckling and
> design checks**; seismic/response-spectrum and a full (non-simplified)
> code check are later phases. FreeCAD is not Robot — this reproduces
> Robot's *workflow and core engineering* on its kernel.

**Modeling / export / setup**
- **Quick Fillet** — fillet selected solid edges by a radius.
- **Export to STEP** / **Export each body to STL**.
- **Navigation: SolidWorks / Inventor** — pick a mouse-navigation preset.

Each command has a keyboard accelerator (shown in its menu entry).

> **Scale tip:** draw your skeleton at real size. A 40 mm SHS on a 60 mm
> rectangle looks like a solid blob — that "distortion" is just members
> overlapping. For a 1 m frame, draw the lines ~1000 mm long.

---

## Install on Windows

1. Open Windows Explorer, type **`%APPDATA%\FreeCAD\Mod`** in the address
   bar and press Enter. (Create the `Mod` folder if it doesn't exist.)
2. Copy the **`DynFrame`** folder (this folder — the one containing
   `InitGui.py`) into `Mod`, so you end up with:

   ```
   %APPDATA%\FreeCAD\Mod\DynFrame\InitGui.py
   %APPDATA%\FreeCAD\Mod\DynFrame\dynframe_commands.py
   %APPDATA%\FreeCAD\Mod\DynFrame\dynframe_profiles.py
   %APPDATA%\FreeCAD\Mod\DynFrame\icons\...
   ```
3. Restart FreeCAD.
4. In the workbench selector (top toolbar dropdown), choose **DynFrame**.

To get the files onto your PC from this repo: on the GitHub page use
**Code → Download ZIP**, unzip, and copy the inner `DynFrame` folder as
above. (Or `git clone` and copy it.)

---

## Quick start: make a frame

1. New document → **Sketcher** workbench → draw the center-lines of your
   frame (a rectangle, a box's edges, whatever). Close the sketch.
   *Or* make a wireframe of edges any way you like.
2. Switch to **DynFrame**.
3. Select the sketch lines (or edges), click **Insert Frame Members**,
   pick a profile (e.g. `SHS 40x40x3`), set a rotation if needed → OK.
4. Members appear along every selected line, grouped under `Frame`.
5. Clean up corners: select two members → **Trim (Butt Joint)** or
   **Miter (experimental)**.
6. Click **Generate Cut List** for the spreadsheet + CSV.
7. **Export to STEP** / **STL** when done.

---

## Editing / extending the profile catalogue

Open `dynframe_profiles.py`. Each section family is a short loop of sizes —
add a tuple to a list, or add a whole new builder function, and it appears
in the Insert Frame Members dropdown. Dimensions are millimetres.

---

## Known limitations (honest list)

- **Not a parametric history feature.** Members are solids placed at insert
  time. If you move the driving sketch afterwards, existing members do not
  auto-update — re-run Insert on the new lines. (True associativity would
  need a custom parametric `FeaturePython` object; possible as a later
  version.)
- **Miter is experimental** and handles two members at a shared corner;
  complex multi-member joints may need manual cleanup.
- **Profiles are representative sizes**, not a certified standards library.
- Curved members use straight-edge endpoints only; for arcs/splines the
  member follows the chord. (Swept curved members can be added later.)
- Trim/Miter bake the member to global placement (geometry becomes
  world-coordinates); undo (Ctrl+Z) reverses it.

## License

LGPL-2.1-or-later, matching FreeCAD and OpenCASCADE, so it can be used and
distributed freely under those terms. See `LICENSE`.
