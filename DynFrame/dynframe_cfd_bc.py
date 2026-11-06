# -*- coding: utf-8 -*-
"""DynFrame CFD - interactive boundary conditions (pure, testable).

SimScale's core interaction: pick faces in the 3D view and assign a boundary
condition to them. This module is the pure model behind that - the BC types and
their colours, and the per-face colour list used to paint a solid's faces by the
BC assigned to each. No FreeCAD imports, so it is unit-tested; the FreeCAD
command (dynframe_commands.py) reads the face selection, stores the assignment on
a BC document object, and applies the colour list to the solid's ViewObject.
"""


# The boundary-condition types a user can assign to faces, the SimScale set, with
# the colour each paints on the 3D view, the blockMesh/mesh patch type, whether
# it needs a value (and some common preset values), and a help line. The field
# treatment per type lives in dynframe_cfd_gen.bc_field_files, keyed by "key".
BC_TYPES = [
    {"key": "velocity_inlet", "label": "Velocity inlet",
     "color": (0.20, 0.70, 0.30), "patch": "patch",
     "value_label": "Inlet speed (m/s)", "value": 10.0,
     "presets": [1, 2, 5, 10, 20, 50],
     "help": "Fixed velocity into the domain, along the inlet face normal. "
             "k/omega set from turbulence."},
    {"key": "pressure_inlet", "label": "Pressure inlet",
     "color": (0.30, 0.78, 0.55), "patch": "patch",
     "value_label": "Total pressure (Pa)", "value": 0.0,
     "presets": [0, 50, 100, 500, 1000],
     "help": "Fixed total pressure; velocity follows from the pressure field."},
    {"key": "velocity_outlet", "label": "Velocity outlet",
     "color": (0.95, 0.55, 0.20), "patch": "patch",
     "value_label": "Outlet speed (m/s)", "value": 10.0,
     "presets": [1, 2, 5, 10, 20, 50],
     "help": "Fixed velocity leaving the domain."},
    {"key": "pressure_outlet", "label": "Pressure outlet",
     "color": (0.85, 0.25, 0.20), "patch": "patch",
     "value_label": "Gauge pressure (Pa)", "value": 0.0,
     "presets": [0, -50, -100, 100, 500],
     "help": "Fixed static pressure (0 = atmosphere); backflow handled."},
    {"key": "wall", "label": "Wall (no-slip)",
     "color": (0.78, 0.80, 0.83), "patch": "wall",
     "value_label": "", "value": 0.0, "presets": [],
     "help": "Stationary solid wall, zero velocity, wall functions on k/omega."},
    {"key": "moving_wall", "label": "Moving wall",
     "color": (0.62, 0.55, 0.42), "patch": "wall",
     "value_label": "Wall speed (m/s)", "value": 1.0,
     "presets": [0.1, 0.5, 1, 2, 5],
     "help": "Wall translating in +X at the given speed (lid-driven etc.)."},
    {"key": "slip", "label": "Slip wall",
     "color": (0.45, 0.65, 0.88), "patch": "patch",
     "value_label": "", "value": 0.0, "presets": [],
     "help": "Frictionless wall: no normal flow, free tangential (far-field)."},
    {"key": "symmetry", "label": "Symmetry",
     "color": (0.55, 0.60, 0.95), "patch": "symmetry",
     "value_label": "", "value": 0.0, "presets": [],
     "help": "Mirror plane: model half the domain to save cells."},
]

BASE_FACE_COLOR = (0.80, 0.80, 0.82)   # unassigned faces (light grey)


def bc_type(key):
    """Look up a BC type by key; None if unknown."""
    for b in BC_TYPES:
        if b["key"] == key:
            return b
    return None


def bc_labels():
    return [b["label"] for b in BC_TYPES]


def bc_by_label(label):
    for b in BC_TYPES:
        if b["label"] == label:
            return b
    return None


def bc_color(key):
    b = bc_type(key)
    return b["color"] if b else BASE_FACE_COLOR


def parse_face_indices(sub_names):
    """Turn FreeCAD sub-element names ('Face3', 'Face12', ...) into 0-based face
    indices, ignoring anything that is not a face."""
    out = []
    for s in sub_names or []:
        s = str(s)
        if s.startswith("Face"):
            try:
                out.append(int(s[4:]) - 1)
            except ValueError:
                pass
    return out


def face_colors(nfaces, assignments, base=BASE_FACE_COLOR):
    """Per-face colour list for a solid with `nfaces` faces.

    `assignments` maps a 0-based face index to a BC key (later assignments win).
    Returns a list of (r,g,b) of length nfaces: the BC colour on assigned faces,
    `base` elsewhere - exactly what a FreeCAD ViewObject.DiffuseColor expects."""
    cols = [tuple(base)] * int(max(0, nfaces))
    for idx, key in (assignments or {}).items():
        i = int(idx)
        if 0 <= i < len(cols):
            cols[i] = tuple(bc_color(key))
    return cols


def merge_assignments(existing, new_indices, key):
    """Add/replace a BC assignment: faces in `new_indices` get `key`. Returns a
    fresh {face_index: key} dict (a face belongs to the BC assigned last)."""
    out = dict(existing or {})
    for i in new_indices or []:
        out[int(i)] = key
    return out


def summarize(assignments):
    """Count faces per BC key, for a short report: {key: n_faces}."""
    out = {}
    for key in (assignments or {}).values():
        out[key] = out.get(key, 0) + 1
    return out
