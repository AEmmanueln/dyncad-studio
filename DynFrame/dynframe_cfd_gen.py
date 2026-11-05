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


# ---- viewport preview: domain box faces -> boundary conditions ---------------
# Part.makeBox returns faces in the order [Xmin, Xmax, Ymin, Ymax, Zmin, Zmax];
# for our +X flow that maps to these boundary conditions, and these SimScale-style
# colours, so the setup is visible on the part in the FreeCAD 3D view.
DOMAIN_FACE_BCS = ("inlet", "outlet", "sides", "sides", "ground", "top")
DOMAIN_FACE_COLORS = ((0.20, 0.70, 0.30),   # inlet  - green
                      (0.85, 0.25, 0.20),   # outlet - red
                      (0.45, 0.65, 0.88),   # side   - blue
                      (0.45, 0.65, 0.88),   # side   - blue
                      (0.62, 0.55, 0.42),   # ground - tan
                      (0.55, 0.78, 0.95))   # top    - light blue


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
        "    %s\n    {\n        type triSurfaceMesh;\n        file \"%s\";\n    }\n"
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
        % (name, stl, name, feature_level, name, level_min, level_max,
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
    L.append('if [ -z "$(find constant -name \'*.eMesh\' 2>/dev/null)" ]; then '
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


# =============================================================================
# Step 2: incompressible-flow case (boundary conditions + solver settings)
# =============================================================================
# Patches produced by our blockMesh box + snappyHexMesh body, so every generated
# field file below declares a boundaryField for exactly these:
OUTER_PATCHES = ("inlet", "outlet", "sides", "top", "ground")
SLIP_PATCHES = ("sides", "top", "ground")   # far-field box walls (freestream)
BODY_PATCH = "body"


def inlet_turbulence(U, intensity=0.05, L=1.0):
    """Inlet k and omega for a RANS (kOmegaSST) run from the inlet speed, the
    turbulence intensity I and a length scale from the body (l = 0.07 L):
        k      = 1.5 (I U)^2
        omega  = k^0.5 / (Cmu^0.25 l),   Cmu = 0.09
    Returns (k, omega), floored so a zero inlet speed is still well-posed."""
    U = abs(float(U)); I = float(intensity); L = max(float(L), 1e-6)
    k = max(1.5 * (I * U) ** 2, 1e-8)
    l = max(0.07 * L, 1e-6)
    omega = k ** 0.5 / ((0.09 ** 0.25) * l)
    return k, omega


def _foam_header(cls, obj):
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - generated case file                                          |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       %s;\n"
        "    object      %s;\n}\n\n" % (cls, obj))


def _field(cls, obj, dims, internal, bmap):
    """Assemble a field file from a {patch: body-lines} map, in OUTER+body order."""
    body = ""
    for p in list(OUTER_PATCHES) + [BODY_PATCH]:
        body += "    %s\n    {\n%s\n    }\n" % (p, bmap[p])
    return (_foam_header(cls, obj)
            + "dimensions      %s;\n\ninternalField   %s;\n\n"
              "boundaryField\n{\n%s}\n" % (dims, internal, body))


def _slip(bmap):
    for p in SLIP_PATCHES:
        bmap[p] = "        type            slip;"
    return bmap


def field_U(Ux):
    uin = "uniform (%s 0 0)" % _g(Ux)
    b = {"inlet": "        type            fixedValue;\n        value           %s;" % uin,
         "outlet": "        type            inletOutlet;\n        inletValue      uniform (0 0 0);\n        value           %s;" % uin,
         BODY_PATCH: "        type            noSlip;"}
    return _field("volVectorField", "U", "[0 1 -1 0 0 0 0]", uin, _slip(b))


def field_p():
    b = {"inlet": "        type            zeroGradient;",
         "outlet": "        type            fixedValue;\n        value           uniform 0;",
         BODY_PATCH: "        type            zeroGradient;"}
    return _field("volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0", _slip(b))


def field_k(k0):
    kin = "uniform %s" % _g(k0)
    b = {"inlet": "        type            fixedValue;\n        value           %s;" % kin,
         "outlet": "        type            inletOutlet;\n        inletValue      %s;\n        value           %s;" % (kin, kin),
         BODY_PATCH: "        type            kqRWallFunction;\n        value           %s;" % kin}
    return _field("volScalarField", "k", "[0 2 -2 0 0 0 0]", kin, _slip(b))


def field_omega(omega0):
    oin = "uniform %s" % _g(omega0)
    b = {"inlet": "        type            fixedValue;\n        value           %s;" % oin,
         "outlet": "        type            inletOutlet;\n        inletValue      %s;\n        value           %s;" % (oin, oin),
         BODY_PATCH: "        type            omegaWallFunction;\n        value           %s;" % oin}
    return _field("volScalarField", "omega", "[0 0 -1 0 0 0 0]", oin, _slip(b))


def field_nut():
    b = {"inlet": "        type            calculated;\n        value           uniform 0;",
         "outlet": "        type            calculated;\n        value           uniform 0;",
         BODY_PATCH: "        type            nutkWallFunction;\n        value           uniform 0;"}
    return _field("volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0", _slip(b))


def momentum_transport_dict(model="kOmegaSST"):
    return _foam_header("dictionary", "momentumTransport") + (
        "simulationType  RAS;\n\nRAS\n{\n    model           %s;\n"
        "    turbulence      on;\n    printCoeffs     on;\n}\n" % model)


def physical_properties_dict(nu=1.5e-5):
    return _foam_header("dictionary", "physicalProperties") + (
        "viscosityModel  constant;\n\nnu              [0 2 -1 0 0 0 0] %s;\n" % _g(nu))


def fv_schemes_simple():
    return _foam_header("dictionary", "fvSchemes") + (
        "ddtSchemes\n{\n    default         steadyState;\n}\n\n"
        "gradSchemes\n{\n    default         Gauss linear;\n"
        "    grad(U)         cellLimited Gauss linear 1;\n}\n\n"
        "divSchemes\n{\n    default         none;\n"
        "    div(phi,U)      bounded Gauss linearUpwind grad(U);\n"
        "    div(phi,k)      bounded Gauss upwind;\n"
        "    div(phi,omega)  bounded Gauss upwind;\n"
        "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n}\n\n"
        "laplacianSchemes\n{\n    default         Gauss linear corrected;\n}\n\n"
        "interpolationSchemes\n{\n    default         linear;\n}\n\n"
        "snGradSchemes\n{\n    default         corrected;\n}\n\n"
        "wallDist\n{\n    method          meshWave;\n}\n")


def fv_solution_simple():
    return _foam_header("dictionary", "fvSolution") + (
        "solvers\n{\n"
        "    p\n    {\n        solver          GAMG;\n        tolerance       1e-7;\n"
        "        relTol          0.01;\n        smoother        GaussSeidel;\n    }\n\n"
        "    \"(U|k|omega)\"\n    {\n        solver          smoothSolver;\n"
        "        smoother        symGaussSeidel;\n        tolerance       1e-8;\n"
        "        relTol          0.1;\n    }\n}\n\n"
        "SIMPLE\n{\n    nNonOrthogonalCorrectors 0;\n    consistent      yes;\n"
        "    residualControl\n    {\n        p               1e-4;\n"
        "        U               1e-4;\n        \"(k|omega)\"     1e-4;\n    }\n}\n\n"
        "relaxationFactors\n{\n    equations\n    {\n        U               0.9;\n"
        "        \".*\"            0.9;\n    }\n}\n")


def control_dict_simple(solver="incompressibleFluid", end_iter=1000,
                        write_interval=200, deltaT=1):
    return _foam_header("dictionary", "controlDict") + (
        "solver          %s;\n\n"
        "startFrom       startTime;\nstartTime       0;\n"
        "stopAt          endTime;\nendTime         %d;\n"
        "deltaT          %s;\n\n"
        "writeControl    timeStep;\nwriteInterval   %d;\n\n"
        "purgeWrite      0;\nwriteFormat     ascii;\nwritePrecision  7;\n"
        "writeCompression off;\ntimeFormat      general;\ntimePrecision   6;\n"
        "runTimeModifiable true;\n"
        % (solver, int(end_iter), _g(deltaT), int(write_interval)))


def flow_case_files(Ux, nu=1.5e-5, intensity=0.05, L=1.0,
                    end_iter=1000, write_interval=200):
    """All the non-mesh files of a steady incompressible (kOmegaSST) case, as a
    {filename: text} map. Patch BCs match the blockMesh+snappy patches, so the
    case is self-consistent on the mesh DynFrame generates."""
    k0, omega0 = inlet_turbulence(Ux, intensity, L)
    return {
        "U": field_U(Ux), "p": field_p(), "k": field_k(k0),
        "omega": field_omega(omega0), "nut": field_nut(),
        "momentumTransport": momentum_transport_dict("kOmegaSST"),
        "physicalProperties": physical_properties_dict(nu),
        "fvSchemes": fv_schemes_simple(), "fvSolution": fv_solution_simple(),
        "controlDict": control_dict_simple("incompressibleFluid", end_iter,
                                            write_interval),
    }, k0, omega0


def build_flow_script(opts):
    """Bash for the full incompressible-flow pipeline: assemble the staged case,
    mesh (blockMesh+snappyHexMesh), solve (foamRun -> incompressibleFluid) and
    convert to VTK for ParaView. opts: of_env, name, stage_win (holds every
    generated file + body.stl), win_out, latest."""
    import dynframe_cfd as cfd
    of_env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    name = opts.get("name", "flow1")
    stage = cfd.win_to_wsl(opts["stage_win"])
    win_out = opts["win_out"]
    out = cfd.win_to_wsl(win_out)
    lt = " -latestTime" if opts.get("latest", True) else ""
    work = cfd.WORK_ROOT

    L = []
    L.append("# DynFrame CFD - generated incompressible-flow case (mesh + solve + view)")
    L.append(". %s" % of_env)
    L.append('STAGE=%s' % cfd.shq(stage))
    L.append('mkdir -p %s' % work)
    L.append('DST=%s/%s' % (work, name))
    L.append('rm -rf "$DST"; mkdir -p "$DST/0" "$DST/constant/triSurface" "$DST/system"')
    L.append('cd "$DST" || exit 1')
    L.append('cp "$STAGE"/blockMeshDict "$STAGE"/snappyHexMeshDict '
             '"$STAGE"/surfaceFeaturesDict "$STAGE"/fvSchemes "$STAGE"/fvSolution '
             '"$STAGE"/controlDict system/')
    L.append('cp "$STAGE"/momentumTransport "$STAGE"/physicalProperties constant/')
    L.append('cp "$STAGE"/U "$STAGE"/p "$STAGE"/k "$STAGE"/omega "$STAGE"/nut 0/')
    L.append('cp "$STAGE"/body.stl constant/triSurface/body.stl')
    L.append('echo "== blockMesh =="; blockMesh 2>&1 | tee log.blockMesh | tail -3')
    L.append('echo "== surfaceFeatures =="; surfaceFeatures 2>&1 | tail -3 || echo "skipped"')
    L.append('if [ -z "$(find constant -name \'*.eMesh\' 2>/dev/null)" ]; then '
             'echo "no eMesh -> disabling feature snapping"; '
             'foamDictionary -entry castellatedMeshControls/features -set "()" '
             'system/snappyHexMeshDict 2>/dev/null || true; fi')
    L.append('echo "== snappyHexMesh =="; snappyHexMesh -overwrite 2>&1 | '
             'tee log.snappyHexMesh | tail -4')
    L.append('echo "== checkMesh =="; checkMesh 2>&1 | tee log.checkMesh | tail -12')
    L.append('echo "== foamRun (incompressibleFluid) =="; foamRun 2>&1 | '
             'tee log.foamRun | tail -25')
    L.append('echo "== foamToVTK =="; foamToVTK%s 2>&1 | tail -3' % lt)
    L.append('OUT=%s' % cfd.shq(out))
    L.append('mkdir -p "$OUT"; rm -rf "$OUT/VTK"')
    L.append('[ -d VTK ] && cp -r VTK "$OUT/" && echo "=== results VTK copied to: %s ==="'
             % win_out)
    L.append('echo "=== FLOW DONE: $DST  (colour by U or p in ParaView) ==="')
    return "\n".join(L)


# =============================================================================
# Face-assigned (SimScale-style) boundary conditions -> OpenFOAM 0/ fields
# =============================================================================
# The interactive BC command assigns each patch a type (inlet/outlet/wall/slip/
# noslip) and a value; this turns that list into the 0/ field files so a case
# meshed with those named patches solves with exactly the user's BCs.
def bc_field_files(patches, nu=1.5e-5, intensity=0.05, L=1.0):
    """0/ fields (U, p, k, omega, nut) + transport/solver dicts whose
    boundaryField is driven by the user's face-assigned BCs.

    `patches`: list of {"name": patch, "bc": one of inlet/outlet/wall/slip/
    noslip, "value": speed(m/s) or pressure(Pa)}. Returns ({filename: text},
    k0, omega0). kOmegaSST turbulence sized from the fastest inlet."""
    speeds = [abs(float(p.get("value", 0.0)))
              for p in patches if p.get("bc") == "inlet"]
    Uref = max(speeds) if speeds else 1.0
    k0, om0 = inlet_turbulence(Uref, intensity, L)
    kin = "uniform %s" % _g(k0)
    oin = "uniform %s" % _g(om0)

    def U_entry(p):
        bc = p.get("bc"); v = _g(p.get("value", 0.0))
        if bc == "inlet":
            return ("        type            fixedValue;\n"
                    "        value           uniform (%s 0 0);" % v)
        if bc == "outlet":
            return ("        type            pressureInletOutletVelocity;\n"
                    "        value           uniform (0 0 0);")
        if bc == "slip":
            return "        type            slip;"
        if bc == "noslip":
            return ("        type            fixedValue;\n"
                    "        value           uniform (%s 0 0);" % v)
        return "        type            noSlip;"

    def p_entry(p):
        bc = p.get("bc")
        if bc == "outlet":
            return ("        type            fixedValue;\n"
                    "        value           uniform %s;" % _g(p.get("value", 0.0)))
        if bc == "slip":
            return "        type            slip;"
        return "        type            zeroGradient;"

    def k_entry(p):
        bc = p.get("bc")
        if bc == "inlet":
            return ("        type            fixedValue;\n        value           %s;" % kin)
        if bc == "outlet":
            return ("        type            inletOutlet;\n        inletValue      %s;\n"
                    "        value           %s;" % (kin, kin))
        if bc == "slip":
            return "        type            slip;"
        return "        type            kqRWallFunction;\n        value           %s;" % kin

    def omega_entry(p):
        bc = p.get("bc")
        if bc == "inlet":
            return ("        type            fixedValue;\n        value           %s;" % oin)
        if bc == "outlet":
            return ("        type            inletOutlet;\n        inletValue      %s;\n"
                    "        value           %s;" % (oin, oin))
        if bc == "slip":
            return "        type            slip;"
        return "        type            omegaWallFunction;\n        value           %s;" % oin

    def nut_entry(p):
        bc = p.get("bc")
        if bc == "slip":
            return "        type            slip;"
        if bc in ("inlet", "outlet"):
            return "        type            calculated;\n        value           uniform 0;"
        return "        type            nutkWallFunction;\n        value           uniform 0;"

    def assemble(cls, obj, dims, internal, entry):
        body = ""
        for p in patches:
            body += "    %s\n    {\n%s\n    }\n" % (p.get("name", "patch"), entry(p))
        return (_foam_header(cls, obj)
                + "dimensions      %s;\n\ninternalField   %s;\n\n"
                  "boundaryField\n{\n%s}\n" % (dims, internal, body))

    files = {
        "U": assemble("volVectorField", "U", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)", U_entry),
        "p": assemble("volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0", p_entry),
        "k": assemble("volScalarField", "k", "[0 2 -2 0 0 0 0]", kin, k_entry),
        "omega": assemble("volScalarField", "omega", "[0 0 -1 0 0 0 0]", oin, omega_entry),
        "nut": assemble("volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0", nut_entry),
        "momentumTransport": momentum_transport_dict("kOmegaSST"),
        "physicalProperties": physical_properties_dict(nu),
        "fvSchemes": fv_schemes_simple(),
        "fvSolution": fv_solution_simple(),
        "controlDict": control_dict_simple("incompressibleFluid", 1000, 200),
    }
    return files, k0, om0


# ---- internal flow through a box solid: blockMesh with user-named patches ----
# The 6 geometric faces of the body's bounding box, as blockMesh face quads.
_BOX_FACE_QUADS = {
    "xmin": "(0 4 7 3)", "xmax": "(2 6 5 1)",
    "ymin": "(1 5 4 0)", "ymax": "(3 7 6 2)",
    "zmin": "(0 3 2 1)", "zmax": "(4 5 6 7)",
}
# Order the 6 box faces so a Part.makeBox-style face list (Xmin,Xmax,Ymin,Ymax,
# Zmin,Zmax) maps 1:1 onto them.
BOX_FACE_ORDER = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")


def box_blockmesh_named(x0, y0, z0, x1, y1, z1, nx, ny, nz, face_patches):
    """A single-block hex mesh of the box interior where each of the 6 box faces
    is given a named patch from `face_patches` ({face_key: (patch_name, type)}).
    Faces that share a patch_name are merged into one patch, so assigning inlet
    to one face, outlet to the opposite and wall to the rest yields exactly those
    three patches - the fluid domain is the box interior (internal flow)."""
    V = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    verts = "\n".join("    " + _pt(*v) for v in V)
    head = (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - generated blockMeshDict (internal flow, named patches)        |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      blockMeshDict;\n}\n\n"
        "scale   1;\n\n"
        "vertices\n(\n%s\n);\n\n"
        "blocks\n(\n    hex (0 1 2 3 4 5 6 7) (%d %d %d) simpleGrading (1 1 1)\n);\n\n"
        "edges\n(\n);\n\n" % (verts, nx, ny, nz))
    # group face quads by patch name (preserving first-seen order + type)
    order = []
    groups = {}
    for fk in BOX_FACE_ORDER:
        name, ptype = face_patches.get(fk, ("walls", "wall"))
        if name not in groups:
            groups[name] = [ptype, []]
            order.append(name)
        groups[name][1].append(_BOX_FACE_QUADS[fk])
    boundary = "boundary\n(\n"
    for name in order:
        ptype, quads = groups[name]
        boundary += ("    %s\n    {\n        type %s;\n        faces ( %s );\n    }\n"
                     % (name, ptype, " ".join(quads)))
    boundary += ");\n\nmergePatchPairs\n(\n);\n"
    return head + boundary


def build_internal_flow_script(opts):
    """Bash for an internal-flow case meshed by blockMesh with user-named patches
    (no snappy): assemble the staged case, blockMesh -> checkMesh -> foamRun
    (incompressibleFluid) -> VTK. opts: of_env, name, stage_win, win_out, latest."""
    import dynframe_cfd as cfd
    of_env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    name = opts.get("name", "flowint1")
    stage = cfd.win_to_wsl(opts["stage_win"])
    win_out = opts["win_out"]
    out = cfd.win_to_wsl(win_out)
    lt = " -latestTime" if opts.get("latest", True) else ""
    work = cfd.WORK_ROOT

    L = []
    L.append("# DynFrame CFD - internal-flow case (blockMesh named patches + solve)")
    L.append(". %s" % of_env)
    L.append('STAGE=%s' % cfd.shq(stage))
    L.append('mkdir -p %s' % work)
    L.append('DST=%s/%s' % (work, name))
    L.append('rm -rf "$DST"; mkdir -p "$DST/0" "$DST/constant" "$DST/system"')
    L.append('cd "$DST" || exit 1')
    L.append('cp "$STAGE"/blockMeshDict "$STAGE"/fvSchemes "$STAGE"/fvSolution '
             '"$STAGE"/controlDict system/')
    L.append('cp "$STAGE"/momentumTransport "$STAGE"/physicalProperties constant/')
    L.append('cp "$STAGE"/U "$STAGE"/p "$STAGE"/k "$STAGE"/omega "$STAGE"/nut 0/')
    L.append('echo "== blockMesh =="; blockMesh 2>&1 | tee log.blockMesh | tail -3')
    L.append('echo "== checkMesh =="; checkMesh 2>&1 | tee log.checkMesh | tail -12')
    L.append('echo "== foamRun (incompressibleFluid) =="; foamRun 2>&1 | '
             'tee log.foamRun | tail -25')
    L.append('echo "== foamToVTK =="; foamToVTK%s 2>&1 | tail -3' % lt)
    L.append('OUT=%s' % cfd.shq(out))
    L.append('mkdir -p "$OUT"; rm -rf "$OUT/VTK"')
    L.append('[ -d VTK ] && cp -r VTK "$OUT/" && echo "=== results VTK copied to: %s ==="'
             % win_out)
    L.append('echo "=== INTERNAL FLOW DONE: $DST  (colour by U or p) ==="')
    return "\n".join(L)
