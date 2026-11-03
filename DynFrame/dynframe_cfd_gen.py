# -*- coding: utf-8 -*-
"""DynFrame CFD - mesh generation from CAD (pure, testable).

Turns a FreeCAD solid into an OpenFOAM mesh the *accurate* way: a background hex
box (blockMesh) with the solid's surface carved out and boundary-layered by
**snappyHexMesh** - the same mesher SimScale's standard ("hex-dominant") mesh
uses under the hood. This module writes the dictionaries; the FreeCAD command
exports the solid to STL and runs them on the user's OpenFOAM.

No FreeCAD/numpy imports here, so every generator is unit-tested in validate.py.
The generators take plain numbers (metres) and return OpenFOAM dictionary text,
so their structure and values are checked without a GUI or OpenFOAM present.

Units: FreeCAD works in millimetres, OpenFOAM in metres. The command exports the
STL already scaled to metres and passes metre bounds here, so everything down-
stream is consistent (no convertToMeters juggling).
"""


def _g(v):
    """Compact number format for dict values."""
    return ("%.6g" % float(v))


# ---- STL writer (from a tessellated FreeCAD solid) ---------------------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normal(a, b, c):
    """Unit normal of triangle a,b,c (0,0,0 if degenerate)."""
    u = _sub(b, a)
    v = _sub(c, a)
    nx = u[1] * v[2] - u[2] * v[1]
    ny = u[2] * v[0] - u[0] * v[2]
    nz = u[0] * v[1] - u[1] * v[0]
    m = (nx * nx + ny * ny + nz * nz) ** 0.5
    if m < 1e-30:
        return (0.0, 0.0, 0.0)
    return (nx / m, ny / m, nz / m)


def ascii_stl(name, points, facets):
    """Serialise a tessellated surface to ASCII STL. `points` is a sequence of
    (x,y,z); `facets` a sequence of (i,j,k) indices into points. Pure, so the
    command can tessellate the FreeCAD solid and this stays unit-tested."""
    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    out = ["solid %s" % name]
    for f in facets:
        a, b, c = pts[f[0]], pts[f[1]], pts[f[2]]
        n = _normal(a, b, c)
        out.append(" facet normal %s %s %s" % (_g(n[0]), _g(n[1]), _g(n[2])))
        out.append("  outer loop")
        for v in (a, b, c):
            out.append("   vertex %s %s %s" % (_g(v[0]), _g(v[1]), _g(v[2])))
        out.append("  endloop")
        out.append(" endfacet")
    out.append("endsolid %s" % name)
    return "\n".join(out) + "\n"


def _pt(x, y, z):
    return "(%s %s %s)" % (_g(x), _g(y), _g(z))


# ---- domain + resolution from the body's bounding box ------------------------
def body_length(dx, dy, dz):
    """Characteristic length = largest body dimension (metres)."""
    return max(float(dx), float(dy), float(dz), 1e-9)


def domain_from_bbox(bx0, by0, bz0, bx1, by1, bz1,
                     up=2.0, down=4.0, side=2.0, top=2.0, ground=1.0):
    """Flow domain around a body bbox, margins as multiples of the body length L
    (SimScale-style wind-tunnel box: room upstream, more downstream, sides/top/
    ground). Returns (x0, y0, z0, x1, y1, z1) in metres. +x is the flow dir."""
    L = body_length(bx1 - bx0, by1 - by0, bz1 - bz0)
    return (bx0 - up * L, by0 - side * L, bz0 - ground * L,
            bx1 + down * L, by1 + side * L, bz1 + top * L)


def cell_counts(x0, y0, z0, x1, y1, z1, h):
    """Background cell counts for a target base cell size h (metres), >=1 each."""
    def n(a, b):
        return max(1, int(round(abs(b - a) / float(h))))
    return n(x0, x1), n(y0, y1), n(z0, z1)


def location_in_mesh(x0, y0, z0, x1, y1, z1, bx0, up_frac=0.25):
    """A point guaranteed to be in the fluid: well upstream of the body (x below
    the body's min-x), centred in y and z. snappyHexMesh keeps the side of the
    surface that contains this point."""
    L = (x1 - x0)
    xloc = x0 + up_frac * (bx0 - x0)        # between inlet and the body's front
    if not (x0 < xloc < bx0):
        xloc = 0.5 * (x0 + bx0)
    return (xloc, 0.5 * (y0 + y1), 0.5 * (z0 + z1))


# ---- blockMesh (background hex box) -----------------------------------------
def block_mesh_dict(x0, y0, z0, x1, y1, z1, nx, ny, nz,
                    inlet="inlet", outlet="outlet", sides="sides",
                    top="top", ground="ground", ground_type="wall"):
    """A single-block hex box in metres with named far-field patches. +x = inlet
    -> outlet; the two y faces are one 'sides' patch; z-min is 'ground' (a wall
    by default, for ground-mounted bodies), z-max is 'top'."""
    V = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    verts = "\n".join("    " + _pt(*v) for v in V)
    head = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - generated blockMeshDict (background hex box)                  |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      blockMeshDict;\n}\n\n"
        "scale   1;\n\n"
        "vertices\n(\n%s\n);\n\n"
        "blocks\n(\n    hex (0 1 2 3 4 5 6 7) (%d %d %d) simpleGrading (1 1 1)\n);\n\n"
        "edges\n(\n);\n\n" % (verts, nx, ny, nz))
    boundary = (
        "boundary\n(\n"
        "    %s\n    {\n        type patch;\n        faces ( (0 4 7 3) );\n    }\n"
        "    %s\n    {\n        type patch;\n        faces ( (2 6 5 1) );\n    }\n"
        "    %s\n    {\n        type patch;\n        faces ( (1 5 4 0) (3 7 6 2) );\n    }\n"
        "    %s\n    {\n        type patch;\n        faces ( (4 5 6 7) );\n    }\n"
        "    %s\n    {\n        type %s;\n        faces ( (0 3 2 1) );\n    }\n"
        ");\n\n"
        "mergePatchPairs\n(\n);\n"
        % (inlet, outlet, sides, top, ground, ground_type))
    return head + boundary


# ---- surfaceFeatures (sharp-edge extraction, helps snapping) -----------------
def surface_features_dict(stl="body.stl", angle=150.0):
    return (
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      surfaceFeaturesDict;\n}\n\n"
        "surfaces ( \"%s\" );\n\n"
        "includedAngle   %s;\n" % (stl, _g(angle)))


# ---- snappyHexMesh (carve the body out + boundary layers) --------------------
def snappy_hex_mesh_dict(stl="body.stl", name="body", level_min=2, level_max=4,
                         feature_level=4, resolve_angle=30.0, n_layers=3,
                         expansion=1.3, final_layer=0.5, location=(0.0, 0.0, 0.0)):
    """A complete, standard snappyHexMesh setup: castellate to the STL with
    surface + feature refinement, snap, then add n_layers boundary layers on the
    body. Defaults are conservative and work for most external-flow geometries;
    the dialog exposes the levels and layer count."""
    lx, ly, lz = location
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - generated snappyHexMeshDict                                   |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      snappyHexMeshDict;\n}\n\n"
        "castellatedMesh true;\n"
        "snap            true;\n"
        "addLayers       true;\n\n"
        "geometry\n{\n"
        "    %s\n    {\n        type triSurfaceMesh;\n        name %s;\n    }\n"
        "}\n\n"
        "castellatedMeshControls\n{\n"
        "    maxLocalCells 1000000;\n"
        "    maxGlobalCells 5000000;\n"
        "    minRefinementCells 10;\n"
        "    maxLoadUnbalance 0.10;\n"
        "    nCellsBetweenLevels 3;\n\n"
        "    features\n    (\n        { file \"%s.eMesh\"; level %d; }\n    );\n\n"
        "    refinementSurfaces\n    {\n"
        "        %s\n        {\n            level (%d %d);\n            patchInfo { type wall; }\n        }\n"
        "    }\n\n"
        "    resolveFeatureAngle %s;\n\n"
        "    refinementRegions\n    {\n    }\n\n"
        "    locationInMesh (%s %s %s);\n"
        "    allowFreeStandingZoneFaces true;\n"
        "}\n\n"
        "snapControls\n{\n"
        "    nSmoothPatch 3;\n    tolerance 2.0;\n    nSolveIter 30;\n"
        "    nRelaxIter 5;\n    nFeatureSnapIter 10;\n"
        "    implicitFeatureSnap false;\n    explicitFeatureSnap true;\n"
        "    multiRegionFeatureSnap false;\n}\n\n"
        "addLayersControls\n{\n"
        "    relativeSizes true;\n"
        "    layers\n    {\n        \"%s.*\"\n        {\n            nSurfaceLayers %d;\n        }\n    }\n"
        "    expansionRatio %s;\n"
        "    finalLayerThickness %s;\n"
        "    minThickness 0.1;\n"
        "    nGrow 0;\n    featureAngle 60;\n    nRelaxIter 5;\n"
        "    nSmoothSurfaceNormals 1;\n    nSmoothNormals 3;\n"
        "    nSmoothThickness 10;\n    maxFaceThicknessRatio 0.5;\n"
        "    maxThicknessToMedialRatio 0.3;\n    minMedialAxisAngle 90;\n"
        "    nBufferCellsNoExtrude 0;\n    nLayerIter 50;\n}\n\n"
        "meshQualityControls\n{\n"
        "    maxNonOrtho 65;\n    maxBoundarySkewness 20;\n    maxInternalSkewness 4;\n"
        "    maxConcave 80;\n    minVol 1e-13;\n    minTetQuality 1e-15;\n"
        "    minArea -1;\n    minTwist 0.02;\n    minDeterminant 0.001;\n"
        "    minFaceWeight 0.02;\n    minVolRatio 0.01;\n    minTriangleTwist -1;\n"
        "    nSmoothScale 4;\n    errorReduction 0.75;\n}\n\n"
        "mergeTolerance 1e-6;\n"
        % (stl, name, name, feature_level, name, level_min, level_max,
           _g(resolve_angle), _g(lx), _g(ly), _g(lz), name, n_layers,
           _g(expansion), _g(final_layer)))


# ---- mesh run script ---------------------------------------------------------
def build_mesh_script(opts):
    """Bash that builds a meshed case from the CAD geometry:
      - copies an incompressibleFluid tutorial for version-correct boilerplate
        (fvSchemes/fvSolution/controlDict), then strips its mesh,
      - drops in the generated blockMeshDict / snappyHexMeshDict /
        surfaceFeaturesDict (staged on the Windows side) and the body STL,
      - runs surfaceFeatures -> blockMesh -> snappyHexMesh -> checkMesh,
      - converts the mesh to VTK and copies it to Windows for ParaView.
    opts: of_env, name, stage_win (Windows dir holding the generated files +
    body.stl), win_out (Windows dir to receive VTK), base_tutorial (optional).
    """
    import dynframe_cfd as cfd
    of_env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    name = opts.get("name", "mesh1")
    stage = cfd.win_to_wsl(opts["stage_win"])
    win_out = opts["win_out"]
    out = cfd.win_to_wsl(win_out)
    base = opts.get("base_tutorial", "incompressibleFluid")
    work = cfd.WORK_ROOT

    L = []
    L.append("# DynFrame CFD - generated mesh-from-CAD script (snappyHexMesh)")
    L.append(". %s" % of_env)
    L.append('STAGE=%s' % cfd.shq(stage))
    L.append('SRC=$(ls -d "$FOAM_TUTORIALS/%s"/*/ 2>/dev/null | head -1)' % base)
    L.append('if [ -z "$SRC" ]; then echo "ERROR: no %s tutorial for boilerplate"; exit 1; fi'
             % base)
    L.append('mkdir -p %s' % work)
    L.append('DST=%s/%s' % (work, name))
    L.append('rm -rf "$DST" && cp -r "$SRC" "$DST" && cd "$DST" || exit 1')
    # strip the tutorial's mesh/geometry so only our mesh remains
    L.append('rm -rf constant/polyMesh constant/triSurface constant/geometry '
             '0 0.orig processor* VTK')
    L.append('mkdir -p constant/triSurface')
    # bring in the generated dictionaries + STL
    L.append('cp "$STAGE/blockMeshDict"        system/blockMeshDict')
    L.append('cp "$STAGE/snappyHexMeshDict"    system/snappyHexMeshDict')
    L.append('cp "$STAGE/surfaceFeaturesDict"  system/surfaceFeaturesDict')
    L.append('cp "$STAGE/body.stl"             constant/triSurface/body.stl')
    # mesh
    L.append('echo "== surfaceFeatures =="; surfaceFeatures 2>&1 | tail -4 || '
             'echo "surfaceFeatures skipped"')
    # if no edge mesh was produced, disable feature snapping so snappy still runs
    L.append('if ! ls constant/*/*.eMesh constant/*.eMesh >/dev/null 2>&1; then '
             'echo "no eMesh -> disabling feature snapping"; '
             'foamDictionary -entry castellatedMeshControls/features -set "()" '
             'system/snappyHexMeshDict 2>/dev/null || true; fi')
    L.append('echo "== blockMesh =="; blockMesh 2>&1 | tee log.blockMesh | tail -4')
    L.append('echo "== snappyHexMesh =="; snappyHexMesh -overwrite 2>&1 | '
             'tee log.snappyHexMesh | tail -6')
    L.append('echo "== checkMesh =="; checkMesh -allGeometry 2>&1 | '
             'tee log.checkMesh | tail -25')
    # convert the mesh to VTK for ParaView (mesh only; fields come once it solves)
    L.append('foamToVTK -constant 2>&1 | tail -3 || foamToVTK 2>&1 | tail -3')
    L.append('OUT=%s' % cfd.shq(out))
    L.append('mkdir -p "$OUT"; rm -rf "$OUT/VTK"')
    L.append('[ -d VTK ] && cp -r VTK "$OUT/" && echo "=== mesh VTK copied to: %s ==="'
             % win_out)
    L.append('echo "=== MESH DONE: $DST  (read the checkMesh summary above) ==="')
    return "\n".join(L)
