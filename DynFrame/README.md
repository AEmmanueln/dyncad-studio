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

> **Two panels.** **Frame Analysis Panel** (DynFrame · Analysis Panel) opens a
> single window where you build the model, apply supports and loads to the
> current 3D selection, manage cases and combinations, Calculate, and switch
> the shown result — all in one place, instead of a chain of pop-ups.
> **Results Viewer** is a second, Inventor-style window for *analysing and
> viewing* results: a list of every available result (displacement, each force
> component, stress, and any mode / buckling / seismic shape) that you click to
> show as a **bold coloured contour** that **varies along each member** (the
> colour changes with the local bending / stress / displacement, not one flat
> colour per bar), a **readable colour legend painted in the panel** (with
> numeric value ticks that update to the shown result — no squinting at tiny 3D
> text), a **summary** of the key maxima (max displacement and where, max N / M
> / shear, max utilisation), a **deformation-scale** control to exaggerate the
> deflected shape, a **show/hide undeformed model** toggle, a **Solid beams
> (real section)** toggle that redraws the result on the members' actual swept
> profiles (the Inventor solid-beam look) instead of tubes, and an **Animate**
> button that oscillates the deflected shape (it plays a few smooth loops then
> stops, or press **Stop** — it stops instantly because the frames are
> pre-built and only toggled, not recomputed). Results are drawn **one at a
> time, on demand**, so switching result, scale or style re-renders instantly.
> The individual commands below still exist and use single-form dialogs.

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
5. **Define Support** — select node vertices → Fixed / Pinned / Roller. Works
   on **solid-body members** as well as line members: the pick snaps to the
   nearest structural node, so clicking a corner vertex (or the base face) of a
   solid column lands the support on that column's centreline node. Nodal
   loads and settlements snap the same way.
6. **Add Nodal Load** (on selected node vertices) / **Add Bar Load** (on
   selected bars/lines) — one dialog each, assigned to a load case. A bar load
   can be **uniform (UDL)**, a **concentrated point load** at any position
   along the bar, or a **trapezoidal** (linearly varying `w1`→`w2`) load — the
   three Robot bar-load types. All are solved with exact consistent fixed-end
   forces, so nodal results and the force diagrams are exact.
7. **Support Settlement** — select supported node(s) → prescribe an imposed
   support movement (settlement) for a load case; the solve finds the forces
   it induces (see *Advanced analysis* below).
8. **Load Combinations** — the **full EN 1990** code combinations, the way
   Robot does them (not a single 1.35G+1.5Q lump): **ULS** eq 6.10 (or eqs
   6.10a/6.10b) with each variable action taken in turn as the **leading** one
   and the others reduced by **ψ₀**, plus **SLS** characteristic, frequent (ψ₁/ψ₂)
   and quasi-permanent (ψ₂) — or a custom factored combination
   (`1.35*DL1 + 1.5*LL1`). ψ factors per EN 1990 Table A1.1.

*Solve & results (DynFrame · Results):*
9. **Calculate** — choose a case, a combination, or *All loads* (+ optional
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
10. **Show Result / Diagram** — switch the displayed result: Displacement
    contour, or an N / Vy / Vz / Mx / My / Mz / Stress diagram. The **Results
    Viewer** (above) does the same from a persistent list, and adds the maxima
    summary, deformation scaling and animation.
11. **Clear Results** — remove results only, or everything (supports, loads,
    combinations).

Everything the analysis creates — supports, loads, the setup, the result
tables and the force diagrams — is collected under **one `DynFrame` group** in
the model tree (sub-groups *Supports / Loads / Analysis Setup / Results /
Force Diagrams*), so the document stays tidy instead of scattering loose
spreadsheets at the root.

*Design & dynamics (DynFrame · Loads / Results):*
- **Member Releases** — free member end DOFs: moment releases for a pinned
  connection, or pin both ends for a truss member (presets). Handled by
  static condensation; non-released members are unaffected.
- **Tension / Compression-only members** — mark selected bars as
  **tension-only** (a cable or slack cross-brace) or **compression-only** (a
  strut). See *Advanced analysis* below.
- **Nodal Load** also takes **moments** Mx / My / Mz, not just forces.
- **Envelope (all combinations)** — solves every combination and keeps the
  worst axial / My / Mz / utilisation per member (the design envelope),
  colours members by it, and stores the governing forces so the code check
  runs against the envelope.
- **Moving Load Envelope** — a bridge/crane **influence analysis**: select the
  lane members (the path the load travels), and a **single point load or a
  train of equally-spaced axles** (vehicle/crane, load per axle) is stepped
  along them while the model is re-solved at every position; the **worst force
  at every section** is kept (the influence envelope). It reuses the beam
  solver on a dedicated bars-only carrier model (one factorisation, many
  positions), renders the moment envelope with the deformed shape at the
  governing position, writes a `MovingEnvelope` table, and stores the envelope
  forces so the **Steel Code Check** verifies against them. (Validated: a
  simply-supported span gives the absolute-maximum moment PL/4 to the digit,
  the shear envelope reaches P next to a support, and two axles a hair apart
  reproduce the single-2P result PL/2.)
- **Plate Reinforcement (EC2)** — required slab steel to EN 1992-1-1 from the
  Wood–Armer design moments: the **area of reinforcement A_s (mm²/m)** for the
  bottom (sagging) and top (hogging) face in X and Y, for each plate, as a
  singly-reinforced section (K = M/bd²f_cd, lever arm z, A_s = M/0.87f_yk z).
  Pick the concrete grade, f_yk, cover and bar diameter; the slab thickness is
  taken from each plate. Minimum steel (9.2.1.1) is applied and a section that
  would need compression steel is flagged. Results go to the `PlateSteel`
  table. (Validated: a 200 mm slab at 50 kN·m/m → ≈757 mm²/m, matching the
  hand calc; minimum-steel and over-moment cases flagged correctly.)
- **Punching Shear (EC2)** — EN 1992-1-1 (6.4) punching check at slab–column
  junctions: the design column load β·V_Ed over the control perimeter u₁ at 2d
  (v_Ed) against v_Rd,c = C_Rd,c·k·(100ρ_l f_ck)^⅓ ≥ v_min, plus the column-face
  check v_Ed,0 against the crushing limit v_Rd,max = 0.5·ν·f_cd. Select the
  columns (it reads their axial load N_Ed from the analysis) and pick position
  (internal/edge/corner → β), column size, slab d, grade and ρ_l; results and a
  pass/fail go to the `PunchingShear` table (util > 1 ⇒ needs links/studs or a
  thicker slab/drop panel). Validated: a 400×400 internal column, d=200, C30/37,
  ρ_l=0.01, V_Ed=800 kN → u₁=4113 mm, v_Rd,c=0.746 MPa, v_Ed=1.118 MPa,
  utilisation 1.50 — matching the hand calc.
- **RC Beam Design (EC2)** — design a rectangular reinforced-concrete beam to
  EN 1992-1-1: **flexural** steel by the rectangular stress block (singly
  reinforced while K = M/bd²f_ck ≤ K′ = 0.167, **doubly reinforced** with
  compression steel above that), and **shear links** by the variable-strut
  method (V_Rd,c for the concrete, Asw/s from the chosen strut angle, with the
  V_Rd,max crushing check), plus EC2 minimum/maximum steel. Enter the section,
  grade and the ULS envelope M_Ed / V_Ed; results go to the `RcBeam` table.
  (Validated: 300×450 d, C30/37, M=250 kN·m → K=0.137, z=387 mm, As≈1486 mm²;
  M=400 kN·m → doubly reinforced, As2≈550, As≈2445 mm²; V=300 kN → V_Rd,c≈87 kN,
  V_Rd,max≈442 kN, Asw/s≈682 mm²/m — all matching the textbook hand calc.)
- **RC Column Design (EC2)** — check/design a symmetrically-reinforced
  rectangular RC column to EN 1992-1-1 by its **N–M interaction**: the moment
  capacity M_Rd at the design axial load N_Ed (rectangular stress block, steel
  on both faces, strains from plane sections), the utilisation for M_Ed, and the
  steel auto-sized if it fails. **Slender columns** are handled by the EC2 5.8
  nominal-curvature method — give the effective length l₀ and it computes the
  slenderness λ against λ_lim and adds the second-order moment M₂ = N_Ed·e₂ to
  the design moment. Enter the section, bars and ULS N_Ed / M_Ed; results go to
  the `RcColumn` table. (Validated: 300×400, 2000 mm² symmetric, C30/37 → squash
  load 3270 kN, M_Rd=246 kN·m at N=960 kN; with l₀=6 m → λ=52 > λ_lim=17
  (slender), M₂≈48 kN·m — all matching the hand calc.)
- **Wall U-value & Condensation (building physics)** — **Wall U-value &
  Condensation** analyses a layered wall/roof: the **U-value** (thermal
  transmittance) to EN ISO 6946 (R-values in series + surface resistances),
  and **interstitial condensation / mould risk** by the **Glaser** method
  (EN ISO 13788) — the temperature, vapour‑pressure and saturation profiles
  through the build‑up, flagging any interface where vapour reaches saturation
  and the internal‑surface temperature factor f_Rsi (mould). Pick the layers
  (a small thermal‑material library with conductivity λ and vapour‑resistance μ)
  from inside to outside and the inside/outside temperature and humidity;
  results go to the `WallThermal` table. It also reports the **dynamic
  (thermal‑mass) response** by the EN ISO 13786 heat‑transfer‑matrix method —
  the **decrement factor** f (how much a daily temperature swing is damped) and
  the **time lag** (hours the peak is delayed) — so you can judge summer
  overheating / thermal comfort, not just steady heat loss. (Validated: 200 mm concrete + 100 mm
  EPS → U = 0.320 W/m²K; Glaser correctly predicts condensation for
  wrong‑side (internal) insulation and none for external insulation.) This is
  the standards method for insulation performance — CFD is only needed for
  2D/3D thermal bridges (see the conduction solver).
- **Thermal Bridge (2D conduction)** — a **steady heat‑conduction finite‑element
  solver** (EN ISO 10211) for a wall whose insulation is **bridged by a
  repeating conductive element** (steel/timber stud, concrete rib): it meshes
  the 2D cross‑section, solves ∇·(k∇T)=0 with **convective surface boundaries**
  (Rsi/Rse), and reports the **temperature field** (coloured contour), the
  **bridged U‑value** vs the plain‑wall U, and the **surface temperature factor
  f_Rsi** (mould/condensation risk at the cold spot). This is the "conduction
  side of conjugate heat transfer" that OpenFOAM does — now native in DynFrame,
  no CFD needed. (Validated: with a bridge of the *same* material as the
  insulation the 2D solver reproduces the 1D U‑value to the digit; a steel stud
  through 140 mm mineral wool raises U from 0.23 to 0.60 W/m²K and drops f_Rsi
  from 0.97 to 0.57 — a severe bridge, as expected.)
- **Fire Resistance (transient thermal)** — **transient 2D heat‑conduction FE**
  of a section in the **standard fire** (ISO 834 / EN 1991‑1‑2): the gas
  temperature 20 + 345·log₁₀(8t+1) drives the exposed faces and the temperature
  field is time‑stepped (implicit backward‑Euler with a lumped heat‑capacity
  matrix). Reports the **temperature at the reinforcement cover depth and the
  core over time** (for fire‑rating / reduced‑capacity checks — steel loses
  ~50 % strength by ~550 °C). Pick the section, material, exposure (4 sides /
  3 sides / underside / one face), cover and duration; results go to the
  `FireThermal` table with a temperature contour. (Validated: the transient
  solver matches the semi‑infinite `erf` solution to the digit — 273 °C at
  50 mm after 1 h of a 500 °C face — and the ISO 834 curve gives 842 °C at
  30 min, 945 °C at 60 min.)
- **CFD Mesh from CAD / CFD Case / CFD View (OpenFOAM)** — drive real CFD from
  FreeCAD. **SimScale's CFD _is_ OpenFOAM**, so for the same case you get the
  same results on the free engine. **CFD Mesh from CAD** auto-meshes a selected
  solid the accurate way — it exports the body to STL and writes a full
  **snappyHexMesh** setup (background box + surface/feature refinement +
  boundary layers), *the same mesher SimScale's standard mesh uses*, then runs
  `blockMesh → snappyHexMesh → checkMesh` and converts the mesh to VTK for
  ParaView. **CFD Domain & BCs** draws the flow domain **on the part in the 3D
  view** — a box with its faces coloured by boundary condition (green inlet, red
  outlet, blue far-field, tan ground) and inlet-velocity arrows, a SimScale-style
  visual preview of the setup. **CFD Flow (wind / air)** is the end-to-end command: it auto-meshes
  the solid, **generates the boundary conditions + kOmegaSST turbulence to match
  the mesh patches** (inlet k/ω from your turbulence intensity), solves with
  OpenFOAM's `incompressibleFluid`, and writes VTK — colour by U or p in
  ParaView. *Pick geometry → set inlet speed → Run → view*, steady RANS. **CFD Case** lets you pick any of OpenFOAM 14's **20 solver modules**
  (incompressible flow, compressible/buoyant `fluid` for HVAC, conjugate heat
  transfer `multiRegion`, VOF free surface, Euler–Euler + boiling,
  reacting/combustion `multicomponentFluid`, premixed `XiFluid`, dense
  particles, drift-flux, films, shocks, solid stress, moving mesh, meshing) —
  **well beyond the flow+heat CfdOF exposes**. DynFrame copies OpenFOAM's own
  validated tutorial for that physics, sets your run controls and inlet via the
  native `foamDictionary`, and writes ready-to-run `run_<name>.sh` /
  `view_<name>.sh` scripts plus the one-liners to paste into your WSL OpenFOAM
  terminal; **CFD View** converts a case's latest results to VTK (all regions)
  and copies them to a Windows folder for ParaView. The engine is OpenFOAM and
  the viewer is ParaView; DynFrame automates the setup/run/convert/view loop.
  (Validated: the path translation, `foamDictionary` edits, catalog, and the
  generated run/view scripts are checked in the test suite; the physics is
  OpenFOAM's, run and viewed on your machine.) See **`CFD_with_OpenFOAM.md`**
  §0 and **`OpenFOAM14_solver_catalog.md`**.
- **Steel Code Check (EC3)** — a full EN 1993-1-1 member verification, the
  way Robot does it: each member is **classified** (Class 1–4) from its own
  flange/web slenderness under the actual axial force and moment; the bending
  resistance then uses the **plastic** modulus Wpl (Class 1/2) or **elastic**
  Wel (Class 3). It checks cross-section resistance, **flexural buckling** with
  the buckling curve chosen **automatically** from the section type (EC3
  Table 6.2), **lateral-torsional buckling** through the elastic critical
  moment **Mcr** (from the section's torsion It and warping Iw constants), and
  the **Annex-B beam-column interaction** (equations 6.61 and 6.62). You set
  γ_M0 / γ_M1, the buckling-length factors for each axis and the LTB restraint
  spacing, and pick the moment distribution (which sets the C1 / Cm factors).
  The `CodeCheck` table lists the class, χ_LT and both interaction
  utilisations per member, with the governing check and OK/FAIL, and members
  are coloured green→red by utilisation.
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
- **Time-History (dynamic)** — transient response by **Newmark-β direct
  integration** (average-acceleration, unconditionally stable). Excite the
  frame with a **nodal force** (on selected nodes) or a **ground acceleration**
  (seismic base motion), with a **step / harmonic / half-sine-pulse** time
  function **or a real recorded accelerogram** (El Centro, etc.), and
  **Rayleigh damping** (ζ anchored at the first two natural frequencies, found
  internally). A record is read from a FreeCAD **spreadsheet** — column A =
  time (s), column B = acceleration (g, m/s² or mm/s²); name the sheet and
  pick it in the dialog (a header row is skipped, and the analysis runs on
  past the record for the free-vibration decay). **Import Ground Motion** reads
  a record straight from a file — **PEER `.AT2`** (NGA strong-motion format,
  which carries its own time step) or a **CSV** (time,accel or accel-only) —
  into that spreadsheet in one step. Two solution methods:
  **direct** Newmark integration of the full system, or **modal
  superposition** (project onto the lowest N modes, integrate the decoupled
  modal SDOFs, reconstruct) — faster for large models and closer to how the
  code idealises the response. (Validated: 6-mode superposition reproduces the
  direct step-load DAF to 0.5 %.) It reports the peak response, the dynamic
  amplification, the peak base shear, a monitored-node **`ResponseHistory`**
  table, the deformed shape at peak, an **inter-storey drift** envelope
  (`StoreyDrift` table — peak relative displacement and drift ratio per storey)
  and a member-force envelope stored for the code check. (Validated: a
  cantilever under a suddenly-applied step force
  gives the exact SDOF dynamic amplification factor of 2.0, the response
  oscillates at its natural period T₁, f₁ matches the analytical cantilever,
  and heavy damping collapses the response to the static value.)
- **Ground-Motion Spectrum** — the **elastic response spectrum** (Sd, Sa vs
  period T) of a recorded accelerogram: a unit SDOF is run over a range of
  periods to get its peak response per period — the classic Sa-vs-T curve for
  comparing a record against the code design spectrum. Reads the record from a
  spreadsheet, writes a `GMSpectrum` table. (Validated: for a sinusoid the
  spectrum gives Sa → PGA at short period and a resonant peak Sa ≈ PGA/2ζ at
  T = 1/f, matching the closed form.)
- **Seismic (Response Spectrum)** — EN 1998-1 (EC8) response-spectrum
  analysis built on the modal results: pick the direction, ground
  acceleration aₘ, ground type (A–E) and behaviour factor q; it reports
  per-mode period / modal mass % / spectral acceleration / base shear, the
  combined base shear and the seismic displacement shape (warns if < 90 %
  modal mass is captured). Modes are combined by **CQC** (the complete
  quadratic combination, with correlation ρ_ij from the modal frequencies and
  damping — correct for closely-spaced modes) or **SRSS**, your choice.
- **Deflection Check (SLS)** — check every member's maximum span deflection
  from the latest analysis against the serviceability limit (**span/250** for
  appearance, span/350 or span/500 for brittle finishes). The deflection is
  measured **perpendicular to the member, relative to its displaced
  end-to-end chord**, so a rigid-body translation or rotation correctly reads
  as zero; results and a pass/fail per member go to the `Deflections` table
  (run it on an SLS combination).
- **Elastic (spring) supports** — model foundations / soil: in **Define
  Support** choose *Elastic (spring)* and enter the spring stiffnesses per DOF
  (Kx, Ky, Kz in N/mm; Krx, Kry, Krz in N·mm/rad). The springs add stiffness
  to the node instead of fixing it rigidly (validated: a tip spring equal to
  the beam's tip stiffness halves the cantilever deflection).
- **Thermal loads** — in **Add Bar Load** choose *Thermal (temperature)* and
  enter a uniform temperature change ΔT (°C); each material carries its own
  expansion coefficient α. A restrained member then develops N = −E·A·α·ΔT
  (validated exactly against the fixed-fixed bar).
- **Wind loads (EN 1991-1-4)** — **Add Wind Load** builds the peak velocity
  pressure q_p(z) up the height from the basic wind velocity v_b and terrain
  category (0–IV roughness), and applies it to the selected members as a
  **horizontal, height-varying line load** (q_p(z) × net pressure coefficient
  c_p × tributary width), stored as a per-member trapezoid so it grows with
  height — then solved like any other case and combined in the ULS/SLS
  combinations. Validated: q_p(10 m, terrain II, v_b = 26 m/s) ≈ 0.99 kPa
  (exposure factor c_e ≈ 2.35, matching the EN chart) and the applied base
  shear equals the pressure integral exactly. For true CFD (flow field,
  non-standard shapes), see **`CFD_with_OpenFOAM.md`**: DynFrame is a
  structural solver, so CFD is run with OpenFOAM via the free **CfdOF**
  FreeCAD workbench (the same engine SimScale uses), and the CFD pressure
  coefficients feed straight back into this wind tool.
- **Sway imperfections (EC3)** — **Sway Imperfection** forms the EN 1993-1-1
  (5.3.2) global initial sway as **equivalent horizontal forces**: φ =
  (1/200)·α_h·α_m (α_h = 2/√h clamped to [2/3, 1], α_m = √(0.5(1+1/m))), and
  applies φ·N at each column top, where N is the column axial force from the
  gravity analysis. Put it in its own case, combine with gravity and tick
  **P-Δ** to capture the second-order sway. (Validated: φ(h=10 m, m=1) =
  0.00333 and the notional force equals φ·N exactly.)
- **Support settlement** — in **Support Settlement** select the supported
  node(s) and prescribe an imposed support movement (translations in mm,
  −Z = sinks down; rotations in rad) for a load case, e.g. a foundation that
  settles. The analysis holds those DOFs at the given values and solves for
  the forces the movement induces (a partitioned solve, K_ff·u_f =
  F_f − K_fp·u_p). Validated against the closed form: a moment-free support
  that settles δ on a span of length L induces an end moment 3EIδ/L² and a
  shear 3EIδ/L³; a zero settlement reduces to the ordinary solve.
- **Tension-only / compression-only members** — cross-bracing and cables
  carry tension only; a strut carries compression only. In **Tension /
  Compression Member** mark the selected bars (optionally pinning their ends
  to make them true truss members). The solver runs a **nonlinear active-set
  iteration**: it drops out any such member whose axial force takes the wrong
  sign (a slack cable, a buckled brace), re-solves, and repeats until the
  active set is stable — so an X-braced panel sheds its compression diagonal
  and the tension diagonal carries the shear. Dropped members report zero
  force. Validated: a tension-only bar in parallel with a support spring is
  active (and carries P·kb/(kb+ks)) when pulled, and drops out — doubling the
  deflection — when pushed; a compression-only bar behaves oppositely. Models
  with no such members solve exactly as before.
- **Plates / Shells (2D elements)** — model walls, slabs and floor
  diaphragms. **Add Plate** turns 3 or 4 selected node vertices into a
  meshed plate (pick thickness, material and mesh divisions); it shares
  nodes with any bars at the same points, so a **slab sits on its beams**
  and they work together. **Add Plate Pressure** applies a surface pressure
  (plus plate self-weight as Dead). The solver uses a validated **flat shell
  = CST membrane + DKT thin-plate bending** (6 DOF/node), so plates and
  frames solve in one combined model. Results: the plate **von Mises stress
  contour** (each triangle coloured by its stress — a "Plate stress" result
  in the Results Viewer), **bending-moment contours Mₓ, M_y and M_xy** (the
  moments per unit width recovered from the DKT element and reported in one
  consistent plate coordinate frame, so the contour is smooth across the mesh;
  drawn with a signed blue→red map, hogging→sagging, with a −peak … +peak
  colour bar — the Robot/Inventor way of reading a slab), the **principal
  moments M₁ / M₂**, and the **Wood–Armer design moments** for orthogonal
  reinforcement — the sagging (bottom) and hogging (top) moment the x- and
  y-bars must resist, |M_xy| folded in by the standard corner corrections
  (Wood 1968). Tables: `PlateForces` (max von Mises, utilisation, max
  |Mₓ| / |M_y| / |M_xy| per plate) and `PlateReinforcement` (the four
  Wood–Armer design moments per plate), plus the plate nodes' deflections in
  `Displacements`. Pick any of **Plate stress / Mx / My / Mxy / M1 / M2 /
  Wood–Armer (bottom & top, X & Y)** in the Results Viewer to switch the
  contour; the colour bar re-ranges to match. There are also **principal-moment
  trajectory plots** (M1 red, M2 blue) — a short line at each element along the
  principal moment directions, scaled by magnitude: the "flow of forces" a
  slab's reinforcement ideally follows.

**Materials:** Steel S235 / S275 / S355, Stainless 304, Aluminium 6061-T6,
and Concrete C25/30 / C30/37 / C35/45 (E_cm and ν = 0.2 per EN 1992-1-1, for
RC slabs) — each with its own E, G, yield/fck and density. Edit `MATERIALS`
in `dynframe_commands.py` to add more.

## Verification & Validation

Correctness here is reproducible, not a matter of trust in a logo. Every
feature is checked against a closed-form or benchmark solution in a test suite
that runs with no GUI (FreeCAD/Part/PySide are mocked; the solver uses real
numpy). Run it yourself from the repository root:

```
python3 DynFrame/tests/validate.py          # engine vs closed-form benchmarks
python3 DynFrame/tests/test_registration.py # workbench + all commands register
```

`validate.py` prints each check with its expected value and exits non-zero on
any mismatch — so "it matches theory" is something you can watch happen, the
same Verification & Validation discipline commercial tools (Ansys, SimScale)
rely on. The checks it runs:

> **Validation** (all numeric, against closed-form solutions): the static
> solver is exact in both bending planes — cantilever (point and UDL),
> simply-supported and fixed-fixed beams (tip = wL⁴/8EI, mid = 5wL⁴/384EI,
> M = wL²/8, end = wL²/12), all six force components and load-case
> superposition; **bar loads** are exact — a tip point load gives PL³/3EI and
> M = PL, a trapezoid with w1 = w2 reproduces the UDL result exactly, and a
> triangular load balances qL/2; **releases** reproduce the propped
> cantilever (wL²/8);
> **modal** matches the cantilever f₁ = (1.875²/2π)·√(EI/ρAL⁴) to four
> figures; **buckling** matches the Euler load Pcr = π²EI/(2L)² (ratio
> 1.000); the **section-property engine** reproduces the published section
> tables (IPE 300: A, I, Wel, Wpl, It, Iw; a solid rectangle gives the exact
> Wpl/Wel = 1.5 shape factor); the **full EC3 check** classifies IPE 300 as
> Class 1 in bending, uses the plastic modulus accordingly, matches the code
> buckling curves and a worked column check (χ_z = 0.452, Nb,z = 551 kN,
> U = 0.73) and reproduces the LTB reduction (χ_LT ≈ 0.52 for a long
> unrestrained span); **P-Δ** reproduces the 1/(1−P/Pcr) amplification;
> **seismic** effective modal masses sum to 100 % of the total mass, and the
> **CQC** modal combination is exact — ρ = 1 for identical modes, → 0 (SRSS)
> for well-separated ones, and two fully-correlated modes combine to |R₁+R₂|;
> the **time-history** (Newmark-β) reproduces the exact step-load dynamic
> amplification factor of 2.0, oscillates at the natural period T₁, and
> collapses to the static response under heavy damping; **modal superposition**
> matches the direct result to 0.5 %, a **recorded accelerogram** read from a
> spreadsheet reproduces the matching built-in excitation to the digit, the
> inter-storey **drift ratio** equals the relative storey displacement over the
> storey height, and the **ground-motion response spectrum** of a sinusoid
> gives Sa → PGA at short period and a resonant peak Sa ≈ PGA/2ζ at T = 1/f; the
> **plate/shell** element converges to the exact simply-supported-plate
> deflection (w_c = 0.00406 q a⁴/D, ratio ≈ 0.996), its recovered
> **bending moment** matches the Timoshenko centre value (Mₓ = M_y =
> 0.0479 q a², ratio ≈ 0.99), and it is frame-invariant on a tilted plane;
> **Wood–Armer** design moments reproduce the closed-form corner cases (pure
> sagging → bottom steel one way, pure twist → equal steel all four faces,
> combined → the corrected design moments), and are always sign-correct
> (bottom ≥ 0, top ≤ 0, enveloping the raw field); the **principal-moment
> direction** is exact for the textbook cases (uniaxial → 0°, pure twist → 45°,
> M_y > M_x → 90°);
> **support settlement** matches 3EIδ/L² and 3EIδ/L³ for a settling prop;
> **tension-only / compression-only** members drop out under the wrong-sign
> axial force (active-set), matching the spring-parallel closed form; the
> **EC2 slab reinforcement** matches the hand calc (200 mm C30/37 slab at
> 50 kN·m/m → ≈757 mm²/m, min-steel and over-moment cases flagged); the
> **EC2 punching shear** matches its hand calc (400×400 internal column,
> d = 200, C30/37, V_Ed = 800 kN → u₁ = 4113 mm, v_Rd,c = 0.746 MPa,
> utilisation 1.50); the **full EN 1990 load combinations** are exact — ULS
> eq 6.10 enumerates each variable action as leading with the others at γ_Q·ψ₀
> (1.35G + 1.5·LL + 0.9·WL, and 1.35G + 1.05·LL + 1.5·WL), eqs 6.10a/6.10b carry
> ξ = 0.85 on the permanent action, and SLS gives the characteristic, frequent
> (ψ₁/ψ₂) and quasi-permanent (ψ₂) sets; the **EC2 RC beam design** matches the
> textbook hand calc (300×450, C30/37: M = 250 kN·m → K = 0.137, z = 387 mm,
> As ≈ 1486 mm²; M = 400 kN·m → doubly reinforced As2 ≈ 550, As ≈ 2445 mm²;
> V = 300 kN → V_Rd,c ≈ 87 kN, V_Rd,max ≈ 442 kN, Asw/s ≈ 682 mm²/m); the
> **EC2 RC column** N–M interaction matches the hand-calculated point (300×400,
> 2000 mm² symmetric, C30/37: squash 3270 kN, and M_Rd = 246 kN·m at N = 960 kN,
> with EC2 5.8 slenderness λ = 52 > λ_lim = 17 and a nominal-curvature M₂ ≈
> 48 kN·m at l₀ = 6 m); the **SLS deflection** extraction is exact — a 10 mm
> mid-span sag reads as 10 mm (span/deflection = 1000 for a 10 m span) while a
> rigid-body rotation and a purely axial displacement both read as zero;
> the
> **EN 1991-1-4 wind** pressure q_p(10 m, terrain II, v_b = 26 m/s) ≈ 0.99 kPa
> (c_e ≈ 2.35, matching the exposure chart) with the applied base shear equal
> to the pressure integral; and the **EC3 sway imperfection** gives φ =
> (1/200)α_h α_m with the notional force φ·N applied exactly; and the
> **moving-load envelope** returns the absolute-maximum moment PL/4 on a
> simply-supported span (ratio 1.000) with the shear envelope reaching P at a
> support; the **building thermal** tools match their standards (wall
> U = 0.320 W/m²K; Glaser flags wrong‑side insulation; dynamic EN ISO 13786
> gives decrement ≈ 0.33 / lag ≈ 8 h for 300 mm concrete; the 2D thermal‑bridge
> conduction FE reproduces the 1D U‑value exactly and a steel stud raises U
> from 0.23 to 0.60 W/m²K); and the **CFD (OpenFOAM) driver** is checked as
> software — Windows↔WSL path translation round-trips, the native
> `foamDictionary` edits and shell quoting are exact, the 20-module catalog is
> complete, and the generated run script (multi-region → `foamMultiRun`, prefers
> the tutorial `Allrun`, sets `endTime`) and view script (region-aware
> `foamToVTK`, VTK copied to the Windows path) are asserted, with the WSL
> invocation base64-round-tripping; the **mesh-from-CAD** generators are checked
> too — the wind-tunnel domain and cell counts from a body bounding box, the
> `blockMesh` box (patches, extents, ground wall), the `snappyHexMesh` dict
> (STL reference, refinement levels, boundary layers, balanced braces), the
> ASCII-STL writer (triangle unit normals) and the mesh script
> (`surfaceFeatures → blockMesh → snappyHexMesh → checkMesh`); and the
> **incompressible-flow case generator** — the inlet turbulence closed form
> (k = 1.5(I·U)², ω = √k/(C_μ^0.25·l)), the five field files (U/p/k/ω/νt) each
> declaring a BC for every mesh patch with the right wall functions, the
> kOmegaSST momentum-transport / physical-properties / fvSchemes / fvSolution /
> controlDict dicts (all with balanced braces), and the full mesh-plus-solve
> script (`blockMesh → snappyHexMesh → foamRun → foamToVTK`), with the commands
> staging every file end-to-end (the *physics and the mesh* are OpenFOAM's, run
> and validated on your machine, exactly as SimScale runs them). It covers
> **static,
> P-Δ, modal, buckling, seismic
> (response-spectrum), time-history (Newmark-β), moving-load influence,
> plates/shells, wind, building thermal (U-value / condensation / thermal mass /
> 2D thermal bridges) and a full EN 1993-1-1 / EN 1992-1-1 design check
> (members, slab reinforcement and punching)**.
> FreeCAD is not Robot — this reproduces Robot's *workflow and core
> engineering* on its kernel.

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

### Install / update straight from the FreeCAD Python console

If you'd rather not download by hand, open FreeCAD's **Python console**
(View → Panels → Python console) and paste this **single line**, then press
Enter. It downloads the whole `DynFrame` folder from this branch into the
right place; restart FreeCAD afterwards:

```python
exec("import os,json,urllib.request,FreeCAD\nrepo='AEmmanueln/dyncad-studio'\nref='claude/sleepy-ramanujan-96b3y6'\ndst=os.path.join(FreeCAD.getUserAppDataDir(),'Mod','DynFrame')\ndef grab(p):\n u='https://api.github.com/repos/%s/contents/%s?ref=%s'%(repo,p,ref)\n for it in json.load(urllib.request.urlopen(u)):\n  lp=os.path.join(dst,os.path.relpath(it['path'],'DynFrame'))\n  if it['type']=='dir':\n   os.makedirs(lp,exist_ok=True); grab(it['path'])\n  else:\n   os.makedirs(os.path.dirname(lp),exist_ok=True); urllib.request.urlretrieve(it['download_url'],lp)\nos.makedirs(dst,exist_ok=True); grab('DynFrame'); print('DynFrame updated ->',dst)")
```

It is deliberately a **single line**. Paste it as one line — don't retype
it as an indented block, because FreeCAD's interactive console rejects a
pasted multi-line `def …:` block (it reports `SyntaxError` on the line after
the block). If a multi-line version ever gives a `File "<input>"` syntax
error, that error is the console refusing the paste, not a bug in DynFrame —
use this one-line form (or the ZIP method above) instead.

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
