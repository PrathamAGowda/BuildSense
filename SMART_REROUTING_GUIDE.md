# 🚚 Smart Transport Re-Routing Implementation Guide

## Overview
Add **weather** + **traffic** awareness to dynamically suggest route alternatives that minimize delay + fuel consumption.

---

## Phase 1: Add Weather API Integration

### Step 1.1 — Create `Project/engine/weather_service.py`

```python
"""
Weather Service — Real-time weather & delay estimation
Integrates with OpenWeatherMap API (free tier available)
Falls back to mock data for development
"""

import os
import json
from typing import Dict, Tuple
from datetime import datetime

def get_weather_data(latitude: float, longitude: float) -> Dict:
    """
    Fetch weather for delivery location.
    Returns: {
        "condition": "rain|clear|cloudy|snow",
        "rainfall_mm": float,
        "wind_speed_kmh": float,
        "delay_minutes": int
    }
    """
    API_KEY = os.getenv("OPENWEATHER_API_KEY", "mock")
    
    if API_KEY == "mock":
        return _mock_weather(latitude, longitude)
    
    try:
        import requests
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={API_KEY}&units=metric"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        
        condition = data["weather"][0]["main"].lower()  # rain, clear, etc
        rainfall = data.get("rain", {}).get("1h", 0)  # mm in last hour
        wind = data["wind"]["speed"] * 3.6  # m/s to km/h
        
        delay = _calculate_weather_delay(condition, rainfall, wind)
        
        return {
            "condition": condition,
            "rainfall_mm": rainfall,
            "wind_speed_kmh": round(wind, 1),
            "delay_minutes": delay,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"Weather API error: {e}")
        return _mock_weather(latitude, longitude)


def _mock_weather(lat: float, lon: float) -> Dict:
    """Development fallback with random conditions"""
    import random
    conditions = [
        {"condition": "clear", "rainfall_mm": 0, "wind_speed_kmh": 10, "delay": 0},
        {"condition": "rain", "rainfall_mm": 5, "wind_speed_kmh": 20, "delay": 15},
        {"condition": "heavy_rain", "rainfall_mm": 15, "wind_speed_kmh": 35, "delay": 45},
        {"condition": "cloudy", "rainfall_mm": 0, "wind_speed_kmh": 12, "delay": 5},
    ]
    chosen = random.choice(conditions)
    return {
        "condition": chosen["condition"],
        "rainfall_mm": chosen["rainfall_mm"],
        "wind_speed_kmh": chosen["wind_speed_kmh"],
        "delay_minutes": chosen["delay"],
        "timestamp": datetime.now().isoformat(),
    }


def _calculate_weather_delay(condition: str, rainfall_mm: float, wind_kmh: float) -> int:
    """
    Estimate delay (minutes) based on weather conditions
    
    Logic:
      - No rain: 0 min
      - Light rain (< 5mm): 10-15 min
      - Moderate rain (5-10mm): 20-30 min
      - Heavy rain (> 10mm): 45+ min
      - High wind (> 30 km/h): +10-15 min penalty
    """
    delay = 0
    
    if condition == "clear":
        delay = 0
    elif condition == "cloudy":
        delay = 5
    elif condition == "rain" or condition == "drizzle":
        if rainfall_mm < 5:
            delay = 10
        elif rainfall_mm < 10:
            delay = 25
        else:
            delay = 45
    elif condition == "heavy_rain":
        delay = 60
    elif condition == "snow":
        delay = 90
    elif condition == "thunderstorm":
        delay = 120
    
    # Wind penalty
    if wind_kmh > 30:
        delay += int((wind_kmh - 30) * 0.5)  # ~0.5 min per km/h above 30
    
    return delay


def get_weather_for_route(
    waypoints: list  # [(lat, lon), (lat, lon), ...]
) -> Dict[str, any]:
    """
    Get weather for all waypoints in a route
    Returns aggregated impact
    """
    weather_points = []
    max_delay = 0
    has_rain = False
    
    for lat, lon in waypoints:
        w = get_weather_data(lat, lon)
        weather_points.append(w)
        max_delay = max(max_delay, w["delay_minutes"])
        if "rain" in w["condition"].lower():
            has_rain = True
    
    return {
        "waypoints": weather_points,
        "total_delay_minutes": max_delay,
        "has_rain": has_rain,
        "risk_level": _assess_risk(max_delay),
    }


def _assess_risk(delay_minutes: int) -> str:
    """Risk assessment for route viability"""
    if delay_minutes == 0:
        return "clear"
    elif delay_minutes < 15:
        return "low"
    elif delay_minutes < 45:
        return "moderate"
    elif delay_minutes < 120:
        return "high"
    else:
        return "critical"
```

---

## Phase 2: Add Traffic API Integration

### Step 2.1 — Create `Project/engine/traffic_service.py`

```python
"""
Traffic Service — Real-time traffic & congestion estimation
Google Maps API or mocked data for development
"""

import os
from typing import List, Tuple, Dict
from datetime import datetime

def get_traffic_for_route(
    waypoints: List[Tuple[float, float]],  # [(lat, lon), ...]
    route_name: str = "Route A"
) -> Dict:
    """
    Get traffic delays for a multi-stop route
    
    Returns: {
        "route_name": str,
        "total_distance_km": float,
        "free_flow_time_min": float,   # Best case (no traffic)
        "current_time_min": float,     # Actual time with traffic
        "delay_minutes": float,        # delay = current - free_flow
        "congestion_level": "low|medium|high|critical",
        "segments": [
            {
                "from": (lat, lon),
                "to": (lat, lon),
                "distance_km": float,
                "speed_kmh": float,
                "duration_min": float,
                "congestion": "low|high"
            }
        ]
    }
    """
    GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "mock")
    
    if GOOGLE_MAPS_KEY == "mock":
        return _mock_traffic_route(waypoints, route_name)
    
    try:
        return _fetch_google_traffic(waypoints, route_name, GOOGLE_MAPS_KEY)
    except Exception as e:
        print(f"Traffic API error: {e}")
        return _mock_traffic_route(waypoints, route_name)


def _mock_traffic_route(
    waypoints: List[Tuple[float, float]],
    route_name: str
) -> Dict:
    """
    Development: Mock traffic data
    Simulates different congestion patterns for route analysis
    """
    import random
    from math import radians, cos, sin, asin, sqrt
    
    def haversine(lat1, lon1, lat2, lon2):
        """Distance between two points in km"""
        R = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return R * 2 * asin(sqrt(a))
    
    segments = []
    total_distance = 0
    total_free_flow = 0
    total_current = 0
    
    for i in range(len(waypoints) - 1):
        lat1, lon1 = waypoints[i]
        lat2, lon2 = waypoints[i + 1]
        
        dist = haversine(lat1, lon1, lat2, lon2)
        total_distance += dist
        
        # Simulate traffic patterns
        congestion = random.choice(["low", "low", "medium", "high", "high"])
        
        base_speed = 60  # km/h
        if congestion == "low":
            current_speed = 60 + random.randint(0, 10)
        elif congestion == "medium":
            current_speed = 40 + random.randint(0, 10)
        else:
            current_speed = 20 + random.randint(0, 10)
        
        free_flow_time = (dist / base_speed) * 60  # minutes
        current_time = (dist / current_speed) * 60
        
        total_free_flow += free_flow_time
        total_current += current_time
        
        segments.append({
            "from": waypoints[i],
            "to": waypoints[i + 1],
            "distance_km": round(dist, 2),
            "speed_kmh": round(current_speed, 1),
            "duration_min": round(current_time, 1),
            "congestion": congestion,
        })
    
    delay = total_current - total_free_flow
    
    # Overall congestion assessment
    if delay < 5:
        congestion_level = "low"
    elif delay < 15:
        congestion_level = "medium"
    elif delay < 30:
        congestion_level = "high"
    else:
        congestion_level = "critical"
    
    return {
        "route_name": route_name,
        "total_distance_km": round(total_distance, 2),
        "free_flow_time_min": round(total_free_flow, 1),
        "current_time_min": round(total_current, 1),
        "delay_minutes": round(delay, 1),
        "congestion_level": congestion_level,
        "segments": segments,
        "timestamp": datetime.now().isoformat(),
    }


def _fetch_google_traffic(
    waypoints: List[Tuple[float, float]],
    route_name: str,
    api_key: str
) -> Dict:
    """
    Real integration with Google Maps Directions API
    Requires: `pip install googlemaps`
    
    Note: Create via Google Cloud > Maps > Directions API
    Costs apply after 25,000 free monthly requests
    """
    try:
        import googlemaps
    except ImportError:
        print("googlemaps not installed. Run: pip install googlemaps")
        return _mock_traffic_route(waypoints, route_name)
    
    client = googlemaps.Client(key=api_key)
    
    # Build waypoint list
    origin = waypoints[0]
    waypts = waypoints[1:-1]
    destination = waypoints[-1]
    
    try:
        result = client.directions(
            origin=origin,
            destination=destination,
            waypoints=waypts,
            departure_time="now",  # Current traffic
            mode="driving",
        )
        
        if not result:
            return _mock_traffic_route(waypoints, route_name)
        
        route = result[0]
        leg_data = route["legs"]
        
        total_distance = sum(leg["distance"]["value"] for leg in leg_data) / 1000  # km
        total_duration = sum(leg["duration"]["value"] for leg in leg_data) / 60  # minutes
        
        # Free flow time (no traffic)
        total_free_flow = sum(
            leg["duration_in_traffic"]["value"] if "duration_in_traffic" in leg 
            else leg["duration"]["value"] 
            for leg in leg_data
        ) / 60
        
        delay = total_duration - total_free_flow
        
        segments = []
        for i, leg in enumerate(leg_data):
            segments.append({
                "from": waypoints[i],
                "to": waypoints[i + 1],
                "distance_km": leg["distance"]["value"] / 1000,
                "duration_min": leg["duration"]["value"] / 60,
                "congestion": "high" if leg.get("duration_in_traffic", 0) > leg["duration"]["value"] else "low",
            })
        
        return {
            "route_name": route_name,
            "total_distance_km": round(total_distance, 2),
            "free_flow_time_min": round(total_free_flow, 1),
            "current_time_min": round(total_duration, 1),
            "delay_minutes": round(delay, 1),
            "congestion_level": "high" if delay > 15 else "medium" if delay > 5 else "low",
            "segments": segments,
        }
    except Exception as e:
        print(f"Google Maps error: {e}")
        return _mock_traffic_route(waypoints, route_name)
```

---

## Phase 3: Add Route Re-Routing Engine

### Step 3.1 — Create `Project/engine/rerouting_engine.py`

```python
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
    route_waypoints: List[Tuple[float, float]],  # [(lat, lon), ...]
    route_name: str,
    truck_load_kg: float,
    truck_capacity_kg: float,
) -> Dict:
    """
    Full analysis of a route considering weather + traffic
    
    Returns: {
        "route_name": str,
        "base_distance_km": float,
        "base_time_min": float,
        "weather": {...},
        "traffic": {...},
        "total_delay_minutes": float,
        "fuel_cost_usd": float,
        "co2_kg": float,
        "efficiency_score": 0-100,  # Higher is better
    }
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
    delay_cost = total_delay * 2.5  # ~$2.50 per minute delay (labor, penalties)
    total_cost = fuel_cost + delay_cost
    
    # Efficiency score (0-100)
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
    route_options: List[Tuple[str, List[Tuple[float, float]]]],  # [(name, waypoints), ...]
    truck_load_kg: float,
    truck_capacity_kg: float,
) -> Dict:
    """
    Compare multiple route options
    Recommends best route and highlights why
    
    Returns: {
        "routes": [analyzed_route_data, ...],
        "best_route": "Route A",
        "recommendation": "Route A will cause 2 hr delay → switching to Route B reduces fuel + delay",
        "savings": {
            "time_minutes": 120,
            "cost_usd": 400,
            "co2_kg": 15,
        }
    }
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
            f"{worst['route_name']} will cause {int(worst['final_delivery_time_min'])} min delay "
            f"→ switching to {best['route_name']} saves {int(time_savings)} min + ${int(cost_savings)} "
            f"+ {int(co2_savings)} kg CO2"
        )
    elif cost_savings > 50:
        recommendation = (
            f"{best['route_name']} reduces cost by ${int(cost_savings)} "
            f"(less delay + optimized fuel)"
        )
    else:
        recommendation = f"{best['route_name']} is {int(best['efficiency_score'])}% efficient"
    
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
    # Normalize each factor (assume worst case for scoring)
    distance_score = max(0, 100 - (distance / 100) * 10)  # 0 km = 100, 100 km = 0
    delay_score = max(0, 100 - (delay / 5))               # 0 min delay = 100, 5+ min = 0
    emission_score = max(0, 100 - (co2 / 0.5) * 10)       # 0 kg = 100, 0.5 kg = 0
    utilization = (load / capacity) * 100
    utilization_score = min(100, utilization)              # Max 100 at full capacity
    
    # Weighted average
    score = (
        distance_score * 0.40 +
        delay_score * 0.35 +
        emission_score * 0.15 +
        utilization_score * 0.10
    )
    
    return max(0, min(100, int(score)))
```

---

## Phase 4: Integrate into Flask API

### Step 4.1 — Update `Frontend/api/server.py`

Add these imports at the top:

```python
from engine.rerouting_engine import analyze_route_with_conditions, compare_routes
```

Add these new endpoints:

```python
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
    body = request.json
    route_name = body.get("route_name", "Route")
    waypoints = [(lat, lon) for lat, lon in body["waypoints"]]
    load = float(body["truck_load_kg"])
    capacity = float(body["truck_capacity_kg"])
    
    analysis = analyze_route_with_conditions(waypoints, route_name, load, capacity)
    return jsonify(analysis)


@app.post("/api/delivery/compare-routes")
def compare_delivery_routes():
    """
    Compare multiple routes and recommend the best one
    
    POST body: {
        "routes": [
            {
                "name": "Route A",
                "waypoints": [[lat, lon], [lat, lon], ...]
            },
            {
                "name": "Route B",
                "waypoints": [[lat, lon], [lat, lon], ...]
            }
        ],
        "truck_load_kg": 2500,
        "truck_capacity_kg": 5000
    }
    """
    body = request.json
    routes = [
        (r["name"], [(lat, lon) for lat, lon in r["waypoints"]])
        for r in body.get("routes", [])
    ]
    load = float(body["truck_load_kg"])
    capacity = float(body["truck_capacity_kg"])
    
    if len(routes) < 2:
        return jsonify({"error": "Provide at least 2 routes to compare"}), 400
    
    comparison = compare_routes(routes, load, capacity)
    return jsonify(comparison)


@app.post("/api/delivery/plan-with-rerouting")
def delivery_plan_with_rerouting():
    """
    Enhanced delivery planning that includes rerouting suggestions
    
    POST body: Same as /api/delivery/plan, plus recheck for better routes
    """
    body = request.json
    mats = load_materials()
    sites = load_sites()
    depot = sites[0]
    dpts = sites[1:]
    
    order_quantities = body.get("order_quantities", {})
    trucks = body.get("trucks", [])
    
    if not trucks or not order_quantities:
        return jsonify({"error": "Provide trucks and order_quantities"}), 400
    
    # Original route planning
    assignments = optimize_truck_loads(mats, order_quantities, trucks)
    vehicle_cap = max(t["capacity_kg"] for t in trucks)
    assignments = solve_routes(depot, dpts, assignments, vehicle_cap)
    
    # Add rerouting analysis for each truck
    result = []
    for a in assignments:
        if a.distance_km == 0 or not a.route:
            # Idle truck
            result.append(_assignment_to_json(a))
            continue
        
        # Build waypoints from route
        waypoints = [depot.coords]
        for site_name in a.route[1:-1]:  # Skip depot at start and end
            for site in dpts:
                if site.name == site_name:
                    waypoints.append(site.coords)
                    break
        waypoints.append(depot.coords)
        
        # Analyze current route
        analysis = analyze_route_with_conditions(
            waypoints, a.truck_id, a.used_capacity_kg, a.capacity_kg
        )
        
        truck_json = _assignment_to_json(a)
        truck_json["route_analysis"] = analysis
        result.append(truck_json)
    
    return jsonify(result)


def _assignment_to_json(a):
    """Helper to convert TruckAssignment to JSON"""
    counts = Counter(a.materials_loaded)
    return {
        "truck_id": a.truck_id,
        "capacity_kg": a.capacity_kg,
        "used_kg": a.used_capacity_kg,
        "utilization_pct": a.utilization_pct,
        "materials": dict(counts),
        "route": a.route,
        "distance_km": a.distance_km,
        "co2_kg": a.co2_kg,
    }
```

---

## Phase 5: Frontend Display

### Step 5.1 — Update `Frontend/index.html` to show route comparisons

Add this section to display rerouting recommendations:

```html
<!-- Route Analysis Section -->
<div class="section delivery-analysis" style="display:none;">
    <h3>🚗 Smart Route Recommendations</h3>
    
    <div id="route-comparison">
        <div class="card">
            <h4>Route Analysis</h4>
            <div id="best-route-recommendation" class="highlight"></div>
            
            <table border="1">
                <thead>
                    <tr>
                        <th>Route</th>
                        <th>Distance</th>
                        <th>Weather Delay</th>
                        <th>Traffic Delay</th>
                        <th>Total Time</th>
                        <th>Cost</th>
                        <th>CO₂</th>
                        <th>Efficiency</th>
                    </tr>
                </thead>
                <tbody id="route-comparison-table"></tbody>
            </table>
            
            <h4 style="margin-top: 20px;">Savings by Switching</h4>
            <div id="savings-breakdown"></div>
        </div>
    </div>
</div>
```

---

## Phase 6: Setup & Configuration

### Step 6.1 — Install Dependencies

```bash
# These are optional - already in requirements
pip install requests
pip install googlemaps  # If using Google Maps (costs apply)
```

### Step 6.2 — Environment Variables (Optional)

Create `.env` file in project root:

```bash
# For real APIs (leave blank to use mock data in development)
OPENWEATHER_API_KEY=your_key_here
GOOGLE_MAPS_API_KEY=your_key_here
```

---

## Testing the Feature

### Simple Test: Analyze a Route

```bash
curl -X POST http://localhost:5001/api/delivery/analyze-route \
  -H "Content-Type: application/json" \
  -d '{
    "route_name": "Route A",
    "waypoints": [[40.7128, -74.0060], [40.7580, -73.9855], [40.7614, -73.9776]],
    "truck_load_kg": 2500,
    "truck_capacity_kg": 5000
  }'
```

### Compare Routes

```bash
curl -X POST http://localhost:5001/api/delivery/compare-routes \
  -H "Content-Type: application/json" \
  -d '{
    "routes": [
      {
        "name": "Route A",
        "waypoints": [[40.7128, -74.0060], [40.7580, -73.9855], [40.7614, -73.9776]]
      },
      {
        "name": "Route B",
        "waypoints": [[40.7128, -74.0060], [40.7614, -73.9776], [40.7580, -73.9855]]
      }
    ],
    "truck_load_kg": 2500,
    "truck_capacity_kg": 5000
  }'
```

---

## Why Judges Will Love This 🏆

| Feature | Impact |
|---------|--------|
| **Weather Awareness** | Prevents delays, avoids safety risks (rain, snow, wind) |
| **Traffic Integration** | Real-time congestion avoidance = time + fuel + cost savings |
| **Dynamic Rerouting** | "2 hr delay averted" = concrete business value |
| **Sustainability** | CO₂ tracking shows environmental impact per route |
| **Cost Savings** | $$$ quantified: "Route B saves $400 in labor + fuel" |
| **Real-World Relevance** | Construction logistics faces these daily challenges |

---

## Implementation Checklist

- [ ] Create `Project/engine/weather_service.py`
- [ ] Create `Project/engine/traffic_service.py`
- [ ] Create `Project/engine/rerouting_engine.py`
- [ ] Add re-routing endpoints to `Frontend/api/server.py`
- [ ] Update `Project/requirements.txt` (add `requests` if not present)
- [ ] Test with mock data first (no API keys needed)
- [ ] (Optional) Get real API keys for OpenWeather + Google Maps
- [ ] Update frontend UI to display recommendations
- [ ] Demo: "Route A: 2 hr delay → Route B: 15 min delay"

