# -*- coding: utf-8 -*-
"""DynFrame structural-profile library.

Profiles are grouped into FAMILIES (I-beams, channels, angles, hollow
sections, etc.), each with many nominal sizes — closer to the catalogue
you get in Inventor's Frame Generator.

Each builder returns a planar Part cross-section (a Face, possibly with a
hole) in the local XY plane, centred on its bounding-box centre, normal
+Z. The Frame Generator extrudes that face along each selected edge.

Dimensions are millimetres. Sizes are representative nominal values for
common European/metric sections — good for modelling and cut lists, but
not a certified standards table. Edit the tables below to add your own.
"""

import Part
from FreeCAD import Vector


# ── low-level face builders ──────────────────────────────────────
def _rect_wire(b, h):
    hb, hh = b / 2.0, h / 2.0
    return Part.makePolygon([Vector(-hb, -hh, 0), Vector(hb, -hh, 0),
                             Vector(hb, hh, 0), Vector(-hb, hh, 0),
                             Vector(-hb, -hh, 0)])


def _poly_face(points):
    """Face from [(x, y), ...], recentred on its bounding-box centre."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    v = [Vector(x - cx, y - cy, 0) for (x, y) in points]
    v.append(v[0])
    return Part.Face(Part.makePolygon(v))


def solid_rect(b, h):
    return Part.Face(_rect_wire(b, h))


def hollow_rect(b, h, t):
    return Part.Face(_rect_wire(b, h)).cut(Part.Face(_rect_wire(b - 2.0 * t, h - 2.0 * t)))


def round_bar(d):
    return Part.Face(Part.Wire(Part.makeCircle(d / 2.0)))


def tube(od, t):
    o = Part.Face(Part.Wire(Part.makeCircle(od / 2.0)))
    i = Part.Face(Part.Wire(Part.makeCircle(od / 2.0 - t)))
    return o.cut(i)


def angle(a, b, t):
    """L section: leg a along x, leg b along y, thickness t."""
    return _poly_face([(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)])


def channel(h, b, tw, tf):
    """U/C channel: web height h (y), flange width b (x), opening +x."""
    return _poly_face([(0, 0), (b, 0), (b, tf), (tw, tf),
                       (tw, h - tf), (b, h - tf), (b, h), (0, h)])


def ibeam(h, b, tw, tf):
    """I/H section: height h, flange width b, web tw, flange tf."""
    x1, xw = b / 2.0, tw / 2.0
    y1, yf = h / 2.0, h / 2.0 - tf
    return _poly_face([
        (-x1, -y1), (x1, -y1), (x1, -yf), (xw, -yf), (xw, yf), (x1, yf),
        (x1, y1), (-x1, y1), (-x1, yf), (-xw, yf), (-xw, -yf), (-x1, -yf)])


def tee(h, b, t):
    """T section: height h, flange width b, thickness t (flange on top)."""
    cx = b / 2.0
    return _poly_face([
        (cx - t / 2.0, 0), (cx + t / 2.0, 0), (cx + t / 2.0, h - t),
        (b, h - t), (b, h), (0, h), (0, h - t), (cx - t / 2.0, h - t)])


# ── registry ─────────────────────────────────────────────────────
FAMILIES = {}        # family name -> [(size name, builder), ...]
_NAME2BUILDER = {}   # size name  -> builder
SECTION_DIMS = {}    # size name  -> (kind, {dim: value})  [no Part needed]


def _reg(family, name, builder, kind=None, dims=None):
    FAMILIES.setdefault(family, []).append((name, builder))
    _NAME2BUILDER[name] = builder
    if kind is not None:
        SECTION_DIMS[name] = (kind, dims)


# dimension tables  -------------------------------------------------
# IPE I-beams: (nominal, h, b, tw, tf)
_IPE = [(80, 80, 46, 3.8, 5.2), (100, 100, 55, 4.1, 5.7), (120, 120, 64, 4.4, 6.3),
        (140, 140, 73, 4.7, 6.9), (160, 160, 82, 5.0, 7.4), (180, 180, 91, 5.3, 8.0),
        (200, 200, 100, 5.6, 8.5), (220, 220, 110, 5.9, 9.2), (240, 240, 120, 6.2, 9.8),
        (270, 270, 135, 6.6, 10.2), (300, 300, 150, 7.1, 10.7), (330, 330, 160, 7.5, 11.5),
        (360, 360, 170, 8.0, 12.7), (400, 400, 180, 8.6, 13.5), (450, 450, 190, 9.4, 14.6),
        (500, 500, 200, 10.2, 16.0), (550, 550, 210, 11.1, 17.2), (600, 600, 220, 12.0, 19.0)]
# HEA: (nominal, h, b, tw, tf)
_HEA = [(100, 96, 100, 5.0, 8.0), (120, 114, 120, 5.0, 8.0), (140, 133, 140, 5.5, 8.5),
        (160, 152, 160, 6.0, 9.0), (180, 171, 180, 6.0, 9.5), (200, 190, 200, 6.5, 10.0),
        (220, 210, 220, 7.0, 11.0), (240, 230, 240, 7.5, 12.0), (260, 250, 260, 7.5, 12.5),
        (280, 270, 280, 8.0, 13.0), (300, 290, 300, 8.5, 14.0), (340, 330, 300, 9.5, 16.5),
        (400, 390, 300, 11.0, 19.0)]
# HEB: (nominal, h, b, tw, tf)
_HEB = [(100, 100, 100, 6.0, 10.0), (120, 120, 120, 6.5, 11.0), (140, 140, 140, 7.0, 12.0),
        (160, 160, 160, 8.0, 13.0), (180, 180, 180, 8.5, 14.0), (200, 200, 200, 9.0, 15.0),
        (220, 220, 220, 9.5, 16.0), (240, 240, 240, 10.0, 17.0), (260, 260, 260, 10.0, 17.5),
        (280, 280, 280, 10.5, 18.0), (300, 300, 300, 11.0, 19.0), (340, 340, 300, 12.0, 21.5),
        (400, 400, 300, 13.5, 24.0)]
# UPN channels: (nominal, h, b, tw, tf)
_UPN = [(50, 50, 38, 5.0, 7.0), (65, 65, 42, 5.5, 7.5), (80, 80, 45, 6.0, 8.0),
        (100, 100, 50, 6.0, 8.5), (120, 120, 55, 7.0, 9.0), (140, 140, 60, 7.0, 10.0),
        (160, 160, 65, 7.5, 10.5), (180, 180, 70, 8.0, 11.0), (200, 200, 75, 8.5, 11.5),
        (220, 220, 80, 9.0, 12.5), (240, 240, 85, 9.5, 13.0), (260, 260, 90, 10.0, 14.0),
        (300, 300, 100, 10.0, 16.0)]
# Equal angles: (leg, thickness)
_LEQ = [(20, 3), (25, 3), (30, 3), (30, 4), (40, 4), (40, 5), (45, 5), (50, 5), (50, 6),
        (60, 6), (60, 8), (70, 7), (80, 8), (90, 9), (100, 10), (120, 12), (150, 15)]
# Unequal angles: (a, b, t)
_LUN = [(40, 25, 4), (50, 30, 5), (60, 40, 5), (65, 50, 6), (75, 50, 6), (80, 60, 7),
        (100, 65, 8), (100, 75, 8), (125, 75, 10), (150, 90, 10)]
# Square hollow: (a, t)
_SHS = [(20, 2), (25, 2), (25, 3), (30, 2), (30, 3), (40, 2), (40, 3), (40, 4), (50, 3),
        (50, 4), (50, 5), (60, 3), (60, 4), (60, 5), (70, 4), (70, 5), (80, 4), (80, 5),
        (80, 6), (90, 5), (90, 6), (100, 4), (100, 5), (100, 6), (100, 8), (120, 5),
        (120, 6), (120, 8), (140, 6), (140, 8), (150, 6), (150, 8), (150, 10), (160, 8),
        (180, 8), (180, 10), (200, 8), (200, 10), (200, 12)]
# Rectangular hollow: (b, h, t)
_RHS = [(40, 20, 2), (50, 25, 3), (50, 30, 3), (60, 40, 3), (60, 40, 4), (80, 40, 3),
        (80, 40, 4), (80, 40, 5), (90, 50, 4), (100, 50, 4), (100, 50, 5), (100, 60, 5),
        (120, 60, 5), (120, 60, 6), (120, 80, 5), (140, 80, 5), (150, 100, 6), (160, 80, 6),
        (160, 80, 8), (200, 100, 6), (200, 100, 8), (200, 120, 8), (250, 150, 8),
        (250, 150, 10), (300, 200, 10)]
# Circular hollow: (od, t)
_CHS = [(21.3, 2.3), (26.9, 2.6), (33.7, 2.6), (33.7, 3.2), (42.4, 2.6), (42.4, 3.2),
        (48.3, 3.2), (48.3, 4.0), (60.3, 3.2), (60.3, 4.0), (76.1, 3.2), (76.1, 4.0),
        (88.9, 4.0), (88.9, 5.0), (114.3, 4.0), (114.3, 5.0), (139.7, 5.0), (139.7, 6.0),
        (168.3, 6.0), (219.1, 6.0), (219.1, 8.0)]
# T sections: (h, b, t)
_TEE = [(40, 40, 5), (50, 50, 6), (60, 60, 6), (80, 80, 8), (100, 100, 10), (120, 120, 12)]
# Flat bar: (width, thickness)
_FLAT = [(20, 3), (25, 3), (30, 3), (40, 5), (50, 5), (50, 6), (60, 6), (60, 8),
         (80, 8), (100, 10), (120, 10)]
# Round bar: diameter
_ROUND = [6, 8, 10, 12, 16, 20, 25, 30, 40, 50]


def _build_all():
    if FAMILIES:
        return
    for n, h, b, tw, tf in _IPE:
        _reg("I-beam (IPE)", "IPE %d" % n, (lambda h=h, b=b, tw=tw, tf=tf: ibeam(h, b, tw, tf)),
             "I", {"h": h, "b": b, "tw": tw, "tf": tf})
    for n, h, b, tw, tf in _HEA:
        _reg("H-beam (HEA)", "HEA %d" % n, (lambda h=h, b=b, tw=tw, tf=tf: ibeam(h, b, tw, tf)),
             "I", {"h": h, "b": b, "tw": tw, "tf": tf})
    for n, h, b, tw, tf in _HEB:
        _reg("H-beam (HEB)", "HEB %d" % n, (lambda h=h, b=b, tw=tw, tf=tf: ibeam(h, b, tw, tf)),
             "I", {"h": h, "b": b, "tw": tw, "tf": tf})
    for n, h, b, tw, tf in _UPN:
        _reg("Channel (UPN)", "UPN %d" % n, (lambda h=h, b=b, tw=tw, tf=tf: channel(h, b, tw, tf)),
             "U", {"h": h, "b": b, "tw": tw, "tf": tf})
    for a, t in _LEQ:
        _reg("Angle (equal)", "L %dx%dx%d" % (a, a, t), (lambda a=a, t=t: angle(a, a, t)),
             "L", {"a": a, "b": a, "t": t})
    for a, b, t in _LUN:
        _reg("Angle (unequal)", "L %dx%dx%d" % (a, b, t), (lambda a=a, b=b, t=t: angle(a, b, t)),
             "L", {"a": a, "b": b, "t": t})
    for a, t in _SHS:
        _reg("Square tube (SHS)", "SHS %dx%dx%d" % (a, a, t), (lambda a=a, t=t: hollow_rect(a, a, t)),
             "box", {"b": a, "h": a, "t": t})
    for b, h, t in _RHS:
        _reg("Rectangular tube (RHS)", "RHS %dx%dx%d" % (b, h, t), (lambda b=b, h=h, t=t: hollow_rect(b, h, t)),
             "box", {"b": b, "h": h, "t": t})
    for od, t in _CHS:
        _reg("Round tube (CHS)", "CHS %.1fx%.1f" % (od, t), (lambda od=od, t=t: tube(od, t)),
             "CHS", {"d": od, "t": t})
    for h, b, t in _TEE:
        _reg("T section", "T %dx%dx%d" % (h, b, t), (lambda h=h, b=b, t=t: tee(h, b, t)),
             "T", {"h": h, "b": b, "t": t})
    for b, t in _FLAT:
        _reg("Flat bar", "Flat %dx%d" % (b, t), (lambda b=b, t=t: solid_rect(b, t)),
             "flat", {"b": b, "t": t})
    for d in _ROUND:
        _reg("Round bar", "Round D%d" % d, (lambda d=d: round_bar(d)),
             "round", {"d": d})


def families():
    _build_all()
    return FAMILIES


def builder_for(name):
    _build_all()
    return _NAME2BUILDER.get(name)


def dims_for(name):
    """(kind, {dim: value}) for a profile size name, or None if unknown.
    Pure data — no OpenCASCADE geometry is built, so this is safe to call
    for section-property maths without a running FreeCAD kernel."""
    _build_all()
    return SECTION_DIMS.get(name)
