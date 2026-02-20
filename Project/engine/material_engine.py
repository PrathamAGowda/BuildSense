"""
BuildSense — Material Engine
─────────────────────────────
Covers Phases 1–6 of the workflow:

  Phase 1 – Project Initialization  : baseline planned quantities
  Phase 2 – Smart Ordering          : recommend_order_qty (planned + buffer)
  Phase 3 – Inventory Tracking      : inventory_status / log_daily_usage / get_usage_trend
  Phase 4 – Reorder Monitoring      : check_reorder
  Phase 5 – Waste Review            : evaluate_waste / record_phase
  Phase 6 – Adaptive Update         : update_buffer (EMA)
"""

from datetime import date, datetime, timedelta
from typing import Optional
from models.material import Material, PhaseRecord, DailyUsageEntry
from data.store import load_materials, save_materials

MOVING_AVG_WEIGHT   = 0.3    # EMA weight — 0.3 = moderate adaptation
REORDER_THRESHOLD   = 0.20   # trigger reorder when remaining ≤ 20 % of ordered


# ─────────────────────────────────────────────────────────────────── #
#  Phase 2 — Smart Ordering                                            #
# ─────────────────────────────────────────────────────────────────── #

def recommend_order_qty(material: Material, planned_qty: float) -> float:
    """
    Recommended order = planned_qty × (1 + buffer_pct / 100).
    The buffer absorbs expected waste so the phase does not run short.
    """
    if planned_qty <= 0:
        raise ValueError("Planned quantity must be greater than zero.")
    return round(planned_qty * (1 + material.buffer_pct / 100), 3)


# ─────────────────────────────────────────────────────────────────── #
#  Phase 5 — Waste Review                                              #
# ─────────────────────────────────────────────────────────────────── #

def evaluate_waste(ordered_qty: float, consumed_qty: float) -> float:
    """
    Waste % = (ordered − consumed) / ordered × 100.

    Positive  → over-ordered (waste / surplus).
    Negative  → under-ordered (deficit, ran short).
    """
    if ordered_qty <= 0:
        raise ValueError("Ordered quantity must be greater than zero.")
    return round(((ordered_qty - consumed_qty) / ordered_qty) * 100, 4)


# ─────────────────────────────────────────────────────────────────── #
#  Phase 6 — Adaptive Buffer Update (EMA)                              #
# ─────────────────────────────────────────────────────────────────── #

def update_buffer(material: Material, actual_waste_pct: float) -> float:
    """
    new_buffer = (1 − α) × old_buffer + α × actual_waste_pct
    Clamped to [0, 100]. Returns the updated buffer value.

    This implements Phase 6: Adaptive Update — the system learns from
    real consumption to make each ordering cycle smarter.
    """
    a = MOVING_AVG_WEIGHT
    new = (1 - a) * material.buffer_pct + a * actual_waste_pct
    material.buffer_pct = round(max(0.0, min(100.0, new)), 4)
    return material.buffer_pct


# ─────────────────────────────────────────────────────────────────── #
#  Phase 3 — Inventory Status                                          #
# ─────────────────────────────────────────────────────────────────── #

def inventory_status(ordered_qty: float, consumed_qty: float, carry_in: float = 0.0) -> dict:
    """
    Returns a snapshot of real-time inventory (Phase 3).

    Returns:
        dict with keys: total_available, used, remaining, utilization_pct
    """
    total_available = ordered_qty + carry_in
    remaining       = max(0.0, round(total_available - consumed_qty, 4))
    utilization     = round(consumed_qty / total_available * 100, 2) if total_available > 0 else 0.0
    return {
        "total_available":  round(total_available, 4),
        "used":             round(consumed_qty, 4),
        "remaining":        remaining,
        "utilization_pct":  utilization,
    }


# ─────────────────────────────────────────────────────────────────── #
#  Phase 4 — Reorder Monitoring                                        #
# ─────────────────────────────────────────────────────────────────── #

def check_reorder(
    material:    Material,
    ordered_qty: float,
    remaining:   float,
    planned_qty: float,
) -> dict:
    """
    Phase 4: Reorder Monitoring.

    Triggers a reorder alert when remaining stock falls at or below
    REORDER_THRESHOLD × ordered_qty.

    Returns:
        dict with keys: alert (bool), remaining, threshold_qty, suggested_reorder_qty
    """
    threshold_qty        = round(REORDER_THRESHOLD * ordered_qty, 4)
    alert                = remaining <= threshold_qty
    suggested_reorder    = recommend_order_qty(material, planned_qty) if alert else 0.0
    return {
        "alert":               alert,
        "remaining":           round(remaining, 4),
        "threshold_qty":       threshold_qty,
        "suggested_reorder_qty": suggested_reorder,
    }


# ─────────────────────────────────────────────────────────────────── #
#  Phase 5 + 6 — Record a completed phase                              #
# ─────────────────────────────────────────────────────────────────── #

def record_phase(
    material:     Material,
    phase_name:   str,
    planned_qty:  float,
    ordered_qty:  float,
    consumed_qty: float,
    carry_in:     float = 0.0,
) -> PhaseRecord:
    """
    Finalise a phase (Phases 5 & 6):
      - calculate actual waste %
      - compute remaining stock
      - update the adaptive buffer via EMA (Phase 6)
      - append PhaseRecord to material history
      - return the PhaseRecord
    """
    waste_pct       = evaluate_waste(ordered_qty, consumed_qty)
    remaining_stock = max(0.0, round(ordered_qty + carry_in - consumed_qty, 4))

    record = PhaseRecord(
        phase_name=phase_name,
        planned_qty=planned_qty,
        ordered_qty=ordered_qty,
        consumed_qty=consumed_qty,
        waste_pct=waste_pct,
        remaining_stock=remaining_stock,
    )
    material.history.append(record)
    update_buffer(material, waste_pct)   # Phase 6: adaptive update
    return record


# ─────────────────────────────────────────────────────────────────── #
#  Daily Usage Logging                                                 #
# ─────────────────────────────────────────────────────────────────── #

def log_daily_usage(
    material: Material,
    phase_index: int,
    qty_used: float,
    usage_date: Optional[str] = None,
) -> PhaseRecord:
    """Append one day's usage to a phase and recompute consumed/remaining.

    This lets usage vary day by day instead of assuming a constant rate.
    Raises ValueError if logging qty_used would exceed the ordered stock.
    """
    if phase_index < 0 or phase_index >= len(material.history):
        raise IndexError("Invalid phase index for material history.")

    phase = material.history[phase_index]

    if usage_date is None:
        usage_date = date.today().isoformat()

    # Enforce stock limit: cannot consume more than what was ordered
    already_consumed = sum(e.quantity for e in phase.daily_usage)
    total_after = already_consumed + qty_used
    if total_after > phase.ordered_qty:
        available = max(0.0, round(phase.ordered_qty - already_consumed, 4))
        raise ValueError(
            f"Cannot log {qty_used} {material.unit} — only {available} {material.unit} "
            f"remaining in stock for phase '{phase.phase_name}' "
            f"(ordered: {phase.ordered_qty}, already consumed: {round(already_consumed, 4)})."
        )

    phase.daily_usage.append(DailyUsageEntry(date=usage_date, quantity=qty_used))

    # Recompute aggregates from daily_usage
    total_consumed = sum(entry.quantity for entry in phase.daily_usage)
    phase.consumed_qty = total_consumed
    phase.remaining_stock = max(0.0, round(phase.ordered_qty - total_consumed, 4))

    return phase


def get_usage_trend(
    material: Material,
    phase_index: int,
    days: int = 7,
) -> dict:
    """Compute consumption rate metrics for a phase, accounting for calendar gaps.

    Returns a dict with:
        avg_per_active_day  — total / number of days that had a log entry
        avg_per_calendar_day — total / actual calendar days elapsed (first→last entry)
        total_consumed      — sum of all daily_usage quantities
        active_days         — number of distinct dates logged
        calendar_days       — calendar days from first to last log (inclusive)
        days_remaining_est  — estimated days until stock runs out (at calendar rate)
    """
    if phase_index < 0 or phase_index >= len(material.history):
        return _empty_trend()

    phase = material.history[phase_index]
    if not phase.daily_usage:
        return _empty_trend()

    cutoff = datetime.today().date() - timedelta(days=days)
    recent = [
        e for e in phase.daily_usage
        if datetime.fromisoformat(e.date).date() >= cutoff
    ]
    if not recent:
        # Fall back to all-time data
        recent = list(phase.daily_usage)

    total         = sum(e.quantity for e in recent)
    active_days   = len(recent)

    dates = sorted(datetime.fromisoformat(e.date).date() for e in recent)
    if len(dates) >= 2:
        calendar_days = (dates[-1] - dates[0]).days + 1  # inclusive span
    else:
        calendar_days = 1

    avg_active   = round(total / active_days, 4)
    avg_calendar = round(total / calendar_days, 4)

    remaining = phase.remaining_stock
    days_left  = round(remaining / avg_calendar, 1) if avg_calendar > 0 else None

    return {
        "avg_per_active_day":   avg_active,
        "avg_per_calendar_day": avg_calendar,
        "total_consumed":       round(total, 4),
        "active_days":          active_days,
        "calendar_days":        calendar_days,
        "days_remaining_est":   days_left,
    }


def _empty_trend() -> dict:
    return {
        "avg_per_active_day":   0.0,
        "avg_per_calendar_day": 0.0,
        "total_consumed":       0.0,
        "active_days":          0,
        "calendar_days":        0,
        "days_remaining_est":   None,
    }


# ─────────────────────────────────────────────────────────────────── #
#  Display helpers                                                     #
# ─────────────────────────────────────────────────────────────────── #

def phase_summary(material: Material, record: PhaseRecord) -> str:
    """Return a formatted, human-readable summary of a completed phase."""
    direction = "over-ordered" if record.waste_pct >= 0 else "under-ordered"
    return "\n".join([
        "",
        f"  {'─' * 58}",
        f"  Phase Complete   : {record.phase_name}",
        f"  Material         : {material.name} ({material.unit})",
        f"  {'─' * 58}",
        f"  Planned Qty      : {record.planned_qty:>10.3f} {material.unit}",
        f"  Ordered Qty      : {record.ordered_qty:>10.3f} {material.unit}",
        f"  Consumed Qty     : {record.consumed_qty:>10.3f} {material.unit}",
        f"  Remaining Stock  : {record.remaining_stock:>10.3f} {material.unit}",
        f"  {'─' * 58}",
        f"  Actual Waste %   : {record.waste_pct:>+.2f}%  ({direction})",
        f"  New Buffer %     : {material.buffer_pct:.2f}%   ← adaptive update",
        f"  Baseline Buffer  : {material.baseline_buffer_pct:.2f}%",
        f"  Phases Logged    : {len(material.history)}",
        f"  {'─' * 58}",
        "",
    ])


def material_report(material: Material) -> str:
    """Full history report for a single material."""
    if not material.history:
        return f"\n  No phase history recorded for '{material.name}'.\n"

    lines = [
        "",
        f"  {'=' * 58}",
        f"  Material Report  : {material.name} ({material.unit})",
        f"  Baseline Buffer  : {material.baseline_buffer_pct:.2f}%"
        f"   →   Current Buffer: {material.buffer_pct:.2f}%",
        f"  {'=' * 58}",
    ]

    total_ordered  = 0.0
    total_consumed = 0.0

    for i, r in enumerate(material.history, 1):
        total_ordered  += r.ordered_qty
        total_consumed += r.consumed_qty
        lines.append(
            f"  [{i:>2}] {r.phase_name:<20} "
            f"Planned: {r.planned_qty:>8.3f}  "
            f"Ordered: {r.ordered_qty:>8.3f}  "
            f"Consumed: {r.consumed_qty:>8.3f}  "
            f"Waste: {r.waste_pct:>+6.2f}%  "
            f"Remaining: {r.remaining_stock:>7.3f}"
        )

    overall = evaluate_waste(total_ordered, total_consumed) if total_ordered else 0.0
    lines += [
        f"  {'─' * 58}",
        f"  Total Ordered  : {total_ordered:.3f}   "
        f"Consumed: {total_consumed:.3f}   "
        f"Overall Waste: {overall:+.2f}%",
        f"  {'=' * 58}",
        "",
    ]
    return "\n".join(lines)
