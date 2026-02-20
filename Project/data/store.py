"""
Persistence layer — loads and saves all BuildSense data as JSON.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from models.material import Material
from models.delivery  import DeliveryPoint

DATA_DIR           = os.path.dirname(__file__)
MATERIALS_FILE     = os.path.join(DATA_DIR, "materials.json")
SITES_FILE         = os.path.join(DATA_DIR, "sites.json")


# ─────────────────────────────────────────────────────────────────── #
#  Default seed data                                                   #
# ─────────────────────────────────────────────────────────────────── #

DEFAULT_MATERIALS: Dict[str, dict] = {
    "Cement": {
        "unit": "bags", "baseline_buffer_pct": 6.0,
        "weight_per_unit": 50.0, "priority": 9,
    },
    "Brick": {
        "unit": "pcs",  "baseline_buffer_pct": 10.0,
        "weight_per_unit": 3.0,  "priority": 7,
    },
    "Steel": {
        "unit": "kg",   "baseline_buffer_pct": 2.0,
        "weight_per_unit": 1.0,  "priority": 10,
    },
    "Sand": {
        "unit": "tons", "baseline_buffer_pct": 8.0,
        "weight_per_unit": 1000.0, "priority": 6,
    },
    "Aggregate": {
        "unit": "tons", "baseline_buffer_pct": 5.0,
        "weight_per_unit": 1000.0, "priority": 5,
    },
    "Paint": {
        "unit": "litres", "baseline_buffer_pct": 7.0,
        "weight_per_unit": 1.2,  "priority": 4,
    },
    "Wood": {
        "unit": "sq ft", "baseline_buffer_pct": 12.0,
        "weight_per_unit": 5.0,  "priority": 6,
    },
    "Glass": {
        "unit": "sq ft", "baseline_buffer_pct": 5.0,
        "weight_per_unit": 2.5,  "priority": 5,
    },
}

DEFAULT_SITES: List[dict] = [
    {"name": "Depot (Bangalore)",  "lat": 12.9716, "lon": 77.5946, "demand": 0},
    {"name": "Chennai Site",       "lat": 13.0827, "lon": 80.2707, "demand": 40},
    {"name": "Hyderabad Site",     "lat": 17.3850, "lon": 78.4867, "demand": 60},
    {"name": "Mumbai Site",        "lat": 19.0760, "lon": 72.8777, "demand": 50},
    {"name": "Delhi Site",         "lat": 28.6139, "lon": 77.2090, "demand": 70},
    {"name": "Kolkata Site",       "lat": 22.5726, "lon": 88.3639, "demand": 30},
    {"name": "Jaipur Site",        "lat": 26.9124, "lon": 75.7873, "demand": 45},
    {"name": "Ahmedabad Site",     "lat": 23.0225, "lon": 72.5714, "demand": 35},
    {"name": "Goa Site",           "lat": 15.2993, "lon": 74.1240, "demand": 25},
    {"name": "Coimbatore Site",    "lat": 11.0168, "lon": 76.9558, "demand": 10},
]


# ─────────────────────────────────────────────────────────────────── #
#  Materials                                                           #
# ─────────────────────────────────────────────────────────────────── #

def _build_default_materials() -> Dict[str, Material]:
    result: Dict[str, Material] = {}
    for name, cfg in DEFAULT_MATERIALS.items():
        result[name] = Material(
            name=name,
            unit=cfg["unit"],
            baseline_buffer_pct=cfg["baseline_buffer_pct"],
            buffer_pct=cfg["baseline_buffer_pct"],
            weight_per_unit=cfg["weight_per_unit"],
            priority=cfg["priority"],
        )
    return result


def load_materials() -> Dict[str, Material]:
    if not os.path.exists(MATERIALS_FILE):
        mats = _build_default_materials()
        save_materials(mats)
        return mats
    with open(MATERIALS_FILE, "r") as fh:
        raw: dict = json.load(fh)
    return {name: Material.from_dict(data) for name, data in raw.items()}


def save_materials(materials: Dict[str, Material]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {name: mat.to_dict() for name, mat in materials.items()}
    with open(MATERIALS_FILE, "w") as fh:
        json.dump(payload, fh, indent=2)


def add_custom_material(
    materials:           Dict[str, Material],
    name:                str,
    unit:                str,
    baseline_buffer_pct: float,
    weight_per_unit:     float,
    priority:            int,
) -> Material:
    key = name.strip().title()
    if key in materials:
        raise ValueError(f"Material '{key}' already exists.")
    mat = Material(
        name=key,
        unit=unit.strip(),
        baseline_buffer_pct=baseline_buffer_pct,
        buffer_pct=baseline_buffer_pct,
        weight_per_unit=weight_per_unit,
        priority=priority,
    )
    materials[key] = mat
    save_materials(materials)
    return mat


# ─────────────────────────────────────────────────────────────────── #
#  Delivery Sites                                                      #
# ─────────────────────────────────────────────────────────────────── #

def load_sites() -> List[DeliveryPoint]:
    if not os.path.exists(SITES_FILE):
        sites = [DeliveryPoint.from_dict(d) for d in DEFAULT_SITES]
        save_sites(sites)
        return sites
    with open(SITES_FILE, "r") as fh:
        raw: list = json.load(fh)
    return [DeliveryPoint.from_dict(d) for d in raw]


def save_sites(sites: List[DeliveryPoint]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SITES_FILE, "w") as fh:
        json.dump([s.to_dict() for s in sites], fh, indent=2)
