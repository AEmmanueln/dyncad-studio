# DynFrame — Verification & Validation report

Every analysis and design feature in DynFrame is checked against an independent
reference: a **closed-form / textbook** result, or a **real Autodesk Robot**
run. The checks are executable and reproducible — they live in
`tests/validate.py`, which prints each benchmark with its expected value and
**exits non-zero on any mismatch**:

```
python3 DynFrame/tests/validate.py        # the V&V suite (numbers below)
python3 DynFrame/tests/test_registration.py   # all commands register
```

This is the same discipline commercial tools rely on; here it is open and you
can run it.

## 1. Cross-checked against Autodesk Robot (the strongest evidence)

A real Robot steel-design export (BS-EN 1993-1:2005/NA, a steel portal building,
sections UB 356×171×57 / 610×229×101 / 203×133×30) is reproduced **to the
digit** by DynFrame's `_ec3_member_check`:

| Member / section | Robot | DynFrame |
|---|---|---|
| Column UB356×171×57 — N_c,Rd | 2577.30 kN | 2577.30 |
| — M_y,c,Rd / M_z,c,Rd | 358.19 / 70.29 kN·m | 358.19 / 70.29 |
| — V_y,c,Rd / V_z,c,Rd | 970.70 / 646.30 kN | 970.69 / 646.24 |
| — class, χ_y, χ_z | 2, 0.94, 0.28 | 2, 0.94, 0.29 |
| — **Eq 6.62 interaction** | **1.07 (fails)** | **1.06 (fails)** |
| Beam UB610×229×101 — N_c,Rd / M_y,c,Rd | 4579.50 / 1024.88 | 4579.50 / 1024.88 |
| — χ_LT (restrained) | 1.00 | 1.00 |
| Beam UB203×133×30 — M_cr / χ_LT (LTB) | 67.04 kN·m / 0.53 | 68.6 / 0.54 |
| — verdict (overloaded) | fails (M/M_b ≈ 3.5) | fails |
| Torsion (6.2.7) — V_pl,T,Rd | 920.84 kN | 893 (−3 %, warping) |
| Shear–moment (6.2.8) — V_pl,web (UB356) | 646.3 kN | 646.24 |
| — M_y,V,Rd at V = 500 kN (ρ = 0.300) | — | 334.7 kN·m (hand 334.7) |

Matching Robot's beam-column interaction and LTB uses the Steel Code Check's
**LTB-susceptible** and **LTB load-position** options. The only acknowledged
difference is open-section **warping** torsion (Robot does a full thin-walled
analysis); the St-Venant torsion check matches to a few percent.

## 2. Validated against closed-form / textbook results

- **Static FE** — cantilever/simply-supported/fixed beams, both planes, all six
  force components and load-case superposition, exact (wL⁴/8EI, 5wL⁴/384EI,
  wL²/8, wL²/12); bar loads exact (PL³/3EI, PL, UDL, triangular); releases give
  the propped cantilever (wL²/8).
- **Modal** f₁ = (1.875²/2π)√(EI/ρAL⁴) to 4 figures; **buckling** P_cr = π²EI/(2L)²
  (ratio 1.000); **P-Δ** the 1/(1−P/P_cr) amplification.
- **Dynamics** — time-history (Newmark-β) DAF = 2.0, period T₁, heavy-damping
  static limit; modal superposition to 0.5 %; a recorded accelerogram to the
  digit; **CQC** ρ=1 identical / →0 separated; response spectrum S_a→PGA,
  resonant peak PGA/2ζ; **pushover** reproduces the plastic-collapse loads to the
  newton (8/6/4 M_p/L, 3/2/1 hinges).
- **Plates/shells** — simply-supported plate w_c=0.00406qa⁴/D (ratio 0.996),
  Timoshenko moment M=0.0479qa² (0.99); Wood-Armer corner cases; principal-moment
  direction exact.
- **Section engine** reproduces published tables (IPE 300 A/I/W_el/W_pl/I_t/I_w;
  rectangle shape factor 1.5); **full EC3 check** classifies, picks buckling
  curves, LTB reduction, Annex-B interaction, and the **6.2.8 shear–moment**
  reduction (reduced W_pl at high web shear, to the hand calc); the **section
  optimiser** returns the lightest family member that passes — verified against
  the invariant that every lighter size fails.
- **Design** — EC2 slab reinforcement (≈757 mm²/m), punching (util 1.50), beam
  (K=0.137, A_s≈1486; shear A_sw/s≈682), column N-M (M_Rd=246 at N=960 kN),
  slenderness (λ=52, M₂≈48), biaxial (a=1.25), pad footing, combined footing;
  EC5 timber (f_m,d, buckling k_c=0.285); EC6 masonry (f_k=4.06, Φ Annex G);
  EC9 aluminium; AISC 360 (F_cr=306.9, φP_n=2762); connections (bolt
  94.1/88.3/141.1 kN, weld 233.7 MPa); EN 1990 combinations exact; SLS deflection.
- **Building physics** — EN ISO 6946 U-value, Glaser condensation, EN ISO 13786
  thermal mass, 2D thermal bridge, EN 1991-1-2 fire vs the erf solution.

## 3. Scope and honest limits

DynFrame reproduces **Robot's workflow and core engineering** on FreeCAD's
kernel. Known gaps (see the README): open-section warping torsion; detailed
connection components (moment end-plates); pile groups; automatic code
detailing/drawings. CFD stays with OpenFOAM (see `CFD_with_OpenFOAM.md`).
