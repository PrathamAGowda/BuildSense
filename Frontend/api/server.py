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
    load_materials, save_materials, add_custom_material,
    load_supply_network,
    load_reorder_logs, append_reorder_log, clear_reorder_logs,
    load_pending_reorders, append_pending_reorder,
    update_pending_reorder, count_pending_reorders,
    list_projects, create_project, get_project, delete_project,
)
from engine.supply_engine import plan_supply
from engine.auto_reorder_engine import check_auto_reorder, check_all_materials
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
from models.material import Material, PhaseRecord
from models.delivery import DeliveryPoint

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)


def _pid() -> str | None:
    """Read the active project id from the X-Project-Id request header."""
    return request.headers.get("X-Project-Id") or None


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
    mats = load_materials(_pid())
    return jsonify([_material_to_json(m) for m in mats.values()])


@app.post("/api/materials")
def add_material():
    body = request.json
    mats = load_materials(_pid())
    try:
        mat = add_custom_material(
            mats,
            name=body["name"],
            unit=body["unit"],
            baseline_buffer_pct=float(body["baseline_buffer_pct"]),
            weight_per_unit=float(body["weight_per_unit"]),
            priority=int(body["priority"]),
            project_id=_pid(),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_material_to_json(mat)), 201


@app.delete("/api/materials/<name>")
def delete_material(name: str):
    mats = load_materials(_pid())
    key = name.strip().title()
    if key not in mats:
        return jsonify({"error": f"Material '{key}' not found."}), 404
    del mats[key]
    save_materials(mats, _pid())
    return jsonify({"deleted": key})


@app.post("/api/materials/<name>/reset-buffer")
def reset_buffer(name: str):
    mats = load_materials(_pid())
    key = name.strip().title()
    if key not in mats:
        return jsonify({"error": f"Material '{key}' not found."}), 404
    mats[key].buffer_pct = mats[key].baseline_buffer_pct
    save_materials(mats, _pid())
    return jsonify(_material_to_json(mats[key]))


# ─────────────────────────────────────────────────────────────────── #
#  Phase 1 — Initialize Phase (persist planned quantities)             #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/initialize")
def initialize_phase():
    body = request.json
    mats = load_materials(_pid())
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404
    mat = mats[name]
    phase_name  = body.get("phase_name", "Unnamed Phase").strip()
    planned_qty = float(body["planned_qty"])
    # Recommended order = planned × (1 + buffer/100) — returned for display only
    ordered_qty = round(planned_qty * (1 + mat.buffer_pct / 100), 4)

    # Check for duplicate phase name on this material
    existing = [r.phase_name for r in mat.history]
    if phase_name in existing:
        return jsonify({"error": f"Phase '{phase_name}' already exists for {name}."}), 409

    record = PhaseRecord(
        phase_name=phase_name,
        planned_qty=planned_qty,
        ordered_qty=0.0,        # no inventory until a real order arrives
        consumed_qty=0.0,
        waste_pct=0.0,
        remaining_stock=0.0,    # no stock until order is received
    )
    mat.history.append(record)
    save_materials(mats, _pid())
    return jsonify({
        "material":    name,
        "unit":        mat.unit,
        "phase_name":  phase_name,
        "planned_qty": planned_qty,
        "buffer_pct":  mat.buffer_pct,
        "ordered_qty": ordered_qty,   # recommended — not yet committed
        "phase_index": len(mat.history) - 1,
    }), 201


# ─────────────────────────────────────────────────────────────────── #
#  Manual multi-material order cart → pending reorders                 #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/manual-order")
def manual_order():
    """
    POST /api/phase/manual-order
    Body: { "items": [{ "material": "Cement", "planned_qty": 200 }, ...] }

    All items share a batch_id so they can be approved together with one
    combined supply plan.  Does NOT touch ordered_qty / remaining_stock.
    """
    import uuid
    from datetime import datetime as _dt
    body  = request.json or {}
    items = body.get("items", [])
    if not items:
        return jsonify({"error": "No items provided."}), 400

    mats     = load_materials(_pid())
    ts       = _dt.utcnow().isoformat() + "Z"
    batch_id = str(uuid.uuid4())[:8]
    results  = []
    errors   = []

    for item in items:
        name        = str(item.get("material", "")).strip().title()
        planned_qty = float(item.get("planned_qty", 0))
        if not name or planned_qty <= 0:
            errors.append({"material": name, "error": "Invalid qty"})
            continue
        if name not in mats:
            errors.append({"material": name, "error": "Material not found"})
            continue

        mat             = mats[name]
        recommended_qty = round(planned_qty * (1 + mat.buffer_pct / 100), 4)

        pending_item = {
            "timestamp":      ts,
            "source":         "manual-order",
            "batch_id":       batch_id,
            "material":       name,
            "unit":           mat.unit,
            "planned_qty":    planned_qty,
            "reorder_qty":    recommended_qty,
            "buffer_pct":     mat.buffer_pct,
            "days_remaining": None,
            "stockout_date":  None,
            "ema_rate":       None,
            "critical":       False,
        }
        created = append_pending_reorder(pending_item, _pid())
        results.append({
            "material":         name,
            "unit":             mat.unit,
            "planned_qty":      planned_qty,
            "buffer_pct":       mat.buffer_pct,
            "recommended_qty":  recommended_qty,
            "pending_id":       created.get("id"),
            "batch_id":         batch_id,
        })

    return jsonify({"created": results, "errors": errors, "batch_id": batch_id}), 201


# ─────────────────────────────────────────────────────────────────── #
#  Supply route planning without needing phase history                 #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/supply/route-only")
def supply_route_only():
    """
    POST /api/supply/route-only
    Single-material convenience wrapper — delegates to route-combined.
    Body: { "material": "Cement", "qty": 212, "dest_lat", "dest_lon", "dest_name" }
    """
    body      = request.json or {}
    name      = str(body.get("material", "")).strip().title()
    qty       = float(body.get("qty", 0))
    dest_lat  = body.get("dest_lat")
    dest_lon  = body.get("dest_lon")
    dest_name = body.get("dest_name", "Construction Site")

    if not name or qty <= 0 or dest_lat is None or dest_lon is None:
        return jsonify({"error": "material, qty, dest_lat and dest_lon are required"}), 400

    mats = load_materials(_pid())
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found"}), 404

    mat = mats[name]
    try:
        supply_plan = plan_supply(
            dest_lat     = float(dest_lat),
            dest_lon     = float(dest_lon),
            dest_name    = dest_name,
            requirements = [{"material": name, "qty": qty, "unit_weight": mat.weight_per_unit}],
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"supply_plan": supply_plan, "material": name, "qty": qty})


@app.post("/api/supply/route-combined")
def supply_route_combined():
    """
    POST /api/supply/route-combined
    Runs ONE combined supply plan for multiple materials — trucks are
    shared across all materials.
    Body: {
      "items": [{ "material": "Cement", "qty": 212 }, { "material": "Sand", "qty": 530 }],
      "dest_lat": 26.9124,
      "dest_lon": 75.7873,
      "dest_name": "Jaipur Site"
    }
    """
    body      = request.json or {}
    items     = body.get("items", [])
    dest_lat  = body.get("dest_lat")
    dest_lon  = body.get("dest_lon")
    dest_name = body.get("dest_name", "Construction Site")

    if not items:
        return jsonify({"error": "items list is required"}), 400
    if dest_lat is None or dest_lon is None:
        return jsonify({"error": "dest_lat and dest_lon are required"}), 400

    mats = load_materials(_pid())
    requirements = []
    errors = []
    for item in items:
        name = str(item.get("material", "")).strip().title()
        qty  = float(item.get("qty", 0))
        if name not in mats:
            errors.append(f"Material '{name}' not found")
            continue
        requirements.append({
            "material":    name,
            "qty":         qty,
            "unit_weight": mats[name].weight_per_unit,
        })

    if not requirements:
        return jsonify({"error": "No valid materials", "details": errors}), 400

    try:
        supply_plan = plan_supply(
            dest_lat     = float(dest_lat),
            dest_lon     = float(dest_lon),
            dest_name    = dest_name,
            requirements = requirements,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"supply_plan": supply_plan, "items": requirements, "errors": errors})


# ─────────────────────────────────────────────────────────────────── #
#  Phase 2 — Smart Ordering                                            #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/smart-order")
def smart_order():
    body = request.json
    mats = load_materials(_pid())
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
    mats = load_materials(_pid())
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
    save_materials(mats, _pid())
    trend = get_usage_trend(mat, phase_index, days=7)

    # ── Auto-reorder: run EMA prediction on every log ──────────── #
    dest_lat  = body.get("dest_lat")
    dest_lon  = body.get("dest_lon")
    dest_name = body.get("dest_name", "Construction Site")

    # Sum qty already on order (pending + approved) so the engine treats
    # that stock as "effective remaining" and won't re-alert needlessly.
    pending = load_pending_reorders(_pid())
    on_order_qty = sum(
        float(r.get("reorder_qty", 0))
        for r in pending
        if r.get("material") == name and r.get("status") in ("pending", "approved")
    )

    auto_reorder = check_auto_reorder(
        mat, phase_index,
        dest_lat     = float(dest_lat)  if dest_lat  is not None else None,
        dest_lon     = float(dest_lon)  if dest_lon  is not None else None,
        dest_name    = dest_name,
        on_order_qty = on_order_qty,
    )

    # ── Persist reorder log if triggered ─────────────────────────── #
    if auto_reorder.get("triggered"):
        from datetime import datetime as _dt
        pred = auto_reorder.get("prediction", {})
        sp   = auto_reorder.get("supply_plan") or {}
        log_entry = {
            "timestamp":      _dt.utcnow().isoformat() + "Z",
            "source":         "daily-log",
            "material":       auto_reorder["material"],
            "unit":           auto_reorder["unit"],
            "reorder_qty":    auto_reorder["reorder_qty"],
            "days_remaining": pred.get("days_remaining"),
            "stockout_date":  pred.get("stockout_date"),
            "ema_rate":       pred.get("ema_rate"),
            "critical":       auto_reorder.get("critical", False),
            "dest_name":      dest_name,
            "depots_used":    [d["depot"]["name"] if isinstance(d.get("depot"), dict) else str(d.get("depot","")) for d in sp.get("depot_plans", [])],
            "total_distance_km": sp.get("total_distance_km"),
            "total_co2_kg":      sp.get("total_co2_kg"),
            "status":         "triggered",
        }
        append_reorder_log(log_entry, _pid())
        # Push to pending approval queue (deduplicates by material)
        append_pending_reorder({
            "timestamp":      log_entry["timestamp"],
            "source":         "daily-log",
            "material":       log_entry["material"],
            "unit":           log_entry["unit"],
            "reorder_qty":    log_entry["reorder_qty"],
            "days_remaining": log_entry["days_remaining"],
            "stockout_date":  log_entry["stockout_date"],
            "ema_rate":       log_entry["ema_rate"],
            "critical":       log_entry["critical"],
        }, _pid())

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
        "auto_reorder":           auto_reorder,
    })


# ─────────────────────────────────────────────────────────────────── #
#  Auto-Reorder — intelligent stockout prediction + supply planning    #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/auto-reorder-check")
def auto_reorder_check():
    """
    POST /api/phase/auto-reorder-check
    Body:
    {
      "material":    "Cement",
      "phase_index": -1,          // optional, defaults to latest phase
      "dest_lat":    26.9124,     // optional — triggers supply planning if given
      "dest_lon":    75.7873,
      "dest_name":   "Jaipur Site",
      "horizon_days": 7           // optional, default 7
    }

    Runs EMA-based stockout prediction. If triggered, automatically
    sources the reorder quantity from the supply network via Clarke-Wright VRP.
    """
    body = request.json or {}
    mats = load_materials(_pid())
    name = body.get("material", "").strip().title()
    if name not in mats:
        return jsonify({"error": f"Material '{name}' not found."}), 404

    mat         = mats[name]
    phase_index = int(body.get("phase_index", len(mat.history) - 1))
    dest_lat    = body.get("dest_lat")
    dest_lon    = body.get("dest_lon")
    dest_name   = body.get("dest_name", "Construction Site")
    horizon     = int(body.get("horizon_days", 7))

    # Include on-order qty so the check accounts for already-ordered stock
    pending = load_pending_reorders(_pid())
    on_order_qty = sum(
        float(r.get("reorder_qty", 0))
        for r in pending
        if r.get("material") == name and r.get("status") in ("pending", "approved")
    )

    alert = check_auto_reorder(
        mat, phase_index,
        dest_lat     = float(dest_lat)  if dest_lat  is not None else None,
        dest_lon     = float(dest_lon)  if dest_lon  is not None else None,
        dest_name    = dest_name,
        horizon_days = horizon,
        on_order_qty = on_order_qty,
    )
    return jsonify(alert)


@app.post("/api/phase/auto-reorder-all")
def auto_reorder_all():
    """
    POST /api/phase/auto-reorder-all
    Body:
    {
      "dest_lat":    26.9124,   // optional
      "dest_lon":    75.7873,
      "dest_name":   "Jaipur Site",
      "horizon_days": 7
    }

    Runs auto-reorder check across ALL materials (latest phase).
    Returns alerts sorted: critical → triggered → ok.
    Supply planning is done per-material and merged into a combined
    multi-material supply plan for the triggered ones.
    """
    body      = request.json or {}
    mats      = load_materials(_pid())
    dest_lat  = body.get("dest_lat")
    dest_lon  = body.get("dest_lon")
    dest_name = body.get("dest_name", "Construction Site")
    horizon   = int(body.get("horizon_days", 7))

    # Build on-order map: material name → total qty pending/approved
    pending = load_pending_reorders(_pid())
    on_order_map: dict = {}
    for r in pending:
        if r.get("status") in ("pending", "approved"):
            mat_name = r.get("material", "")
            on_order_map[mat_name] = on_order_map.get(mat_name, 0.0) + float(r.get("reorder_qty", 0))

    alerts = check_all_materials(
        mats,
        dest_lat     = float(dest_lat)  if dest_lat  is not None else None,
        dest_lon     = float(dest_lon)  if dest_lon  is not None else None,
        dest_name    = dest_name,
        horizon_days = horizon,
        on_order_map = on_order_map,
    )

    triggered = [a for a in alerts if a.get("triggered")]
    critical  = [a for a in alerts if a.get("critical")]

    # Combined supply plan for all triggered materials at once
    combined_plan = None
    if triggered and dest_lat is not None and dest_lon is not None:
        requirements = [
            {
                "material":    a["material"],
                "qty":         a["reorder_qty"],
                "unit_weight": mats[a["material"]].weight_per_unit,
            }
            for a in triggered
            if a["reorder_qty"] > 0 and a["material"] in mats
        ]
        if requirements:
            try:
                combined_plan = plan_supply(
                    dest_lat  = float(dest_lat),
                    dest_lon  = float(dest_lon),
                    dest_name = dest_name,
                    requirements = requirements,
                )
            except Exception as e:
                combined_plan = {"error": str(e)}

    # ── Persist one log entry per triggered material ──────────────── #
    if triggered:
        from datetime import datetime as _dt
        ts = _dt.utcnow().isoformat() + "Z"
        cp = combined_plan or {}
        for a in triggered:
            pred = a.get("prediction", {})
            append_reorder_log({
                "timestamp":         ts,
                "source":            "batch-check",
                "material":          a["material"],
                "unit":              a["unit"],
                "reorder_qty":       a["reorder_qty"],
                "days_remaining":    pred.get("days_remaining"),
                "stockout_date":     pred.get("stockout_date"),
                "ema_rate":          pred.get("ema_rate"),
                "critical":          a.get("critical", False),
                "dest_name":         dest_name,
                "depots_used":       [d["depot"]["name"] if isinstance(d.get("depot"), dict) else str(d.get("depot","")) for d in cp.get("depot_plans", [])],
                "total_distance_km": cp.get("total_distance_km"),
                "total_co2_kg":      cp.get("total_co2_kg"),
                "status":            "triggered",
            }, _pid())
            append_pending_reorder({
                "timestamp":      ts,
                "source":         "batch-check",
                "material":       a["material"],
                "unit":           a["unit"],
                "reorder_qty":    a["reorder_qty"],
                "days_remaining": pred.get("days_remaining"),
                "stockout_date":  pred.get("stockout_date"),
                "ema_rate":       pred.get("ema_rate"),
                "critical":       a.get("critical", False),
            }, _pid())

    return jsonify({
        "alerts":         alerts,
        "triggered_count": len(triggered),
        "critical_count":  len(critical),
        "combined_supply_plan": combined_plan,
    })


# ─────────────────────────────────────────────────────────────────── #
#  Reorder Transaction Logs                                            #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/reorder-logs")
def get_reorder_logs():
    """
    GET /api/reorder-logs
    Returns all persisted auto-reorder events, newest first.
    Optional query param: ?limit=N (default 100).
    """
    limit = int(request.args.get("limit", 100))
    logs  = load_reorder_logs(_pid())
    return jsonify({"logs": logs[:limit], "total": len(logs)})


@app.delete("/api/reorder-logs")
def delete_reorder_logs():
    """
    DELETE /api/reorder-logs
    Clears all reorder log entries (irreversible).
    """
    clear_reorder_logs(_pid())
    return jsonify({"cleared": True})


# ─────────────────────────────────────────────────────────────────── #
#  Projects — multi-project management                                 #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/projects")
def get_projects():
    """GET /api/projects — list all projects."""
    return jsonify(list_projects())


@app.post("/api/projects")
def post_create_project():
    """
    POST /api/projects
    Body: { name, dest_lat, dest_lon, dest_name }
    """
    body = request.json or {}
    for k in ("name", "dest_lat", "dest_lon", "dest_name"):
        if k not in body:
            return jsonify({"error": f"Missing field: {k}"}), 400
    project = create_project(
        name=body["name"],
        dest_lat=float(body["dest_lat"]),
        dest_lon=float(body["dest_lon"]),
        dest_name=body["dest_name"],
        start_date=body.get("start_date"),
        end_date=body.get("end_date"),
    )
    return jsonify(project), 201


@app.get("/api/projects/<project_id>")
def get_single_project(project_id: str):
    p = get_project(project_id)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)


@app.delete("/api/projects/<project_id>")
def delete_single_project(project_id: str):
    ok = delete_project(project_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"deleted": project_id})


# ─────────────────────────────────────────────────────────────────── #
#  Pending Reorders — approval queue                                   #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/pending-reorders")
def get_pending_reorders():
    """
    GET /api/pending-reorders
    Returns all pending reorder items.
    Query: ?status=pending|approved|rejected|all (default: all)
    """
    status_filter = request.args.get("status", "all")
    items = load_pending_reorders(_pid())
    if status_filter != "all":
        items = [i for i in items if i.get("status") == status_filter]
    pending_count = sum(1 for i in items if i.get("status") == "pending")
    return jsonify({"items": items, "pending_count": pending_count})


@app.post("/api/pending-reorders/approve/<int:item_id>")
def approve_pending_reorder(item_id: int):
    from datetime import datetime as _dt
    pid  = _pid()
    proj = get_project(pid) if pid else {}
    cfg  = proj
    if not cfg.get("dest_lat"):
        return jsonify({"error": "Project site not configured."}), 400

    all_items = load_pending_reorders(pid)
    item      = next((i for i in all_items if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": f"Pending reorder id={item_id} not found."}), 404
    if item["status"] != "pending":
        return jsonify({"error": f"Item is already {item['status']}."}), 409

    mats = load_materials(pid)

    # ── Determine batch siblings ──────────────────────────────────── #
    batch_id = item.get("batch_id")
    if batch_id:
        # All pending items from the same batch cart checkout
        batch_items = [
            i for i in all_items
            if i.get("batch_id") == batch_id and i["status"] == "pending"
        ]
    else:
        batch_items = [item]

    # ── Build combined requirements for one supply plan ───────────── #
    requirements = []
    for bi in batch_items:
        mat = mats.get(bi["material"])
        if mat:
            requirements.append({
                "material":    mat.name,
                "qty":         bi["reorder_qty"],
                "unit_weight": mat.weight_per_unit,
            })

    supply_plan = None
    try:
        supply_plan = plan_supply(
            dest_lat     = cfg["dest_lat"],
            dest_lon     = cfg["dest_lon"],
            dest_name    = cfg["dest_name"],
            requirements = requirements,
        )
    except Exception as e:
        supply_plan = {"error": str(e)}

    ts = _dt.utcnow().isoformat() + "Z"
    sp = supply_plan or {}
    depots_used       = [d["depot"]["name"] if isinstance(d.get("depot"), dict) else str(d.get("depot", "")) for d in sp.get("depot_plans", [])]
    total_distance_km = sp.get("total_distance_km")
    total_co2_kg      = sp.get("total_co2_kg")

    # ── Approve all batch items ───────────────────────────────────── #
    updated_items = []
    for bi in batch_items:
        u = update_pending_reorder(bi["id"], "approved", {
            "approved_at":       ts,
            "supply_plan":       supply_plan,
            "dest_name":         cfg["dest_name"],
            "depots_used":       depots_used,
            "total_distance_km": total_distance_km,
            "total_co2_kg":      total_co2_kg,
        }, pid)
        updated_items.append(u)
        append_reorder_log({
            "timestamp":         ts,
            "source":            "approved",
            "material":          bi["material"],
            "unit":              bi["unit"],
            "reorder_qty":       bi["reorder_qty"],
            "days_remaining":    bi.get("days_remaining"),
            "stockout_date":     bi.get("stockout_date"),
            "ema_rate":          bi.get("ema_rate"),
            "critical":          bi.get("critical", False),
            "dest_name":         cfg["dest_name"],
            "depots_used":       depots_used,
            "total_distance_km": total_distance_km,
            "total_co2_kg":      total_co2_kg,
            "status":            "approved",
        }, pid)

    return jsonify({
        "approved":      True,
        "item":          updated_items[0] if updated_items else None,
        "batch_approved": [u["id"] for u in updated_items],
        "supply_plan":   supply_plan,
        "pending_count": count_pending_reorders(pid),
    })


@app.post("/api/pending-reorders/reject/<int:item_id>")
def reject_pending_reorder(item_id: int):
    from datetime import datetime as _dt
    pid = _pid()
    try:
        updated = update_pending_reorder(item_id, "rejected", {
            "rejected_at": _dt.utcnow().isoformat() + "Z",
        }, pid)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"rejected": True, "item": updated, "pending_count": count_pending_reorders(pid)})


@app.post("/api/pending-reorders/arrived/<int:item_id>")
def mark_arrived(item_id: int):
    """
    POST /api/pending-reorders/arrived/<id>
    Marks an approved order as arrived and adds the reorder_qty
    to the material's current phase (ordered_qty + remaining_stock).
    """
    from datetime import datetime as _dt
    pid = _pid()
    items = load_pending_reorders(pid)
    item  = next((i for i in items if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": f"Order id={item_id} not found."}), 404
    if item["status"] != "approved":
        return jsonify({"error": f"Order is '{item['status']}', not approved."}), 409

    mats     = load_materials(pid)
    mat_name = item["material"]
    mat      = mats.get(mat_name)
    if not mat or not mat.history:
        return jsonify({"error": f"Material '{mat_name}' or its phases not found."}), 404

    qty  = float(item.get("reorder_qty", 0))
    phase = mat.history[-1]   # add to latest active phase
    phase.ordered_qty    = round(phase.ordered_qty + qty, 4)
    phase.remaining_stock = round(phase.remaining_stock + qty, 4)
    save_materials(mats, pid)

    ts = _dt.utcnow().isoformat() + "Z"
    updated = update_pending_reorder(item_id, "arrived", {
        "arrived_at": ts,
        "added_to_phase": phase.phase_name,
        "qty_added": qty,
    }, pid)

    return jsonify({
        "arrived": True,
        "item": updated,
        "material": mat_name,
        "phase": phase.phase_name,
        "qty_added": qty,
        "new_ordered_qty": phase.ordered_qty,
        "new_remaining_stock": phase.remaining_stock,
    })


@app.get("/api/pending-reorders/count")
def get_pending_count():
    """GET /api/pending-reorders/count — lightweight badge check."""
    return jsonify({"pending_count": count_pending_reorders(_pid())})


# ─────────────────────────────────────────────────────────────────── #
#  Phase 4 — Reorder Monitoring                                        #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/reorder-check")
def reorder_check():
    body = request.json
    mats = load_materials(_pid())
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
    mats = load_materials(_pid())
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
    save_materials(mats, _pid())
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
#  Forecast — adaptive MA / ARIMA consumption forecast                 #
# ─────────────────────────────────────────────────────────────────── #

@app.post("/api/phase/forecast")
def phase_forecast():
    body = request.json
    mats = load_materials(_pid())
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
#  Geocoding — resolve a place name to lat/lon via Nominatim           #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/geocode")
def geocode():
    import urllib.request, urllib.parse, json as _json, ssl, certifi

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Provide ?q=<place name>"}), 400

    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 5, "addressdetails": 0})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "BuildSense/1.0"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        return jsonify({"error": f"Geocoding failed: {e}"}), 502

    return jsonify([
        {
            "name":         item.get("name") or item.get("display_name", "").split(",")[0],
            "display_name": item.get("display_name", ""),
            "lat":          float(item["lat"]),
            "lon":          float(item["lon"]),
        }
        for item in data
    ])


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

    mats = load_materials(_pid())

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
#  Supply Network — destination-only auto-sourcing                     #
# ─────────────────────────────────────────────────────────────────── #

@app.get("/api/supply/network")
def supply_network_info():
    """Return counts of depots and stores for UI info cards."""
    net = load_supply_network()
    return jsonify({
        "depots": len(net.get("depots", [])),
        "stores": len(net.get("stores", [])),
        "depot_names": [d["name"] for d in net.get("depots", [])],
    })


@app.post("/api/supply/plan")
def supply_plan():
    """
    POST /api/supply/plan
    Body:
    {
      "destination": {"name": "Jaipur Site", "lat": 26.9124, "lon": 75.7873},
      "requirements": [
        {"material": "Cement", "qty": 1000},
        {"material": "Steel",  "qty": 200}
      ]
    }
    Automatically sources all materials from nearest stores,
    routes trucks from nearest depots via Clarke-Wright VRP.
    """
    body = request.json or {}
    dest = body.get("destination", {})
    reqs_raw = body.get("requirements", [])

    if not dest or "lat" not in dest or "lon" not in dest:
        return jsonify({"error": "destination with {name, lat, lon} is required"}), 400
    if not reqs_raw:
        return jsonify({"error": "requirements list is required"}), 400

    mats = load_materials(_pid())

    # Enrich requirements with unit_weight from material database
    requirements = []
    for r in reqs_raw:
        mat_name = r.get("material", "").strip().title()
        qty = float(r.get("qty", 0))
        if qty <= 0:
            continue
        unit_weight = mats[mat_name].weight_per_unit if mat_name in mats else 1.0
        requirements.append({
            "material":    mat_name,
            "qty":         qty,
            "unit_weight": unit_weight,
        })

    if not requirements:
        return jsonify({"error": "No valid requirements with qty > 0"}), 400

    result = plan_supply(
        dest_lat=float(dest["lat"]),
        dest_lon=float(dest["lon"]),
        dest_name=dest.get("name", "Destination"),
        requirements=requirements,
    )
    return jsonify(result)


# ─────────────────────────────────────────────────────────────────── #
#  Run                                                                 #
# ─────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    app.run(debug=False, port=5001)
