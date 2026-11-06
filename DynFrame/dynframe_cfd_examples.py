# -*- coding: utf-8 -*-
"""DynFrame CFD - curated, fully-parameterised example cases (pure generators).

These are canonical CFD benchmarks built from the DynFrame generators so they
are small, fast and guaranteed to run on OpenFOAM's incompressibleFluid solver
and open cleanly in ParaView. Each example exposes rich *physical* parameters
(speeds, viscosity, size, mesh, turbulence) - not just time controls - so it can
be re-run by changing numbers, SimScale-style. No FreeCAD imports, so it is
unit-testable; dynframe_commands drives the panel, staging and run.
"""

import dynframe_cfd_gen as g


def example_catalog():
    """The curated examples and their editable physical parameters. Each param:
    {key, label, default, kind(float|int|combo), [min,max], [options]}."""
    return [
        {"key": "cavity",
         "title": "Lid-driven cavity (laminar)",
         "help": "The classic benchmark: a closed square cavity whose top lid "
                 "slides and drives a recirculating vortex. Raise the lid speed "
                 "or drop the viscosity for a higher Reynolds number.",
         "params": [
             {"key": "side", "label": "Cavity side (mm)", "default": 100.0},
             {"key": "lid", "label": "Lid speed (m/s)", "default": 1.0},
             {"key": "nu", "label": "Kinematic viscosity (m2/s)", "default": 1.0e-3,
              "decimals": 8},
             {"key": "cells", "label": "Cells per side", "default": 50, "kind": "int"},
             {"key": "iters", "label": "Iterations", "default": 2000, "kind": "int"},
         ]},
        {"key": "channel",
         "title": "Channel flow between plates",
         "help": "Flow between two parallel plates: a uniform inlet develops into "
                 "the parabolic Poiseuille profile (laminar) or a flatter "
                 "turbulent profile. Change inlet speed, gap, length, viscosity, "
                 "mesh and turbulence model.",
         "params": [
             {"key": "length", "label": "Length (mm)", "default": 2000.0},
             {"key": "height", "label": "Gap height (mm)", "default": 100.0},
             {"key": "speed", "label": "Inlet speed (m/s)", "default": 0.1},
             {"key": "nu", "label": "Kinematic viscosity (m2/s)", "default": 1.0e-4,
              "decimals": 8},
             {"key": "cells", "label": "Cells across gap", "default": 48, "kind": "int"},
             {"key": "iters", "label": "Iterations", "default": 2000, "kind": "int"},
             {"key": "model", "label": "Turbulence", "default": "laminar",
              "kind": "combo", "options": ["laminar", "kOmegaSST"]},
         ]},
        {"key": "step",
         "title": "Backward-facing step (turbulent)",
         "help": "The pitzDaily-style separated flow: fluid enters a narrow inlet "
                 "and expands over a step, forming a recirculation bubble. Change "
                 "inlet speed, expansion ratio, viscosity, mesh and model.",
         "params": [
             {"key": "speed", "label": "Inlet speed (m/s)", "default": 10.0},
             {"key": "inlet_h", "label": "Inlet height (mm)", "default": 25.0},
             {"key": "step_h", "label": "Step height (mm)", "default": 25.0},
             {"key": "length", "label": "Downstream length (mm)", "default": 300.0},
             {"key": "nu", "label": "Kinematic viscosity (m2/s)", "default": 1.5e-5,
              "decimals": 8},
             {"key": "cells", "label": "Cells across inlet", "default": 24, "kind": "int"},
             {"key": "iters", "label": "Iterations", "default": 2000, "kind": "int"},
             {"key": "model", "label": "Turbulence", "default": "kOmegaSST",
              "kind": "combo", "options": ["kOmegaSST", "laminar"]},
         ]},
    ]


def example_spec(key):
    for e in example_catalog():
        if e["key"] == key:
            return e
    return None


def example_study_spec(key, p):
    """Geometry size (mm), a face->BC scheme and study settings for loading a
    box-geometry template as an EDITABLE CFD study (geometry + tree + BCs the user
    can then change). 'bcs' maps a box side (xmin/xmax/ymin/ymax/zmin/zmax) to
    (bc_key, value). Returns None for non-box examples (e.g. the step)."""
    if key == "cavity":
        S = float(p.get("side", 100.0))
        return {
            "label": "Lid-driven cavity",
            "dims": (S, S, max(5.0, S * 0.1)),
            "study": {"CfdNu": g._g(float(p.get("nu", 1.0e-3))),
                      "CfdIters": str(int(p.get("iters", 2000))),
                      "CfdTurbulence": "laminar",
                      "CfdCells": str(int(p.get("cells", 50)))},
            "bcs": {"ymax": ("moving_wall", float(p.get("lid", 1.0))),
                    "xmin": ("wall", 0.0), "xmax": ("wall", 0.0),
                    "ymin": ("wall", 0.0),
                    "zmin": ("slip", 0.0), "zmax": ("slip", 0.0)},
        }
    if key == "channel":
        L = float(p.get("length", 2000.0)); H = float(p.get("height", 100.0))
        return {
            "label": "Channel flow",
            "dims": (L, H, H),
            "study": {"CfdNu": g._g(float(p.get("nu", 1.0e-4))),
                      "CfdIters": str(int(p.get("iters", 2000))),
                      "CfdTurbulence": str(p.get("model", "laminar")),
                      "CfdCells": str(int(p.get("cells", 48)))},
            "bcs": {"xmin": ("velocity_inlet", float(p.get("speed", 0.1))),
                    "xmax": ("pressure_outlet", 0.0),
                    "zmin": ("wall", 0.0), "zmax": ("wall", 0.0),
                    "ymin": ("slip", 0.0), "ymax": ("slip", 0.0)},
        }
    return None


def _common(files, nu, model, iters):
    files["momentumTransport"] = g.momentum_transport_dict(model)
    files["physicalProperties"] = g.physical_properties_dict(nu)
    files["fvSchemes"] = g.fv_schemes_simple(second_order=True)
    files["fvSolution"] = g.fv_solution_simple()
    files["controlDict"] = g.control_dict_simple(
        "incompressibleFluid", int(iters), max(1, int(iters) // 5))
    return files


def build_example(key, p):
    """Return {filename: text} (including blockMeshDict) for example `key`."""
    if key == "cavity":
        return _cavity(p)
    if key == "channel":
        return _channel(p)
    if key == "step":
        return _step(p)
    raise KeyError("unknown example %r" % key)


def _cavity(p):
    S = float(p.get("side", 100.0)) / 1000.0
    U = float(p.get("lid", 1.0))
    nu = float(p.get("nu", 1.0e-3))
    N = max(8, int(p.get("cells", 50)))
    iters = max(50, int(p.get("iters", 2000)))
    t = S / N                               # one cell thick (slip z-faces => 2-D)
    face_patches = {
        "ymax": ("lid", "wall"),
        "xmin": ("fixedWalls", "wall"), "xmax": ("fixedWalls", "wall"),
        "ymin": ("fixedWalls", "wall"),
        "zmin": ("frontBack", "patch"), "zmax": ("frontBack", "patch"),
    }
    bm = g.box_blockmesh_named(0, 0, 0, S, S, t, N, N, 1, face_patches)
    patches = [
        {"name": "lid", "bc": "moving_wall", "value": U},   # slides +x at U
        {"name": "fixedWalls", "bc": "wall", "value": 0.0},
        {"name": "frontBack", "bc": "slip", "value": 0.0},  # 2-D
    ]
    files, _k, _o = g.bc_field_files(patches, nu=nu, intensity=0.01, L=S)
    files["blockMeshDict"] = bm
    return _common(files, nu, "laminar", iters)


def _channel(p):
    L = float(p.get("length", 2000.0)) / 1000.0
    H = float(p.get("height", 100.0)) / 1000.0
    U = float(p.get("speed", 0.1))
    nu = float(p.get("nu", 1.0e-4))
    N = max(8, int(p.get("cells", 48)))
    iters = max(50, int(p.get("iters", 2000)))
    model = str(p.get("model", "laminar"))
    nx = max(40, min(400, int(N * (L / H) / 2.0)))
    face_patches = {
        "xmin": ("inlet", "patch"), "xmax": ("outlet", "patch"),
        "zmin": ("walls", "wall"), "zmax": ("walls", "wall"),
        "ymin": ("frontBack", "patch"), "ymax": ("frontBack", "patch"),
    }
    bm = g.box_blockmesh_named(0, 0, 0, L, H, H, nx, 1, N, face_patches)
    patches = [
        {"name": "inlet", "bc": "velocity_inlet", "value": U, "dir": (1.0, 0.0, 0.0)},
        {"name": "outlet", "bc": "pressure_outlet", "value": 0.0},
        {"name": "walls", "bc": "wall", "value": 0.0},
        {"name": "frontBack", "bc": "slip", "value": 0.0},
    ]
    files, _k, _o = g.bc_field_files(patches, nu=nu, intensity=0.03, L=H)
    files["blockMeshDict"] = bm
    return _common(files, nu, model, iters)


def _step(p):
    """Backward-facing step via a two-block blockMesh (inlet channel of height
    inlet_h, then a sudden expansion to inlet_h+step_h over `length`)."""
    U = float(p.get("speed", 10.0))
    hi = float(p.get("inlet_h", 25.0)) / 1000.0
    hs = float(p.get("step_h", 25.0)) / 1000.0
    Ld = float(p.get("length", 300.0)) / 1000.0
    nu = float(p.get("nu", 1.5e-5))
    N = max(8, int(p.get("cells", 24)))
    iters = max(50, int(p.get("iters", 2000)))
    model = str(p.get("model", "kOmegaSST"))
    Li = Ld * 0.25                     # short inlet channel before the step
    H = hi + hs                        # full downstream height
    t = H / N                          # 2-D thickness (one cell, slip front/back)
    nyi = max(6, N)                    # cells over inlet height
    nys = max(6, int(N * hs / hi))     # cells over step height
    nxi = max(8, int(N * Li / hi))     # cells along inlet
    nxd = max(20, int(N * Ld / hi))    # cells along downstream
    bm = _step_blockmesh(Li, Ld, hi, hs, t, nxi, nxd, nyi, nys)
    patches = [
        {"name": "inlet", "bc": "velocity_inlet", "value": U, "dir": (1.0, 0.0, 0.0)},
        {"name": "outlet", "bc": "pressure_outlet", "value": 0.0},
        {"name": "walls", "bc": "wall", "value": 0.0},
        {"name": "frontBack", "bc": "slip", "value": 0.0},
    ]
    files, _k, _o = g.bc_field_files(patches, nu=nu, intensity=0.05, L=hi)
    files["blockMeshDict"] = bm
    return _common(files, nu, model, iters)


def _step_blockmesh(Li, Ld, hi, hs, t, nxi, nxd, nyi, nys):
    """Three-block 2-D backward-facing-step mesh (conformal on shared faces).
    Levels: x = -Li, 0, Ld ; y = 0, hs, hs+hi ; z = 0, t.
    Block A = inlet channel (x -Li..0, y hs..H); block B = downstream top
    (x 0..Ld, y hs..H); block C = downstream bottom / step (x 0..Ld, y 0..hs).
    A|B share x=0 (y hs..H); B|C share y=hs (x 0..Ld). The step face (x=0,
    y 0..hs) and the outer edges are walls; the two z faces are slip (2-D)."""
    H = hs + hi
    z0, z1 = 0.0, t
    # 8 distinct (x,y) points, back face (z0) 0..7, front face (z1) 8..15.
    pts = [(-Li, hs), (0, hs), (0, H), (-Li, H),      # 0-3
           (0, 0), (Ld, 0), (Ld, hs), (Ld, H)]        # 4-7
    verts = ["    (%s %s %s)" % (g._g(x), g._g(y), g._g(z0)) for (x, y) in pts]
    verts += ["    (%s %s %s)" % (g._g(x), g._g(y), g._g(z1)) for (x, y) in pts]
    blocks = (
        "    hex (0 1 2 3 8 9 10 11) (%d %d 1) simpleGrading (1 1 1)\n"      # A inlet
        "    hex (4 5 6 1 12 13 14 9) (%d %d 1) simpleGrading (1 1 1)\n"     # C bottom
        "    hex (1 6 7 2 9 14 15 10) (%d %d 1) simpleGrading (1 1 1)\n"     # B top
        % (nxi, nyi, nxd, nys, nxd, nyi))
    boundary = (
        "    inlet\n    {\n        type patch;\n        faces ( (0 3 11 8) );\n    }\n"
        "    outlet\n    {\n        type patch;\n        faces ( (5 6 14 13) (6 7 15 14) );\n    }\n"
        "    walls\n    {\n        type wall;\n        faces\n        (\n"
        "            (3 2 10 11) (0 1 9 8)\n"      # inlet top, inlet bottom
        "            (2 7 15 10) (4 5 13 12)\n"    # duct top, duct bottom
        "            (4 1 9 12)\n"                 # the step face (x=0, y 0..hs)
        "        );\n    }\n"
        "    frontBack\n    {\n        type patch;\n        faces\n        (\n"
        "            (0 1 2 3) (8 9 10 11)\n"      # block A z faces
        "            (4 5 6 1) (12 13 14 9)\n"     # block C z faces
        "            (1 6 7 2) (9 14 15 10)\n"     # block B z faces
        "        );\n    }\n")
    head = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - backward-facing-step blockMeshDict                            |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      blockMeshDict;\n}\n\nscale   1;\n\nvertices\n(\n%s\n);\n\n"
        "blocks\n(\n%s);\n\nedges\n(\n);\n\nboundary\n(\n%s);\n\n"
        "mergePatchPairs\n(\n);\n" % ("\n".join(verts), blocks, boundary))
    return head
