"""
Persistence layer — loads and saves all BuildSense data as JSON.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from models.material import Material
from models.delivery  import DeliveryPoint

DATA_DIR              = os.path.dirname(__file__)
MATERIALS_FILE        = os.path.join(DATA_DIR, "materials.json")
SITES_FILE            = os.path.join(DATA_DIR, "sites.json")
SUPPLY_NETWORK_FILE   = os.path.join(DATA_DIR, "supply_network.json")
REORDER_LOG_FILE      = os.path.join(DATA_DIR, "reorder_log.json")
PROJECT_CONFIG_FILE   = os.path.join(DATA_DIR, "project_config.json")
PENDING_REORDERS_FILE = os.path.join(DATA_DIR, "pending_reorders.json")


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


# ─────────────────────────────────────────────────────────────────── #
#  Supply Network                                                      #
# ─────────────────────────────────────────────────────────────────── #

def load_supply_network() -> dict:
    """Load depots + stores from supply_network.json."""
    if not os.path.exists(SUPPLY_NETWORK_FILE):
        return {"depots": [], "stores": []}
    with open(SUPPLY_NETWORK_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────── #
#  Reorder Transaction Logs                                            #
# ─────────────────────────────────────────────────────────────────── #

def load_reorder_logs() -> List[dict]:
    """Return all persisted auto-reorder log entries (newest first)."""
    if not os.path.exists(REORDER_LOG_FILE):
        return []
    with open(REORDER_LOG_FILE, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def append_reorder_log(entry: dict) -> dict:
    """
    Persist a single reorder event.

    Expected fields in *entry* (all strings/numbers):
      material, unit, reorder_qty, days_remaining, stockout_date,
      ema_rate, critical, dest_name, source (trigger source string),
      timestamp (ISO 8601 string — caller should set this).

    Returns the entry with an auto-assigned integer `id`.
    """
    logs = load_reorder_logs()
    entry["id"] = (logs[0]["id"] + 1) if logs else 1   # newest first → highest id
    # Prepend so list stays newest-first
    logs.insert(0, entry)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REORDER_LOG_FILE, "w", encoding="utf-8") as fh:
        json.dump(logs, fh, indent=2)
    return entry


def clear_reorder_logs() -> None:
    """Wipe all reorder logs."""
    if os.path.exists(REORDER_LOG_FILE):
        os.remove(REORDER_LOG_FILE)


# ─────────────────────────────────────────────────────────────────── #
#  Project Site Config (saved once at project start)                   #
# ─────────────────────────────────────────────────────────────────── #

def load_project_config() -> dict:
    """
    Return the project-level config dict.
    Keys: name, dest_lat, dest_lon, dest_name, created_at
    Returns {} if not yet configured.
    """
    if not os.path.exists(PROJECT_CONFIG_FILE):
        return {}
    with open(PROJECT_CONFIG_FILE, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return {}


def save_project_config(config: dict) -> dict:
    """Persist project config. Merges into existing if present."""
    existing = load_project_config()
    existing.update(config)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROJECT_CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
    return existing


# ─────────────────────────────────────────────────────────────────── #
#  Pending Reorders queue                                              #
# ─────────────────────────────────────────────────────────────────── #

def load_pending_reorders() -> List[dict]:
    """Return all pending reorder items (newest first)."""
    if not os.path.exists(PENDING_REORDERS_FILE):
        return []
    with open(PENDING_REORDERS_FILE, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def _save_pending_reorders(items: List[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PENDING_REORDERS_FILE, "w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2)


def append_pending_reorder(entry: dict) -> dict:
    """
    Add a new pending reorder item.
    Auto-assigns an integer id. Status starts as 'pending'.
    Deduplicates: if a pending entry for the same material already exists,
    updates it instead of adding a duplicate.
    """
    items = load_pending_reorders()
    # Dedup — update existing pending item for same material
    for existing in items:
        if (existing["material"] == entry["material"]
                and existing["status"] == "pending"):
            existing.update(entry)
            existing["status"] = "pending"
            _save_pending_reorders(items)
            return existing
    # New entry
    entry["id"] = (max((i["id"] for i in items), default=0) + 1)
    entry["status"] = "pending"
    items.insert(0, entry)
    _save_pending_reorders(items)
    return entry


def update_pending_reorder(item_id: int, status: str, extra: dict = None) -> dict:
    """Set status of a pending reorder item ('approved' | 'rejected')."""
    items = load_pending_reorders()
    for item in items:
        if item["id"] == item_id:
            item["status"] = status
            if extra:
                item.update(extra)
            _save_pending_reorders(items)
            return item
    raise KeyError(f"Pending reorder id={item_id} not found.")


def count_pending_reorders() -> int:
    """Count items with status='pending' — used for nav badge."""
    return sum(1 for i in load_pending_reorders() if i.get("status") == "pending")
