# Smart Transport Re-Routing — Quick Test Examples

## Test 1: Analyze a Single Route

```bash
curl -X POST http://localhost:5001/api/delivery/analyze-route \
  -H "Content-Type: application/json" \
  -d '{
    "route_name": "Route A - Through Downtown",
    "waypoints": [
      [40.7128, -74.0060],
      [40.7580, -73.9855],
      [40.7614, -73.9776]
    ],
    "truck_load_kg": 2500,
    "truck_capacity_kg": 5000
  }'
```

**Expected Response:**
```json
{
  "route_name": "Route A - Through Downtown",
  "base_distance_km": 8.5,
  "base_time_min": 8.5,
  "weather": {
    "waypoints": [...],
    "total_delay_minutes": 15,
    "has_rain": true,
    "risk_level": "low"
  },
  "traffic": {
    "route_name": "Route A - Through Downtown",
    "total_distance_km": 8.5,
    "delay_minutes": 12.3,
    "congestion_level": "high"
  },
  "delay_minutes": 27.3,
  "final_delivery_time_min": 35.8,
  "fuel_cost_usd": 1.28,
  "delay_cost_usd": 68.25,
  "total_cost_usd": 69.53,
  "co2_kg": 0.42,
  "utilization_pct": 50.0,
  "efficiency_score": 62,
  "risk_level": "low"
}
```

---

## Test 2: Compare Two Routes

```bash
curl -X POST http://localhost:5001/api/delivery/compare-routes \
  -H "Content-Type: application/json" \
  -d '{
    "routes": [
      {
        "name": "Route A - Through Downtown",
        "waypoints": [
          [40.7128, -74.0060],
          [40.7580, -73.9855],
          [40.7614, -73.9776]
        ]
      },
      {
        "name": "Route B - Highway Bypass",
        "waypoints": [
          [40.7128, -74.0060],
          [40.7614, -73.9776],
          [40.7580, -73.9855]
        ]
      }
    ],
    "truck_load_kg": 2500,
    "truck_capacity_kg": 5000
  }'
```

**Expected Response:**
```json
{
  "routes": [
    {
      "route_name": "Route A - Through Downtown",
      "efficiency_score": 62,
      "final_delivery_time_min": 35.8,
      "total_cost_usd": 69.53,
      ...
    },
    {
      "route_name": "Route B - Highway Bypass",
      "efficiency_score": 78,
      "final_delivery_time_min": 18.2,
      "total_cost_usd": 32.15,
      ...
    }
  ],
  "best_route": "Route B - Highway Bypass",
  "best_efficiency": 78,
  "recommendation": "🚦 Route A - Through Downtown will cause 36 min delay → switching to Route B - Highway Bypass saves 18 min + $37 + 0.2 kg CO₂",
  "savings": {
    "time_minutes": 17.6,
    "cost_usd": 37.38,
    "co2_kg": 0.15
  }
}
```

---

## Test 3: Using Python (requests library)

```python
import requests
import json

# Set API endpoint
API_URL = "http://localhost:5001/api/delivery"

# Create sample routes
routes_data = {
    "routes": [
        {
            "name": "Downtown Route",
            "waypoints": [
                [40.7128, -74.0060],
                [40.7580, -73.9855],
                [40.7614, -73.9776],
            ]
        },
        {
            "name": "Highway Route",
            "waypoints": [
                [40.7128, -74.0060],
                [40.7614, -73.9776],
                [40.7580, -73.9855],
            ]
        }
    ],
    "truck_load_kg": 2500,
    "truck_capacity_kg": 5000
}

# Compare routes
response = requests.post(
    f"{API_URL}/compare-routes",
    json=routes_data,
    headers={"Content-Type": "application/json"}
)

result = response.json()
print("\n✨ Route Comparison Result:\n")
print(f"Best Route: {result['best_route']}")
print(f"Efficiency Score: {result['best_efficiency']}/100")
print(f"\n💡 Recommendation:")
print(result['recommendation'])
print(f"\n💰 Savings by switching:")
print(f"  • Time: {result['savings']['time_minutes']} minutes")
print(f"  • Cost: ${result['savings']['cost_usd']}")
print(f"  • CO₂: {result['savings']['co2_kg']} kg")
```

---

## What the Numbers Mean

### Efficiency Score (0-100)
- **90-100:** Excellent route (minimal delay, low cost, low emissions)
- **70-89:** Good route (acceptable delays, reasonable cost)
- **50-69:** Fair route (may have traffic/weather issues)
- **<50:** Poor route (significant delays or high costs)

### Delay Breakdown
- **Weather Delay:** Rain, snow, wind, etc.
  - Clear: 0 min
  - Light rain: 10-15 min
  - Heavy rain: 45+ min
  - Snow: 90 min
  
- **Traffic Delay:** Congestion impact
  - Low: < 5 min
  - Medium: 5-15 min
  - High: 15-30 min
  - Critical: > 30 min

### Cost Calculation
- **Fuel Cost:** $0.15 per km (diesel, ~60L/100km consumption)
- **Delay Cost:** $2.50 per minute (driver labor + penalties)
- **Total Cost = Fuel Cost + Delay Cost**

### CO₂ Emissions
- Base: 0.12 kg CO₂ per km (fully loaded truck)
- Adjusted for truck utilization (under-loaded trucks burn more fuel)
- Example: 50% loaded = 1.5x emissions per km

---

## Development Notes

### Mock Data (Default)
By default, weather and traffic return **mocked random data**:
- No API keys required
- Perfect for development & testing
- Simulates realistic variations

### Real APIs (Optional)
To use **real** weather + traffic data:

#### OpenWeatherMap (Free tier: 1000 calls/day)
1. Get API key: https://openweathermap.org/api
2. Set env var: `export OPENWEATHER_API_KEY=your_key`

#### Google Maps (Free tier: 25,000 requests/month)
1. Get API key: https://cloud.google.com/maps-platform
2. Set env var: `export GOOGLE_MAPS_API_KEY=your_key`
3. Install: `pip install googlemaps`

```bash
# Example with env vars on Windows (PowerShell)
$env:OPENWEATHER_API_KEY="your_api_key_here"
python Frontend/api/server.py
```

---

## Demo Scenario

**Situation:** A construction site needs to deliver materials today but weather forecast shows rain.

**Query:** Compare two routes
- Route A: Direct route through city (fastest normally, ~10 km)
- Route B: Highway bypass (longer, ~15 km, but avoids rain)

**System Analysis:**
- Route A: 15 min rain delay + 12 min traffic = 27 min total delay, $69 cost
- Route B: 5 min rain delay + 2 min traffic = 7 min total delay, $32 cost
- **Recommendation:** "Route B saves 20 minutes + $37 in costs"

**Impact:** 🏆
- **Time Saved:** 20 min (finish delivery earlier, more time for next job)
- **Cost Saved:** $37 (company profit increases)
- **Safety:** Avoid heavy rain zone
- **Emissions:** 0.15 kg less CO₂ (sustainability metric)
