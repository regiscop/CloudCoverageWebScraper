"""
SQLAlchemy ORM models — mirrors db/schema.sql.
Used by the ingestion pipeline and the output API.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, Integer, String, Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from config import DATABASE_URL

# Use the portable DateTime(timezone=True) instead of the postgres-only
# TIMESTAMP(timezone=True). Works identically with SQLite (local default)
# and PostgreSQL/TimescaleDB.
TIMESTAMP = DateTime


class Base(DeclarativeBase):
    pass


class SatelliteImage(Base):
    __tablename__ = "satellite_images"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    captured_at = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    channel     = Column(String(20), nullable=False)
    zoom_level  = Column(Integer)
    tile_x1     = Column(Integer)
    tile_y1     = Column(Integer)
    tile_x2     = Column(Integer)
    tile_y2     = Column(Integer)
    file_path   = Column(Text)
    cloud_index = Column(Float)
    cloud_std   = Column(Float)
    processed   = Column(Boolean, default=False)


class CloudFeature(Base):
    __tablename__ = "cloud_features"

    id             = Column(BigInteger, primary_key=True, autoincrement=True)
    captured_at    = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    zone_name      = Column(String(50))
    cloud_index    = Column(Float)
    cloud_index_ir = Column(Float)
    cloud_std_vis  = Column(Float)
    motion_u       = Column(Float)
    motion_v       = Column(Float)
    channel        = Column(String(20))


class WeatherData(Base):
    __tablename__ = "weather_data"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    captured_at      = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    zone_name        = Column(String(50))
    cloud_cover      = Column(Float)
    cloud_cover_low  = Column(Float)
    cloud_cover_mid  = Column(Float)
    cloud_cover_high = Column(Float)
    ghi              = Column(Float)
    direct_rad       = Column(Float)
    diffuse_rad      = Column(Float)
    temperature      = Column(Float)
    wind_speed       = Column(Float)
    wind_dir         = Column(Float)
    precipitation    = Column(Float)
    source           = Column(String(20))


class SolarForecast(Base):
    __tablename__ = "solar_forecasts"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    produced_at      = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    valid_at         = Column(TIMESTAMP(timezone=True), nullable=False)
    zone_name        = Column(String(50))
    cloud_cover_pred = Column(Float)
    ghi_pred         = Column(Float)
    confidence       = Column(Float)
    model_version    = Column(String(20))


def get_engine():
    # SQLite needs the parent directory to exist before connect.
    if DATABASE_URL.startswith("sqlite:///"):
        from pathlib import Path
        db_path = DATABASE_URL.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(DATABASE_URL)


def get_session(engine=None) -> Session:
    from sqlalchemy.orm import sessionmaker
    eng = engine or get_engine()
    return sessionmaker(bind=eng)()


def create_tables(engine=None) -> None:
    """Create all tables (non-TimescaleDB environments only)."""
    Base.metadata.create_all(engine or get_engine())
