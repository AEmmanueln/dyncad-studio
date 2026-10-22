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
