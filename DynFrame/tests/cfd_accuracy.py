#!/usr/bin/env python3
"""Accuracy benchmark: laminar plane-channel (Poiseuille) flow, built with the
DynFrame generators and solved on OpenFOAM, checked against the analytical
answer u_max = 1.5 * u_mean.

Flow is in +X between two no-slip walls (z = 0 and z = H); the span (y) is slip
so the case is effectively 2-D. A uniform inlet velocity U develops into the
parabolic Poiseuille profile; once fully developed the centreline (and domain
maximum) velocity is exactly 1.5 U. We measure max|U| from the solved field and
require it within 5 % of 1.5 U.

Run inside WSL with OpenFOAM sourced:
    source /opt/openfoam14/etc/bashrc && python3 tests/cfd_accuracy.py
Exit code 0 = PASS.
"""
import os
import re
import sys
import math
import glob
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dynframe_cfd_gen as g

# --- physical setup -------------------------------------------------------
U_IN = 0.01            # inlet speed (m/s), uniform
NU = 1.0e-4            # kinematic viscosity (m2/s) -> Re_Dh ~ 20, firmly laminar
H = 0.1                # channel gap (m), walls at z=0 and z=H
L = 2.0               # channel length (m) >> entry length, so flow fully develops
SPAN = 0.1             # y extent (slip, 2-D)
NX, NY, NZ = 120, 1, 48
U_MAX_EXACT = 1.5 * U_IN
TOL = 0.05             # 5 %


def build(case):
    for d in ("0", "constant", "system"):
        os.makedirs(os.path.join(case, d), exist_ok=True)
    face_patches = {
        "xmin": ("velocity_inlet", "patch"), "xmax": ("velocity_outlet", "patch"),
        "zmin": ("wall", "wall"), "zmax": ("wall", "wall"),
        "ymin": ("slip_y", "patch"), "ymax": ("slip_y", "patch"),
    }
    bm = g.box_blockmesh_named(0, 0, 0, L, SPAN, H, NX, NY, NZ, face_patches)
    patches = [
        {"name": "velocity_inlet", "bc": "velocity_inlet", "value": U_IN,
         "dir": (1.0, 0.0, 0.0)},
        {"name": "velocity_outlet", "bc": "pressure_outlet", "value": 0.0},
        {"name": "wall", "bc": "wall", "value": 0.0},
        {"name": "slip_y", "bc": "slip", "value": 0.0},
    ]
    files, _k, _o = g.bc_field_files(patches, nu=NU, intensity=0.01, L=H)
    files["momentumTransport"] = g.momentum_transport_dict("laminar")
    files["fvSchemes"] = g.fv_schemes_simple(second_order=True)
    files["controlDict"] = g.control_dict_simple("incompressibleFluid", 4000, 4000)
    layout = {"blockMeshDict": "system", "fvSchemes": "system",
              "fvSolution": "system", "controlDict": "system",
              "momentumTransport": "constant", "physicalProperties": "constant",
              "U": "0", "p": "0", "k": "0", "omega": "0", "nut": "0"}
    open(os.path.join(case, "system", "blockMeshDict"), "w").write(bm)
    for fn, txt in files.items():
        sub = layout.get(fn, "system")
        open(os.path.join(case, sub, fn), "w").write(txt)


def run(case):
    for cmd in (["blockMesh"], ["foamRun"]):
        r = subprocess.run(cmd, cwd=case, capture_output=True, text=True)
        if r.returncode != 0:
            print("%s FAILED:\n%s" % (cmd[0], (r.stdout + r.stderr)[-1500:]))
            return False
    return True


def max_speed(case):
    times = []
    for d in glob.glob(os.path.join(case, "*")):
        b = os.path.basename(d)
        try:
            times.append((float(b), d))
        except ValueError:
            pass
    if not times:
        return None
    _t, latest = max(times, key=lambda x: x[0])
    with open(os.path.join(latest, "U")) as fp:
        txt = fp.read()
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*\d+\s*\((.*?)\)\s*;",
                  txt, re.S)
    if not m:
        return None
    best = 0.0
    for v in re.findall(r"\(([^)]+)\)", m.group(1)):
        try:
            x, y, z = (float(t) for t in v.split())
        except ValueError:
            continue
        best = max(best, math.sqrt(x * x + y * y + z * z))
    return best


def main():
    case = os.path.join(os.path.expanduser("~"), "dynframe_cfd", "_accuracy_channel")
    shutil.rmtree(case, ignore_errors=True)
    build(case)
    if not run(case):
        print("ACCURACY: FAIL (solver did not complete)")
        return 1
    umax = max_speed(case)
    if umax is None:
        print("ACCURACY: FAIL (no velocity field)")
        return 1
    err = abs(umax - U_MAX_EXACT) / U_MAX_EXACT
    print("Plane-channel Poiseuille (laminar):")
    print("  U_inlet        = %.5g m/s" % U_IN)
    print("  u_max measured = %.5g m/s" % umax)
    print("  u_max exact    = %.5g m/s (1.5 * U_inlet)" % U_MAX_EXACT)
    print("  relative error = %.2f %%  (tol %.0f %%)" % (err * 100, TOL * 100))
    if err <= TOL:
        print("ACCURACY: PASS")
        return 0
    print("ACCURACY: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
