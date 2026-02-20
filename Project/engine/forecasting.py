"""
BuildSense — Adaptive Forecasting Engine
─────────────────────────────────────────
Selects a forecasting model based on the number of calendar days
of daily-usage history available for a phase:

  • < MA_THRESHOLD calendar days  →  Moving Average (MA window)
  • ≥ MA_THRESHOLD calendar days  →  ARMA / ARIMA (auto-order via pmdarima
                                     or ARMA(1,1) fallback via statsmodels)

Returns a unified ForecastResult so callers never need to know which
model ran.  All heavy dependencies (pmdarima, statsmodels) are soft-
imported — if absent the engine degrades gracefully to MA.

Public API
──────────
    result = forecast_consumption(daily_usage, ordered_qty, consumed_qty, horizon=14)

    result.model          – str, e.g. "MA(7)", "ARMA(2,1)", "auto_arima(1,0,1)"
    result.horizon        – int, days ahead forecasted
    result.forecast       – list[dict]  [{"date": "YYYY-MM-DD", "qty": float}, ...]
    result.total_forecast – float, sum of forecast quantities
    result.expected_excess – float, ordered − consumed − total_forecast  (neg = shortfall)
    result.backtest_mape  – float | None, rolling-origin MAPE % on held-out tail
    result.note           – str, human-readable explanation of model choice
    result.warning        – str | None, set if MAPE is high or fallback was used
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

# ── soft imports ──────────────────────────────────────────────────────────── #
try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

try:
    from pmdarima import auto_arima as _auto_arima  # type: ignore
    _HAS_PMDARIMA = True
except Exception:
    _HAS_PMDARIMA = False

try:
    from statsmodels.tsa.arima.model import ARIMA as _ARIMA  # type: ignore
    _HAS_STATS = True
except Exception:
    _HAS_STATS = False


# ── tuneable constants ────────────────────────────────────────────────────── #

# Switch from MA → ARIMA once we have at least this many calendar days
MA_THRESHOLD: int = 14

# Minimum actual data points (log entries) required before ARIMA is attempted
MIN_ARIMA_POINTS: int = 10

# Moving-average window (days) used in the MA regime
MA_WINDOW: int = 7

# High-MAPE warning threshold — warn user when backtest MAPE exceeds this
MAPE_WARN_THRESHOLD: float = 25.0

# Rolling-origin backtest size (tail points held out)
BACKTEST_SIZE: int = 7


# ── result dataclass ──────────────────────────────────────────────────────── #

@dataclass
class ForecastResult:
    model:           str
    horizon:         int
    forecast:        List[Dict]       # [{"date": "YYYY-MM-DD", "qty": float}]
    total_forecast:  float
    expected_excess: float            # positive = surplus, negative = shortfall
    backtest_mape:   Optional[float]  # None when too few points
    note:            str
    warning:         Optional[str] = None


# ── series helpers ────────────────────────────────────────────────────────── #

def _build_series(daily_usage: List[Dict]) -> "pd.Series":
    """Build a gap-filled daily pd.Series from daily_usage list."""
    if not _HAS_PANDAS:
        raise ImportError("pandas is required for forecasting.")

    if not daily_usage:
        return pd.Series(dtype=float)

    df = pd.DataFrame(daily_usage)
    df["date"] = pd.to_datetime(df["date"])
    s = df.groupby("date")["quantity"].sum().sort_index()
    idx = pd.date_range(start=s.index.min(), end=s.index.max(), freq="D")
    return s.reindex(idx, fill_value=0.0).astype(float)


def _calendar_days(s: "pd.Series") -> int:
    if s.empty:
        return 0
    return (s.index[-1] - s.index[0]).days + 1


def _future_dates(last_date: "pd.Timestamp", horizon: int) -> List[str]:
    return [(last_date + timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(horizon)]


def _clamp_forecast(vals: np.ndarray) -> np.ndarray:
    """Forecast quantities cannot be negative."""
    return np.maximum(vals, 0.0)


# ── MAPE helpers ─────────────────────────────────────────────────────────── #

def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    denom = np.where(np.abs(actual) < 1e-6, 1.0, np.abs(actual))
    return float(np.mean(np.abs((actual - pred) / denom))) * 100.0


def _backtest_ma(s: "pd.Series", window: int, n: int) -> Optional[float]:
    if len(s) < window + n + 1:
        return None
    errs = []
    for k in range(n, 0, -1):
        hist = s.iloc[: len(s) - k]
        pred = float(hist[-window:].mean()) if len(hist) >= window else float(hist.mean())
        actual = float(s.iloc[len(s) - k])
        denom = max(abs(actual), 1e-6)
        errs.append(abs((actual - pred) / denom))
    return round(float(np.mean(errs)) * 100.0, 2) if errs else None


def _backtest_arima_statsmodels(
    s: "pd.Series", order: Tuple[int, int, int], n: int
) -> Optional[float]:
    if len(s) < n * 2 + 2:
        return None
    errs = []
    for k in range(n, 0, -1):
        cutoff = len(s) - k
        train = s.iloc[:cutoff]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = _ARIMA(train, order=order).fit()
                pred = float(m.get_forecast(steps=1).predicted_mean.iloc[0])
        except Exception:
            continue
        actual = float(s.iloc[cutoff])
        denom = max(abs(actual), 1e-6)
        errs.append(abs((actual - pred) / denom))
    return round(float(np.mean(errs)) * 100.0, 2) if errs else None


def _backtest_pmdarima(s: "pd.Series", n: int) -> Optional[float]:
    if len(s) < n * 2 + 2:
        return None
    errs = []
    for k in range(n, 0, -1):
        cutoff = len(s) - k
        train = s.iloc[:cutoff]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = _auto_arima(
                    train, seasonal=False,
                    error_action="ignore", suppress_warnings=True,
                    max_p=3, max_q=3, max_d=1,
                )
                pred = float(m.predict(n_periods=1)[0])
        except Exception:
            continue
        actual = float(s.iloc[cutoff])
        denom = max(abs(actual), 1e-6)
        errs.append(abs((actual - pred) / denom))
    return round(float(np.mean(errs)) * 100.0, 2) if errs else None


# ── regime 1: Moving Average ─────────────────────────────────────────────── #

def _forecast_ma(
    s: "pd.Series",
    horizon: int,
    ordered_qty: float,
    consumed_qty: float,
) -> ForecastResult:
    window = min(MA_WINDOW, len(s))
    mean_val = float(s[-window:].mean()) if len(s) >= window else float(s.mean())
    fc_vals = _clamp_forecast(np.full(horizon, mean_val))
    dates = _future_dates(s.index[-1], horizon)
    bk = _backtest_ma(s, window, min(BACKTEST_SIZE, len(s) // 3))

    total = float(fc_vals.sum())
    excess = round(ordered_qty - consumed_qty - total, 4)
    warn = None
    if bk is not None and bk > MAPE_WARN_THRESHOLD:
        warn = f"High forecast error: backtest MAPE = {bk:.1f}% (threshold {MAPE_WARN_THRESHOLD}%). Results may be unreliable."

    return ForecastResult(
        model=f"MA(window={window})",
        horizon=horizon,
        forecast=[{"date": d, "qty": round(v, 4)} for d, v in zip(dates, fc_vals)],
        total_forecast=round(total, 4),
        expected_excess=excess,
        backtest_mape=bk,
        note=f"Used {len(s)}-point MA with window={window}. "
             f"Fewer than {MA_THRESHOLD} calendar days — switching to ARIMA later.",
        warning=warn,
    )


# ── regime 2: ARIMA / ARMA ───────────────────────────────────────────────── #

def _forecast_arima(
    s: "pd.Series",
    horizon: int,
    ordered_qty: float,
    consumed_qty: float,
) -> ForecastResult:
    """
    Try (in order):
      1. pmdarima auto_arima  — auto order selection, ARMA preferred (d=0 if stationary)
      2. statsmodels ARMA(1,1) — reliable fallback, no integration needed for short series
      3. statsmodels ARIMA(1,1,1) — if series is non-stationary
      4. MA fallback
    """

    # ── attempt 1: pmdarima auto_arima ──────────────────────────────────── #
    if _HAS_PMDARIMA:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = _auto_arima(
                    s, seasonal=False,
                    error_action="ignore", suppress_warnings=True,
                    max_p=3, max_q=3, max_d=1,
                    information_criterion="aic",
                )
                fc_vals = _clamp_forecast(model.predict(n_periods=horizon))
                order = getattr(model, "order", "?")
                p, d, q = order
                # Determine if purely ARMA (d=0)
                model_label = f"ARMA({p},{q})" if d == 0 else f"ARIMA{order}"

                dates = _future_dates(s.index[-1], horizon)
                bk = _backtest_pmdarima(s, min(BACKTEST_SIZE, len(s) // 3))
                total = float(fc_vals.sum())
                excess = round(ordered_qty - consumed_qty - total, 4)
                warn = None
                if bk is not None and bk > MAPE_WARN_THRESHOLD:
                    warn = f"High forecast error: backtest MAPE = {bk:.1f}%. Interpret with caution."

                return ForecastResult(
                    model=f"auto_{model_label}",
                    horizon=horizon,
                    forecast=[{"date": d, "qty": round(v, 4)} for d, v in zip(dates, fc_vals)],
                    total_forecast=round(total, 4),
                    expected_excess=excess,
                    backtest_mape=bk,
                    note=f"auto_arima selected order {order} on {len(s)} calendar days of data.",
                    warning=warn,
                )
        except Exception:
            pass  # fall through

    # ── attempt 2: statsmodels ARMA(1,1) ────────────────────────────────── #
    if _HAS_STATS:
        for order in [(1, 0, 1), (1, 1, 1)]:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    m = _ARIMA(s, order=order).fit()
                    fc_vals = _clamp_forecast(m.get_forecast(steps=horizon).predicted_mean.values)
                    p, d, q = order
                    label = f"ARMA({p},{q})" if d == 0 else f"ARIMA{order}"

                    dates = _future_dates(s.index[-1], horizon)
                    bk = _backtest_arima_statsmodels(s, order, min(BACKTEST_SIZE, len(s) // 3))
                    total = float(fc_vals.sum())
                    excess = round(ordered_qty - consumed_qty - total, 4)
                    warn = None
                    if bk is not None and bk > MAPE_WARN_THRESHOLD:
                        warn = f"High forecast error: backtest MAPE = {bk:.1f}%. Interpret with caution."

                    return ForecastResult(
                        model=label,
                        horizon=horizon,
                        forecast=[{"date": d, "qty": round(v, 4)} for d, v in zip(dates, fc_vals)],
                        total_forecast=round(total, 4),
                        expected_excess=excess,
                        backtest_mape=bk,
                        note=f"statsmodels {label} fitted on {len(s)} calendar days of data.",
                        warning=warn,
                    )
            except Exception:
                continue

    # ── attempt 3: fallback to MA ────────────────────────────────────────── #
    result = _forecast_ma(s, horizon, ordered_qty, consumed_qty)
    result.model = f"MA(fallback, window={min(MA_WINDOW, len(s))})"
    result.note = (
        f"ARIMA unavailable (pmdarima={_HAS_PMDARIMA}, statsmodels={_HAS_STATS}). "
        f"Fell back to MA on {len(s)} calendar days."
    )
    result.warning = "Install pmdarima or statsmodels to enable ARIMA forecasting."
    return result


# ── public entry point ────────────────────────────────────────────────────── #

def forecast_consumption(
    daily_usage:  List[Dict],
    ordered_qty:  float,
    consumed_qty: float,
    horizon:      int = 14,
) -> ForecastResult:
    """
    Main entry point.

    Parameters
    ──────────
    daily_usage  : list of {"date": "YYYY-MM-DD", "quantity": float}
    ordered_qty  : total amount ordered for this phase
    consumed_qty : amount consumed so far
    horizon      : calendar days to forecast ahead

    Returns
    ───────
    ForecastResult  (see module docstring)
    """
    if not _HAS_PANDAS:
        # absolute fallback with no pandas
        warn_msg = "pandas not installed — install it to enable forecasting."
        empty_dates = [(date.today() + timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(horizon)]
        return ForecastResult(
            model="none",
            horizon=horizon,
            forecast=[{"date": d, "qty": 0.0} for d in empty_dates],
            total_forecast=0.0,
            expected_excess=round(ordered_qty - consumed_qty, 4),
            backtest_mape=None,
            note="pandas unavailable — run: pip install pandas",
            warning=warn_msg,
        )

    s = _build_series(daily_usage)

    if s.empty or s.sum() == 0:
        empty_dates = [(date.today() + timedelta(days=i + 1)).strftime("%Y-%m-%d") for i in range(horizon)]
        return ForecastResult(
            model="zero",
            horizon=horizon,
            forecast=[{"date": d, "qty": 0.0} for d in empty_dates],
            total_forecast=0.0,
            expected_excess=round(ordered_qty - consumed_qty, 4),
            backtest_mape=None,
            note="No usage data logged yet.",
        )

    cal_days = _calendar_days(s)
    n_points = len(daily_usage)   # raw log entries (may be < cal_days due to gaps)

    # ── regime selection ─────────────────────────────────────────────────── #
    if cal_days < MA_THRESHOLD or n_points < MIN_ARIMA_POINTS:
        return _forecast_ma(s, horizon, ordered_qty, consumed_qty)
    else:
        return _forecast_arima(s, horizon, ordered_qty, consumed_qty)
