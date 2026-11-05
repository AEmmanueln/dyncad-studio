# -*- coding: utf-8 -*-
"""DynFrame CFD - SimScale-style simulation tree model (pure, testable).

SimScale's defining element is a *simulation tree*: a study (one of the OpenFOAM
physics modules) with an ordered set of setup steps - Geometry, Materials,
Boundary conditions, Numerics, Simulation control, Mesh, Run - each with a status
(green = set, red = needs input). DynFrame mirrors this as a tree of FreeCAD
document objects in the Model panel; this module is the pure data model behind
it (no FreeCAD imports), so the study list and step structure are unit-tested.

The FreeCAD command layer (dynframe_commands.py) turns `study_steps()` into
document-object groups and attaches the per-node setup panels.
"""

try:
    import dynframe_cfd as _cfd
except Exception:                      # keep importable without the driver
    _cfd = None


# Status a step starts at (mirrors SimScale's green/red dots): "done" = sensible
# defaults already satisfy it; "todo" = needs the user's input before running.
STATUS_DONE = "done"
STATUS_TODO = "todo"

# The ordered setup steps of a CFD study, SimScale-style. `panel` names the
# setup panel the node opens (wired in the command layer); None = not yet built.
_BASE_STEPS = (
    {"key": "geometry",  "label": "Geometry",           "status": STATUS_TODO, "panel": "geometry"},
    {"key": "materials", "label": "Materials",          "status": STATUS_TODO, "panel": "materials"},
    {"key": "bcs",       "label": "Boundary conditions", "status": STATUS_TODO, "panel": "bcs"},
    {"key": "numerics",  "label": "Numerics",           "status": STATUS_DONE, "panel": "numerics"},
    {"key": "control",   "label": "Simulation control",  "status": STATUS_DONE, "panel": "control"},
    {"key": "mesh",      "label": "Mesh",               "status": STATUS_TODO, "panel": "mesh"},
    {"key": "run",       "label": "Run",                "status": STATUS_TODO, "panel": "run"},
)


def study_types():
    """The selectable studies = the OpenFOAM module catalog (all capabilities),
    as a list of {id, title, use, multiRegion}. Empty if the driver is absent."""
    if _cfd is None or not getattr(_cfd, "CATALOG", None):
        return []
    out = []
    for c in _cfd.CATALOG:
        out.append({"id": c.get("id"), "title": c.get("title", c.get("id")),
                    "use": c.get("use", ""), "multiRegion": bool(c.get("multiRegion"))})
    return out


def study_titles():
    """Just the titles, for a picker combo."""
    return [s["title"] for s in study_types()]


def find_study(title_or_id):
    """Look a study up by its title or id."""
    for s in study_types():
        if title_or_id in (s["title"], s["id"]):
            return s
    return None


def study_steps(study_id=None, multi_region=False):
    """The ordered setup steps for a study. CHT / multi-region studies carry both
    fluid and solid materials, so the Materials step is split for them - the one
    place the tree differs by physics so far."""
    steps = [dict(s) for s in _BASE_STEPS]
    if multi_region:
        mats_i = next((i for i, s in enumerate(steps) if s["key"] == "materials"), None)
        if mats_i is not None:
            steps[mats_i:mats_i + 1] = [
                {"key": "mat_fluid", "label": "Materials - fluid",
                 "status": STATUS_TODO, "panel": "materials"},
                {"key": "mat_solid", "label": "Materials - solid",
                 "status": STATUS_TODO, "panel": "materials"},
            ]
    return steps


def safe_name(text, prefix="CFD"):
    """A FreeCAD-object-safe name (letters/digits/underscore) from a study title."""
    out = []
    for ch in str(text):
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    name = "".join(out).strip("_") or "study"
    return "%s_%s" % (prefix, name)
