"""
Traffic Service — Real-time traffic & congestion estimation
Google Maps API or mocked data for development
"""

import os
from typing import List, Tuple, Dict
from datetime import datetime


def get_traffic_for_route(
    waypoints: List[Tuple[float, float]],
    route_name: str = "Route A"
) -> Dict:
    """
    Get traffic delays for a multi-stop route
    
    Returns: {
        "route_name": str,
        "total_distance_km": float,
        "free_flow_time_min": float,
        "current_time_min": float,
        "delay_minutes": float,
        "congestion_level": "low|medium|high|critical",
        "segments": [...]
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
            departure_time="now",
            mode="driving",
        )
        
        if not result:
            return _mock_traffic_route(waypoints, route_name)
        
        route = result[0]
        leg_data = route["legs"]
        
        total_distance = sum(leg["distance"]["value"] for leg in leg_data) / 1000
        total_duration = sum(leg["duration"]["value"] for leg in leg_data) / 60
        
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
