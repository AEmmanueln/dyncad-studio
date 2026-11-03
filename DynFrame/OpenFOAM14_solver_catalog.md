# OpenFOAM 14 — the complete solver catalog (do *everything*, no coding)

This is the full capability map of the OpenFOAM 14 install in your WSL/Ubuntu
terminal (the one where `ls $FOAM_TUTORIALS` worked). **One universal recipe
runs every module below** — you reuse the module's own validated tutorial and
change a few parameters. Nothing here needs you to write a solver.

> Use the **OpenFOAM 14 (Ubuntu/WSL)** terminal, not blueCFD — blueCFD's
> `sourceOF` is broken by the space in *Program Files*. Make OF‑14 automatic:
> `echo '. /opt/openfoam14/etc/bashrc' >> ~/.bashrc`

> **Shortcut from FreeCAD:** DynFrame's **CFD Case (OpenFOAM)** command (toolbar
> *DynFrame · CFD*) runs this whole recipe for any module below — pick the
> physics, it copies the module's tutorial, sets your run controls with
> `foamDictionary`, and writes `run_<name>.sh` / `view_<name>.sh` plus the
> one-liners to paste here. See `CFD_with_OpenFOAM.md` §0. The catalog below is
> the reference for *which* module and *what* to change.

---

## The universal recipe (identical for every module)

```
. /opt/openfoam14/etc/bashrc                 # once per terminal (or put in ~/.bashrc)
ls $FOAM_TUTORIALS/<module>                  # see the cases for that physics
cp -r $FOAM_TUTORIALS/<module>/<case> ~/run && cd ~/run
# change the handful of parameters listed per module below, then:
./Allrun                                     # the case's own script (meshes + runs)
#   or step by step:  blockMesh   then   foamRun        (foamMultiRun for multiRegion)
```

**How a case is organised (same for all):**
- `system/controlDict` — picks the solver (`solver <module>;`), `endTime`,
  `deltaT`, `writeInterval`.
- `system/fvSchemes`, `fvSolution` — numerics (leave the tutorial's).
- `system/blockMeshDict` (and/or `snappyHexMeshDict`) — the geometry/mesh.
- `constant/physicalProperties` (viscosity/thermo), `momentumTransport`
  (turbulence), `g` (gravity), plus model dicts.
- `0/` — the initial & boundary values (U, p, T, species, alpha…).

**Change the physics by editing those files** — never the solver code.

## Running & viewing

- **Run:** `foamRun` reads the module from `controlDict`; `foamMultiRun` for
  multi‑region (CHT). Mesh first with `blockMesh` (+`snappyHexMesh`).
- **Serial** is simplest. **Parallel** works on this WSL OF‑14 (unlike blueCFD):
  `decomposePar` → `mpirun -np 4 foamRun -parallel` → `reconstructPar`.
- **ParaView:** in WSL, `paraFoam` (if ParaView is installed there:
  `sudo apt install paraview`). Or from **Windows ParaView 5.11**: `touch
  case.foam` in the case, then open `\\wsl.localhost\Ubuntu\home\<you>\run\case.foam`.

---

## Flow

**`incompressibleFluid`** — incompressible turbulent flow, steady/transient
(was *simpleFoam/pimpleFoam*). Wind, ventilation, ducts, pumps, low‑speed
external aero. *Change:* inlet `0/U`, outlet `0/p`, turbulence in
`constant/momentumTransport`, viscosity `nu` in `constant/physicalProperties`.

**`isothermalFluid`** — compressible flow at fixed temperature. Low‑speed
compressible where heating is ignored. *Change:* inlet U/p, thermo.

**`fluid`** — general **compressible flow with energy + buoyancy** (was
*rhoPimpleFoam / buoyant\*Foam*). Natural & forced convection, HVAC with
temperature, stack/chimney flow, heated rooms. *Change:* inlet `0/U`,`0/T`,
`constant/g`, thermo + turbulence. **This is your buoyant HVAC solver.**

**`potentialFoam`** — inviscid potential flow; a fast first field or an
initialiser for the solvers above. *Change:* just the `0/U` BCs.

**`shockFluid`** — density‑based compressible with shock capturing (was
*rhoCentralFoam*). Supersonic nozzles, shock tubes, blast. *Change:* inlet
Mach/p/T, geometry.

## Heat transfer & multi‑region

**`multiRegion`** — **coupled fluid + solid regions = conjugate heat transfer**
(was *chtMultiRegionFoam*). CHT walls/insulation, heat exchangers, electronics
& battery cooling, thermal bridges with the air side. Run with **`foamMultiRun`**.
*Change:* each solid region's conductivity in `constant/<solid>/physicalProperties`
(concrete 1.7, mineral wool 0.035, steel 50), fluid inlet U/T; leave the
coupled interface patches alone.

**`solidDisplacement`** — linear‑elastic solid stress incl. **thermal stress**
(was *solidDisplacementFoam*). Thermal stress in a part, simple solid mechanics.
*Change:* mechanical props, thermal load, BCs. (For frames/beams use DynFrame.)

## Multiphase (water, bubbles, particles‑as‑phase)

**`incompressibleVoF`** — two‑phase **free surface** (VOF) (was *interFoam*).
Water waves, dam break, tank sloshing, weirs, drainage. *Change:*
`system/blockMeshDict` (geometry), `system/setFieldsDict` (initial water — run
`setFields`), phases in `constant/physicalProperties` (nu, rho, `sigma` surface
tension), `constant/g`. View `alpha.water`.

**`compressibleVoF`** — two‑phase VOF with compressibility — **cavitation**,
water‑hammer with a free surface.

**`incompressibleMultiphaseVoF` / `compressibleMultiphaseVoF`** — **3+ immiscible
phases** (was *multiphaseInterFoam*). Oil‑water‑air, layered fluids.

**`multiphaseEuler`** — **Euler–Euler multiphase** with interphase drag/heat/mass
transfer and **boiling** (was *reactingTwoPhaseEulerFoam*). Bubble columns,
fluidised beds, aeration, gas‑liquid reactors, boiling. *Change:* phases, the
transfer models, inlets.

**`incompressibleDriftFlux`** — drift‑flux **settling/sedimentation** (was
*driftFluxFoam*). Clarifiers, settling tanks, slurries. *Change:* settling model,
inlet concentration.

**`incompressibleDenseParticleFluid`** — **dense particle‑laden flow** (DPM /
MPPIC parcels) (was *DPMFoam/MPPICFoam*). Fluidised beds, pneumatic conveying,
cyclones, dense sprays. *Change:* particle size/density, injection, cloud
settings in `constant/cloudProperties`.

**`film` / `isothermalFilm`** — thin **liquid film on surfaces** (was
*surfaceFilm*). Rain films, cooling/lubricating films, condensation, fire‑
suppression films — usually coupled to a gas flow.

## Combustion / reacting flow

**`multicomponentFluid`** — **multi‑species reacting flow + combustion** with
finite‑rate chemistry (was *reactingFoam*). Non‑premixed combustion, furnaces,
burners, pollutant (NOx/CO) formation, chemical reactors. *Keep* the tutorial's
`constant/reactions` + thermo (the validated hard part); change inlets (species
mass fractions, U, T) and the ignition kernel (`system/setFieldsDict`).

**`XiFluid`** — **premixed / partially‑premixed combustion** (flame‑wrinkling Xi)
(was *XiFoam/PDRFoam*). Premixed flames, SI engines, **gas explosions** (PDR for
congested plant). *Change:* equivalence ratio, inlet, ignition.

## Mesh & motion

**`mesh`** — the meshing tutorials: `blockMesh`, `snappyHexMesh`, `foamyHexMesh`.
How to build the mesh for any case (box domains, STL‑based, boundary layers).

**`movingMesh`** — mesh‑motion / dynamic‑mesh cases (prescribed or solved
motion), combined with a flow solver via `dynamicMeshDict`. Moving valves,
pistons, deforming domains, basic FSI.

**`legacy`** — older solver cases kept for reference/porting.

---

## Add‑on physics — models you drop into *any* solver (no new solver)

These are `fvModels`/`fvConstraints` and dictionaries you add to a case, so you
mix physics on top of the modules above:

- **Radiation** — `constant/radiationProperties` (fvDOM / P1 / viewFactor):
  solar gains, furnace/surface radiation. Add to `fluid` or `multiRegion`.
- **Porous media** — `constant/fvModels` with a porosity source: filters, packed
  beds, perforated screens, vegetation/urban canopy, HVAC coils.
- **Rotating machinery** — `fvModels` **MRF** zone (frozen‑rotor) or **AMI** sliding
  mesh: fans, pumps, turbines, mixers, wind turbines.
- **Sources** — heat, momentum or **scalar sources** via `fvModels`: occupant/
  equipment heat, a contaminant/CO₂ release, a fan body force.
- **Passive scalars / age‑of‑air** — add a `scalarTransport` fvModel to carry a
  tracer in the flow: IAQ, smoke spread (passive), residence time.
- **Chemistry** — `constant/chemistryProperties` + a reaction mechanism, for
  `multicomponentFluid`.

So "doing all of OpenFOAM" = **the universal recipe + the module list above +
these add‑on models.** Pick a module, copy its tutorial, change the parameters,
run, view — the same five steps every time.

---

*Guidance, not a solver. These are OpenFOAM 14's own validated tutorial cases;
confirm the exact case names with `ls $FOAM_TUTORIALS/<module>` on your install.
DynFrame doesn't run OpenFOAM — your WSL OpenFOAM 14 does; DynFrame handles the
structural + validated‑thermal side and takes CFD results (pressures, c_p) back
in as loads.*
