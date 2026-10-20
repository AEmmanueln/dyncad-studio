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
  choose a structural profile (SHS, RHS, CHS, angle, channel, I/IPE, flat
  bar, round bar), optionally rotate the profile about the member axis,
  and DynFrame sweeps a real solid member down each edge. Members land in
  a `Frame` group and remember their profile + cut length.
- **Trim Members (Butt Joint)** — cut the first selected member against
  the others for clean butt joints. Reliable.
- **Miter Two Members (experimental)** — trim two members that meet at a
  corner on their angle bisector. Best-effort; check the result.
- **Generate Cut List** — tabulate every member (label, profile, length)
  into a `CutList` spreadsheet, with per-profile quantity/total and an
  optional CSV export. (This is the frame "BOM / cut list.")

**Modeling helper**
- **Quick Fillet** — fillet the selected solid edges by a radius.

**Export / automation**
- **Export to STEP** — selected objects (or all solids) to one STEP file.
- **Export each body to STL** — one STL per body into a chosen folder.

**Setup**
- **Use Inventor Navigation** — switches FreeCAD's 3D navigation preset to
  Inventor-style orbit/pan/zoom.

Each command also has a keyboard accelerator (shown in its menu entry).

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
