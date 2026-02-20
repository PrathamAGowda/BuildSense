#!/usr/bin/env python3
"""
BuildSense — Unified Pipeline
══════════════════════════════════════════════════════════════════════
Combines:
  P1 — Material input, management & adaptive waste adjustment
  P2 — Truck load allocation (knapsack optimisation)
  P3 — Truck routing & emissions (CVRP via OR-Tools)

Six-Phase Workflow
──────────────────
  Phase 1  Project Initialization   Record baseline planned quantities
  Phase 2  Smart Ordering           Recommend order qty with adaptive buffer
  Phase 3  Inventory Tracking       Track used vs remaining in real time
  Phase 4  Reorder Monitoring       Alert when stock hits low-level threshold
  Phase 5  Waste Review             Record actual consumption, compute waste %
  Phase 6  Adaptive Update          EMA-based buffer update for next cycle

  + Delivery Planning: truck load optimisation + route planning + CO₂ estimate

Run:
    python main.py
"""

import sys
import os

# Ensure the project root is on sys.path so all sub-packages resolve.
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.store import load_materials, save_materials
from cli.workflows import (
    workflow_initialize_phase,
    workflow_smart_order,
    workflow_track_inventory,
    workflow_reorder_check,
    workflow_complete_phase,
    workflow_plan_delivery,
    workflow_view_report,
    workflow_all_materials,
    workflow_add_material,
    workflow_reset_buffer,
)

# ─────────────────────────────────────────────────────────────────── #
#  UI strings                                                          #
# ─────────────────────────────────────────────────────────────────── #

BANNER = r"""
  ╔══════════════════════════════════════════════════════════╗
  ║   ██████╗ ██╗   ██╗██╗██╗     ██████╗                  ║
  ║   ██╔══██╗██║   ██║██║██║     ██╔══██╗                 ║
  ║   ██████╔╝██║   ██║██║██║     ██║  ██║                 ║
  ║   ██╔══██╗██║   ██║██║██║     ██║  ██║                 ║
  ║   ██████╔╝╚██████╔╝██║███████╗██████╔╝                 ║
  ║   ╚═════╝  ╚═════╝ ╚═╝╚══════╝╚═════╝                  ║
  ║                                                          ║
  ║        S E N S E   —   Unified Pipeline                 ║
  ╚══════════════════════════════════════════════════════════╝
"""

MENU = """
  ┌──────────────────────────────────────────────────────────┐
  │   BuildSense  —  Main Menu                               │
  ├─────┬────────────────────────────────────────────────────┤
  │     │  MATERIAL MANAGEMENT PHASES                        │
  │  1  │  Phase 1 · Project Initialization                  │
  │  2  │  Phase 2 · Smart Ordering (with adaptive buffer)   │
  │  3  │  Phase 3 · Inventory & Consumption Tracking        │
  │  4  │  Phase 4 · Reorder Monitoring                      │
  │  5  │  Phase 5+6 · Waste Review & Adaptive Update        │
  ├─────┼────────────────────────────────────────────────────┤
  │     │  LOGISTICS                                         │
  │  6  │  Delivery Planning (truck load + route + CO₂)      │
  ├─────┼────────────────────────────────────────────────────┤
  │     │  REPORTS & SETTINGS                                │
  │  7  │  View full material history report                 │
  │  8  │  View all materials & buffers                      │
  │  9  │  Add a new material                                │
  │ 10  │  Reset a material buffer to baseline               │
  ├─────┼────────────────────────────────────────────────────┤
  │  0  │  Save & Exit                                       │
  └─────┴────────────────────────────────────────────────────┘
"""


# ─────────────────────────────────────────────────────────────────── #
#  Main loop                                                           #
# ─────────────────────────────────────────────────────────────────── #

def main() -> None:
    print(BANNER)
    print("  Loading material data…")
    materials = load_materials()
    print(f"  {len(materials)} material(s) loaded.\n")

    actions = {
        "1":  workflow_initialize_phase,
        "2":  workflow_smart_order,
        "3":  workflow_track_inventory,
        "4":  workflow_reorder_check,
        "5":  workflow_complete_phase,
        "6":  workflow_plan_delivery,
        "7":  workflow_view_report,
        "8":  workflow_all_materials,
        "9":  workflow_add_material,
        "10": workflow_reset_buffer,
    }

    while True:
        print(MENU)
        choice = input("  Enter choice: ").strip()

        if choice == "0":
            save_materials(materials)
            print("\n  ✔  Data saved. Goodbye!\n")
            break

        handler = actions.get(choice)
        if handler is None:
            print("  ⚠  Invalid choice. Please enter 0–10.\n")
            continue

        try:
            handler(materials)
        except KeyboardInterrupt:
            print("\n\n  Interrupted. Returning to menu…\n")
        except Exception as exc:
            print(f"\n  ✗  Error: {exc}\n")


if __name__ == "__main__":
    main()
