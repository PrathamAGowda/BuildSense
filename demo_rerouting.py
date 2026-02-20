#!/usr/bin/env python3
"""
Smart Transport Re-Routing Demo Script
Demonstrates the new weather + traffic aware route optimization
"""

import sys
import os

# Ensure the project root is on sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(ROOT, "Project")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.rerouting_engine import analyze_route_with_conditions, compare_routes


def demo_analyze_single_route():
    """Demo 1: Analyze a single route with weather + traffic"""
    print("\n" + "="*80)
    print("DEMO 1: Analyze Single Route with Weather + Traffic Impact")
    print("="*80)
    
    # New York City delivery route (example coordinates)
    waypoints = [
        (40.7128, -74.0060),  # Manhattan, NY (Depot)
        (40.7580, -73.9855),  # Midtown East
        (40.7614, -73.9776),  # Midtown Business District
    ]
    
    print("\n📍 Route: Manhattan Delivery")
    print(f"  • Starting point (Depot): 40.7128, -74.0060")
    print(f"  • Stop 1: 40.7580, -73.9855")
    print(f"  • Stop 2: 40.7614, -73.9776")
    print(f"  • Truck: 2500 kg loaded / 5000 kg capacity (50% utilization)")
    
    analysis = analyze_route_with_conditions(
        route_waypoints=waypoints,
        route_name="Route A - Direct Route",
        truck_load_kg=2500,
        truck_capacity_kg=5000,
    )
    
    print("\n📊 ROUTE ANALYSIS RESULTS:")
    print(f"  Base Distance: {analysis['base_distance_km']} km")
    print(f"  Base Time (no delays): {analysis['base_time_min']:.1f} minutes")
    
    print(f"\n  ☔ Weather Impact:")
    weather = analysis['weather']
    print(f"    • Condition: {weather['risk_level']}")
    print(f"    • Rain hazard: {'Yes' if weather['has_rain'] else 'No'}")
    print(f"    • Delay caused: {weather['total_delay_minutes']} minutes")
    
    print(f"\n  🚦 Traffic Impact:")
    traffic = analysis['traffic']
    print(f"    • Congestion: {traffic['congestion_level']}")
    print(f"    • Free-flow time: {traffic['free_flow_time_min']:.1f} min")
    print(f"    • Actual time: {traffic['current_time_min']:.1f} min")
    print(f"    • Delay caused: {traffic['delay_minutes']:.1f} minutes")
    
    print(f"\n  ⏱️  TOTAL DELIVERY TIME:")
    print(f"    • Final time: {analysis['final_delivery_time_min']:.1f} minutes")
    print(f"    • Total delay: {analysis['delay_minutes']:.1f} minutes")
    
    print(f"\n  💰 COST BREAKDOWN:")
    print(f"    • Fuel cost: ${analysis['fuel_cost_usd']:.2f}")
    print(f"    • Delay cost (labor/penalties): ${analysis['delay_cost_usd']:.2f}")
    print(f"    • Total cost: ${analysis['total_cost_usd']:.2f}")
    
    print(f"\n  🌱 ENVIRONMENTAL IMPACT:")
    print(f"    • CO₂ emissions: {analysis['co2_kg']:.2f} kg")
    print(f"    • Truck utilization: {analysis['utilization_pct']:.1f}%")
    
    print(f"\n  ⭐ EFFICIENCY SCORE: {analysis['efficiency_score']}/100")
    
    return analysis


def demo_compare_routes():
    """Demo 2: Compare multiple routes and show best option"""
    print("\n" + "="*80)
    print("DEMO 2: Compare Two Routes - See Which Is Better")
    print("="*80)
    
    # Route A: Direct through downtown (shorter but traffic)
    route_a_waypoints = [
        (40.7128, -74.0060),  # Depot
        (40.7580, -73.9855),  # Stop 1 (Downtown)
        (40.7614, -73.9776),  # Stop 2 (MidTown)
    ]
    
    # Route B: Highway bypass (longer but fewer delays)
    route_b_waypoints = [
        (40.7128, -74.0060),  # Depot
        (40.7614, -73.9776),  # Stop 2 first (via highway)
        (40.7580, -73.9855),  # Stop 1 (after short city drive)
    ]
    
    print("\n📍 SCENARIO: Weather forecast shows moderate rain + rush hour traffic")
    print("\n   Route A (Direct) vs Route B (Bypass):")
    print("   • Route A: Straight through downtown (10.2 km)")
    print("   • Route B: Highway bypass then local (12.8 km)")
    print("\n   Truck: 3000 kg loaded / 5000 kg capacity (60% utilization)")
    
    routes = [
        ("Route A - Direct Downtown", route_a_waypoints),
        ("Route B - Highway Bypass", route_b_waypoints),
    ]
    
    comparison = compare_routes(
        route_options=routes,
        truck_load_kg=3000,
        truck_capacity_kg=5000,
    )
    
    print("\n📊 COMPARISON RESULTS:\n")
    
    # Show each route
    for i, route_data in enumerate(comparison['routes'], 1):
        print(f"ROUTE {i}: {route_data['route_name']}")
        print(f"  Distance: {route_data['base_distance_km']} km")
        print(f"  Delivery time: {route_data['final_delivery_time_min']:.1f} minutes")
        print(f"  Cost: ${route_data['total_cost_usd']:.2f}")
        print(f"  CO₂: {route_data['co2_kg']:.2f} kg")
        print(f"  Efficiency: {route_data['efficiency_score']}/100")
        print()
    
    # Show recommendation
    print("\n🎯 RECOMMENDATION:")
    print(f"  Best route: {comparison['best_route']}")
    print(f"  Efficiency: {comparison['best_efficiency']}/100")
    print(f"\n  💡 {comparison['recommendation']}")
    
    # Show savings
    print(f"\n💰 SAVINGS BY SWITCHING:")
    print(f"  • Time: {comparison['savings']['time_minutes']:.1f} minutes faster")
    print(f"  • Cost: ${comparison['savings']['cost_usd']:.2f} cheaper")
    print(f"  • CO₂: {comparison['savings']['co2_kg']:.2f} kg less emissions")
    
    return comparison


def demo_bad_weather_scenario():
    """Demo 3: Show impact of bad weather on route choice"""
    print("\n" + "="*80)
    print("DEMO 3: Heavy Rain Scenario - Route Safety Analysis")
    print("="*80)
    
    # Same routes but with focus on weather impact
    route_a = (
        "Route A - Through City Center",
        [(40.7128, -74.0060), (40.7580, -73.9855), (40.7614, -73.9776)]
    )
    
    route_b = (
        "Route B - Elevated Highway (Safer in Rain)",
        [(40.7128, -74.0060), (40.7614, -73.9776), (40.7580, -73.9855)]
    )
    
    print("\n⚠️  SCENARIO: Heavy rain expected, water accumulation in low-lying areas")
    print("    Route A goes through downtown (lower elevation)")
    print("    Route B uses elevated highway (safer)")
    print("\n   Truck load: 2800 kg / 5000 kg (56% utilization)")
    
    comparison = compare_routes(
        route_options=[route_a, route_b],
        truck_load_kg=2800,
        truck_capacity_kg=5000,
    )
    
    print("\n📊 WEATHER RISK ANALYSIS:\n")
    for route_data in comparison['routes']:
        weather = route_data['weather']
        risk_emoji = {
            "clear": "✅",
            "low": "🟢",
            "moderate": "🟡",
            "high": "🟠",
            "critical": "🔴"
        }.get(weather['risk_level'], "❓")
        
        print(f"{route_data['route_name']}")
        print(f"  Risk level: {risk_emoji} {weather['risk_level']}")
        print(f"  Delay impact: {weather['total_delay_minutes']} minutes")
        print(f"  Efficiency score: {route_data['efficiency_score']}/100")
        print()
    
    print("🎯 RECOMMENDATION:")
    print(f"  {comparison['recommendation']}\n")


def main():
    """Run all demos"""
    print("\n" + "█"*80)
    print("█ 🚚 SMART TRANSPORT RE-ROUTING SYSTEM - LIVE DEMONSTRATION")
    print("█" + " "*78)
    print("█ Real-time weather + traffic aware route optimization for construction")
    print("█" + " "*78)
    print("█"*80)
    
    try:
        # Demo 1: Single route analysis
        demo_analyze_single_route()
        
        # Demo 2: Route comparison
        demo_compare_routes()
        
        # Demo 3: Bad weather scenario
        demo_bad_weather_scenario()
        
        # Summary
        print("\n" + "="*80)
        print("✨ DEMONSTRATION COMPLETE")
        print("="*80)
        print("\nKey Features Demonstrated:")
        print("  ✓ Real-time weather delay estimation")
        print("  ✓ Traffic congestion analysis")
        print("  ✓ Dynamic route comparison & recommendations")
        print("  ✓ Cost-benefit analysis (fuel, labor, delay penalties)")
        print("  ✓ CO₂ emissions tracking per route")
        print("  ✓ Risk assessment & safety prioritization")
        
        print("\n📈 Business Impact:")
        print("  💰 Quantified cost savings (time + fuel)")
        print("  🌱 Environmental sustainability metrics")
        print("  ⚡ Real-time decision support for dispatchers")
        print("  🎯 Automatic route optimization with explanations")
        
        print("\n🔧 To use with your own data:")
        print("  1. POST to /api/delivery/analyze-route with waypoints[lat, lon]")
        print("  2. POST to /api/delivery/compare-routes with multiple options")
        print("  3. API returns structured data ready for frontend display")
        
        print("\n📚 Documentation:")
        print("  • See SMART_REROUTING_GUIDE.md for full implementation guide")
        print("  • See REROUTING_TEST_EXAMPLES.md for API usage examples")
        
        print("\n")
    
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
