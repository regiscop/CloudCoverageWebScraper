"""
Module 3 — Ingestion pipeline.

Persists satellite image metadata, Open-Meteo weather rows,
cloud features, and solar forecasts to the database.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

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
) -> bool:
    """Insert one satellite image row. Idempotent: returns False if a row for
    this (captured_at, channel, zoom_level, tile_x1, tile_y1) already exists.
    """
    session = get_session()
    try:
        existing = (
            session.query(SatelliteImage.id)
            .filter(
                SatelliteImage.captured_at == captured_at,
                SatelliteImage.channel == channel,
                SatelliteImage.zoom_level == tile["zoom"],
                SatelliteImage.tile_x1 == tile["x1"],
                SatelliteImage.tile_y1 == tile["y1"],
            )
            .first()
        )
        if existing is not None:
            return False

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
        try:
            session.commit()
        except IntegrityError:
            # Concurrent insert won the race — treat as a no-op.
            session.rollback()
            return False
        logger.debug("Ingested satellite metadata id=%s", row.id)
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_WEATHER_COL_MAP = {
    "captured_at":      "captured_at",
    "zone_name":        "zone_name",
    "cloud_cover":      "cloud_cover",
    "cloud_cover_low":  "cloud_cover_low",
    "cloud_cover_mid":  "cloud_cover_mid",
    "cloud_cover_high": "cloud_cover_high",
    "shortwave_radiation": "ghi",
    "direct_radiation": "direct_rad",
    "diffuse_radiation": "diffuse_rad",
    "temperature_2m":   "temperature",
    "wind_speed_10m":   "wind_speed",
    "wind_direction_10m": "wind_dir",
    "precipitation":    "precipitation",
    "source":           "source",
}


def ingest_weather_dataframe(df: pd.DataFrame) -> int:
    """Bulk-insert an Open-Meteo DataFrame; returns number of rows inserted."""
    if df.empty:
        return 0

    records = []
    for _, r in df.iterrows():
        record = {
            db_col: r.get(src_col)
            for src_col, db_col in _WEATHER_COL_MAP.items()
            if src_col in df.columns
        }
        record.setdefault("source", r.get("source", "forecast"))
        records.append(record)

    session = get_session()
    try:
        session.bulk_insert_mappings(WeatherData, records)
        session.commit()
        logger.info("Ingested %d weather rows", len(records))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return len(records)


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


def ingest_cloud_features_bulk(records: list[dict], session=None) -> int:
    """Bulk-insert cloud feature records. If `session` is provided, reuses it
    and does NOT commit (caller controls the transaction); otherwise opens its
    own session and commits.
    """
    if not records:
        return 0

    own_session = session is None
    sess = session or get_session()
    try:
        sess.bulk_insert_mappings(CloudFeature, records)
        if own_session:
            sess.commit()
        return len(records)
    except Exception:
        if own_session:
            sess.rollback()
        raise
    finally:
        if own_session:
            sess.close()


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
    """Return the most recent forecast run for a zone, ordered by valid_at asc.

    Filters on the latest `produced_at` so callers always see a coherent run
    rather than a mix of rows from successive prediction triggers.
    """
    session = get_session()
    try:
        latest_produced_at = (
            session.query(SolarForecast.produced_at)
            .filter(SolarForecast.zone_name == zone_name)
            .order_by(SolarForecast.produced_at.desc())
            .limit(1)
            .scalar()
        )
        if latest_produced_at is None:
            return pd.DataFrame()

        q = (
            session.query(SolarForecast)
            .filter(
                SolarForecast.zone_name == zone_name,
                SolarForecast.produced_at == latest_produced_at,
            )
            .order_by(SolarForecast.valid_at.asc())
            .limit(limit)
        )
        return pd.read_sql(q.statement, session.bind)
    finally:
        session.close()
