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
