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
SITES_FILE            = os.path.join(DATA_DIR, "sites.json")
SUPPLY_NETWORK_FILE   = os.path.join(DATA_DIR, "supply_network.json")

# ── Multi-project registry ──────────────────────────────────────── #
PROJECTS_FILE         = os.path.join(DATA_DIR, "projects.json")

# ── Per-project file paths (call get_project_dir(pid) first) ──────── #
def get_project_dir(project_id: str) -> str:
    d = os.path.join(DATA_DIR, "projects", project_id)
    os.makedirs(d, exist_ok=True)
    return d

def _pfile(project_id: str, name: str) -> str:
    return os.path.join(get_project_dir(project_id), name)

# Legacy single-project paths (kept for backward compat if needed)
_DEFAULT_PID          = "default"
MATERIALS_FILE        = os.path.join(DATA_DIR, "materials.json")
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


def load_materials(project_id: str = None) -> Dict[str, Material]:
    path = _pfile(project_id, "materials.json") if project_id else MATERIALS_FILE
    if not os.path.exists(path):
        mats = _build_default_materials()
        save_materials(mats, project_id)
        return mats
    with open(path, "r") as fh:
        raw: dict = json.load(fh)
    return {name: Material.from_dict(data) for name, data in raw.items()}


def save_materials(materials: Dict[str, Material], project_id: str = None) -> None:
    path = _pfile(project_id, "materials.json") if project_id else MATERIALS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {name: mat.to_dict() for name, mat in materials.items()}
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)


def add_custom_material(
    materials:           Dict[str, Material],
    name:                str,
    unit:                str,
    baseline_buffer_pct: float,
    weight_per_unit:     float,
    priority:            int,
    project_id:          str = None,
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
    save_materials(materials, project_id)
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
#  Reorder Transaction Logs  (project-aware)                           #
# ─────────────────────────────────────────────────────────────────── #

def load_reorder_logs(project_id: str = None) -> List[dict]:
    path = _pfile(project_id, "reorder_log.json") if project_id else REORDER_LOG_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def append_reorder_log(entry: dict, project_id: str = None) -> dict:
    path = _pfile(project_id, "reorder_log.json") if project_id else REORDER_LOG_FILE
    logs = load_reorder_logs(project_id)
    entry["id"] = (logs[0]["id"] + 1) if logs else 1
    logs.insert(0, entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(logs, fh, indent=2)
    return entry


def clear_reorder_logs(project_id: str = None) -> None:
    path = _pfile(project_id, "reorder_log.json") if project_id else REORDER_LOG_FILE
    if os.path.exists(path):
        os.remove(path)


# ─────────────────────────────────────────────────────────────────── #
#  Multi-Project Registry                                              #
# ─────────────────────────────────────────────────────────────────── #

def _load_projects_raw() -> List[dict]:
    if not os.path.exists(PROJECTS_FILE):
        return []
    with open(PROJECTS_FILE, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []

def _save_projects_raw(projects: List[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROJECTS_FILE, "w", encoding="utf-8") as fh:
        json.dump(projects, fh, indent=2)

def list_projects() -> List[dict]:
    """Return all projects, newest first."""
    return list(reversed(_load_projects_raw()))

def create_project(name: str, dest_lat: float, dest_lon: float, dest_name: str) -> dict:
    """Create a new project, persist it, and return it."""
    import uuid
    from datetime import datetime as _dt
    projects = _load_projects_raw()
    project = {
        "id":         str(uuid.uuid4())[:8],
        "name":       name,
        "dest_lat":   dest_lat,
        "dest_lon":   dest_lon,
        "dest_name":  dest_name,
        "created_at": _dt.utcnow().isoformat() + "Z",
    }
    projects.append(project)
    _save_projects_raw(projects)
    # Initialise empty data files for this project
    get_project_dir(project["id"])
    return project

def get_project(project_id: str) -> dict:
    """Return a single project dict or {} if not found."""
    for p in _load_projects_raw():
        if p["id"] == project_id:
            return p
    return {}

def delete_project(project_id: str) -> bool:
    """Remove a project from the registry (does not delete data files)."""
    projects = _load_projects_raw()
    new = [p for p in projects if p["id"] != project_id]
    if len(new) == len(projects):
        return False
    _save_projects_raw(new)
    return True

# ─────────────────────────────────────────────────────────────────── #
#  Project Site Config — legacy single-project shim                   #
#  (still used by server endpoints that haven't migrated yet)          #
# ─────────────────────────────────────────────────────────────────── #

def load_project_config() -> dict:
    if not os.path.exists(PROJECT_CONFIG_FILE):
        return {}
    with open(PROJECT_CONFIG_FILE, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return {}

def save_project_config(config: dict) -> dict:
    existing = load_project_config()
    existing.update(config)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROJECT_CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
    return existing


# ─────────────────────────────────────────────────────────────────── #
#  Pending Reorders queue  (project-aware)                             #
# ─────────────────────────────────────────────────────────────────── #

def load_pending_reorders(project_id: str = None) -> List[dict]:
    path = _pfile(project_id, "pending_reorders.json") if project_id else PENDING_REORDERS_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            return []


def _save_pending_reorders(items: List[dict], project_id: str = None) -> None:
    path = _pfile(project_id, "pending_reorders.json") if project_id else PENDING_REORDERS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2)


def append_pending_reorder(entry: dict, project_id: str = None) -> dict:
    items = load_pending_reorders(project_id)
    for existing in items:
        if (existing["material"] == entry["material"]
                and existing["status"] == "pending"):
            existing.update(entry)
            existing["status"] = "pending"
            _save_pending_reorders(items, project_id)
            return existing
    entry["id"] = (max((i["id"] for i in items), default=0) + 1)
    entry["status"] = "pending"
    items.insert(0, entry)
    _save_pending_reorders(items, project_id)
    return entry


def update_pending_reorder(item_id: int, status: str, extra: dict = None, project_id: str = None) -> dict:
    items = load_pending_reorders(project_id)
    for item in items:
        if item["id"] == item_id:
            item["status"] = status
            if extra:
                item.update(extra)
            _save_pending_reorders(items, project_id)
            return item
    raise KeyError(f"Pending reorder id={item_id} not found.")


def count_pending_reorders(project_id: str = None) -> int:
    return sum(1 for i in load_pending_reorders(project_id) if i.get("status") == "pending")
