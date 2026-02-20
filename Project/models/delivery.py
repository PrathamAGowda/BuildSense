"""
Delivery / routing models — delivery sites and truck assignments.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class DeliveryPoint:
    """
    A construction site that needs materials delivered.
    """
    name:     str
    lat:      float
    lon:      float
    demand:   int    # total weight units requested (kg)

    @property
    def coords(self) -> Tuple[float, float]:
        return (self.lat, self.lon)

    def to_dict(self) -> dict:
        return {
            "name":   self.name,
            "lat":    self.lat,
            "lon":    self.lon,
            "demand": self.demand,
        }

    @staticmethod
    def from_dict(d: dict) -> "DeliveryPoint":
        return DeliveryPoint(
            name=d["name"],
            lat=d["lat"],
            lon=d["lon"],
            demand=d["demand"],
        )


@dataclass
class TruckAssignment:
    """
    Result of one truck's optimised delivery run.
    """
    truck_id:         str
    capacity_kg:      int
    materials_loaded: List[str]   = field(default_factory=list)
    used_capacity_kg: int         = 0
    route:            List[str]   = field(default_factory=list)  # site names in order
    distance_km:      float       = 0.0
    co2_kg:           float       = 0.0

    @property
    def utilization_pct(self) -> float:
        if self.capacity_kg == 0:
            return 0.0
        return round(self.used_capacity_kg / self.capacity_kg * 100, 2)
