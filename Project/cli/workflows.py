"""
BuildSense — CLI Workflows
───────────────────────────
All six pipeline phases as interactive menu handlers.

Phase 1 – Project Initialization   : workflow_initialize_phase
Phase 2 – Smart Ordering           : workflow_smart_order
Phase 3 – Inventory Tracking       : workflow_track_inventory
Phase 4 – Reorder Monitoring       : workflow_reorder_check
Phase 5 – Waste Review             : workflow_complete_phase
Phase 6 – Adaptive Update          : (automatic inside workflow_complete_phase)

Plus:
  workflow_plan_delivery  — truck load + route optimisation
  workflow_view_report    — full material history
  workflow_all_materials  — overview table
  workflow_add_material   — register new material
  workflow_reset_buffer   — reset buffer to baseline
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from models.material import Material
from cli.prompts      import (
    prompt_float, prompt_int, prompt_str, prompt_confirm, prompt_choice,
)
import engine
from engine.material_engine import inventory_status
from data.store import (
    add_custom_material, save_materials,
    load_sites, save_sites,
)


# ─────────────────────────────────────────────────────────────────── #
#  Shared helpers                                                      #
# ─────────────────────────────────────────────────────────────────── #

def _pick_material(materials: Dict[str, Material], verb: str = "work with") -> Material:
    names = sorted(materials.keys())
    print(f"\n  Select a material to {verb}:")
    idx = prompt_choice("  Enter number: ", names)
    return materials[names[idx]]


def _show_material_status(mat: Material) -> None:
    print(
        f"\n  +-- {mat.name} ({mat.unit})\n"
        f"  |   Baseline Buffer : {mat.baseline_buffer_pct:.2f}%\n"
        f"  |   Current Buffer  : {mat.buffer_pct:.2f}%\n"
        f"  |   Phases Logged   : {len(mat.history)}\n"
        f"  |   Weight / unit   : {mat.weight_per_unit} kg\n"
        f"  |   Priority        : {mat.priority}/10\n"
        f"  +{'─' * 38}"
    )


# ─────────────────────────────────────────────────────────────────── #
#  Phase 1 — Project Initialization                                   #
# ─────────────────────────────────────────────────────────────────── #

def workflow_initialize_phase(materials: Dict[str, Material]) -> None:
    """
    Phase 1: Record baseline planned quantities for a new project phase.
    Prints a confirmation summary — no quantities are deducted yet.
    """
    print("\n  ── Phase 1: Project Initialization ──────────────────────")
    phase_name = prompt_str("  Phase name (e.g. Foundation): ")
    n_materials = prompt_int("  How many materials to plan? : ", min_val=1)

    plan: List[tuple] = []
    for i in range(n_materials):
        mat      = _pick_material(materials, f"plan [{i + 1}/{n_materials}]")
        qty      = prompt_float(f"  Planned quantity for {mat.name}: ", min_val=0.001)
        plan.append((mat, qty))

    print(f"\n  {'─' * 56}")
    print(f"  Phase '{phase_name}' — Planned Requirements")
    print(f"  {'─' * 56}")
    for mat, qty in plan:
        print(f"  {mat.name:<16} {qty:>10.3f} {mat.unit}")
    print(f"  {'─' * 56}")
    print("  ✔  Baseline quantities recorded. Proceed to Phase 2 to order.\n")


# ─────────────────────────────────────────────────────────────────── #
#  Phase 2 — Smart Ordering                                            #
# ─────────────────────────────────────────────────────────────────── #

def workflow_smart_order(materials: Dict[str, Material]) -> None:
    """
    Phase 2: Calculate the recommended order quantity with buffer.
    """
    print("\n  ── Phase 2: Smart Ordering ───────────────────────────────")
    mat = _pick_material(materials, "get an order recommendation for")
    _show_material_status(mat)

    planned     = prompt_float("\n  Planned quantity needed: ", min_val=0.001)
    recommended = engine.recommend_order_qty(mat, planned)

    print(
        f"\n  Planned        : {planned:.3f} {mat.unit}\n"
        f"  Buffer Applied : {mat.buffer_pct:.2f}%\n"
        f"  ─────────────────────────────────────\n"
        f"  Recommended Qty: {recommended:.3f} {mat.unit}  ← order this amount\n"
    )


# ─────────────────────────────────────────────────────────────────── #
#  Phase 3 — Inventory & Consumption Tracking                          #
# ─────────────────────────────────────────────────────────────────── #

def workflow_track_inventory(materials: Dict[str, Material]) -> None:
    """
    Phase 3: Track how much has been used and what remains.
    """
    print("\n  ── Phase 3: Inventory & Consumption Tracking ─────────────")
    mat = _pick_material(materials, "track inventory for")

    ordered_qty  = prompt_float("  Ordered quantity            : ", min_val=0.001)
    carry_in     = prompt_float("  Carry-in stock from before  : ", min_val=0.0, allow_zero=True)
    consumed_qty = prompt_float("  Quantity consumed so far    : ", min_val=0.0, allow_zero=True)

    status = inventory_status(ordered_qty, consumed_qty, carry_in)

    print(
        f"\n  {'─' * 48}\n"
        f"  Material         : {mat.name} ({mat.unit})\n"
        f"  Total Available  : {status['total_available']:.3f}\n"
        f"  Used             : {status['used']:.3f}\n"
        f"  Remaining        : {status['remaining']:.3f}\n"
        f"  Utilisation      : {status['utilization_pct']:.1f}%\n"
        f"  {'─' * 48}\n"
    )


# ─────────────────────────────────────────────────────────────────── #
#  Phase 4 — Reorder Monitoring                                        #
# ─────────────────────────────────────────────────────────────────── #

def workflow_reorder_check(materials: Dict[str, Material]) -> None:
    """
    Phase 4: Check if remaining stock is low and alert if reorder is needed.
    """
    print("\n  ── Phase 4: Reorder Monitoring ───────────────────────────")
    mat = _pick_material(materials, "check reorder for")

    ordered_qty  = prompt_float("  Ordered quantity            : ", min_val=0.001)
    remaining    = prompt_float("  Current remaining stock     : ", min_val=0.0, allow_zero=True)
    planned_qty  = prompt_float("  Planned qty for next phase  : ", min_val=0.001)

    result = engine.check_reorder(mat, ordered_qty, remaining, planned_qty)

    if result["alert"]:
        print(
            f"\n  ⚠  REORDER ALERT for {mat.name}\n"
            f"  Remaining        : {result['remaining']:.3f} {mat.unit}\n"
            f"  Threshold        : {result['threshold_qty']:.3f} {mat.unit}  (≤20% of order)\n"
            f"  Suggested Reorder: {result['suggested_reorder_qty']:.3f} {mat.unit}\n"
        )
    else:
        print(
            f"\n  ✔  Stock is sufficient for {mat.name}.\n"
            f"  Remaining  : {result['remaining']:.3f} {mat.unit}\n"
            f"  Threshold  : {result['threshold_qty']:.3f} {mat.unit}\n"
        )


# ─────────────────────────────────────────────────────────────────── #
#  Phase 5 + 6 — Waste Review & Adaptive Update                        #
# ─────────────────────────────────────────────────────────────────── #

def workflow_complete_phase(materials: Dict[str, Material]) -> None:
    """
    Phase 5: Record actual consumption and compute real waste.
    Phase 6: Automatically adapts the buffer for the next ordering cycle.
    """
    print("\n  ── Phase 5: Waste Review  +  Phase 6: Adaptive Update ────")
    mat = _pick_material(materials, "complete a phase for")
    _show_material_status(mat)

    phase_name   = prompt_str("\n  Phase name (e.g. Foundation): ")
    planned_qty  = prompt_float("  Planned quantity            : ", min_val=0.001)
    ordered_qty  = prompt_float("  Actual quantity ordered     : ", min_val=0.001)
    consumed_qty = prompt_float("  Actual quantity consumed    : ", min_val=0.0, allow_zero=True)
    carry_in     = prompt_float("  Carry-in stock from before  : ", min_val=0.0, allow_zero=True)

    record = engine.record_phase(
        mat, phase_name, planned_qty, ordered_qty, consumed_qty, carry_in
    )
    print(engine.phase_summary(mat, record))

    save_materials(materials)
    print("  ✔  Phase recorded. Buffer updated. Data saved.\n")


# ─────────────────────────────────────────────────────────────────── #
#  Delivery Planning — Truck Load + Route Optimisation                 #
# ─────────────────────────────────────────────────────────────────── #

def workflow_plan_delivery(materials: Dict[str, Material]) -> None:
    """
    Plan truck loads (knapsack) and optimise delivery routes (CVRP).
    """
    print("\n  ── Delivery Planning: Truck Load & Route Optimisation ────")
    sites = load_sites()
    depot = sites[0]
    delivery_sites = sites[1:]

    if not delivery_sites:
        print("  No delivery sites configured.\n")
        return

    # Collect order quantities for each material
    print("\n  Enter order quantities to dispatch (0 = skip material):")
    order_quantities: Dict[str, float] = {}
    for name in sorted(materials.keys()):
        mat = materials[name]
        qty_str = input(f"    {name:<16} ({mat.unit}): ").strip()
        try:
            qty = float(qty_str)
            if qty > 0:
                order_quantities[name] = qty
        except ValueError:
            pass

    if not order_quantities:
        print("  No quantities entered. Returning.\n")
        return

    # Truck fleet
    n_trucks = prompt_int("\n  Number of trucks: ", min_val=1, max_val=20)
    trucks   = []
    for k in range(n_trucks):
        tid  = prompt_str(f"  Truck {k + 1} ID      : ")
        cap  = prompt_int(f"  Truck {k + 1} capacity (kg): ", min_val=1)
        trucks.append({"truck_id": tid, "capacity_kg": cap})

    rain = prompt_confirm("\n  Rain expected? (boosts priority for Cement/Sand/Wood)")

    # Phase 2 supplement — optimise loads
    assignments = engine.optimize_truck_loads(
        materials, order_quantities, trucks, rain_expected=rain
    )

    # Phase 3 supplement — optimise routes
    vehicle_capacity = trucks[0]["capacity_kg"] if trucks else 1000
    assignments = engine.solve_routes(
        depot, delivery_sites, assignments, vehicle_capacity
    )

    # Print results
    print(f"\n  {'═' * 60}")
    print(f"  Delivery Plan Summary")
    print(f"  {'═' * 60}")
    for a in assignments:
        mat_counts = Counter(a.materials_loaded)
        load_str = ", ".join(f"{m} ×{c}" for m, c in mat_counts.items()) or "— empty —"
        route_str = " → ".join(a.route) if a.route else "—"

        print(
            f"\n  Truck        : {a.truck_id}\n"
            f"  Capacity     : {a.capacity_kg} kg\n"
            f"  Loaded       : {a.used_capacity_kg} kg  ({a.utilization_pct:.1f}% utilised)\n"
            f"  Materials    : {load_str}\n"
            f"  Route        : {route_str}\n"
            f"  Distance     : {a.distance_km} km\n"
            f"  CO₂ Estimate : {a.co2_kg} kg\n"
            f"  {'─' * 58}"
        )
    print()


# ─────────────────────────────────────────────────────────────────── #
#  Utility workflows                                                   #
# ─────────────────────────────────────────────────────────────────── #

def workflow_view_report(materials: Dict[str, Material]) -> None:
    """Print the full history report for one material."""
    mat = _pick_material(materials, "view report for")
    print(engine.material_report(mat))


def workflow_all_materials(materials: Dict[str, Material]) -> None:
    """Print a one-line status for every material."""
    print(
        f"\n  {'Material':<14} {'Unit':<8} {'Baseline%':>10} "
        f"{'Buffer%':>8} {'Wt/unit(kg)':>12} {'Priority':>9} {'Phases':>7}"
    )
    print(f"  {'─' * 72}")
    for name in sorted(materials.keys()):
        m = materials[name]
        print(
            f"  {m.name:<14} {m.unit:<8} "
            f"{m.baseline_buffer_pct:>9.2f}% "
            f"{m.buffer_pct:>7.2f}% "
            f"{m.weight_per_unit:>12.1f} "
            f"{m.priority:>9} "
            f"{len(m.history):>7}"
        )
    print()


def workflow_add_material(materials: Dict[str, Material]) -> None:
    """Register a brand-new material."""
    print("\n  ── Add New Material ──────────────────────────────────────")
    name   = prompt_str("  Material name       : ")
    unit   = prompt_str("  Unit of measure     : ")
    buf    = prompt_float("  Starting buffer %   : ", min_val=0.0, max_val=100.0, allow_zero=True)
    weight = prompt_float("  Weight per unit (kg): ", min_val=0.001)
    prio   = prompt_int("  Priority (1–10)     : ", min_val=1, max_val=10)

    mat = add_custom_material(materials, name, unit, buf, weight, prio)
    print(f"\n  ✔  '{mat.name}' added with {mat.buffer_pct:.2f}% buffer, "
          f"{mat.weight_per_unit} kg/unit, priority {mat.priority}.\n")


def workflow_reset_buffer(materials: Dict[str, Material]) -> None:
    """Reset the adaptive buffer back to its baseline."""
    mat = _pick_material(materials, "reset buffer for")
    if prompt_confirm(
        f"\n  Reset '{mat.name}' buffer from {mat.buffer_pct:.2f}% "
        f"to {mat.baseline_buffer_pct:.2f}%?"
    ):
        mat.buffer_pct = mat.baseline_buffer_pct
        save_materials(materials)
        print(f"  ✔  Buffer reset to {mat.buffer_pct:.2f}%.\n")
    else:
        print("  Cancelled.\n")
