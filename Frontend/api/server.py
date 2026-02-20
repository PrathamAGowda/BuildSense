#!/usr/bin/env python3
"""
BuildSense — Flask API Server
Bridges the Project/ backend to the Frontend/ UI.
Run from the Frontend/ directory:
    python api/server.py
"""

import sys
import os
from collections import Counter

# Resolve absolute path to Project/ so imports work from anywhere
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../Project"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, jsonify, request
from flask_cors import CORS

from data.store import (
    load_materials, save_materials,
    load_sites, save_sites,
    add_custom_material,
)
from engine.material_engine import (
    recommend_order_qty,
    record_phase,
    inventory_status,
    check_reorder,
    log_daily_usage,
    get_usage_trend,
)
from engine.logistics_engine import (
    optimize_truck_loads,
    solve_routes,
)
from models.material import Material, PhaseRecord

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)


@app.get("/")
def index():
    return app.send_static_file("index.html")


# ─────────────────────────────────────────────────────────────────── #
#  Helpers                                                             #
# ─────────────────────────────────────────────────────────────────── #

def _material_to_json(mat: Material) -> dict:
    return {
        "name":                mat.name,
        "unit":                mat.unit,
        "baseline_buffer_pct": mat.baseline_buffer_pct,
        "buffer_pct":          mat.buffer_pct,
        "weight_per_unit":     mat.weight_per_unit,
        "priority":            mat.priority,
        "phases_logged":       len(mat.history),
        "history": [
            {
                "phase_name":      r.phase_name,
                "planned_qty":     r.planned_qty,
                "ordered_qty":     r.ordered_qty,
                "consumed_qty":    r.consumed_qty,
                "waste_pct":       r.waste_pct,
                "remaining_stock": r.remaining_stock,
                "daily_usage": [
                    {"date": e.date, "quantity": e.quantity}
                    for e in r.daily_usage
                ],
            }
            for r in mat.history
        ],
    }


# ─────────────────────────────────────────────────────────────────── #
#  Materials                                                           #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/materials")
def get_materials():
    mats = load_materials()
    return jsonify([_material_to_json(m) for m in mats.values()])


@app.post("/api/materials")
def add_material():
    body = request.json
    mats = load_materials()
    try:
        mat = add_custom_material(
            mats,
            name=body["name"],
            unit=body["unit"],
            baseline_buffer_pct=float(body["baseline_buffer_pct"]),
            weight_per_unit=float(body["weight_per_unit"]),
            priority=int(body["priority"]),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_material_to_json(mat)), 201


@app.delete("/api/materials/<name>")
def delete_material(name: str):
    mats = load_materials()
    key = name.strip().title()
    if key not in mats:
        return jsonify({"error": f"Material '{key}' not found."}), 404
    del mats[key]
    save_materials(mats)
    return jsonify({"deleted": key})


@app.post("/api/materials/<name>/reset-buffer")
def reset_buffer(name: str):
    mats = load_materials()
    key = name.strip().title()
    if key not in mats:
        return jsonify({"error": f"Material '{key}' not found."}), 404
    mats[key].buffer_pct = mats[key].baseline_buffer_pct
    save_materials(mats)
    return jsonify(_material_to_json(mats[key]))


# ─────────────────────────────────────────────────────────────────── #
#  Phase 1 — Initialize Phase (persist planned quantities)             #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/initialize")
def initialize_phase():
    """
    Creates an active (in-progress) phase record for a material with
    consumed_qty=0, so it shows up in the Phase 3 dropdown immediately.
    ordered_qty is the recommended order (planned × buffer).
    """
    body = request.json
    mats = load_materials()
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]
    phase_name  = body.get("phase_name", "Unnamed Phase").strip()
    planned_qty = float(body["planned_qty"])
    # Recommended order = planned × (1 + buffer/100)
    ordered_qty = round(planned_qty * (1 + mat.buffer_pct / 100), 4)

    # Check for duplicate phase name on this material
    existing = [r.phase_name for r in mat.history]
    if phase_name in existing:
        return jsonify({"error": f"Phase '{phase_name}' already exists for {name}."}), 409

    record = PhaseRecord(
        phase_name=phase_name,
        planned_qty=planned_qty,
        ordered_qty=ordered_qty,
        consumed_qty=0.0,
        waste_pct=0.0,
        remaining_stock=ordered_qty,
    )
    mat.history.append(record)
    save_materials(mats)
    return jsonify({
        "material":    name,
        "unit":        mat.unit,
        "phase_name":  phase_name,
        "planned_qty": planned_qty,
        "ordered_qty": ordered_qty,
        "phase_index": len(mat.history) - 1,
    }), 201


# ─────────────────────────────────────────────────────────────────── #
#  Phase 2 — Smart Ordering                                            #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/smart-order")
def smart_order():
    body = request.json
    mats = load_materials()
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]
    planned = float(body["planned_qty"])
    try:
        recommended = recommend_order_qty(mat, planned)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "material":        name,
        "unit":            mat.unit,
        "planned_qty":     planned,
        "buffer_pct":      mat.buffer_pct,
        "recommended_qty": recommended,
    })


# ─────────────────────────────────────────────────────────────────── #
#  Phase 3 — Inventory Tracking                                        #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/inventory-status")
def get_inventory_status():
    body = request.json
    ordered   = float(body["ordered_qty"])
    consumed  = float(body["consumed_qty"])
    carry_in  = float(body.get("carry_in", 0.0))
    status    = inventory_status(ordered, consumed, carry_in)
    return jsonify(status)


# ─────────────────────────────────────────────────────────────────── #
#  Phase 3 — Log Daily Usage                                           #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/log-daily-usage")
def post_log_daily_usage():
    body = request.json
    mats = load_materials()
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]
    phase_index = int(body.get("phase_index", len(mat.history) - 1))
    qty_used    = float(body["qty_used"])
    usage_date  = body.get("date")           # optional, defaults to today
    try:
        phase = log_daily_usage(mat, phase_index, qty_used, usage_date)
    except (IndexError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    save_materials(mats)
    trend = get_usage_trend(mat, phase_index, days=7)
    return jsonify({
        "material":               name,
        "phase_name":             phase.phase_name,
        "consumed_qty":           phase.consumed_qty,
        "remaining_stock":        phase.remaining_stock,
        "ordered_qty":            phase.ordered_qty,
        "daily_usage": [
            {"date": e.date, "quantity": e.quantity} for e in phase.daily_usage
        ],
        "avg_per_active_day":     trend["avg_per_active_day"],
        "avg_per_calendar_day":   trend["avg_per_calendar_day"],
        "active_days":            trend["active_days"],
        "calendar_days":          trend["calendar_days"],
        "days_remaining_est":     trend["days_remaining_est"],
    })


# ─────────────────────────────────────────────────────────────────── #
#  Phase 4 — Reorder Monitoring                                        #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/reorder-check")
def reorder_check():
    body = request.json
    mats = load_materials()
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]
    ordered     = float(body["ordered_qty"])
    remaining   = float(body["remaining"])
    planned_qty = float(body["planned_qty"])
    result = check_reorder(mat, ordered, remaining, planned_qty)
    return jsonify({**result, "material": name, "unit": mat.unit})


# ─────────────────────────────────────────────────────────────────── #
#  Phase 5 + 6 — Complete Phase (Waste Review + Adaptive Update)       #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/complete")
def complete_phase():
    body = request.json
    mats = load_materials()
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]
    try:
        rec = record_phase(
            mat,
            phase_name=body["phase_name"],
            planned_qty=float(body["planned_qty"]),
            ordered_qty=float(body["ordered_qty"]),
            consumed_qty=float(body["consumed_qty"]),
            carry_in=float(body.get("carry_in", 0.0)),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    save_materials(mats)
    return jsonify({
        "material":        name,
        "unit":            mat.unit,
        "phase_name":      rec.phase_name,
        "planned_qty":     rec.planned_qty,
        "ordered_qty":     rec.ordered_qty,
        "consumed_qty":    rec.consumed_qty,
        "remaining_stock": rec.remaining_stock,
        "waste_pct":       rec.waste_pct,
        "new_buffer_pct":  mat.buffer_pct,
        "baseline_buffer": mat.baseline_buffer_pct,
        "phases_logged":   len(mat.history),
    })


# ─────────────────────────────────────────────────────────────────── #
#  Delivery Planning                                                    #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/delivery/plan")
def delivery_plan():
    body      = request.json
    mats      = load_materials()
    sites     = load_sites()
    depot     = sites[0]
    dpts      = sites[1:]

    order_quantities = body.get("order_quantities", {})    # {material: qty}
    trucks           = body.get("trucks", [])              # [{truck_id, capacity_kg}]
    rain_expected    = bool(body.get("rain_expected", False))

    if not trucks:
        return jsonify({"error": "Provide at least one truck."}), 400
    if not order_quantities:
        return jsonify({"error": "Provide at least one material order quantity."}), 400

    assignments = optimize_truck_loads(mats, order_quantities, trucks, rain_expected)
    vehicle_cap = max(t["capacity_kg"] for t in trucks)
    assignments = solve_routes(depot, dpts, assignments, vehicle_cap)

    result = []
    for a in assignments:
        counts = Counter(a.materials_loaded)
        result.append({
            "truck_id":        a.truck_id,
            "capacity_kg":     a.capacity_kg,
            "used_kg":         a.used_capacity_kg,
            "utilization_pct": a.utilization_pct,
            "materials":       dict(counts),
            "route":           a.route,
            "distance_km":     a.distance_km,
            "co2_kg":          a.co2_kg,
        })
    return jsonify(result)


# ─────────────────────────────────────────────────────────────────── #
#  Sites                                                               #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/sites")
def get_sites():
    sites = load_sites()
    return jsonify([s.to_dict() for s in sites])


# ─────────────────────────────────────────────────────────────────── #
#  Run                                                                 #
# ─────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    app.run(debug=True, port=5001)
