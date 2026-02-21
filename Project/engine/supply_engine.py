"""
BuildSense — Supply Network Engine
────────────────────────────────────
Given a destination site and per-material requirements, this engine:

  1. Selects the best stores from the supply network (greedy by distance).
  2. Assigns each store-run to the nearest available depot.
  3. Solves truck routing using the Clarke-Wright Savings algorithm,
     which is the industry-standard heuristic for VRP (Vehicle Routing
     Problem) and typically finds routes 10–20% shorter than nearest-
     neighbour greedy.
  4. Returns a fully structured plan: which truck carries what, from
     which depot, visiting which stores en-route to the destination.

Algorithm: Clarke-Wright Savings (1964)
───────────────────────────────────────
Idea: start with one truck per store (depot→store→destination).
Then compute the "saving" of merging two routes into one:
    S(i,j) = d(depot,i) + d(depot,j) - d(i,j)
Sort savings descending. Greedily merge route pairs if the merged
truck's load stays under capacity. The result is a good, fast
approximation of the optimal VRP solution with no solver dependency.

Complexity: O(n² log n) — fast even for 55 stores.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────── #
#  Data path                                                           #
# ─────────────────────────────────────────────────────────────────── #

_DATA_DIR    = os.path.dirname(__file__)
_NETWORK_FILE = os.path.join(_DATA_DIR, "..", "data", "supply_network.json")


# ─────────────────────────────────────────────────────────────────── #
#  Load supply network                                                 #
# ─────────────────────────────────────────────────────────────────── #

def load_network() -> dict:
    path = os.path.normpath(_NETWORK_FILE)
    if not os.path.exists(path):
        return {"depots": [], "stores": []}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────── #
#  Geometry                                                            #
# ─────────────────────────────────────────────────────────────────── #

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ─────────────────────────────────────────────────────────────────── #
#  Internal route structure for Clarke-Wright                          #
# ─────────────────────────────────────────────────────────────────── #

@dataclass
class _Route:
    stops: List[str]      = field(default_factory=list)   # store ids in order
    load_kg: float        = 0.0
    km: float             = 0.0


# ─────────────────────────────────────────────────────────────────── #
#  Clarke-Wright Savings VRP                                           #
# ─────────────────────────────────────────────────────────────────── #

def _clarke_wright(
    depot_lat: float,
    depot_lon: float,
    stops: List[Dict],          # [{"id", "lat", "lon", "demand_kg"}]
    capacity_kg: float,
) -> List[_Route]:
    """
    Clarke-Wright savings algorithm for single-depot VRP.

    Returns a list of Routes, each a merged sequence of stop ids,
    respecting the truck capacity.
    """
    if not stops:
        return []

    # 1) Initialise: one route per stop  depot→stop→dest
    routes: Dict[str, _Route] = {}
    stop_map: Dict[str, Dict] = {s["id"]: s for s in stops}

    for s in stops:
        d = haversine(depot_lat, depot_lon, s["lat"], s["lon"])
        routes[s["id"]] = _Route(stops=[s["id"]], load_kg=s["demand_kg"], km=2 * d)

    # 2) Compute savings  S(i,j) = d(0,i)+d(0,j)-d(i,j)
    savings: List[Tuple[float, str, str]] = []
    ids = [s["id"] for s in stops]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = stop_map[ids[i]], stop_map[ids[j]]
            d0a  = haversine(depot_lat, depot_lon, a["lat"], a["lon"])
            d0b  = haversine(depot_lat, depot_lon, b["lat"], b["lon"])
            dab  = haversine(a["lat"], a["lon"], b["lat"], b["lon"])
            sav  = d0a + d0b - dab
            savings.append((sav, ids[i], ids[j]))

    savings.sort(key=lambda x: -x[0])

    # 3) Greedy merge
    # Map each stop to its current route key (first stop in route)
    stop_to_route: Dict[str, str] = {s["id"]: s["id"] for s in stops}

    for sav, si, sj in savings:
        if sav <= 0:
            break

        rk_i = stop_to_route.get(si)
        rk_j = stop_to_route.get(sj)
        if rk_i is None or rk_j is None or rk_i == rk_j:
            continue
        r_i = routes[rk_i]
        r_j = routes[rk_j]

        # Only merge if si is at the tail of route_i and sj at the head of route_j
        # (standard CW constraint; relaxed here to allow any end-to-end merge)
        if r_i.stops[-1] != si and r_i.stops[0] != si:
            continue
        if r_j.stops[0] != sj and r_j.stops[-1] != sj:
            continue

        # Flip routes if needed so si is tail of r_i, sj is head of r_j
        if r_i.stops[0] == si:
            r_i.stops.reverse()
        if r_j.stops[-1] == sj:
            r_j.stops.reverse()

        # Capacity check
        if r_i.load_kg + r_j.load_kg > capacity_kg:
            continue

        # Merge r_j into r_i
        merged_stops = r_i.stops + r_j.stops
        merged_load  = r_i.load_kg + r_j.load_kg

        # Recompute km for merged route (depot → all stops → back)
        merged_km  = haversine(depot_lat, depot_lon,
                               stop_map[merged_stops[0]]["lat"],
                               stop_map[merged_stops[0]]["lon"])
        for k in range(len(merged_stops) - 1):
            a = stop_map[merged_stops[k]]
            b = stop_map[merged_stops[k + 1]]
            merged_km += haversine(a["lat"], a["lon"], b["lat"], b["lon"])
        merged_km += haversine(stop_map[merged_stops[-1]]["lat"],
                               stop_map[merged_stops[-1]]["lon"],
                               depot_lat, depot_lon)

        merged_route = _Route(stops=merged_stops, load_kg=merged_load, km=merged_km)

        # Remove old routes, add merged
        del routes[rk_i]
        del routes[rk_j]
        new_key = merged_stops[0]
        routes[new_key] = merged_route
        for sid in merged_stops:
            stop_to_route[sid] = new_key

    return list(routes.values())


# ─────────────────────────────────────────────────────────────────── #
#  CO2 estimate                                                        #
# ─────────────────────────────────────────────────────────────────── #

def _co2(distance_km: float, load_kg: float, capacity_kg: float) -> float:
    if capacity_kg == 0 or distance_km == 0:
        return 0.0
    util        = max(0.01, load_kg / capacity_kg)
    load_factor = 1.0 / util
    return round(distance_km * 0.12 * load_factor, 2)


# ─────────────────────────────────────────────────────────────────── #
#  Main planning function                                              #
# ─────────────────────────────────────────────────────────────────── #

def plan_supply(
    dest_lat: float,
    dest_lon: float,
    dest_name: str,
    requirements: List[Dict],      # [{"material": str, "qty": float, "unit_weight": float}]
) -> Dict:
    """
    Plan optimal supply from the network to the destination.

    Parameters
    ----------
    dest_lat, dest_lon : float
        Destination GPS coordinates.
    dest_name : str
        Human-readable name for the destination site.
    requirements : list
        Each entry: {"material": str, "qty": float, "unit_weight": float}
        unit_weight is kg per unit (from Material.weight_per_unit).

    Returns
    -------
    dict with keys:
        destination     : {name, lat, lon}
        requirements    : original list
        shortfalls      : [{material, needed, available}]  (if any)
        picks           : per-store allocation list
        depot_plans     : list of per-depot plans, each with:
                            depot info, CW-routed truck assignments
        summary         : aggregate stats
    """
    net    = load_network()
    depots = net.get("depots", [])
    stores = net.get("stores", [])

    # ── 1. Greedy store selection per material ───────────────────── #
    picks: List[Dict] = []          # {store_id, store_name, lat, lon, material, qty_units, weight_kg}
    shortfalls: List[Dict] = []

    for req in requirements:
        mat         = req["material"]
        qty_units   = float(req.get("qty", 0))
        unit_weight = float(req.get("unit_weight", 1.0))  # kg per unit
        needed_kg   = qty_units * unit_weight
        remaining   = needed_kg

        # Find candidate stores sorted by distance to destination (closest first)
        candidates = []
        for s in stores:
            inv  = s.get("inventory", {})
            avail_units = float(inv.get(mat, 0))
            if avail_units > 0:
                avail_kg = avail_units * unit_weight
                dist     = haversine(dest_lat, dest_lon, float(s["lat"]), float(s["lon"]))
                candidates.append((dist, s, avail_units, avail_kg))
        candidates.sort(key=lambda x: x[0])

        for dist, s, avail_units, avail_kg in candidates:
            if remaining <= 0:
                break
            take_kg    = min(avail_kg, remaining)
            take_units = take_kg / unit_weight
            picks.append({
                "store_id":   s["id"],
                "store_name": s["name"],
                "lat":        float(s["lat"]),
                "lon":        float(s["lon"]),
                "material":   mat,
                "qty_units":  round(take_units, 2),
                "weight_kg":  round(take_kg, 2),
                "dist_to_dest_km": round(dist, 1),
            })
            remaining -= take_kg

        if remaining > 1e-3:
            shortfalls.append({
                "material":  mat,
                "needed_kg": round(needed_kg, 2),
                "available_kg": round(needed_kg - remaining, 2),
                "shortfall_kg": round(remaining, 2),
            })

    # ── 2. Aggregate picks by store ─────────────────────────────── #
    by_store: Dict[str, Dict] = {}
    for p in picks:
        sid = p["store_id"]
        if sid not in by_store:
            by_store[sid] = {
                "id":        p["store_id"],
                "name":      p["store_name"],
                "lat":       p["lat"],
                "lon":       p["lon"],
                "materials": [],
                "total_kg":  0.0,
            }
        by_store[sid]["materials"].append({
            "material": p["material"],
            "qty":      p["qty_units"],
            "weight_kg": p["weight_kg"],
        })
        by_store[sid]["total_kg"] += p["weight_kg"]

    # ── 3. Assign each store to nearest depot ───────────────────── #
    by_depot: Dict[str, Dict] = {}
    for store in by_store.values():
        nearest_depot = min(
            depots,
            key=lambda d: haversine(float(d["lat"]), float(d["lon"]),
                                    store["lat"], store["lon"])
        )
        did = nearest_depot["id"]
        if did not in by_depot:
            by_depot[did] = {"depot": nearest_depot, "stores": []}
        by_depot[did]["stores"].append(store)

    # ── 4. Clarke-Wright per depot ───────────────────────────────── #
    depot_plans: List[Dict] = []

    for did, payload in by_depot.items():
        depot  = payload["depot"]
        d_lat  = float(depot["lat"])
        d_lon  = float(depot["lon"])
        trucks = [
            {"id": t["id"], "cap": int(str(t["cap"]).replace('"', ''))}
            for t in depot.get("trucks", [])
        ]
        if not trucks:
            trucks = [{"id": f"{did}-T1", "cap": 16000}]

        max_cap = max(t["cap"] for t in trucks)

        # Build stop list for CW (demand = total kg this store needs picked up)
        cw_stops = [
            {
                "id":        s["id"],
                "name":      s["name"],
                "lat":       s["lat"],
                "lon":       s["lon"],
                "demand_kg": s["total_kg"],
            }
            for s in payload["stores"]
        ]

        # Run Clarke-Wright
        cw_routes = _clarke_wright(d_lat, d_lon, cw_stops, max_cap)

        # Assign CW routes to actual trucks (round-robin if more routes than trucks)
        store_lookup = {s["id"]: s for s in payload["stores"]}
        assignments  = []
        truck_idx    = 0

        for route in cw_routes:
            if not route.stops:
                continue
            truck      = trucks[truck_idx % len(trucks)]
            truck_idx += 1

            # Build stop details for this route
            stop_details = []
            for sid in route.stops:
                s = store_lookup.get(sid)
                if s:
                    stop_details.append({
                        "store_id":   s["id"],
                        "store_name": s["name"],
                        "lat":        s["lat"],
                        "lon":        s["lon"],
                        "materials":  s["materials"],
                        "weight_kg":  s["total_kg"],
                    })

            # Route: depot → stores → destination  (as objects with coords)
            full_route = (
                [{"name": depot["name"], "lat": d_lat, "lon": d_lon}]
                + [{"name": s["store_name"], "lat": s["lat"], "lon": s["lon"]}
                   for s in stop_details]
                + [{"name": dest_name, "lat": dest_lat, "lon": dest_lon}]
            )

            # Total km: depot → stores (CW gives this) + last store → destination
            last_store = store_lookup.get(route.stops[-1])
            km_to_dest = 0.0
            if last_store:
                km_to_dest = haversine(last_store["lat"], last_store["lon"],
                                       dest_lat, dest_lon)
            total_km = round(route.km + km_to_dest, 2)

            assignments.append({
                "truck_id":    truck["id"],
                "capacity_kg": truck["cap"],
                "load_kg":     round(route.load_kg, 2),
                "util_pct":    round(route.load_kg / truck["cap"] * 100, 1),
                "route":       full_route,
                "stops":       stop_details,
                "distance_km": total_km,
                "co2_kg":      _co2(total_km, route.load_kg, truck["cap"]),
            })

        depot_plans.append({
            "depot": {
                "id":   depot["id"],
                "name": depot["name"],
                "lat":  d_lat,
                "lon":  d_lon,
            },
            "assignments": assignments,
        })

    # ── 5. Summary ───────────────────────────────────────────────── #
    all_assignments = [a for dp in depot_plans for a in dp["assignments"]]
    total_km  = round(sum(a["distance_km"] for a in all_assignments), 2)
    total_co2 = round(sum(a["co2_kg"]      for a in all_assignments), 2)
    total_kg  = round(sum(a["load_kg"]     for a in all_assignments), 2)

    return {
        "destination": {"name": dest_name, "lat": dest_lat, "lon": dest_lon},
        "requirements": requirements,
        "shortfalls":   shortfalls,
        "picks":        picks,
        "depot_plans":  depot_plans,
        "summary": {
            "total_trucks":   len(all_assignments),
            "total_kg":       total_kg,
            "total_km":       total_km,
            "total_co2_kg":   total_co2,
            "depots_used":    len(depot_plans),
            "stores_sourced": len(by_store),
            "shortfalls":     len(shortfalls),
        },
    }
