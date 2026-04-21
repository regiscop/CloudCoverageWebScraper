"""
Module 3 — Ingestion pipeline.

Persists satellite image metadata, Open-Meteo weather rows,
cloud features, and solar forecasts to the database.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from db.models import (
    CloudFeature, SatelliteImage, SolarForecast, WeatherData, get_session,
)

logger = logging.getLogger(__name__)


def ingest_satellite_metadata(
    channel: str,
    captured_at: datetime,
    tile: dict,
    file_path: Path,
    cloud_index: float | None = None,
    cloud_std: float | None = None,
) -> None:
    session = get_session()
    try:
        row = SatelliteImage(
            captured_at=captured_at,
            channel=channel,
            zoom_level=tile["zoom"],
            tile_x1=tile["x1"],
            tile_y1=tile["y1"],
            tile_x2=tile["x2"],
            tile_y2=tile["y2"],
            file_path=str(file_path),
            cloud_index=cloud_index,
            cloud_std=cloud_std,
        )
        session.add(row)
        session.commit()
        logger.debug("Ingested satellite metadata id=%s", row.id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ingest_weather_dataframe(df: pd.DataFrame) -> int:
    """Bulk-insert an Open-Meteo DataFrame; returns number of rows inserted."""
    session = get_session()
    rows_inserted = 0
    try:
        for _, r in df.iterrows():
            row = WeatherData(
                captured_at=r["captured_at"],
                zone_name=r.get("zone_name"),
                cloud_cover=r.get("cloud_cover"),
                cloud_cover_low=r.get("cloud_cover_low"),
                cloud_cover_mid=r.get("cloud_cover_mid"),
                cloud_cover_high=r.get("cloud_cover_high"),
                ghi=r.get("shortwave_radiation"),
                direct_rad=r.get("direct_radiation"),
                diffuse_rad=r.get("diffuse_radiation"),
                temperature=r.get("temperature_2m"),
                wind_speed=r.get("wind_speed_10m"),
                wind_dir=r.get("wind_direction_10m"),
                precipitation=r.get("precipitation"),
                source=r.get("source", "forecast"),
            )
            session.add(row)
            rows_inserted += 1
        session.commit()
        logger.info("Ingested %d weather rows", rows_inserted)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return rows_inserted


def ingest_cloud_features(features: dict) -> None:
    """Persist a single cloud feature record."""
    session = get_session()
    try:
        row = CloudFeature(**features)
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ingest_forecast(forecast: dict) -> None:
    """Persist a single solar forecast record."""
    session = get_session()
    try:
        row = SolarForecast(**forecast)
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def load_cloud_features(zone_name: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Query cloud features for a zone within [start, end]."""
    session = get_session()
    try:
        q = (
            session.query(CloudFeature)
            .filter(
                CloudFeature.zone_name == zone_name,
                CloudFeature.captured_at >= start,
                CloudFeature.captured_at <= end,
            )
            .order_by(CloudFeature.captured_at)
        )
        return pd.read_sql(q.statement, session.bind)
    finally:
        session.close()


def load_weather_data(zone_name: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Query weather data for a zone within [start, end]."""
    session = get_session()
    try:
        q = (
            session.query(WeatherData)
            .filter(
                WeatherData.zone_name == zone_name,
                WeatherData.captured_at >= start,
                WeatherData.captured_at <= end,
            )
            .order_by(WeatherData.captured_at)
        )
        return pd.read_sql(q.statement, session.bind)
    finally:
        session.close()


def load_latest_forecasts(zone_name: str, limit: int = 48) -> pd.DataFrame:
    """Return the most recent `limit` forecast rows for a zone."""
    session = get_session()
    try:
        q = (
            session.query(SolarForecast)
            .filter(SolarForecast.zone_name == zone_name)
            .order_by(SolarForecast.valid_at.desc())
            .limit(limit)
        )
        return pd.read_sql(q.statement, session.bind)
    finally:
        session.close()
