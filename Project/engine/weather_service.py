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
        
        condition = data["weather"][0]["main"].lower()
        rainfall = data.get("rain", {}).get("1h", 0)
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
        delay += int((wind_kmh - 30) * 0.5)
    
    return delay


def get_weather_for_route(
    waypoints: list
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
