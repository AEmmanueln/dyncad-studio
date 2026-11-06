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
    if str(model).strip().lower() == "laminar":
        return _foam_header("dictionary", "momentumTransport") + \
            "simulationType  laminar;\n"
    return _foam_header("dictionary", "momentumTransport") + (
        "simulationType  RAS;\n\nRAS\n{\n    model           %s;\n"
        "    turbulence      on;\n    printCoeffs     on;\n}\n" % model)


def physical_properties_dict(nu=1.5e-5):
    return _foam_header("dictionary", "physicalProperties") + (
        "viscosityModel  constant;\n\nnu              [0 2 -1 0 0 0 0] %s;\n" % _g(nu))


def fv_schemes_simple(second_order=False, heat=False):
    """Steady-state finite-volume schemes. second_order=True raises the turbulence
    transport to limitedLinear (2nd-order, more accurate); the momentum equation
    is linearUpwind (2nd-order) either way. heat=True adds the temperature scheme."""
    kdiv = ("bounded Gauss limitedLinear 1" if second_order
            else "bounded Gauss upwind")
    tdiv = "    div(phi,T)      bounded Gauss linearUpwind grad(T);\n" if heat else ""
    return _foam_header("dictionary", "fvSchemes") + (
        "ddtSchemes\n{\n    default         steadyState;\n}\n\n"
        "gradSchemes\n{\n    default         Gauss linear;\n"
        "    grad(U)         cellLimited Gauss linear 1;\n}\n\n"
        "divSchemes\n{\n    default         none;\n"
        "    div(phi,U)      bounded Gauss linearUpwind grad(U);\n"
        "    div(phi,k)      %s;\n"
        "    div(phi,omega)  %s;\n"
        "%s"
        "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n}\n\n"
        "laplacianSchemes\n{\n    default         Gauss linear corrected;\n}\n\n"
        "interpolationSchemes\n{\n    default         linear;\n}\n\n"
        "snGradSchemes\n{\n    default         corrected;\n}\n\n"
        "wallDist\n{\n    method          meshWave;\n}\n" % (kdiv, kdiv, tdiv))


def fv_solution_simple(heat=False):
    tsolver = ("    T\n    {\n        solver          PBiCGStab;\n"
               "        preconditioner  DILU;\n        tolerance       1e-7;\n"
               "        relTol          0.1;\n    }\n\n") if heat else ""
    return _foam_header("dictionary", "fvSolution") + (
        "solvers\n{\n"
        "    p\n    {\n        solver          GAMG;\n        tolerance       1e-7;\n"
        "        relTol          0.01;\n        smoother        GaussSeidel;\n    }\n\n"
        "    \"(U|k|omega)\"\n    {\n        solver          smoothSolver;\n"
        "        smoother        symGaussSeidel;\n        tolerance       1e-8;\n"
        "        relTol          0.1;\n    }\n\n"
        "%s}\n\n"
        "SIMPLE\n{\n    nNonOrthogonalCorrectors 0;\n    consistent      yes;\n"
        "    pRefCell        0;\n    pRefValue       0;\n"
        "    residualControl\n    {\n        p               1e-4;\n"
        "        U               1e-4;\n        \"(k|omega)\"     1e-4;\n    }\n}\n\n"
        "relaxationFactors\n{\n    equations\n    {\n        U               0.9;\n"
        "        \".*\"            0.9;\n    }\n}\n" % tsolver)


def control_dict_simple(solver="incompressibleFluid", end_iter=1000,
                        write_interval=200, deltaT=1, functions=""):
    fblock = ("\nfunctions\n{\n%s}\n" % functions) if functions else ""
    return _foam_header("dictionary", "controlDict") + (
        "solver          %s;\n\n"
        "startFrom       startTime;\nstartTime       0;\n"
        "stopAt          endTime;\nendTime         %d;\n"
        "deltaT          %s;\n\n"
        "writeControl    timeStep;\nwriteInterval   %d;\n\n"
        "purgeWrite      0;\nwriteFormat     ascii;\nwritePrecision  7;\n"
        "writeCompression off;\ntimeFormat      general;\ntimePrecision   6;\n"
        "runTimeModifiable true;\n%s"
        % (solver, int(end_iter), _g(deltaT), int(write_interval), fblock))


def scalar_transport_functions(D):
    """controlDict 'functions' entry that solves a temperature field T carried by
    the flow (forced-convection heat transfer), with thermal diffusivity D."""
    return "    #includeFunc scalarTransport(T, diffusivity=constant, D=%s)\n" % _g(D)


def temperature_field(patches, T_in=300.0, T_wall=350.0, heated=True):
    """0/T for forced-convection heat transfer: inlets fix the inflow temperature,
    outlets let it advect out, walls are heated (fixedValue T_wall) or adiabatic
    (zeroGradient). `patches`: the same list of {name, bc} used for the flow."""
    tin = "uniform %s" % _g(T_in)

    def entry(p):
        bc = p.get("bc")
        if bc in ("velocity_inlet", "pressure_inlet"):
            return ("        type            fixedValue;\n"
                    "        value           uniform %s;" % _g(T_in))
        if bc in ("velocity_outlet", "pressure_outlet"):
            return ("        type            inletOutlet;\n"
                    "        inletValue      uniform %s;\n"
                    "        value           uniform %s;" % (_g(T_in), _g(T_in)))
        if bc == "symmetry":
            return "        type            symmetry;"
        if bc == "slip":
            return "        type            zeroGradient;"
        if heated:
            return ("        type            fixedValue;\n"
                    "        value           uniform %s;" % _g(T_wall))
        return "        type            zeroGradient;"

    body = "".join("    %s\n    {\n%s\n    }\n" % (p.get("name", "patch"), entry(p))
                   for p in patches)
    return (_foam_header("volScalarField", "T")
            + "dimensions      [0 0 0 1 0 0 0];\n\ninternalField   %s;\n\n"
              "boundaryField\n{\n%s}\n" % (tin, body))


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
    L.append('[ -f "$STAGE"/T ] && cp "$STAGE"/T 0/ || true')
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
    _INLETS = ("velocity_inlet", "pressure_inlet")
    _OUTLETS = ("velocity_outlet", "pressure_outlet")
    speeds = [abs(float(p.get("value", 0.0)))
              for p in patches if p.get("bc") == "velocity_inlet"]
    Uref = max(speeds) if speeds else 1.0
    k0, om0 = inlet_turbulence(Uref, intensity, L)
    kin = "uniform %s" % _g(k0)
    oin = "uniform %s" % _g(om0)

    def U_entry(p):
        bc = p.get("bc"); vv = float(p.get("value", 0.0)); v = _g(vv)
        if bc in ("velocity_inlet", "velocity_outlet"):
            d = p.get("dir")
            if d:
                vec = "(%s %s %s)" % (_g(vv * d[0]), _g(vv * d[1]), _g(vv * d[2]))
            else:
                vec = "(%s 0 0)" % v
            return ("        type            fixedValue;\n"
                    "        value           uniform %s;" % vec)
        if bc == "moving_wall":
            return ("        type            fixedValue;\n"
                    "        value           uniform (%s 0 0);" % v)
        if bc == "pressure_inlet":
            return ("        type            pressureInletVelocity;\n"
                    "        value           uniform (0 0 0);")
        if bc == "pressure_outlet":
            return ("        type            pressureInletOutletVelocity;\n"
                    "        value           uniform (0 0 0);")
        if bc == "slip":
            return "        type            slip;"
        if bc == "symmetry":
            return "        type            symmetry;"
        return "        type            noSlip;"

    def p_entry(p):
        bc = p.get("bc")
        if bc in ("pressure_inlet", "pressure_outlet"):
            return ("        type            fixedValue;\n"
                    "        value           uniform %s;" % _g(p.get("value", 0.0)))
        if bc == "slip":
            return "        type            slip;"
        if bc == "symmetry":
            return "        type            symmetry;"
        return "        type            zeroGradient;"

    def k_entry(p):
        bc = p.get("bc")
        if bc in _INLETS:
            return "        type            fixedValue;\n        value           %s;" % kin
        if bc in _OUTLETS:
            return ("        type            inletOutlet;\n        inletValue      %s;\n"
                    "        value           %s;" % (kin, kin))
        if bc == "slip":
            return "        type            slip;"
        if bc == "symmetry":
            return "        type            symmetry;"
        return "        type            kqRWallFunction;\n        value           %s;" % kin

    def omega_entry(p):
        bc = p.get("bc")
        if bc in _INLETS:
            return "        type            fixedValue;\n        value           %s;" % oin
        if bc in _OUTLETS:
            return ("        type            inletOutlet;\n        inletValue      %s;\n"
                    "        value           %s;" % (oin, oin))
        if bc == "slip":
            return "        type            slip;"
        if bc == "symmetry":
            return "        type            symmetry;"
        return "        type            omegaWallFunction;\n        value           %s;" % oin

    def nut_entry(p):
        bc = p.get("bc")
        if bc == "slip":
            return "        type            slip;"
        if bc == "symmetry":
            return "        type            symmetry;"
        if bc in _INLETS or bc in _OUTLETS:
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
    L.append('[ -f "$STAGE"/T ] && cp "$STAGE"/T 0/ || true')
    L.append('echo "== blockMesh =="; blockMesh 2>&1 | tee log.blockMesh | tail -3')
    L.append('echo "== checkMesh =="; checkMesh 2>&1 | tee log.checkMesh | tail -12')
    L.append('echo "== foamRun (incompressibleFluid) =="; foamRun 2>&1 | '
             'tee log.foamRun | tail -25')
    L.append('echo "== foamToVTK =="; foamToVTK%s 2>&1 | tail -3' % lt)
    L.append('OUT=%s' % cfd.shq(out))
    L.append('mkdir -p "$OUT"; rm -rf "$OUT/VTK"')
    L.append('[ -d VTK ] && cp -r VTK "$OUT/" && echo "=== results VTK copied to: %s ==="'
             % win_out)
    L.append(mpl_render_block(name))
    L.append('echo "=== INTERNAL FLOW DONE: $DST  (colour by U or p) ==="')
    return "\n".join(L)


# =============================================================================
# Arbitrary solid: snappyHexMesh with a named patch per BC face-group
# =============================================================================
# For a non-box CAD part, each boundary-condition face group is exported as its
# own STL; snappyHexMesh snaps the background mesh to the surfaces and names one
# patch per STL, with boundary layers on the walls for near-wall accuracy.
def background_box_dict(x0, y0, z0, x1, y1, z1, nx, ny, nz, patch="outer"):
    """A plain background hex box with a single outer patch; snappyHexMesh snaps
    the real geometry inside it and discards the cells outside the fluid region."""
    V = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    verts = "\n".join("    " + _pt(*v) for v in V)
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - background blockMeshDict for snappyHexMesh                    |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      blockMeshDict;\n}\n\n"
        "scale   1;\n\n"
        "vertices\n(\n%s\n);\n\n"
        "blocks\n(\n    hex (0 1 2 3 4 5 6 7) (%d %d %d) simpleGrading (1 1 1)\n);\n\n"
        "edges\n(\n);\n\n"
        "boundary\n(\n    %s\n    {\n        type patch;\n        faces\n        (\n"
        "            (0 4 7 3) (2 6 5 1) (1 5 4 0) (3 7 6 2) (0 3 2 1) (4 5 6 7)\n"
        "        );\n    }\n);\n\nmergePatchPairs\n(\n);\n"
        % (verts, nx, ny, nz, patch))


def surface_features_multi(names, angle=150.0):
    """surfaceFeaturesDict extracting sharp edges from every patch STL, so snappy
    can snap to the part's real edges (accuracy on corners)."""
    surfs = " ".join("\"%s.stl\"" % n for n in names)
    return (
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      surfaceFeaturesDict;\n}\n\n"
        "surfaces ( %s );\n\nincludedAngle   %s;\n" % (surfs, _g(angle)))


def snappy_multipatch_dict(patches, location, level_min=1, level_max=2,
                           n_layers=3, expansion=1.2, final_layer=0.4,
                           resolve_angle=45.0):
    """snappyHexMesh for an arbitrary solid given as one STL per BC patch.

    `patches`: list of {"name": patch, "type": patch|wall|symmetry}. Each becomes
    a named patch; boundary layers are grown on the wall patches. `location` is a
    point inside the fluid region to keep. Returns the dictionary text."""
    lx, ly, lz = location
    geom = "".join(
        "    %s\n    {\n        type triSurfaceMesh;\n        file \"%s.stl\";\n    }\n"
        % (p["name"], p["name"]) for p in patches)
    feats = "".join(
        "        { file \"%s.eMesh\"; level %d; }\n" % (p["name"], level_max)
        for p in patches)
    refs = "".join(
        "        %s\n        {\n            level (%d %d);\n"
        "            patchInfo { type %s; }\n        }\n"
        % (p["name"], level_min, level_max, p.get("type", "wall"))
        for p in patches)
    walls = [p["name"] for p in patches if p.get("type", "wall") == "wall"]
    layer_block = "".join(
        "        \"%s\"\n        {\n            nSurfaceLayers %d;\n        }\n"
        % (w, n_layers) for w in walls)
    add_layers = "true" if (n_layers > 0 and walls) else "false"
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| DynFrame CFD - snappyHexMeshDict (arbitrary solid, named patches)           |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n{\n    format      ascii;\n    class       dictionary;\n"
        "    object      snappyHexMeshDict;\n}\n\n"
        "castellatedMesh true;\nsnap            true;\naddLayers       %s;\n\n"
        "geometry\n{\n%s}\n\n"
        "castellatedMeshControls\n{\n"
        "    maxLocalCells 2000000;\n    maxGlobalCells 10000000;\n"
        "    minRefinementCells 10;\n    maxLoadUnbalance 0.10;\n"
        "    nCellsBetweenLevels 3;\n\n"
        "    features\n    (\n%s    );\n\n"
        "    refinementSurfaces\n    {\n%s    }\n\n"
        "    resolveFeatureAngle %s;\n\n    refinementRegions\n    {\n    }\n\n"
        "    locationInMesh (%s %s %s);\n    allowFreeStandingZoneFaces true;\n}\n\n"
        "snapControls\n{\n    nSmoothPatch 3;\n    tolerance 2.0;\n    nSolveIter 30;\n"
        "    nRelaxIter 5;\n    nFeatureSnapIter 10;\n    implicitFeatureSnap false;\n"
        "    explicitFeatureSnap true;\n    multiRegionFeatureSnap false;\n}\n\n"
        "addLayersControls\n{\n    relativeSizes true;\n    layers\n    {\n%s    }\n"
        "    expansionRatio %s;\n    finalLayerThickness %s;\n    minThickness 0.1;\n"
        "    nGrow 0;\n    featureAngle 60;\n    nRelaxIter 5;\n"
        "    nSmoothSurfaceNormals 1;\n    nSmoothNormals 3;\n    nSmoothThickness 10;\n"
        "    maxFaceThicknessRatio 0.5;\n    maxThicknessToMedialRatio 0.3;\n"
        "    minMedialAxisAngle 90;\n    nBufferCellsNoExtrude 0;\n    nLayerIter 50;\n}\n\n"
        "meshQualityControls\n{\n    maxNonOrtho 65;\n    maxBoundarySkewness 20;\n"
        "    maxInternalSkewness 4;\n    maxConcave 80;\n    minVol 1e-13;\n"
        "    minTetQuality 1e-15;\n    minArea -1;\n    minTwist 0.02;\n"
        "    minDeterminant 0.001;\n    minFaceWeight 0.02;\n    minVolRatio 0.01;\n"
        "    minTriangleTwist -1;\n    nSmoothScale 4;\n    errorReduction 0.75;\n}\n\n"
        "mergeTolerance 1e-6;\n"
        % (add_layers, geom, feats, refs, _g(resolve_angle),
           _g(lx), _g(ly), _g(lz), layer_block, _g(expansion), _g(final_layer)))


def build_snappy_flow_script(opts):
    """Internal flow through an ARBITRARY solid: one STL per BC patch ->
    snappyHexMesh named patches (+ boundary layers) -> solve. opts: of_env, name,
    stage_win (holds <patch>.stl, blockMeshDict, snappyHexMeshDict,
    surfaceFeaturesDict, the 0/ fields and constant/system dicts), win_out,
    patch_names (list), latest."""
    import dynframe_cfd as cfd
    of_env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    name = opts.get("name", "flowsnap1")
    stage = cfd.win_to_wsl(opts["stage_win"])
    win_out = opts["win_out"]
    out = cfd.win_to_wsl(win_out)
    lt = " -latestTime" if opts.get("latest", True) else ""
    work = cfd.WORK_ROOT
    names = opts.get("patch_names", [])

    L = []
    L.append("# DynFrame CFD - arbitrary-solid internal flow (snappyHexMesh + solve)")
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
    L.append('[ -f "$STAGE"/T ] && cp "$STAGE"/T 0/ || true')
    for nm in names:
        L.append('cp "$STAGE"/%s.stl constant/triSurface/%s.stl' % (nm, nm))
    L.append('echo "== blockMesh =="; blockMesh 2>&1 | tee log.blockMesh | tail -3')
    L.append('echo "== surfaceFeatures =="; surfaceFeatures 2>&1 | tail -3 || echo skipped')
    L.append('if [ -z "$(find constant -name \'*.eMesh\' 2>/dev/null)" ]; then '
             'foamDictionary -entry castellatedMeshControls/features -set "()" '
             'system/snappyHexMeshDict 2>/dev/null || true; fi')
    L.append('echo "== snappyHexMesh =="; snappyHexMesh -overwrite 2>&1 | '
             'tee log.snappyHexMesh | tail -5')
    L.append('echo "== checkMesh =="; checkMesh 2>&1 | tee log.checkMesh | tail -12')
    L.append('echo "== foamRun (incompressibleFluid) =="; foamRun 2>&1 | '
             'tee log.foamRun | tail -25')
    L.append('echo "== foamToVTK =="; foamToVTK%s 2>&1 | tail -3' % lt)
    L.append('OUT=%s' % cfd.shq(out))
    L.append('mkdir -p "$OUT"; rm -rf "$OUT/VTK"')
    L.append('[ -d VTK ] && cp -r VTK "$OUT/" && echo "=== results VTK copied to: %s ==="'
             % win_out)
    L.append(mpl_render_block(name))
    L.append('echo "=== SNAPPY FLOW DONE: $DST  (colour by U or p) ==="')
    return "\n".join(L)


def build_mesh_check_script(opts):
    """Mesh only (no solve) + checkMesh, to preview mesh QUALITY before running.
    blockMesh, then surfaceFeatures + snappyHexMesh if a snappyHexMeshDict is
    staged, then checkMesh -allGeometry, and mesh -> VTK for inspection. opts:
    of_env, name, stage_win, win_out, patch_names (optional STLs)."""
    import dynframe_cfd as cfd
    of_env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    name = opts.get("name", "mesh1")
    stage = cfd.win_to_wsl(opts["stage_win"])
    win_out = opts["win_out"]
    out = cfd.win_to_wsl(win_out)
    work = cfd.WORK_ROOT
    names = opts.get("patch_names", [])

    L = []
    L.append("# DynFrame CFD - mesh-only + checkMesh (quality preview)")
    L.append(". %s" % of_env)
    L.append('STAGE=%s' % cfd.shq(stage))
    L.append('mkdir -p %s' % work)
    L.append('DST=%s/%s' % (work, name))
    L.append('rm -rf "$DST"; mkdir -p "$DST/constant/triSurface" "$DST/system"')
    L.append('cd "$DST" || exit 1')
    L.append('cp "$STAGE"/blockMeshDict "$STAGE"/controlDict "$STAGE"/fvSchemes '
             '"$STAGE"/fvSolution system/')
    L.append('[ -f "$STAGE"/snappyHexMeshDict ] && cp "$STAGE"/snappyHexMeshDict system/ || true')
    L.append('[ -f "$STAGE"/surfaceFeaturesDict ] && cp "$STAGE"/surfaceFeaturesDict system/ || true')
    for nm in names:
        L.append('[ -f "$STAGE"/%s.stl ] && cp "$STAGE"/%s.stl constant/triSurface/ || true'
                 % (nm, nm))
    L.append('echo "== blockMesh =="; blockMesh 2>&1 | tee log.blockMesh | tail -3')
    L.append('if [ -f system/snappyHexMeshDict ]; then')
    L.append('  echo "== surfaceFeatures =="; surfaceFeatures 2>&1 | tail -3 || echo skipped')
    L.append('  if [ -z "$(find constant -name \'*.eMesh\' 2>/dev/null)" ]; then '
             'foamDictionary -entry castellatedMeshControls/features -set "()" '
             'system/snappyHexMeshDict 2>/dev/null || true; fi')
    L.append('  echo "== snappyHexMesh =="; snappyHexMesh -overwrite 2>&1 | '
             'tee log.snappyHexMesh | tail -6')
    L.append('fi')
    L.append('echo "== checkMesh =="; checkMesh 2>&1 | tee log.checkMesh | tail -25')
    L.append('foamToVTK -constant 2>&1 | tail -2 || foamToVTK 2>&1 | tail -2')
    L.append('OUT=%s' % cfd.shq(out))
    L.append('mkdir -p "$OUT"; rm -rf "$OUT/VTK"')
    L.append('[ -d VTK ] && cp -r VTK "$OUT/" && echo "=== mesh VTK copied to: %s ==="'
             % win_out)
    L.append('echo "=== MESH DONE: $DST ==="')
    return "\n".join(L)


# ---- result visualisation: read the VTK and plot with matplotlib ----
# Reliable everywhere: no OpenGL, no MPI, no display server (so it works where
# WSLg GUI windows / ParaView do not). Reads the foamToVTK output with the vtk
# Python module (data only, no rendering) and draws a filled field with
# matplotlib's Agg backend. The result PNGs are opened in the Windows viewer.
_MPL_RENDER_PY = r'''
import sys, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import vtk
from vtk.util import numpy_support as ns

vtkfile, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
reader = vtk.vtkUnstructuredGridReader()
reader.SetFileName(vtkfile)
reader.ReadAllScalarsOn(); reader.ReadAllVectorsOn()
reader.Update()
grid = reader.GetOutput()
b = grid.GetBounds()
ext = [b[1] - b[0], b[3] - b[2], b[5] - b[4]]
thin = int(np.argmin(ext)); ax = [i for i in range(3) if i != thin]
labels = ["x", "y", "z"]
cc = vtk.vtkCellCenters(); cc.SetInputData(grid); cc.Update()
C = ns.vtk_to_numpy(cc.GetOutput().GetPoints().GetData())
P = ns.vtk_to_numpy(grid.GetPoints().GetData())

def plot(name, fn, title):
    cd = grid.GetCellData(); pd = grid.GetPointData()
    a = cd.GetArray(name); src = "cell"
    if a is None:
        a = pd.GetArray(name); src = "point"
    if a is None:
        print("NOFIELD " + name); return
    data = ns.vtk_to_numpy(a)
    val = np.linalg.norm(data, axis=1) if data.ndim > 1 else data
    xy = C if src == "cell" else P
    x = xy[:, ax[0]]; y = xy[:, ax[1]]
    fig, g = plt.subplots(figsize=(10, 6.5))
    try:
        m = g.tricontourf(x, y, val, levels=40, cmap="turbo")
    except Exception:
        m = g.scatter(x, y, c=val, s=6, cmap="turbo")
    g.set_aspect("equal"); g.set_title(title)
    g.set_xlabel(labels[ax[0]] + " (m)"); g.set_ylabel(labels[ax[1]] + " (m)")
    fig.colorbar(m, ax=g, shrink=0.85)
    fig.savefig(os.path.join(out, fn), dpi=110, bbox_inches="tight")
    plt.close(fig)
    print("PLOT %s range=%.4g..%.4g" % (fn, float(val.min()), float(val.max())))

plot("U", "U.png", "Velocity magnitude |U| (m/s)")
plot("p", "p.png", "Pressure p (m2/s2)")
print("MPL_DONE")
'''


def mpl_render_block(name):
    """Bash (run inside the case dir, with $OUT set to the Windows-side /mnt path
    or empty) that renders the solved result to PNGs with matplotlib and opens the
    velocity image in the Windows default viewer. Reliable where WSLg/ParaView
    windows do not show."""
    L = []
    L.append('VTKMAIN=$(find VTK -maxdepth 1 -name "*.vtk" 2>/dev/null | head -1)')
    L.append('if [ -n "$VTKMAIN" ]; then')
    L.append("  cat > .dynframe_mpl.py <<'DYNFRAMEMPLEOF'")
    L.append(_MPL_RENDER_PY.strip("\n"))
    L.append("DYNFRAMEMPLEOF")
    L.append('  mkdir -p images')
    L.append('  python3 .dynframe_mpl.py "$VTKMAIN" images >> log.dynframe 2>&1 || true')
    L.append('  if [ -n "${OUT:-}" ] && [ -f images/U.png ]; then')
    L.append('    mkdir -p "$OUT/images"; cp -f images/*.png "$OUT/images/" 2>/dev/null || true')
    L.append('    WIN=$(wslpath -w "$OUT/images/U.png" 2>/dev/null)')
    L.append('    [ -n "$WIN" ] && /mnt/c/Windows/System32/cmd.exe /c start "" "$WIN" >/dev/null 2>&1 || true')
    L.append('  fi')
    L.append('fi')
    return "\n".join(L)


# ---- OpenFOAM tutorial / example gallery (run any case, tweak parameters) ----
def tutorials_find_script(of_env=None):
    """Bash that lists every runnable OpenFOAM tutorial as 'category|relpath|abspath'
    (one per case with a system/controlDict). Parsed by the Examples browser."""
    import dynframe_cfd as cfd
    env = of_env or cfd.DEFAULT_OF_ENV
    return (". %s >/dev/null 2>&1\n" % env
            + 'T="${FOAM_TUTORIALS:-$WM_PROJECT_DIR/tutorials}"\n'
            + '[ -d "$T" ] || { echo "NO_TUTORIALS"; exit 0; }\n'
            + 'find "$T" -type f -name controlDict -path "*/system/*" 2>/dev/null '
              '| while read f; do\n'
            + '  c="${f%/system/controlDict}"\n'
            + '  rel="${c#$T/}"\n'
            + '  cat="${rel%%/*}"\n'
            + '  printf "%s|%s|%s\\n" "$cat" "$rel" "$c"\n'
            + 'done | sort\n')


def build_tutorial_run_script(opts):
    """Background pipeline to run one OpenFOAM tutorial and show it in ParaView:
    clone the case, apply the user's time controls, run it (its own Allrun or the
    standard foamRunTutorials sequence), convert to VTK, copy the results to
    Windows, and open ParaView through WSLg. Detached, so FreeCAD never blocks.
    opts: of_env, src (WSL abs path), name (safe case name), win_out (Windows
    path), end_time, write_interval, delta_t (each blank/None = keep as shipped)."""
    import dynframe_cfd as cfd
    env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    src = opts["src"]; name = opts["name"]; work = cfd.WORK_ROOT
    win_out = opts.get("win_out", "")
    foam = '"$DST/%s.foam"' % name     # $DST is tilde-expanded at assignment
    L = []
    L.append(". %s >/dev/null 2>&1" % env)
    L.append("SRC=%s" % cfd.shq(src))
    L.append("mkdir -p %s" % work)
    L.append("DST=%s/%s" % (work, name))
    L.append('rm -rf "$DST"')
    L.append('cp -r "$SRC" "$DST" || exit 1')
    L.append('cd "$DST" || exit 1')
    L.append('rm -f ./*.foam 2>/dev/null || true')
    # apply the user's time-control overrides when given
    for entry, val in (("endTime", opts.get("end_time")),
                       ("writeInterval", opts.get("write_interval")),
                       ("deltaT", opts.get("delta_t"))):
        v = ("" if val is None else str(val)).strip()
        if v != "":
            L.append('foamDictionary system/controlDict -entry %s -set %s '
                     '>/dev/null 2>&1 || true' % (entry, cfd.shq(v)))
    # Run the case (its own Allrun, else the standard tutorial sequence), convert
    # to VTK, render the result to PNGs with matplotlib and open the velocity image
    # in the Windows viewer. The whole script runs detached (Popen), so FreeCAD
    # never blocks; the image appears when the solve finishes.
    L.append('OUT=%s' % (cfd.shq(win_out) if win_out else '""'))
    L.append('echo "== DynFrame: running $DST ==" > log.dynframe')
    L.append('if [ -f ./Allrun ]; then chmod +x ./Allrun >/dev/null 2>&1 || true; '
             './Allrun >> log.dynframe 2>&1; else foamRunTutorials >> log.dynframe 2>&1; fi')
    L.append('foamToVTK -latestTime >> log.dynframe 2>&1 || '
             'foamToVTK >> log.dynframe 2>&1 || true')
    L.append('if [ -n "$OUT" ]; then mkdir -p "$OUT"; rm -rf "$OUT/VTK"; '
             '[ -d VTK ] && cp -r VTK "$OUT/" 2>/dev/null || true; fi')
    L.append(mpl_render_block(name))
    L.append('echo "== DynFrame: DONE ==" >> log.dynframe')
    return "\n".join(L)


def build_example_run_script(opts):
    """Run a curated example case: stage the generated files, blockMesh, solve on
    OpenFOAM (incompressibleFluid), convert to VTK and open ParaView through WSLg.
    The curated cases are small and fast, so ParaView opens when the solve
    finishes and the result is ready. opts: of_env, name, stage_win, win_out."""
    import dynframe_cfd as cfd
    env = opts.get("of_env", cfd.DEFAULT_OF_ENV)
    name = opts["name"]; work = cfd.WORK_ROOT
    stage = cfd.win_to_wsl(opts["stage_win"])
    win_out = opts.get("win_out", "")
    if win_out:
        win_out = cfd.win_to_wsl(win_out)
    foam = '"$DST/%s.foam"' % name
    L = []
    L.append(". %s >/dev/null 2>&1" % env)
    L.append("STAGE=%s" % cfd.shq(stage))
    L.append("mkdir -p %s" % work)
    L.append("DST=%s/%s" % (work, name))
    L.append('rm -rf "$DST"; mkdir -p "$DST/0" "$DST/constant" "$DST/system"')
    L.append('cd "$DST" || exit 1')
    L.append('cp "$STAGE"/blockMeshDict "$STAGE"/fvSchemes "$STAGE"/fvSolution '
             '"$STAGE"/controlDict system/')
    L.append('cp "$STAGE"/momentumTransport "$STAGE"/physicalProperties constant/')
    L.append('cp "$STAGE"/U "$STAGE"/p "$STAGE"/k "$STAGE"/omega "$STAGE"/nut 0/')
    L.append('OUT=%s' % (cfd.shq(win_out) if win_out else '""'))
    L.append('( echo "== blockMesh =="; blockMesh; echo "== checkMesh =="; '
             'checkMesh | tail -12; echo "== foamRun =="; foamRun; '
             'echo "== foamToVTK =="; foamToVTK -latestTime; echo "== solved ==" ) '
             '> log.dynframe 2>&1')
    L.append('if [ -n "$OUT" ]; then mkdir -p "$OUT"; rm -rf "$OUT/VTK"; '
             '[ -d VTK ] && cp -r VTK "$OUT/" 2>/dev/null || true; fi')
    L.append(mpl_render_block(name))
    L.append('echo "== DynFrame: DONE ==" >> log.dynframe')
    return "\n".join(L)
