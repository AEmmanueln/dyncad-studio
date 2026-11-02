# CFD for DynFrame models — the honest guide (OpenFOAM + CfdOF)

**Short version:** DynFrame is a *structural* solver. It does **not** contain a
CFD (fluid-flow) solver, and it never will try to re-implement Ansys Fluent /
CFX or SimScale inside a Python workbench — that would be a toy pretending to
be an engineering tool. For **real** CFD on the *same FreeCAD* you already use,
the right tool is **OpenFOAM**, driven from FreeCAD by the **CfdOF** workbench.

> Worth knowing: **SimScale's own "CFD" analysis runs OpenFOAM under the hood.**
> So "CFD like SimScale" is, quite literally, OpenFOAM — which is free and
> open-source. You are not getting a lesser engine; you are getting the same
> engine without the subscription (you provide the compute).

What DynFrame *does* give you on the wind side is **Add Wind Load (EN 1991-1-4)**
— code wind pressures applied to the frame. That is the normal path for building
design. Use CFD when you need the actual flow field: pressure coefficients on a
complex shape, wind around a cluster of buildings, pedestrian comfort, vortex
shedding, HVAC/duct flow, etc.

---

## 1. What you can and cannot expect

| Capability | DynFrame | OpenFOAM + CfdOF | Ansys / SimScale |
|---|---|---|---|
| Structural FE (beams, plates, modal, buckling, EC3/EC2) | ✅ | ❌ | (their own) |
| Code wind loads (EN 1991-1-4) | ✅ | — | ✅ |
| Incompressible RANS (steady, `simpleFoam`) | ❌ | ✅ | ✅ |
| Transient / LES, turbulence models (k-ε, k-ω SST…) | ❌ | ✅ | ✅ |
| Automatic meshing of complex geometry (`snappyHexMesh`/`cfMesh`) | ❌ | ✅ | ✅ |
| Polished cloud UI, meshing wizards, support | ❌ | partial | ✅ |

OpenFOAM is genuinely production-grade for external aerodynamics and internal
flow. The trade is that **you drive the setup and supply the compute** (a
decent multicore desktop; big transient runs want many cores or a cluster).

---

## 2. Install (once)

1. **FreeCAD → Tools → Addon Manager → search "CfdOF" → Install.** Restart
   FreeCAD; a **CfdOF** workbench appears in the workbench dropdown.
2. **Install OpenFOAM** (the actual solver CfdOF calls):
   - **Windows:** CfdOF → *Preferences* (Edit → Preferences → CfdOF) has an
     **"Install OpenFOAM"** / dependency installer that fetches a bundled
     build (blueCFD or the openfoam.com build). Also offer to install
     **cfMesh** and **ParaView** from the same panel.
   - **Linux:** install `openfoam` from openfoam.org or openfoam.com packages
     (or your distro), then point CfdOF Preferences at the install if it is
     not auto-detected.
   - **macOS:** run OpenFOAM in Docker/WSL-style container, or use Linux.
3. In **CfdOF → Preferences**, click **"Run dependency checker"** until
   OpenFOAM, cfMesh/snappyHexMesh and ParaView all report OK.

CfdOF's own documentation (its GitHub/wiki) is the authoritative, version-
current reference — follow it where it differs from the outline below.

---

## 2a. No-coding setup when you already have blueCFD + OpenFOAM + ParaView (Windows)

If the solver (blueCFD-Core / OpenFOAM) and ParaView are already installed, the
only missing piece is the **CfdOF GUI** — it is what lets you run everything
with dialogs and buttons, never a terminal or a dictionary file.

1. **Install CfdOF**: FreeCAD → **Tools → Addon Manager** → search **CfdOF** →
   **Install** → restart FreeCAD. Pick **CfdOF** in the workbench dropdown.
2. **Point CfdOF at your installs**: **Edit → Preferences → CfdOF**.
   - *OpenFOAM install directory* → your **blueCFD-Core** folder, typically
     `C:\Program Files\blueCFD-Core-2024\` (the folder whose `OpenFOAM-...`
     sub-folder holds `etc\bashrc`). CfdOF usually auto-detects blueCFD; set it
     here if it doesn't.
   - *ParaView executable* → your `...\ParaView\bin\paraview.exe`.
   - Click **Install cfMesh** (and **Install HiSA** only if you need
     compressible) — these download into blueCFD; no compiling by you.
   - Click **Run dependency checker** → every line (OpenFOAM, cfMesh,
     ParaView, Gmsh) must say OK. Fix the paths until it does. **This is the
     only setup step; after it, CFD is all point-and-click.**

Nothing above involves editing an OpenFOAM case by hand — CfdOF writes the
`system/`, `constant/` and `0/` dictionaries from your dialog entries and runs
the solver for you.

**Shortcut for steps 2–the checker:** run the helper script once in the FreeCAD
Python console (View → Panels → Python console):

```python
exec(open(FreeCAD.getUserAppDataDir()+"/Mod/DynFrame/tools/cfdof_setup.py").read())
```

It auto-detects blueCFD and ParaView under *Program Files*, writes CfdOF's
OpenFOAM / ParaView / Gmsh paths, runs the dependency checker and prints the
report, then opens the CfdOF preferences so you click **Install cfMesh** and
**Install HiSA** (these download-and-compile, so there is no stable way to
script them — CfdOF builds them for you from those two buttons). If auto-detect
misses your install, edit `OPENFOAM_DIR` / `PARAVIEW` at the top of
`DynFrame/tools/cfdof_setup.py` and run it again.

---

## 3. The workflow (external wind around a building)

1. **Geometry.** Make (or import) a **solid** of the building envelope — the
   *outside shape* the air flows around, not the frame. From a DynFrame model
   you can build a simple box/extrusion of the envelope in Part/Part Design, or
   import a STEP of the architectural massing. (DynFrame members are lines;
   air flows around surfaces, so model the envelope solid.)
2. **Switch to the CfdOF workbench.**
3. **CFD Analysis container** → add one.
4. **Physics model:** Incompressible, **Steady** (RANS) to start; turbulence
   **k-ω SST** is a good default for bluff-body external flow.
5. **Fluid properties:** air (ν ≈ 1.5 × 10⁻⁵ m²/s, ρ = 1.225 kg/m³).
6. **Computational domain (wind tunnel):** a box around the building. Rules of
   thumb (COST 732 / AIJ): inlet ≈ 5 H upstream, outlet ≈ 15 H downstream,
   ≥ 5 H to the sides and top, where H is the building height. Blockage < 3 %.
7. **Boundary conditions:**
   - **Inlet:** velocity = your design wind speed (optionally an ABL log/power
     profile to match EN 1991-1-4 terrain — the mean-wind profile DynFrame's
     wind tool also uses).
   - **Outlet:** pressure outlet (0 Pa gauge).
   - **Building + ground:** no-slip walls (wall functions with the SST model).
   - **Sides/top:** slip / symmetry.
8. **Mesh:** base Cartesian mesh (`snappyHexMesh` or `cfMesh`), then refine at
   the building surfaces and add **boundary-layer (prism) layers** so y⁺ is in
   the wall-function range. Start coarse, confirm it runs, then refine.
9. **Initialise & run** `simpleFoam`. Watch residuals fall (and a monitored
   force/pressure settle) — that, plus mesh-refinement insensitivity, is your
   convergence check.
10. **Post-process in ParaView:** velocity field, streamlines, and the
    **surface pressure coefficient** c_p = (p − p_ref) / (½ ρ U_ref²).

---

## 3b. Step-by-step worked example — wind around a building block

A concrete walk-through you can follow click-by-click. Example: a
**30 m × 20 m × 40 m (tall) building**, wind at **27 m/s**, air (ν = 1.5e-5
m²/s, ρ = 1.225). The goal is the surface **pressure coefficients c_p** and the
**drag**, which is exactly what SimScale's "Incompressible" analysis gives —
same solver, so matching it is a matter of matching the setup.

> Units: OpenFOAM/CfdOF work in **metres and m/s** (SI), unlike DynFrame's mm.
> Build the CFD geometry in metres.

1. **Model the envelope solid.** In the **Part** workbench, `Part → Primitives
   → Box`, 30 × 20 × 40 m, sitting on the ground plane (z = 0). This is the
   *obstacle* the air flows around (not the frame). Name it `Building`.
2. **Switch to the CfdOF workbench.**
3. **Create the analysis:** toolbar **"Analysis container"**. A `CfdAnalysis`
   plus a `PhysicsModel`, `FluidProperties` and `CfdMesh` tree appear.
4. **Physics model** (double-click): *Flow = Incompressible*, *Steady state*,
   *Turbulence = RANS → k-ω SST*. (SST is the standard choice for bluff-body
   external flow; SimScale defaults to it too.)
5. **Fluid properties:** *Air* — kinematic viscosity `1.5e-5`, density `1.225`.
6. **Domain / wind tunnel.** Make a second, large `Box` around the building and
   mark it the flow region. Sizes (H = 40 m building height):
   - inlet face 5H = 200 m upstream, outlet 15H = 600 m downstream,
   - 5H = 200 m to each side and above; blockage < 3 %.
   In CfdOF you can set this as the mesh's background domain extent.
7. **Mesh** (double-click `CfdMesh`): mesher **cfMesh** (robust) or
   **snappyHexMesh**. Base cell ≈ 4–8 m; add a **surface refinement** on the
   `Building` faces (down to ~0.5–1 m) and **boundary-layer prism layers**
   (3–5 layers) so the near-wall y⁺ suits the SST wall functions. Right-click →
   **"Write mesh case"**, then **"Run mesher"**. Check it completes and the
   cell count is reasonable (start coarse — tens of thousands — then refine).
8. **Boundary conditions** (CfdOF → "Fluid boundary", one per face group):
   - **Inlet** (upstream face): type *Velocity inlet*, U = (27, 0, 0) m/s.
     For a code-consistent profile, use an **atmospheric boundary layer** log
     profile instead of uniform U — this is the same mean-wind shape
     EN 1991-1-4 (and DynFrame's wind tool) use.
   - **Outlet** (downstream face): *Pressure outlet*, p = 0.
   - **Building + ground**: *Wall*, no-slip (with wall functions).
   - **Sides + top**: *Slip* (or symmetry).
9. **Initialise** the internal field (U = inlet, p = 0, with k and ω from the
   turbulence-intensity estimate CfdOF offers).
10. **Solve:** CfdOF → **"Run"**. It calls `simpleFoam`. Watch the residuals
    (Ux, Uy, Uz, p, k, ω) fall several orders of magnitude and a monitored
    quantity (e.g. drag force on the building) flatten out — that is
    convergence. A few hundred to a few thousand iterations is typical.
11. **Post-process:** CfdOF → **"Paraview"** opens the case. Colour the building
    surface by pressure; compute **c_p = (p − p_ref)/(½ρU_ref²)** (p is kinematic
    pressure p/ρ in incompressible OpenFOAM, so multiply by ρ first). Add
    streamlines/velocity glyphs to see separation and the wake.

### Getting the *same* numbers as SimScale

Because the engine is identical, differences come only from the setup. To match
a SimScale run (or any reference):

- **Same turbulence model and wall treatment** (k-ω SST + wall functions).
- **Same inlet** (uniform vs ABL profile, same U, same turbulence intensity).
- **Equivalent mesh** — comparable near-wall resolution (y⁺) and surface
  refinement. Exact cell-for-cell identity is not required; *mesh-independent*
  results are. Refine both until c_p / drag stop changing — they converge to
  the same values.
- **Same fluid properties and reference pressure**.

Then confirm trustworthiness independently of any product:

- **Mesh-independence study:** run coarse → medium → fine; the reported c_p /
  drag should change < a few %. If they keep moving, the mesh (not the brand)
  is the problem.
- **Benchmark once:** reproduce a published case before trusting your own — the
  **surface-mounted cube** (Martinuzzi & Tropea; AIJ building benchmarks) is the
  standard external-flow check; `pitzDaily`/backward-facing step is the standard
  internal one. Match the benchmark and you have shown *your* setup is right,
  which is the only thing a brand name would have been standing in for.

## 3c. Worked example — HVAC room ventilation (internal, buoyant, snappyHexMesh)

A complete no‑coding HVAC case: a supply diffuser blows cool air into an office,
a return grille extracts it, and floor heat gains drive a warm thermal plume.
You get the air **velocity** (draft risk) and **temperature** (stratification,
comfort) fields. Uses **snappyHexMesh** — no cfMesh/HiSA needed. Internal,
incompressible with **buoyancy** (Boussinesq) and heat.

> FreeCAD models in **mm**; CfdOF exports to **metres** for OpenFOAM. So a
> 5000 mm box is a 5 m room. Flow values (velocities, temperatures) are SI.
> Exact dialog labels vary a little by CfdOF version — the intent is what
> matters.

### The case (office, mixing ventilation)

| Item | Value |
|---|---|
| Room | 5 × 4 × 3 m (L×W×H) |
| Supply diffuser | 0.4 × 0.4 m, high on one wall; **U = 1.0 m/s into the room**, **T = 289 K** (16 °C). ≈0.16 m³/s ≈ 9–10 air changes/h |
| Return grille | 0.4 × 0.4 m, high on the opposite wall; **pressure outlet, 0 Pa** |
| Floor | no‑slip wall, **fixed T = 300 K** (27 °C) — stands in for occupant/solar gains |
| Other walls + ceiling | no‑slip wall, **adiabatic** (zero heat flux) |
| Air (Boussinesq) | ρ = 1.2, ν = 1.5e‑5 m²/s, Pr = 0.71, Prt = 0.85, β = 3.4e‑3 1/K, T_ref = 293 K, Cp = 1005 |
| Gravity | (0, 0, −9.81) |
| Turbulence / time | k‑ω SST, **steady** |
| Solver (auto) | `buoyantBoussinesqSimpleFoam` |

### 1. Geometry (Part workbench, in mm)

Build the **air volume** as one solid — the room plus two little nozzle stubs
whose outer faces become the diffuser and grille:

1. `Part → Primitives → Box` **Room**: Length 5000, Width 4000, Height 3000, at
   (0, 0, 0).
2. Box **Supply**: 200 × 400 × 400 at placement (−200, 1800, 2400) — it abuts
   the x = 0 wall, centred in width, up near the ceiling. Its −x face is the
   diffuser.
3. Box **Return**: 200 × 400 × 400 at (5000, 1800, 2400) — abuts the x = 5000
   wall. Its +x face is the grille.
4. Select all three → `Part → Boolean → Union`. One solid "Fusion" = the air
   domain with two stubs. (If a stub ends up fully inside/outside, nudge its x
   so it just overlaps the wall plane.)

### 2. CfdOF set‑up (all dialogs, no files)

5. Switch to **CfdOF** → **Analysis container** (select the Fusion first).
6. **Physics model**: *Steady*; Flow *Incompressible*; **turn on Heat transfer
   / Energy**; **turn on Gravity** (0, 0, −9.81) → this makes it buoyant
   (Boussinesq); Turbulence **k‑ω SST**.
7. **Fluid properties** (Air, from the table): density 1.2, kinematic viscosity
   1.5e‑5, thermal expansion 3.4e‑3, reference T 293, Prandtl 0.71 (turbulent
   0.85), Cp 1005.
8. **Mesh** (select the Fusion → *CFD mesh*): **Mesher = snappyHexMesh**; *Base
   element size* **100 mm**; internal flow (mesh the inside). Add a **Mesh
   refinement**: select the two stub end faces and the floor → relative size
   ~0.5 (finer there); add **boundary layers** (2–3 layers) on the walls.
   **Write mesh** → **Run mesher**. Expect ~0.1–0.4 M cells; check *Check mesh*.
9. **Boundary conditions** (CfdOF *Fluid boundary*, one each — select the faces
   in the 3D view, then set the type):
   - **Supply** (the −x stub face): *Velocity inlet*, U = (1, 0, 0) m/s;
     Thermal → *fixed temperature* 289 K.
   - **Return** (the +x stub face): *Pressure outlet*, 0 Pa; Thermal *outflow /
     zero gradient*.
   - **Floor** (room z = 0 face): *Wall*, no‑slip; Thermal *fixed temperature*
     300 K.
   - **Walls** (every other face — the 3 remaining room walls, ceiling and the
     stub sides): *Wall*, no‑slip; Thermal *adiabatic* (zero heat flux).
10. **Initialise** the internal field: U ≈ 0, T = 293 K, p = 0 (CfdOF fills k, ω
    from a turbulence‑intensity guess — leave the defaults).

### 3. Run and read it

11. **Run** → CfdOF runs `buoyantBoussinesqSimpleFoam` and plots residuals. Let
    Ux/Uy/Uz, p, T, k, ω fall a few orders and a monitor settle (≈500–2000
    iterations; a few minutes). Buoyant runs like strong under‑relaxation —
    CfdOF's defaults are fine; if it wobbles, lower the momentum relaxation a
    touch.
12. **ParaView** button → open the case. Useful views:
    - **Slice** at y = 2.0 m (mid‑room): colour by **T** (stratification,
      comfort band ~295–299 K / 22–26 °C) and by **U magnitude** (occupied zone
      0.1–1.8 m should stay **< ~0.25 m/s** or it feels draughty).
    - **Streamlines** from the supply face: does fresh air reach the occupied
      zone, or **short‑circuit** straight to the return? (A classic HVAC check.)
    - **Glyphs** (vectors) to see the supply jet throw and the floor plume.

### 4. Make it trustworthy (same discipline as Ansys/SimScale)

- **Mesh independence**: re‑run at base 70 mm; the occupied‑zone mean T and
  speed should move < a couple %. If they keep changing, refine more.
- **Convergence**: residuals flat *and* the return‑grille temperature steady.
- **Sanity**: energy in ≈ energy out — the return temperature should sit between
  289 K (supply) and 300 K (floor); the plume should rise, not sink.
- Once you trust it, change one thing at a time (supply angle, flow rate,
  diffuser position) and compare — that's HVAC design by CFD.

### Variations (one change each)

- **Displacement ventilation**: move the supply to the floor (low, slow, cool)
  and the return to the ceiling — compare stratification.
- **A person/equipment hot box**: model a small box on the floor, `Part →
  Boolean → Cut` it from the air, and set its faces to a *fixed temperature*
  (e.g. 308 K) — a localised plume instead of a warm floor.
- **Transient**: switch Physics to *Transient* for how fast the room reaches
  steady comfort after start‑up (uses `buoyantBoussinesqPimpleFoam`).

## 3d. Troubleshooting (blueCFD on Windows)

- **"Trying to use the dummy Pstream library… cannot be used in parallel mode",
  `mpiexec.exe … path not found`** → blueCFD's OpenFOAM is built **without MPI**,
  so it can only run **serial**. In the **Analysis control** panel untick
  **"Solve in Parallel"** (1 core) → **Write** → **Run**. This clears every
  FOAM FATAL ERROR of that kind.
- **"No part of the boundary 'wall' matched any part of the geometry … being
  meshed"** → that boundary has **no faces** (it points at the wrong solid, or
  its face list is stale). Keep **one** analysis, **one** mesh on **one** solid;
  double‑click each boundary, clear it, and re‑select the correct faces so
  **every** face of the meshed solid belongs to exactly one boundary.
- **Two `CfdAnalysis` / two meshes / stray geometry in the tree** → delete the
  extras; a tangled tree is the usual cause of the boundary mismatch above.
- **"Placement selection error" / a tilted, wrong‑shaped mesh** → the solid got
  mis‑placed or rotated. Rebuild it **axis‑aligned at the origin** (no
  rotation), then add the stubs.
- **First run strategy**: prove the pipeline with an **isothermal incompressible**
  run (no heat/buoyancy) first; once it completes, enable Heat transfer +
  Gravity for the thermal/HVAC result.

## 4. Feeding CFD results back into DynFrame

CFD gives you **pressure coefficients** on the real geometry; DynFrame turns
pressures into structural demand. Two clean hand-offs:

- **Per-face c_p → Wind Load tool.** Read the windward/leeward/side/roof c_p
  values off the ParaView surface plot and enter them as the **net c_p** in
  **Add Wind Load (EN 1991-1-4)** for the corresponding frame lines. You keep
  EN's height-varying q_p(z) and just replace the *shape* coefficient with your
  CFD-derived one — often the whole reason to run CFD (odd plan shapes,
  sheltering, non-standard roofs where the code tables don't fit).
- **Pressure → plate pressure load.** For a clad wall/roof modelled as a
  DynFrame **plate**, apply the local CFD pressure (p = c_p · ½ρU²) with **Add
  Plate Pressure**, then read moments and **Wood–Armer / EC2 reinforcement**
  straight out of DynFrame.

(The link is manual on purpose — a blind auto-map of a CFD mesh onto a
structural model hides exactly the modelling decisions an engineer must own.)

---

## 5. Sanity / validation

- Mesh independence: refine until the quantity you care about (base moment,
  mean c_p) stops moving.
- Benchmark your setup once against a known case — e.g. flow around a surface-
  mounted cube (Martinuzzi & Tropea; AIJ building benchmarks) — before trusting
  it on your own geometry.
- Steady RANS gives mean loads; for buffeting, vortex shedding or peak suctions
  you need transient (URANS/LES) and a much finer mesh.

---

## 6. When to use which

- **Standard building, rectangular-ish, code coefficients apply →** just use
  **DynFrame → Add Wind Load (EN 1991-1-4)**. No CFD needed.
- **Unusual shape, sheltering, pedestrian wind, roof suctions off the tables,
  or you need the flow field →** OpenFOAM + CfdOF, then bring c_p back into
  DynFrame as above.

*This file is guidance, not a solver. DynFrame does not install or run
OpenFOAM for you; CfdOF (via the FreeCAD Addon Manager) does.*
