# -*- coding: utf-8 -*-
"""DynFrame CFD - material library (pure, testable).

SimScale lets you pick a fluid (and, for conjugate heat transfer, solids) from a
library and assign it to the simulation. This is the pure data behind that: a
small library of common fluids and solids with the properties OpenFOAM needs
(kinematic viscosity and density for fluids; density, conductivity and specific
heat for solids). The FreeCAD command picks from this and stores the choice on
the study; the case generator reads nu from it.
"""


# Fluids: nu = kinematic viscosity (m2/s), rho = density (kg/m3) at ~20 C, 1 atm.
FLUIDS = [
    {"key": "air",      "name": "Air (20 C)",        "nu": 1.5e-5,  "rho": 1.205},
    {"key": "water",    "name": "Water (20 C)",      "nu": 1.0e-6,  "rho": 998.0},
    {"key": "oil_sae30", "name": "Oil (SAE 30)",     "nu": 2.5e-4,  "rho": 891.0},
    {"key": "glycol",   "name": "Ethylene glycol",   "nu": 1.5e-5,  "rho": 1113.0},
    {"key": "co2",      "name": "Carbon dioxide",    "nu": 8.0e-6,  "rho": 1.84},
    {"key": "steam",    "name": "Steam (100 C)",     "nu": 2.0e-5,  "rho": 0.6},
    {"key": "hydrogen", "name": "Hydrogen",          "nu": 1.05e-4, "rho": 0.0899},
    {"key": "seawater", "name": "Sea water",         "nu": 1.05e-6, "rho": 1025.0},
]

# Solids: rho (kg/m3), k = conductivity (W/m-K), cp = specific heat (J/kg-K).
SOLIDS = [
    {"key": "aluminium", "name": "Aluminium", "rho": 2700.0, "k": 237.0, "cp": 900.0},
    {"key": "steel",     "name": "Steel",     "rho": 7850.0, "k": 50.0,  "cp": 490.0},
    {"key": "stainless", "name": "Stainless 304", "rho": 8000.0, "k": 16.0, "cp": 500.0},
    {"key": "copper",    "name": "Copper",    "rho": 8960.0, "k": 401.0, "cp": 385.0},
    {"key": "concrete",  "name": "Concrete",  "rho": 2300.0, "k": 1.4,   "cp": 880.0},
    {"key": "pcb_fr4",   "name": "PCB (FR-4)", "rho": 1850.0, "k": 0.3,  "cp": 1100.0},
    {"key": "silicon",   "name": "Silicon",   "rho": 2330.0, "k": 148.0, "cp": 700.0},
    {"key": "glass",     "name": "Glass",     "rho": 2500.0, "k": 1.05,  "cp": 840.0},
]


def fluid_names():
    return ["%s" % f["name"] for f in FLUIDS]


def solid_names():
    return ["%s" % s["name"] for s in SOLIDS]


def fluid_by_name(name):
    for f in FLUIDS:
        if f["name"] == name:
            return f
    return None


def solid_by_name(name):
    for s in SOLIDS:
        if s["name"] == name:
            return s
    return None


def fluid_by_key(key):
    for f in FLUIDS:
        if f["key"] == key:
            return f
    return FLUIDS[0]
