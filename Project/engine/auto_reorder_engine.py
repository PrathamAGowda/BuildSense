"""
BuildSense — Intelligent Auto-Reorder Engine
═════════════════════════════════════════════
Monitors stock in real-time as daily usage is logged.
When stock is predicted to run out within a configurable horizon,
it automatically:

  1. Computes an EMA-smoothed consumption rate from recent daily logs.
  2. Predicts the stockout date.
  3. Determines the optimal reorder quantity using Phase 2 Smart Order logic.
  4. Sources that quantity from the supply network using Clarke-Wright VRP
     (exactly the same engine used by the Supply Planner tab).
  5. Returns a fully structured AutoReorderAlert so the UI can show it
     inline — no extra user input needed.

AI Techniques Used
──────────────────
• EMA (Exponential Moving Average) on daily consumption — adapts to
  accelerating or decelerating usage, weights recent days more heavily.
• Remaining-days prediction using smoothed rate — avoids step-function
  alerts from noisy single-day spikes.
• Clarke-Wright Savings VRP for supply routing (via supply_engine).
• Reorder quantity derived from the adaptive buffer (itself trained by
  prior phase EMA updates in material_engine.py).

All computation is O(n log n) or better — no external ML dependencies.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from models.material import Material, PhaseRecord

# ─────────────────────────────────────────────────────────────────── #
#  Tuneable constants                                                   #
# ─────────────────────────────────────────────────────────────────── #

EMA_ALPHA         = 0.35   # EMA smoothing factor for consumption rate
                            # higher → reacts faster to recent spikes
REORDER_HORIZON   = 7      # trigger alert when stock < N days of supply
CRITICAL_HORIZON  = 3      # "critical" flag when < N days left
MIN_DAYS_DATA     = 2      # minimum daily entries needed to make a prediction


# ─────────────────────────────────────────────────────────────────── #
#  EMA rate estimator                                                  #
# ─────────────────────────────────────────────────────────────────── #

def _ema_daily_rate(phase: PhaseRecord, alpha: float = EMA_ALPHA) -> Optional[float]:
    """
    Compute an EMA-smoothed daily consumption rate from the phase's
    daily_usage log.

    Entries are sorted chronologically. The EMA gives exponentially
    more weight to recent days, so a sudden usage surge is captured
    quickly while isolated spikes don't dominate.

    Returns None if there are fewer than MIN_DAYS_DATA entries.
    """
    if not phase.daily_usage or len(phase.daily_usage) < MIN_DAYS_DATA:
        return None

    # Sort entries by date ascending
    entries = sorted(phase.daily_usage, key=lambda e: e.date)

    # Seed EMA with the first entry
    ema = entries[0].quantity
    for entry in entries[1:]:
        ema = alpha * entry.quantity + (1 - alpha) * ema

    return round(ema, 4)


# ─────────────────────────────────────────────────────────────────── #
#  Stockout prediction                                                 #
# ─────────────────────────────────────────────────────────────────── #

def predict_stockout(phase: PhaseRecord, on_order_qty: float = 0.0) -> dict:
    """
    Given the current phase, predict how many days until stock runs out.

    Parameters
    ----------
    phase        : The current PhaseRecord.
    on_order_qty : Quantity already ordered (pending/approved reorders) that
                   has not yet arrived but is guaranteed — added to remaining
                   stock so we don't re-alert when an order is in flight.

    Returns
    -------
    {
      "ema_rate":          float | None   — EMA-smoothed daily consumption
      "days_remaining":    float | None   — estimated days until stockout
      "stockout_date":     str   | None   — ISO date of predicted stockout
      "remaining_stock":   float          — physical stock only
      "effective_stock":   float          — remaining + on_order_qty
      "on_order_qty":      float
      "insufficient_data": bool
    }
    """
    rate = _ema_daily_rate(phase)
    remaining = phase.remaining_stock
    effective = remaining + on_order_qty

    if rate is None or rate <= 0:
        return {
            "ema_rate":          rate,
            "days_remaining":    None,
            "stockout_date":     None,
            "remaining_stock":   remaining,
            "effective_stock":   effective,
            "on_order_qty":      on_order_qty,
            "insufficient_data": True,
        }

    days_left   = effective / rate          # use effective (stock + on-order)
    stockout_dt = date.today() + timedelta(days=days_left)

    return {
        "ema_rate":          rate,
        "days_remaining":    round(days_left, 1),
        "stockout_date":     stockout_dt.isoformat(),
        "remaining_stock":   remaining,
        "effective_stock":   round(effective, 4),
        "on_order_qty":      on_order_qty,
        "insufficient_data": False,
    }


# ─────────────────────────────────────────────────────────────────── #
#  Auto-reorder check                                                  #
# ─────────────────────────────────────────────────────────────────── #

def check_auto_reorder(
    material: Material,
    phase_index: int,
    *,
    dest_lat: Optional[float] = None,
    dest_lon: Optional[float] = None,
    dest_name: str = "Construction Site",
    horizon_days: int = REORDER_HORIZON,
    on_order_qty: float = 0.0,
) -> dict:
    """
    Core auto-reorder decision logic.

    Parameters
    ----------
    material     : Material object (with history and daily_usage populated).
    phase_index  : Which phase to evaluate.
    dest_lat/lon : Site GPS — used to source materials from supply network.
                   If None, supply routing is skipped (alert only mode).
    horizon_days : Number of days ahead to check; default REORDER_HORIZON.
    on_order_qty : Sum of quantities already ordered (pending + approved
                   reorders still in flight). Added to remaining stock when
                   computing days_remaining — prevents duplicate alerts when
                   a reorder has already been placed.

    Returns
    -------
    {
      "triggered":      bool       — True if reorder should be placed
      "critical":       bool       — True if < CRITICAL_HORIZON days left
      "reason":         str        — human-readable explanation
      "prediction":     dict       — stockout prediction details
      "reorder_qty":    float      — recommended quantity to order
      "supply_plan":    dict|None  — full Clarke-Wright VRP plan (if coords given)
      "material":       str
      "unit":           str
    }
    """
    if phase_index < 0 or phase_index >= len(material.history):
        return {"triggered": False, "reason": "Invalid phase index."}

    phase      = material.history[phase_index]
    prediction = predict_stockout(phase, on_order_qty=on_order_qty)

    # Can't make a decision without enough data
    if prediction["insufficient_data"]:
        return {
            "triggered":   False,
            "critical":    False,
            "reason":      f"Need at least {MIN_DAYS_DATA} daily usage entries to predict stockout.",
            "prediction":  prediction,
            "reorder_qty": 0.0,
            "supply_plan": None,
            "material":    material.name,
            "unit":        material.unit,
        }

    days_left = prediction["days_remaining"]
    triggered = days_left is not None and days_left <= horizon_days
    critical  = days_left is not None and days_left <= CRITICAL_HORIZON

    if not triggered:
        suffix = f" (includes {on_order_qty:.2f} {material.unit} on order)" if on_order_qty > 0 else ""
        return {
            "triggered":   False,
            "critical":    False,
            "reason":      f"Stock sufficient — {days_left:.1f} days remaining (threshold: {horizon_days} days){suffix}.",
            "prediction":  prediction,
            "reorder_qty": 0.0,
            "supply_plan": None,
            "material":    material.name,
            "unit":        material.unit,
        }

    # ── Compute reorder quantity ─────────────────────────────────── #
    # Cap at what the phase actually still needs: planned - already ordered/consumed.
    ema_rate      = prediction["ema_rate"]
    days_to_cover = max(horizon_days * 2, 14)   # order enough for 2× horizon
    raw_reorder   = ema_rate * days_to_cover     # units needed to cover window

    # Phase-aware cap: don't order more than what the phase plan requires
    phase_still_needs = max(0.0, phase.planned_qty - phase.ordered_qty - phase.consumed_qty)
    if phase_still_needs > 0:
        raw_reorder = min(raw_reorder, phase_still_needs)

    buffered_qty  = round(raw_reorder * (1 + material.buffer_pct / 100), 2)

    reason_parts = [
        f"Stock will run out in ≈{days_left:.1f} days (EMA rate: {ema_rate:.2f} {material.unit}/day).",
        f"Reorder triggered — threshold is {horizon_days} days.",
    ]
    if critical:
        reason_parts.append("⚠ CRITICAL: Less than 3 days of stock remaining!")

    # ── Source from supply network if destination is known ────────── #
    supply_plan = None
    if dest_lat is not None and dest_lon is not None:
        try:
            from engine.supply_engine import plan_supply
            requirements = [{
                "material":    material.name,
                "qty":         buffered_qty,
                "unit_weight": material.weight_per_unit,
            }]
            supply_plan = plan_supply(
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                dest_name=dest_name,
                requirements=requirements,
            )
        except Exception as e:
            supply_plan = {"error": str(e)}

    return {
        "triggered":   True,
        "critical":    critical,
        "reason":      " ".join(reason_parts),
        "prediction":  prediction,
        "reorder_qty": buffered_qty,
        "days_to_cover": days_to_cover,
        "supply_plan": supply_plan,
        "material":    material.name,
        "unit":        material.unit,
    }


# ─────────────────────────────────────────────────────────────────── #
#  Batch check — all materials in a phase snapshot                     #
# ─────────────────────────────────────────────────────────────────── #

def check_all_materials(
    materials: Dict[str, Material],
    *,
    dest_lat: Optional[float] = None,
    dest_lon: Optional[float] = None,
    dest_name: str = "Construction Site",
    horizon_days: int = REORDER_HORIZON,
    on_order_map: Optional[Dict[str, float]] = None,
) -> List[dict]:
    """
    Run auto-reorder check across ALL materials (latest phase each).

    Parameters
    ----------
    on_order_map : dict mapping material name → qty already on order
                   (pending + approved reorders). Used to avoid re-alerting
                   when a reorder is already in flight.

    Returns a list of alert dicts, sorted: critical first, then triggered,
    then non-triggered — so the UI can show the most urgent first.
    """
    if on_order_map is None:
        on_order_map = {}

    alerts = []
    for mat in materials.values():
        if not mat.history:
            continue
        phase_index = len(mat.history) - 1
        on_order = on_order_map.get(mat.name, 0.0)
        alert = check_auto_reorder(
            mat,
            phase_index,
            dest_lat=dest_lat,
            dest_lon=dest_lon,
            dest_name=dest_name,
            horizon_days=horizon_days,
            on_order_qty=on_order,
        )
        alerts.append(alert)

    # Sort: critical → triggered → not triggered
    def sort_key(a):
        if a.get("critical"):   return 0
        if a.get("triggered"):  return 1
        return 2

    alerts.sort(key=sort_key)
    return alerts
