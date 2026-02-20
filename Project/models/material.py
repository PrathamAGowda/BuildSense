"""
Material model — represents a construction material and its phase history.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class DailyUsageEntry:
    """Single daily usage entry for a phase (date + quantity)."""
    date: str       # ISO date string, e.g. "2026-02-20"
    quantity: float # quantity used that day


@dataclass
class PhaseRecord:
    """
    Stores the planned and actual quantities for one completed project phase.
    """
    phase_name:      str
    planned_qty:     float   # baseline requirement entered at phase start
    ordered_qty:     float   # what was actually ordered
    consumed_qty:    float   # what was actually used (sum of daily_usage)
    waste_pct:       float   # (ordered − consumed) / ordered × 100
    remaining_stock: float   # stock left over after phase
    daily_usage:     List[DailyUsageEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase_name":      self.phase_name,
            "planned_qty":     self.planned_qty,
            "ordered_qty":     self.ordered_qty,
            "consumed_qty":    self.consumed_qty,
            "waste_pct":       round(self.waste_pct, 4),
            "remaining_stock": round(self.remaining_stock, 4),
            "daily_usage": [
                {"date": e.date, "quantity": e.quantity} for e in self.daily_usage
            ],
        }

    @staticmethod
    def from_dict(d: dict) -> "PhaseRecord":
        # Backwards compatible: daily_usage may be missing
        entries = [
            DailyUsageEntry(date=e["date"], quantity=e["quantity"])
            for e in d.get("daily_usage", [])
        ]
        return PhaseRecord(
            phase_name=d["phase_name"],
            planned_qty=d["planned_qty"],
            ordered_qty=d["ordered_qty"],
            consumed_qty=d["consumed_qty"],
            waste_pct=d["waste_pct"],
            remaining_stock=d["remaining_stock"],
            daily_usage=entries,
        )


@dataclass
class Material:
    """
    A tracked construction material with an adaptive waste buffer.
    buffer_pct evolves over time via EMA as real consumption data arrives.
    history holds every completed PhaseRecord for this material.
    """
    name:                str
    unit:                str     # e.g. "bags", "pcs", "kg", "tons"
    baseline_buffer_pct: float   # buffer set at first initialisation
    buffer_pct:          float   # live adaptive buffer (updated after each phase)
    weight_per_unit:     float   # kg per unit — used for truck load planning
    priority:            int     # 1–10, used for truck load allocation priority
    history:             List[PhaseRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name":                self.name,
            "unit":                self.unit,
            "baseline_buffer_pct": self.baseline_buffer_pct,
            "buffer_pct":          round(self.buffer_pct, 4),
            "weight_per_unit":     self.weight_per_unit,
            "priority":            self.priority,
            "history":             [r.to_dict() for r in self.history],
        }

    @staticmethod
    def from_dict(d: dict) -> "Material":
        history = [PhaseRecord.from_dict(r) for r in d.get("history", [])]
        return Material(
            name=d["name"],
            unit=d["unit"],
            baseline_buffer_pct=d["baseline_buffer_pct"],
            buffer_pct=d["buffer_pct"],
            weight_per_unit=d.get("weight_per_unit", 1.0),
            priority=d.get("priority", 5),
            history=history,
        )
