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
from engine.forecasting import (
    forecast_consumption,
    MA_THRESHOLD, MIN_ARIMA_POINTS,
    _calendar_days, _build_series,
)
from engine.logistics_engine import (
    optimize_truck_loads,
    solve_routes,
)
from engine.rerouting_engine import (
    analyze_route_with_conditions,
    compare_routes,
)
from models.material import Material, PhaseRecord
from models.delivery import DeliveryPoint

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
#  Forecast — adaptive MA / ARIMA consumption forecast                 #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/forecast")
def phase_forecast():
    """
    POST body:
        material    : str
        phase_index : int
        horizon     : int  (optional, default 14)

    Returns a ForecastResult serialised as JSON, including:
        model, horizon, forecast (list of {date, qty}),
        total_forecast, expected_excess, backtest_mape, note, warning,
        regime (str: "MA" or "ARIMA"), thresholds used.
    """
    body = request.json
    mats = load_materials()
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]

    phase_index = int(body.get("phase_index", len(mat.history) - 1))
    if phase_index < 0 or phase_index >= len(mat.history):
        return jsonify({"error": "Invalid phase_index."}), 400

    horizon = int(body.get("horizon", 14))
    phase   = mat.history[phase_index]
    usage   = [{"date": e.date, "quantity": e.quantity} for e in phase.daily_usage]

    result = forecast_consumption(
        daily_usage  = usage,
        ordered_qty  = phase.ordered_qty,
        consumed_qty = phase.consumed_qty,
        horizon      = horizon,
    )

    try:
        s        = _build_series(usage)
        cal_days = _calendar_days(s)
        regime   = "MA" if (cal_days < MA_THRESHOLD or len(usage) < MIN_ARIMA_POINTS) else "ARIMA"
    except Exception:
        regime   = "MA"
        cal_days = None

    return jsonify({
        "material":       name,
        "phase_name":     phase.phase_name,
        "model":          result.model,
        "regime":         regime,
        "horizon":        result.horizon,
        "forecast":       result.forecast,
        "total_forecast": result.total_forecast,
        "expected_excess": result.expected_excess,
        "backtest_mape":  result.backtest_mape,
        "note":           result.note,
        "warning":        result.warning,
        "thresholds": {
            "ma_threshold_calendar_days": MA_THRESHOLD,
            "min_arima_points":           MIN_ARIMA_POINTS,
        },
        "data_available": {
            "log_entries":   len(usage),
            "calendar_days": cal_days,
        },
    })


# ─────────────────────────────────────────────────────────────────── #
#  Smart Re-Routing Endpoints                                         #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/delivery/analyze-route")
def analyze_route():
    """
    Analyze a single route with weather + traffic impact

    POST body: {
        "route_name": "Route A",
        "waypoints": [[lat, lon], [lat, lon], ...],
        "truck_load_kg": 2500,
        "truck_capacity_kg": 5000
    }
    """
    try:
        body = request.json
        route_name = body.get("route_name", "Route")
        waypoints = [(float(lat), float(lon)) for lat, lon in body["waypoints"]]
        load = float(body["truck_load_kg"])
        capacity = float(body["truck_capacity_kg"])

        if not waypoints or len(waypoints) < 2:
            return jsonify({"error": "Provide at least 2 waypoints"}), 400

        analysis = analyze_route_with_conditions(waypoints, route_name, load, capacity)
        return jsonify(analysis)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/delivery/compare-routes")
def compare_delivery_routes():
    """
    Compare multiple routes and recommend the best one

    POST body: {
        "routes": [
            {"name": "Route A", "waypoints": [[lat, lon], ...]},
            {"name": "Route B", "waypoints": [[lat, lon], ...]}
        ],
        "truck_load_kg": 2500,
        "truck_capacity_kg": 5000
    }
    """
    try:
        body = request.json
        routes = [
            (r["name"], [(float(lat), float(lon)) for lat, lon in r["waypoints"]])
            for r in body.get("routes", [])
        ]
        load = float(body["truck_load_kg"])
        capacity = float(body["truck_capacity_kg"])

        if len(routes) < 2:
            return jsonify({"error": "Provide at least 2 routes to compare"}), 400

        comparison = compare_routes(routes, load, capacity)
        return jsonify(comparison)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─────────────────────────────────────────────────────────────────── #
#  Sites                                                               #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/sites")
def get_sites():
    sites = load_sites()
    return jsonify([s.to_dict() for s in sites])


# ─────────────────────────────────────────────────────────────────── #
#  Geocoding — resolve a place name to lat/lon via Nominatim           #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/geocode")
def geocode():
    """
    GET /api/geocode?q=Mumbai
    Calls Nominatim (OpenStreetMap) — no API key required.
    Returns up to 5 candidates: [{name, lat, lon, display_name}]
    """
    import urllib.request
    import urllib.parse
    import json as _json
    import ssl
    import certifi

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Provide ?q=<place name>"}), 400

    params = urllib.parse.urlencode({
        "q":              query,
        "format":         "json",
        "limit":          5,
        "addressdetails": 0,
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "BuildSense/1.0"})
    ctx = ssl.create_default_context(cafile=certifi.where())

    try:
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        return jsonify({"error": f"Geocoding failed: {e}"}), 502

    results = [
        {
            "name":         item.get("name") or item.get("display_name", "").split(",")[0],
            "display_name": item.get("display_name", ""),
            "lat":          float(item["lat"]),
            "lon":          float(item["lon"]),
        }
        for item in data
    ]
    return jsonify(results)


# ─────────────────────────────────────────────────────────────────── #
#  Custom Route Delivery Plan                                          #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/delivery/plan-custom")
def delivery_plan_custom():
    """
    Delivery plan with user-defined route stops (no pre-loaded sites.json).

    POST body:
    {
      "order_quantities": {"Cement": 500, "Steel": 200},
      "trucks": [{"truck_id": "TRK-01", "capacity_kg": 10000}],
      "rain_expected": false,
      "stops": [
        {"name": "Depot",       "lat": 12.9716, "lon": 77.5946, "is_depot": true},
        {"name": "Site A",      "lat": 13.0827, "lon": 80.2707},
        {"name": "Site B",      "lat": 17.3850, "lon": 78.4867},
        {"name": "Destination", "lat": 19.0760, "lon": 72.8777}
      ]
    }

    Stops are visited in shortest-path order (TSP/CVRP).
    The first stop marked is_depot=true is used as the depot;
    if none is marked, the first stop in the list is treated as depot.
    """
    body             = request.json
    order_quantities = body.get("order_quantities", {})
    trucks           = body.get("trucks", [])
    rain_expected    = bool(body.get("rain_expected", False))
    stops_raw        = body.get("stops", [])

    if not trucks:
        return jsonify({"error": "Provide at least one truck."}), 400
    if not order_quantities:
        return jsonify({"error": "Provide at least one dispatch quantity."}), 400
    if len(stops_raw) < 2:
        return jsonify({"error": "Provide at least a source and a destination."}), 400

    mats = load_materials()

    # Identify depot (first stop with is_depot=True, or first stop)
    depot_raw  = next((s for s in stops_raw if s.get("is_depot")), stops_raw[0])
    sites_raw  = [s for s in stops_raw if s is not depot_raw]

    # Distribute total demand evenly across non-depot stops
    demand_per_stop = max(1, int(sum(
        mats[n].weight_per_unit * q
        for n, q in order_quantities.items() if n in mats
    ) / max(len(sites_raw), 1)))

    depot = DeliveryPoint(
        name=depot_raw["name"],
        lat=float(depot_raw["lat"]),
        lon=float(depot_raw["lon"]),
        demand=0,
    )
    sites = [
        DeliveryPoint(
            name=s["name"],
            lat=float(s["lat"]),
            lon=float(s["lon"]),
            demand=demand_per_stop,
        )
        for s in sites_raw
    ]

    assignments = optimize_truck_loads(mats, order_quantities, trucks, rain_expected)
    vehicle_cap = max(t["capacity_kg"] for t in trucks)
    assignments = solve_routes(depot, sites, assignments, vehicle_cap)

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

    # Also return stop coordinates so the frontend can draw the map
    stop_coords = {s["name"]: {"lat": s["lat"], "lon": s["lon"]} for s in stops_raw}
    return jsonify({"assignments": result, "stop_coords": stop_coords})


# ─────────────────────────────────────────────────────────────────── #
#  Run                                                                 #
# ─────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    app.run(debug=True, port=5001)
