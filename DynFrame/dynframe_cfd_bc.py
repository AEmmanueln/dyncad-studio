# -*- coding: utf-8 -*-
"""DynFrame CFD - interactive boundary conditions (pure, testable).

SimScale's core interaction: pick faces in the 3D view and assign a boundary
condition to them. This module is the pure model behind that - the BC types and
their colours, and the per-face colour list used to paint a solid's faces by the
BC assigned to each. No FreeCAD imports, so it is unit-tested; the FreeCAD
command (dynframe_commands.py) reads the face selection, stores the assignment on
a BC document object, and applies the colour list to the solid's ViewObject.
"""


# The boundary-condition types a user can assign to faces, SimScale-style, with
# the colour each paints on the 3D view and whether it needs a numeric value.
BC_TYPES = [
    {"key": "inlet",   "label": "Velocity inlet",
     "color": (0.20, 0.70, 0.30), "value_label": "Inlet speed (m/s)",
     "value": 10.0, "patch": "patch"},
    {"key": "outlet",  "label": "Pressure outlet",
     "color": (0.85, 0.25, 0.20), "value_label": "Gauge pressure (Pa)",
     "value": 0.0, "patch": "patch"},
    {"key": "wall",    "label": "Wall (no-slip)",
     "color": (0.78, 0.80, 0.83), "value_label": "",
     "value": 0.0, "patch": "wall"},
    {"key": "slip",    "label": "Slip / symmetry",
     "color": (0.45, 0.65, 0.88), "value_label": "",
     "value": 0.0, "patch": "symmetry"},
    {"key": "noslip",  "label": "Moving wall (velocity)",
     "color": (0.62, 0.55, 0.42), "value_label": "Wall speed (m/s)",
     "value": 0.0, "patch": "wall"},
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
