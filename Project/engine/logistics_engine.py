"""
BuildSense — Logistics Engine
──────────────────────────────
Handles truck load allocation (P2 knapsack) and route optimisation (P3 CVRP).

  optimize_truck_loads  — greedy knapsack: pack materials by priority/weight ratio
  solve_routes          — CVRP via OR-Tools: find shortest multi-truck delivery routes
  calculate_emissions   — CO2 estimate based on distance, load, and utilisation
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from models.material import Material
from models.delivery  import DeliveryPoint, TruckAssignment


# ─────────────────────────────────────────────────────────────────── #
#  Haversine distance (km)                                             #
# ─────────────────────────────────────────────────────────────────── #

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ─────────────────────────────────────────────────────────────────── #
#  Phase 2 supplement — Truck Load Optimisation (Knapsack)            #
# ─────────────────────────────────────────────────────────────────── #

def optimize_truck_loads(
    materials:       Dict[str, Material],
    order_quantities: Dict[str, float],   # {material_name: qty to be delivered}
    trucks:          List[Dict],           # [{"truck_id": str, "capacity_kg": int}, ...]
    rain_expected:   bool = False,
) -> List[TruckAssignment]:
    """
    Greedy knapsack truck load allocation.

    Steps
    -----
    1. Convert order quantities to item list (each unit = weight_per_unit kg).
    2. Optionally boost priority for weather-sensitive materials when rain is expected.
    3. Sort items by priority/weight efficiency ratio (descending).
    4. Pack each truck greedily; deduct fulfilled demand and continue to next truck.

    Returns a list of TruckAssignment objects, one per truck.
    """
    # Build item list
    items: List[Dict] = []
    for mat_name, qty in order_quantities.items():
        if mat_name not in materials:
            continue
        mat    = materials[mat_name]
        demand = int(round(qty))
        weight = mat.weight_per_unit          # kg per unit
        prio   = mat.priority

        # Weather adjustment — rain boosts priority of sensitive materials
        if rain_expected and mat_name in ("Cement", "Sand", "Wood"):
            prio = min(10, int(prio * 1.5))

        ratio = prio / weight if weight > 0 else 0.0
        for _ in range(demand):
            items.append({
                "material": mat_name,
                "weight":   weight,
                "priority": prio,
                "ratio":    ratio,
            })

    # Sort by efficiency (highest priority per kg first)
    items.sort(key=lambda x: x["ratio"], reverse=True)

    assignments: List[TruckAssignment] = []

    for truck in trucks:
        truck_id     = truck["truck_id"]
        capacity_kg  = truck["capacity_kg"]
        used         = 0
        loaded: List[str] = []

        for item in items[:]:
            if used + item["weight"] <= capacity_kg:
                loaded.append(item["material"])
                used   += item["weight"]
                items.remove(item)

        assignments.append(TruckAssignment(
            truck_id=truck_id,
            capacity_kg=capacity_kg,
            materials_loaded=loaded,
            used_capacity_kg=int(used),
        ))

    return assignments


# ─────────────────────────────────────────────────────────────────── #
#  Route Optimisation (CVRP — greedy nearest-neighbour fallback)       #
# ─────────────────────────────────────────────────────────────────── #

def _build_distance_matrix(locations: List[Tuple[float, float]]) -> List[List[float]]:
    n = len(locations)
    matrix: List[List[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = _haversine(
                    locations[i][0], locations[i][1],
                    locations[j][0], locations[j][1],
                )
    return matrix


def _greedy_route(
    depot_idx:    int,
    site_indices: List[int],
    dist_matrix:  List[List[float]],
) -> Tuple[List[int], float]:
    """Nearest-neighbour greedy route for one vehicle."""
    unvisited = site_indices.copy()
    route     = [depot_idx]
    total_km  = 0.0
    current   = depot_idx

    while unvisited:
        nearest  = min(unvisited, key=lambda j: dist_matrix[current][j])
        total_km += dist_matrix[current][nearest]
        route.append(nearest)
        current = nearest
        unvisited.remove(nearest)

    # Return to depot
    total_km += dist_matrix[current][depot_idx]
    route.append(depot_idx)
    return route, total_km


def _solve_cvrp_ortools(
    locations:        List[Tuple[float, float]],
    demands:          List[int],
    vehicle_capacity: int,
    num_vehicles:     int,
) -> Tuple[List[List[int]], float]:
    """
    CVRP via OR-Tools (PATH_CHEAPEST_ARC heuristic).
    Returns (routes, total_distance_km).
    Falls back to an empty list if OR-Tools is not installed.
    """
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        return [], 0.0

    dist_matrix = _build_distance_matrix(locations)
    # Scale to integers (metres)
    int_matrix = [[int(d * 1000) for d in row] for row in dist_matrix]

    manager = pywrapcp.RoutingIndexManager(len(int_matrix), num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_idx, to_idx):
        return int_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    transit_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    def demand_callback(from_idx):
        return demands[manager.IndexToNode(from_idx)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx, 0, [vehicle_capacity] * num_vehicles, True, "Capacity"
    )

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    solution = routing.SolveWithParameters(params)
    routes: List[List[int]] = []
    total_km = 0.0

    if solution:
        for vid in range(num_vehicles):
            idx   = routing.Start(vid)
            route = []
            km    = 0.0
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                route.append(node)
                prev = idx
                idx  = solution.Value(routing.NextVar(idx))
                km  += routing.GetArcCostForVehicle(prev, idx, vid)
            route.append(manager.IndexToNode(idx))
            routes.append(route)
            total_km += km

    return routes, total_km / 1000.0


def solve_routes(
    depot:          DeliveryPoint,
    sites:          List[DeliveryPoint],
    assignments:    List[TruckAssignment],
    vehicle_capacity_kg: int,
) -> List[TruckAssignment]:
    """
    Optimise delivery routes for each truck using CVRP.

    OR-Tools is used when available; otherwise falls back to a greedy
    nearest-neighbour heuristic so the pipeline always produces a result.

    Updates each TruckAssignment with:
      - route  (list of site names in delivery order)
      - distance_km
      - co2_kg
    """
    all_locations = [depot.coords] + [s.coords for s in sites]
    all_demands   = [0] + [s.demand for s in sites]
    # Only route trucks that actually have material to deliver
    active_assignments = [a for a in assignments if a.used_capacity_kg > 0]
    idle_assignments   = [a for a in assignments if a.used_capacity_kg == 0]

    num_vehicles = len(active_assignments)

    # Try OR-Tools CVRP only for active trucks
    if num_vehicles > 0:
        routes_idx, _ = _solve_cvrp_ortools(
            all_locations, all_demands, vehicle_capacity_kg, num_vehicles
        )
    else:
        routes_idx = []

    dist_matrix = _build_distance_matrix(all_locations)

    if not routes_idx:
        # Greedy fallback: distribute sites evenly across active trucks
        site_indices = list(range(1, len(all_locations)))
        chunk_size   = max(1, math.ceil(len(site_indices) / max(num_vehicles, 1)))
        routes_idx   = []
        for k in range(num_vehicles):
            chunk = site_indices[k * chunk_size: (k + 1) * chunk_size]
            if chunk:
                route, _ = _greedy_route(0, chunk, dist_matrix)
                routes_idx.append(route)
            else:
                routes_idx.append([0, 0])

    # Build a name map: index 0 = depot, 1..n = sites
    idx_to_name: Dict[int, str] = {0: depot.name}
    for i, s in enumerate(sites, 1):
        idx_to_name[i] = s.name

    for k, assignment in enumerate(active_assignments):
        if k >= len(routes_idx):
            break
        route_idx = routes_idx[k]

        # A route of [0, 0] means this vehicle stayed at the depot.
        if route_idx == [0, 0] or len(route_idx) <= 1:
            assignment.route       = [depot.name]
            assignment.distance_km = 0.0
            assignment.co2_kg      = 0.0
            continue

        total_km = sum(
            dist_matrix[route_idx[i]][route_idx[i + 1]]
            for i in range(len(route_idx) - 1)
        )
        route_names = [idx_to_name.get(idx, depot.name) for idx in route_idx]
        co2 = calculate_emissions(
            distance=total_km,
            quantity=assignment.used_capacity_kg,
            truck_capacity=assignment.capacity_kg,
        )
        assignment.route       = route_names
        assignment.distance_km = round(total_km, 2)
        assignment.co2_kg      = round(co2, 2)

    # Mark idle trucks
    for assignment in idle_assignments:
        assignment.route       = [depot.name]
        assignment.distance_km = 0.0
        assignment.co2_kg      = 0.0

    return assignments


# ─────────────────────────────────────────────────────────────────── #
#  Emissions                                                           #
# ─────────────────────────────────────────────────────────────────── #

def calculate_emissions(
    distance:        float,
    quantity:        float,
    truck_capacity:  float,
    emission_factor: float = 0.12,   # kg CO2 per km (loaded truck baseline)
) -> float:
    """
    Estimate CO2 emissions (kg) for one truck run.

    Formula:
        utilisation = quantity / truck_capacity
        load_penalty = 1 / utilisation   (under-utilised trucks burn more per tonne)
        emissions = distance × emission_factor × load_penalty

    Under-utilised trucks are penalised because fuel consumption per tonne
    rises when the truck runs partially empty.
    """
    if truck_capacity == 0 or distance == 0:
        return 0.0
    utilisation  = max(0.01, quantity / truck_capacity)
    load_penalty = 1.0 / utilisation
    return round(distance * emission_factor * load_penalty, 4)
