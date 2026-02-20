# BuildSense

Adaptive construction material management system — tracks material consumption across project phases, learns from waste patterns, forecasts future usage, and optimises multi-truck deliveries with weather + traffic awareness.

---

## Quick Start

```bash
# 1. Activate the venv and install dependencies
source .venv/bin/activate
pip install -r Project/requirements.txt

# 2. Start the API (from the repo root)
/Users/pratham/Desktop/BuildSense/.venv/bin/python Frontend/api/server.py

# 3. Open the UI — served by Flask at:
#    http://localhost:5001
```

API base URL: `http://localhost:5001/api`  
Default port: `5001`

---

## Project Layout

```
BuildSense/
├── Project/
│   ├── engine/
│   │   ├── material_engine.py    # Phase 1–6 core logic
│   │   ├── logistics_engine.py   # Truck loading + CVRP routing + CO₂
│   │   ├── forecasting.py        # Adaptive MA / ARIMA forecasting
│   │   ├── rerouting_engine.py   # Weather + traffic route analysis
│   │   ├── weather_service.py    # OpenWeatherMap integration (mock-ready)
│   │   └── traffic_service.py    # Google Maps traffic integration (mock-ready)
│   ├── models/
│   │   ├── material.py           # Material, PhaseRecord, DailyUsageEntry dataclasses
│   │   └── delivery.py           # TruckAssignment, Site dataclasses
│   └── data/
│       ├── store.py              # JSON persistence helpers
│       ├── materials.json        # Persistent material + phase history
│       └── sites.json            # Depot + delivery site coordinates
├── Frontend/
│   ├── index.html                # Single-file SPA (dark UI, sidebar nav)
│   └── api/
│       └── server.py             # Flask REST API
└── requirements.txt
```

---

## Workflow — Phase by Phase

The system follows a 6-phase cycle per material per project phase. Each phase builds on the previous one.

---

### Phase 1 — Initialise Phase

**What it does:**  
Records the planned quantity for a material and calculates the recommended order by applying the current adaptive buffer.

**Endpoint:** `POST /api/phase/initialize`

**Request:**
```json
{
  "material":    "Cement",
  "phase_name":  "Foundation",
  "planned_qty": 200
}
```

**Response fields:**

| Field | What it means |
|---|---|
| `material` | Material name (normalised to title case) |
| `unit` | Unit of measurement (bags, kg, tons, etc.) |
| `phase_name` | Name given to this phase |
| `planned_qty` | Baseline quantity required for this phase |
| `ordered_qty` | Recommended order = `planned_qty × (1 + buffer_pct / 100)` — includes buffer to cover expected waste |
| `phase_index` | 0-based index of this phase in the material's history |

**Why `ordered_qty > planned_qty`:**  
The buffer absorbs expected waste so you don't run short mid-phase. The buffer adapts over time based on real consumption.

---

### Phase 2 — Smart Ordering

**What it does:**  
Calculates the recommended order quantity for any planned amount without creating a phase record — useful for pre-planning.

**Endpoint:** `POST /api/phase/smart-order`

**Request:**
```json
{ "material": "Steel", "planned_qty": 150 }
```

**Response fields:**

| Field | What it means |
|---|---|
| `planned_qty` | What you said you need |
| `buffer_pct` | Current adaptive buffer for this material |
| `recommended_qty` | `planned_qty × (1 + buffer_pct / 100)` — how much to actually order |

---

### Phase 3 — Inventory Tracking

Phase 3 has three sub-operations: daily usage logging, manual inventory snapshots, and consumption forecasting.

#### 3a. Log Daily Usage

**Endpoint:** `POST /api/phase/log-daily-usage`

**Request:**
```json
{
  "material":    "Cement",
  "phase_index": 0,
  "qty_used":    12.5,
  "date":        "2026-02-20"
}
```

**Response fields:**

| Field | What it means |
|---|---|
| `consumed_qty` | Total consumed so far in this phase (sum of all daily entries) |
| `remaining_stock` | `ordered_qty − consumed_qty` — stock left |
| `ordered_qty` | Total stock allocated for this phase |
| `daily_usage` | Full list of `{date, quantity}` entries logged |
| `avg_per_active_day` | Average consumption on days that had an entry (ignores gaps) |
| `avg_per_calendar_day` | Average spread across all calendar days elapsed — includes zero-use days; more realistic for planning |
| `active_days` | Number of distinct dates with a log entry |
| `calendar_days` | Calendar span from first to last entry (inclusive) |
| `days_remaining_est` | Estimated days until stock runs out at the current calendar rate |

**`avg_per_active_day` vs `avg_per_calendar_day`:**  
If you log 100 units over 10 working days but 20 calendar days have passed (weekends off), `avg_per_active_day` = 10/day and `avg_per_calendar_day` = 5/day. The calendar rate gives a more honest picture of stock depletion over real time.

#### 3b. Inventory Status (manual snapshot)

**Endpoint:** `POST /api/phase/inventory-status`

**Request:**
```json
{ "ordered_qty": 220, "consumed_qty": 80, "carry_in": 10 }
```

**Response fields:**

| Field | What it means |
|---|---|
| `total_available` | `ordered_qty + carry_in` |
| `used` | Consumed so far |
| `remaining` | `total_available − used` |
| `utilization_pct` | `used / total_available × 100` — what percentage of stock has been consumed |

#### 3c. Consumption Forecast

**What it does:**  
Projects future material usage based on logged history. Uses **Moving Average (MA)** for short histories, automatically upgrading to **ARIMA/ARMA** once enough data is available.

Model selection rules:
- **MA** is used when: calendar days of history < 14, OR log entries < 10
- **ARIMA/ARMA** is used when: both thresholds are exceeded

**Endpoint:** `POST /api/phase/forecast`

**Request:**
```json
{
  "material":    "Cement",
  "phase_index": 0,
  "horizon":     14
}
```

**Response fields:**

| Field | What it means |
|---|---|
| `model` | Model used, e.g. `"MA(window=7)"`, `"ARMA(1,1)"`, `"auto_ARIMA(1,0,1)"` |
| `regime` | `"MA"` or `"ARIMA"` — which regime was selected |
| `horizon` | Number of days forecasted ahead |
| `forecast` | List of `{date, qty}` — predicted daily usage for each future day |
| `total_forecast` | Sum of all predicted daily quantities over the horizon (= expected total future consumption) |
| `expected_excess` | `ordered_qty − consumed_qty − total_forecast` — **positive = likely surplus, negative = likely shortfall** |
| `backtest_mape` | Backtest Mean Absolute Percentage Error (%) — how well the model fits recent history; lower = more reliable |
| `note` | Why this model was chosen and on how many data points |
| `warning` | Set if MAPE > 25% (unreliable) or a fallback was used; `null` if forecast looks healthy |
| `thresholds.ma_threshold_calendar_days` | Days of history before ARIMA kicks in (default: 14) |
| `thresholds.min_arima_points` | Log entries before ARIMA kicks in (default: 10) |
| `data_available.log_entries` | Number of daily entries used |
| `data_available.calendar_days` | Calendar span of the history |

**How to read `expected_excess`:**
- `+50` → if the current burn pattern holds for `horizon` days, you'll have ~50 units surplus
- `−30` → you'll run short by ~30 units — consider reordering

**Why the MA forecast is a flat line:**  
With MA, all future days get the same predicted value (the recent average rate). This is by design — it means "we don't have enough history to detect a trend, so we assume the current rate continues." The forecast becomes non-flat once ARIMA/ARMA takes over with more data.

**Burn rate vs. forecast — the difference:**
- **Average burn rate** = what has been happening so far (descriptive)
- **Forecast** = what is likely to happen next if that pattern continues, and what surplus/shortfall results (predictive)

---

### Phase 4 — Reorder Monitoring

**What it does:**  
Flags when remaining stock falls to or below 20% of the ordered quantity and suggests a reorder amount.

**Endpoint:** `POST /api/phase/reorder-check`

**Request:**
```json
{
  "material":    "Cement",
  "ordered_qty": 220,
  "remaining":   35,
  "planned_qty": 200
}
```

**Response fields:**

| Field | What it means |
|---|---|
| `alert` | `true` if remaining ≤ 20% of ordered — reorder recommended now |
| `remaining` | Current remaining stock |
| `threshold_qty` | Trigger level = 20% of ordered quantity |
| `suggested_reorder_qty` | If alert is `true`: recommended reorder = `planned_qty × current_buffer`; `0` if no alert |

---

### Phase 5 — Close Phase (Waste Review)

**What it does:**  
Finalises the phase: records actual consumption, computes real waste percentage, and triggers the Phase 6 adaptive buffer update.

**Endpoint:** `POST /api/phase/complete`

**Request:**
```json
{
  "material":     "Cement",
  "phase_name":   "Foundation",
  "planned_qty":  200,
  "ordered_qty":  220,
  "consumed_qty": 195,
  "carry_in":     0
}
```

**Response fields:**

| Field | What it means |
|---|---|
| `planned_qty` | What you planned to use |
| `ordered_qty` | What you actually ordered |
| `consumed_qty` | What was actually used |
| `remaining_stock` | `ordered_qty + carry_in − consumed_qty` — leftover |
| `waste_pct` | `(ordered − consumed) / ordered × 100` — positive = over-ordered (surplus/waste), negative = under-ordered (ran short) |
| `new_buffer_pct` | Updated adaptive buffer — applied to the next phase's ordering |
| `baseline_buffer` | Original default buffer set at material creation — for reference |
| `phases_logged` | Total completed phases for this material |

---

### Phase 6 — Adaptive Buffer Update (automatic)

**What it does:**  
Runs automatically on phase close. Updates the buffer using an Exponential Moving Average (EMA) so ordering improves over time.

**Formula:**
```
new_buffer = 0.7 × old_buffer + 0.3 × actual_waste_pct
```

Clamped to [0, 100].

**Effect over time:**
- Consistently over-ordering (high `waste_pct`) → buffer decreases → smaller safety margin → less waste
- Consistently under-ordering (negative `waste_pct`) → buffer increases → more safety stock → fewer shortages

Each completed phase makes the next order more accurate.

---

## Delivery Planning

### Plan a Delivery

**Endpoint:** `POST /api/delivery/plan`

Allocates materials to trucks (greedy knapsack by priority) then solves delivery routes (OR-Tools CVRP, or nearest-neighbour fallback).

**Request:**
```json
{
  "order_quantities": { "Cement": 500, "Steel": 200 },
  "trucks": [
    { "truck_id": "TRK-01", "capacity_kg": 10000 },
    { "truck_id": "TRK-02", "capacity_kg": 8000 }
  ],
  "rain_expected": false
}
```

**Response — per truck:**

| Field | What it means |
|---|---|
| `truck_id` | Truck identifier |
| `capacity_kg` | Maximum load |
| `used_kg` | Total weight loaded |
| `utilization_pct` | `used_kg / capacity_kg × 100` |
| `materials` | `{material: units}` — what's on this truck |
| `route` | Ordered list of site names for this truck's delivery sequence |
| `distance_km` | Total route distance |
| `co2_kg` | Estimated CO₂ emissions (based on distance, load, and utilisation) |

### Analyse a Single Route

**Endpoint:** `POST /api/delivery/analyze-route`

**Request:**
```json
{
  "route_name": "Route A",
  "waypoints": [[12.9716, 77.5946], [13.0827, 80.2707]],
  "truck_load_kg": 2500,
  "truck_capacity_kg": 5000
}
```

**Response fields:**

| Field | What it means |
|---|---|
| `base_distance_km` | Haversine distance between waypoints |
| `base_time_min` | Travel time at 60 km/h with no delays |
| `weather.total_delay_minutes` | Delay from weather conditions |
| `weather.risk_level` | `clear / low / moderate / high / critical` |
| `traffic.delay_minutes` | Extra time from congestion |
| `traffic.congestion_level` | `low / medium / high / critical` |
| `delay_minutes` | Total delay (weather + traffic) |
| `final_delivery_time_min` | `base_time + delay_minutes` |
| `fuel_cost_usd` | `distance × $0.15/km` |
| `delay_cost_usd` | `delay_minutes × $2.50/min` (labour + penalties) |
| `total_cost_usd` | `fuel_cost + delay_cost` |
| `co2_kg` | CO₂ for this route at this load |
| `utilization_pct` | `truck_load_kg / truck_capacity_kg × 100` |
| `efficiency_score` | 0–100 composite score: 40% distance, 35% delay, 15% emissions, 10% utilisation |
| `risk_level` | Overall route risk level |

### Compare Routes

**Endpoint:** `POST /api/delivery/compare-routes`

Accepts 2+ named routes and returns all analyses plus:

| Field | What it means |
|---|---|
| `best_route` | Name of the highest-efficiency route |
| `best_efficiency` | Its efficiency score (0–100) |
| `recommendation` | Natural language reason why this route is preferred |
| `savings.time_minutes` | Minutes saved vs. worst route |
| `savings.cost_usd` | Cost saved vs. worst route |
| `savings.co2_kg` | CO₂ saved vs. worst route |

---

## Materials API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/materials` | GET | List all materials with full history |
| `/api/materials` | POST | Add a new material |
| `/api/materials/<name>` | DELETE | Remove a material |
| `/api/materials/<name>/reset-buffer` | POST | Reset adaptive buffer to its baseline value |
| `/api/sites` | GET | List all delivery sites |

**Material object key fields:**

| Field | What it means |
|---|---|
| `baseline_buffer_pct` | Original default buffer — starting point |
| `buffer_pct` | Current live adaptive buffer — changes after each phase |
| `weight_per_unit` | kg per unit — used for truck load planning |
| `priority` | 1–10; higher priority materials are loaded onto trucks first |
| `phases_logged` | Number of completed phases |
| `history` | Array of PhaseRecord objects — one per completed phase |

---

## Dependencies

```
flask / flask-cors
numpy
pandas
statsmodels       # ARIMA fallback
pmdarima          # auto_arima (preferred for ARIMA regime)
ortools           # CVRP routing (optional — greedy fallback exists)
```

Optional real-API environment variables (system uses mock data without them):

```bash
export OPENWEATHER_API_KEY=your_key   # real weather delays
export GOOGLE_MAPS_API_KEY=your_key   # real traffic delays
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| API not reachable | Verify server is running: `lsof -i :5001` |
| CORS error | Open via `http://localhost:5001`, not `file://` |
| OR-Tools not found | Delivery still works — greedy routing activates automatically |
| ARIMA not available | Falls back to `statsmodels`; if neither available, falls back to MA |
| Forecast always flat | Expected for short histories (< 14 calendar days / < 10 entries); ARIMA activates automatically with more data |
