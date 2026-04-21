"""
Module 2 — Open-Meteo enrichment fetcher.

Retrieves NWP variables (cloud cover, GHI, temperature, wind…) from
Open-Meteo for each grid point in GRID_POINTS.

Two modes:
  - forecast  : /forecast endpoint, up to 7-day horizon, 1-h resolution
  - archive   : /archive endpoint, historical backfill for ML training
"""

import logging
from datetime import date, datetime, timezone

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

from config import GRID_POINTS, OPEN_METEO_VARIABLES

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"


def _build_client() -> openmeteo_requests.Client:
    """Return an Open-Meteo client with cache + auto-retry."""
    session = requests_cache.CachedSession(".cache/openmeteo", expire_after=3600)
    session = retry(session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=session)


_CLIENT = _build_client()


def _parse_response(response) -> pd.DataFrame:
    """Convert an Open-Meteo response object to a tidy DataFrame."""
    hourly = response.Hourly()
    # Build date range from the response metadata
    times = pd.date_range(
        start=pd.Timestamp(hourly.Time(), unit="s", tz="UTC"),
        end=pd.Timestamp(hourly.TimeEnd(), unit="s", tz="UTC"),
        freq=pd.Timedelta(seconds=hourly.Interval()),
        inclusive="left",
    )
    data = {"captured_at": times}
    for i, var in enumerate(OPEN_METEO_VARIABLES):
        values = hourly.Variables(i)
        data[var] = values.ValuesAsNumpy() if values else None

    return pd.DataFrame(data)


def fetch_forecast(point: dict) -> pd.DataFrame:
    """Fetch 7-day hourly forecast for a single grid point."""
    params = {
        "latitude": point["lat"],
        "longitude": point["lon"],
        "hourly": OPEN_METEO_VARIABLES,
        "timezone": "UTC",
        "forecast_days": 7,
    }
    responses = _CLIENT.weather_api(_FORECAST_URL, params=params)
    df = _parse_response(responses[0])
    df["zone_name"] = point["name"]
    df["source"] = "forecast"
    logger.info("Forecast fetched for %s — %d rows", point["name"], len(df))
    return df


def fetch_archive(point: dict, start: date, end: date) -> pd.DataFrame:
    """Fetch historical hourly data for a single grid point."""
    params = {
        "latitude": point["lat"],
        "longitude": point["lon"],
        "hourly": OPEN_METEO_VARIABLES,
        "timezone": "UTC",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    responses = _CLIENT.weather_api(_ARCHIVE_URL, params=params)
    df = _parse_response(responses[0])
    df["zone_name"] = point["name"]
    df["source"] = "archive"
    logger.info(
        "Archive fetched for %s — %d rows (%s → %s)",
        point["name"], len(df), start, end,
    )
    return df


def fetch_all_forecasts() -> pd.DataFrame:
    """Fetch forecast for every configured grid point and concatenate."""
    frames = [fetch_forecast(p) for p in GRID_POINTS]
    return pd.concat(frames, ignore_index=True)


def fetch_all_archive(start: date, end: date) -> pd.DataFrame:
    """Backfill historical data for every configured grid point."""
    frames = [fetch_archive(p, start, end) for p in GRID_POINTS]
    return pd.concat(frames, ignore_index=True)


def backfill_90_days() -> pd.DataFrame:
    """Convenience wrapper: pull the last 90 days of archive data."""
    today = datetime.now(tz=timezone.utc).date()
    from datetime import timedelta
    start = today - timedelta(days=90)
    logger.info("Starting 90-day backfill %s → %s", start, today)
    return fetch_all_archive(start, today)
