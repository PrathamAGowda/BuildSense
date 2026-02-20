"""
Route Re-Routing Engine
Generates alternative routes and compares them based on:
  - Total delivery time (including weather + traffic delays)
  - Fuel consumption (CO2)
  - Cost-benefit analysis
"""

from typing import List, Dict, Tuple
from .logistics_engine import calculate_emissions, _haversine
from .weather_service import get_weather_for_route
from .traffic_service import get_traffic_for_route


def analyze_route_with_conditions(
    route_waypoints: List[Tuple[float, float]],
    route_name: str,
    truck_load_kg: float,
    truck_capacity_kg: float,
) -> Dict:
    """
    Full analysis of a route considering weather + traffic
    
    Returns detailed breakdown of delays, costs, and efficiency
    """
    # Base distance
    base_distance = sum(
        _haversine(route_waypoints[i][0], route_waypoints[i][1],
                   route_waypoints[i+1][0], route_waypoints[i+1][1])
        for i in range(len(route_waypoints) - 1)
    )
    
    # Base time (assume 60 km/h average)
    base_time = (base_distance / 60) * 60  # minutes
    
    # Weather impact
    weather = get_weather_for_route(route_waypoints)
    
    # Traffic impact
    traffic = get_traffic_for_route(route_waypoints, route_name)
    
    # Total delay
    total_delay = weather["total_delay_minutes"] + traffic["delay_minutes"]
    
    # Final time
    final_time = base_time + total_delay
    
    # Emissions
    co2 = calculate_emissions(base_distance, truck_load_kg, truck_capacity_kg)
    
    # Cost estimate
    fuel_cost = base_distance * 0.15  # ~$0.15 per km
    delay_cost = total_delay * 2.5  # ~$2.50 per minute delay
    total_cost = fuel_cost + delay_cost
    
    # Efficiency score
    efficiency = _calculate_efficiency_score(
        base_distance, total_delay, co2, truck_load_kg, truck_capacity_kg
    )
    
    return {
        "route_name": route_name,
        "base_distance_km": round(base_distance, 2),
        "base_time_min": round(base_time, 1),
        "weather": weather,
        "traffic": traffic,
        "delay_minutes": round(total_delay, 1),
        "final_delivery_time_min": round(final_time, 1),
        "fuel_cost_usd": round(fuel_cost, 2),
        "delay_cost_usd": round(delay_cost, 2),
        "total_cost_usd": round(total_cost, 2),
        "co2_kg": round(co2, 2),
        "utilization_pct": round((truck_load_kg / truck_capacity_kg) * 100, 1),
        "efficiency_score": efficiency,
        "risk_level": weather["risk_level"],
    }


def compare_routes(
    route_options: List[Tuple[str, List[Tuple[float, float]]]],
    truck_load_kg: float,
    truck_capacity_kg: float,
) -> Dict:
    """
    Compare multiple route options and recommend the best
    
    Returns:
      - All route analyses
      - Best route recommendation
      - Quantified savings (time, cost, CO2)
      - Natural language recommendation
    """
    analyzed = []
    for name, waypoints in route_options:
        analysis = analyze_route_with_conditions(
            waypoints, name, truck_load_kg, truck_capacity_kg
        )
        analyzed.append(analysis)
    
    # Rank by efficiency score
    best = max(analyzed, key=lambda r: r["efficiency_score"])
    worst = min(analyzed, key=lambda r: r["efficiency_score"])
    
    # Calculate savings
    time_savings = worst["final_delivery_time_min"] - best["final_delivery_time_min"]
    cost_savings = worst["total_cost_usd"] - best["total_cost_usd"]
    co2_savings = worst["co2_kg"] - best["co2_kg"]
    
    # Generate recommendation
    if time_savings > 30:
        recommendation = (
            f"🚦 {worst['route_name']} will cause {int(worst['final_delivery_time_min'])} min delay "
            f"→ switching to {best['route_name']} saves {int(time_savings)} min + ${int(cost_savings)} "
            f"+ {round(co2_savings, 1)} kg CO₂"
        )
    elif cost_savings > 50:
        recommendation = (
            f"💰 {best['route_name']} reduces cost by ${int(cost_savings)} "
            f"(less delay + optimized fuel)"
        )
    else:
        recommendation = f"✓ {best['route_name']} is {int(best['efficiency_score'])}% efficient"
    
    return {
        "routes": analyzed,
        "best_route": best["route_name"],
        "best_efficiency": best["efficiency_score"],
        "recommendation": recommendation,
        "savings": {
            "time_minutes": round(time_savings, 1),
            "cost_usd": round(cost_savings, 2),
            "co2_kg": round(co2_savings, 2),
        }
    }


def _calculate_efficiency_score(
    distance: float, delay: float, co2: float, load: float, capacity: float
) -> int:
    """
    Composite efficiency score (0-100)
    Weights: distance (40%), delay (35%), emissions (15%), utilization (10%)
    """
    # Normalize each factor
    distance_score = max(0, 100 - (distance / 100) * 10)
    delay_score = max(0, 100 - (delay / 5))
    emission_score = max(0, 100 - (co2 / 0.5) * 10)
    utilization = (load / capacity) * 100 if capacity > 0 else 0
    utilization_score = min(100, utilization)
    
    # Weighted average
    score = (
        distance_score * 0.40 +
        delay_score * 0.35 +
        emission_score * 0.15 +
        utilization_score * 0.10
    )
    
    return max(0, min(100, int(score)))
