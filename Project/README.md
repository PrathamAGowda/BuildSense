# BuildSense — Adaptive Ordering & Delivery

A unified pipeline for adaptive material ordering and multi-truck delivery planning for construction projects.

Key capabilities

- Adaptive buffer learning for material orders (EMA-based) so ordered quantities improve over cycles.
- Smart ordering recommendations that apply adaptive buffers to planned quantities.
- Inventory tracking with daily usage logging and calendar-aware consumption statistics.
- Reorder checks and suggested top-ups when stock approaches critical thresholds.
- Delivery planning: greedy knapsack truck loading and multi-truck routing (OR-Tools CVRP when available) with CO₂ estimation per run.

Status (current)

- Core engines (material and logistics) are implemented under `Project/engine/` and are stable.
- A Flask API used by the frontend is located at `Frontend/api/server.py` and serves endpoints for materials, phases, ordering, inventory and delivery planning (default port: 5001).
- A single-file frontend SPA at `Frontend/index.html` provides a lightweight dark UI with a sidebar workflow. The UI was recently redesigned to remove phase numbers and streamline the flow.
- Persistent JSON storage is handled by `Project/data/store.py` and the data files `Project/data/materials.json` and `Project/data/sites.json`.

Quick start (development)

1. Create / activate a Python virtual environment and install requirements:
   - macOS / zsh example:
     ```bash
     python -m venv .venv
     source .venv/bin/activate
     pip install -r Project/requirements.txt
     ```

2. Start the backend API (default: http://localhost:5001):

   ```bash
   python Frontend/api/server.py
   ```

   The API exposes endpoints used by the SPA (GET/POST for `materials`, `phase/*`, `delivery/*`).

3. Open the frontend SPA in a browser:
   - Open `Frontend/index.html` directly (file://) or serve it from a simple static server. The SPA uses `fetch()` against the API at `http://localhost:5001/api`.

Notes on running

- If OR-Tools is not installed the routing engine falls back to a greedy heuristic — all delivery features remain functional.
- The project includes an example virtual environment at the workspace root (`.venv`) if you want a ready-to-use python binary path: `.venv/bin/python`.

Project layout (important files)

- `Project/engine/material_engine.py` — business logic for Phases 1–6 (initialize, smart-order, inventory, reorder, complete, EMA update).
- `Project/engine/logistics_engine.py` — knapsack and routing helpers, CO₂ estimation.
- `Project/data/store.py` — JSON persistence helpers; data files live in `Project/data/`.
- `Frontend/api/server.py` — Flask REST API for frontend consumption.
- `Frontend/index.html` — single-file SPA (recent redesign: sidebar, no phase numbers, compact cards & progress bars).

Frontend notes

- The SPA expects the API base URL at `http://localhost:5001/api`.
- Sections: Materials, Initialize, Smart Order, Inventory, Reorder Check, Close Phase, Delivery.
- Manual inventory snapshot functionality is inside the Inventory section and outputs to `p3-manual` / `p3-manual-output` elements.

Developer notes

- The adaptive buffer algorithm uses an EMA: `new = 0.7*old + 0.3*waste_pct`, clamped to [0,100]. See `material_engine.py` for details.
- Recent UI rewrite shortened `Frontend/index.html` (cleaner structure). If you edit the SPA, prefer concise DOM changes — JS logic lives inline in the same file.
- Tests and linting: add unit tests for `Project/engine` helpers if you extend algorithms or add OR-Tools specifics.

Troubleshooting

- API not reachable: ensure the Flask process is running and listening on port 5001 (`lsof -i :5001`).
- CORS / file:// issues: if opening the SPA as `file://` you may face cross-origin restrictions in some browsers. Serve the `Frontend/` folder with a tiny static server (e.g. `python -m http.server 8000` from the `Frontend/` directory) and open `http://localhost:8000`.

Contributing

- Keep UI changes small and focused. Update both SPA and API contract together if you add fields.
- Add unit tests to `Project/tests/` and update `requirements.txt` with any new runtime dependencies.

License

- (Insert project license here.)

Contact

- Maintainer: Pratham (local workspace).
