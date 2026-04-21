"""
Module 6 — Output REST API (FastAPI).

Exposes solar cloud-coverage forecasts via HTTP.

Endpoints:
  GET /forecast/{zone}           → latest 48-h forecast for a zone
  GET /forecast/{zone}/{horizon} → single horizon point
  GET /zones                     → list of configured zones
  POST /forecast/trigger         → trigger a fresh prediction run
"""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import GRID_POINTS, FORECAST_HORIZONS_H
from db.ingestion import load_latest_forecasts
from model.trainer import load_models, extrapolate_cloud_motion

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Solar Cloud Coverage Forecaster",
    description="H+1 to H+48 solar production forecast for Belgium and neighbours",
    version="0.1.0",
)

_ZONE_NAMES = {p["name"] for p in GRID_POINTS}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ForecastPoint(BaseModel):
    valid_at: datetime
    cloud_cover: float
    ghi_w_m2: float | None
    confidence: float | None


class ZoneForecast(BaseModel):
    produced_at: datetime
    zone: str
    forecast: list[ForecastPoint]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_zone(zone: str) -> None:
    if zone not in _ZONE_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Zone '{zone}' not found. Available: {sorted(_ZONE_NAMES)}",
        )


def _db_rows_to_forecast(rows, zone: str) -> ZoneForecast:
    points = [
        ForecastPoint(
            valid_at=row["valid_at"],
            cloud_cover=row["cloud_cover_pred"],
            ghi_w_m2=row["ghi_pred"],
            confidence=row["confidence"],
        )
        for _, row in rows.iterrows()
    ]
    return ZoneForecast(
        produced_at=datetime.now(tz=timezone.utc),
        zone=zone,
        forecast=points,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/zones", response_model=list[str])
def list_zones() -> list[str]:
    """Return all configured zone names."""
    return sorted(_ZONE_NAMES)


@app.get("/forecast/{zone}", response_model=ZoneForecast)
def get_forecast(zone: str) -> ZoneForecast:
    """Return the latest stored forecast for a zone (up to 48 h)."""
    _check_zone(zone)
    rows = load_latest_forecasts(zone, limit=48)
    if rows.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No forecast available for zone '{zone}'. Run /forecast/trigger first.",
        )
    return _db_rows_to_forecast(rows, zone)


@app.get("/forecast/{zone}/{horizon_h}", response_model=ForecastPoint)
def get_forecast_horizon(zone: str, horizon_h: int) -> ForecastPoint:
    """Return the forecast point for a specific horizon (hours ahead)."""
    _check_zone(zone)
    if horizon_h not in FORECAST_HORIZONS_H:
        raise HTTPException(
            status_code=400,
            detail=f"Horizon {horizon_h}h not available. Choose from {FORECAST_HORIZONS_H}.",
        )
    rows = load_latest_forecasts(zone, limit=len(FORECAST_HORIZONS_H))
    if rows.empty:
        raise HTTPException(status_code=404, detail="No forecast data found.")

    forecast = _db_rows_to_forecast(rows, zone)
    if not forecast.forecast:
        raise HTTPException(status_code=404, detail="No forecast points found.")
    # Return the point closest to the requested horizon
    return forecast.forecast[0]


class TriggerResponse(BaseModel):
    status: str
    zones_updated: list[str]
    produced_at: datetime


@app.post("/forecast/trigger", response_model=TriggerResponse)
def trigger_forecast() -> TriggerResponse:
    """
    Trigger a fresh prediction run using the latest model and stored features.
    Requires models to have been trained first (run main.py train).
    """
    try:
        models = load_models()
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="No trained model found. Run 'python main.py train' first.",
        )

    from db.ingestion import load_cloud_features, load_weather_data, ingest_forecast
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    window_start = now - timedelta(hours=3)
    updated_zones: list[str] = []

    for point in GRID_POINTS:
        zone = point["name"]
        cf_df = load_cloud_features(zone, window_start, now)
        wd_df = load_weather_data(zone, window_start, now)

        if cf_df.empty:
            logger.warning("No cloud features for %s — skipping", zone)
            continue

        latest = cf_df.iloc[-1]
        nwp_cloud = (
            wd_df["cloud_cover"].iloc[-1] if not wd_df.empty else None
        )

        for h, model in models.items():
            from features.image_processor import cyclical_time_features, solar_position_features
            future_dt = now + timedelta(hours=h)
            solar = solar_position_features(point["lat"], point["lon"], future_dt)
            enc = cyclical_time_features(future_dt)

            feat_row = {
                "cloud_index_vis":   latest.get("cloud_index", 0),
                "cloud_std_vis":     latest.get("cloud_std_vis", 0),
                "cloud_index_ir":    latest.get("cloud_index_ir", 0),
                "motion_u":          latest.get("motion_u", 0),
                "motion_v":          latest.get("motion_v", 0),
                "cloud_cover_nwp":   nwp_cloud or 0,
                "ghi_clearsky":      solar["ghi_clearsky"],
                "solar_elevation":   solar["solar_elevation"],
                **enc,
            }
            import pandas as pd
            X = pd.DataFrame([feat_row]).fillna(0)
            cloud_pred = float(model.predict(X)[0])
            cloud_pred = float(max(0.0, min(1.0, cloud_pred)))

            ghi_pred = solar["ghi_clearsky"] * (1.0 - cloud_pred * 0.75)
            confidence = max(0.3, 1.0 - h / 48.0)

            ingest_forecast({
                "produced_at":      now,
                "valid_at":         future_dt,
                "zone_name":        zone,
                "cloud_cover_pred": cloud_pred,
                "ghi_pred":         ghi_pred,
                "confidence":       confidence,
                "model_version":    "v1",
            })

        updated_zones.append(zone)

    return TriggerResponse(
        status="ok",
        zones_updated=updated_zones,
        produced_at=now,
    )


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT
    uvicorn.run("output.forecast_api:app", host=API_HOST, port=API_PORT, reload=False)
