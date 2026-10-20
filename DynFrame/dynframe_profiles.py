# -*- coding: utf-8 -*-
"""DynFrame structural-profile library.

Each entry maps a display name to a builder that returns a planar Part
cross-section (a Face, possibly with a hole) in the local XY plane,
centred on its bounding-box centre, with its normal along +Z.  The Frame
Generator extrudes that face along each selected edge to make a member.

All dimensions are in millimetres.  The sizes below are representative
common structural sections, not a certified standards table — treat them
as a starting catalogue you can edit/extend.
"""

import Part
from FreeCAD import Vector


def _rect_wire(b, h):
    """Closed rectangular wire of width b, height h, centred on origin."""
    hb, hh = b / 2.0, h / 2.0
    pts = [Vector(-hb, -hh, 0), Vector(hb, -hh, 0),
           Vector(hb, hh, 0), Vector(-hb, hh, 0), Vector(-hb, -hh, 0)]
    return Part.makePolygon(pts)


def _poly_face(points):
    """Face from a list of (x, y) tuples, centred on its bbox centre."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    v = [Vector(x - cx, y - cy, 0) for (x, y) in points]
    v.append(v[0])
    return Part.Face(Part.makePolygon(v))


def _solid_rect_face(b, h):
    return Part.Face(_rect_wire(b, h))


def _hollow_rect_face(b, h, t):
    outer = Part.Face(_rect_wire(b, h))
    inner = Part.Face(_rect_wire(b - 2.0 * t, h - 2.0 * t))
    return outer.cut(inner)


def _round_face(d):
    return Part.Face(Part.Wire(Part.makeCircle(d / 2.0)))


def _tube_face(od, t):
    outer = Part.Face(Part.Wire(Part.makeCircle(od / 2.0)))
    inner = Part.Face(Part.Wire(Part.makeCircle(od / 2.0 - t)))
    return outer.cut(inner)


def _angle_face(a, b, t):
    # L section: legs a (x) and b (y), thickness t.
    return _poly_face([(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)])


def _channel_face(b, h, t):
    # U/C channel: web of height h on the left, flanges of width b, opening +x.
    return _poly_face([(0, 0), (b, 0), (b, t), (t, t),
                       (t, h - t), (b, h - t), (b, h), (0, h)])


def _ibeam_face(b, h, tw, tf):
    # I/H section: flange width b, total height h, web tw, flange tf.
    x1, xw = b / 2.0, tw / 2.0
    y1, yf = h / 2.0, h / 2.0 - tf
    return _poly_face([
        (-x1, -y1), (x1, -y1), (x1, -yf), (xw, -yf), (xw, yf), (x1, yf),
        (x1, y1), (-x1, y1), (-x1, yf), (-xw, yf), (-xw, -yf), (-x1, -yf)])


def build_profiles():
    """Return an ordered list of (display_name, builder_callable)."""
    out = []

    def add(name, fn):
        out.append((name, fn))

    # Square hollow section  a x a x t
    for a, t in [(20, 2), (25, 2), (30, 3), (40, 3), (50, 3), (60, 4), (80, 5), (100, 5)]:
        add("SHS %dx%dx%d" % (a, a, t), (lambda a=a, t=t: _hollow_rect_face(a, a, t)))

    # Rectangular hollow section  b x h x t
    for b, h, t in [(40, 20, 2), (50, 30, 3), (60, 40, 3), (80, 40, 4), (100, 50, 5), (120, 60, 6)]:
        add("RHS %dx%dx%d" % (b, h, t), (lambda b=b, h=h, t=t: _hollow_rect_face(b, h, t)))

    # Circular hollow section  OD x t
    for od, t in [(21.3, 2.3), (26.9, 2.6), (33.7, 3.2), (42.4, 3.2), (48.3, 3.2), (60.3, 4.0)]:
        add("CHS %.1fx%.1f" % (od, t), (lambda od=od, t=t: _tube_face(od, t)))

    # Equal/unequal angle  a x b x t
    for a, b, t in [(20, 20, 3), (25, 25, 3), (30, 30, 3), (40, 40, 4), (50, 50, 5), (60, 40, 5)]:
        add("L %dx%dx%d" % (a, b, t), (lambda a=a, b=b, t=t: _angle_face(a, b, t)))

    # Channel  h x b x t
    for b, h, t in [(20, 40, 3), (25, 50, 3), (42, 65, 5), (45, 80, 6)]:
        add("U %dx%dx%d" % (h, b, t), (lambda b=b, h=h, t=t: _channel_face(b, h, t)))

    # I / H beam (approx IPE)  named by height
    for b, h, tw, tf in [(46, 80, 3.8, 5.2), (55, 100, 4.1, 5.7), (64, 120, 4.4, 6.3), (82, 160, 5.0, 7.4)]:
        add("IPE %d" % h, (lambda b=b, h=h, tw=tw, tf=tf: _ibeam_face(b, h, tw, tf)))

    # Flat bar  b x h
    for b, h in [(40, 5), (50, 6), (60, 8), (80, 10)]:
        add("Flat %dx%d" % (b, h), (lambda b=b, h=h: _solid_rect_face(b, h)))

    # Round bar  diameter
    for d in [8, 10, 12, 16, 20, 25]:
        add("Round D%d" % d, (lambda d=d: _round_face(d)))

    return out
