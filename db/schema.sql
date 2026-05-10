-- Module 3 — PostgreSQL + TimescaleDB schema
-- Run once against an empty database that already has the TimescaleDB extension.
-- For Delta Lake / Databricks, use the same column definitions; partition by date(captured_at).

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw satellite tile metadata
CREATE TABLE IF NOT EXISTS satellite_images (
    id          BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL,
    channel     VARCHAR(20)  NOT NULL,  -- 'visible' | 'infrared'
    zoom_level  INT,
    tile_x1     INT,
    tile_y1     INT,
    tile_x2     INT,
    tile_y2     INT,
    file_path   TEXT,
    cloud_index FLOAT,   -- mean pixel value normalised 0–1
    cloud_std   FLOAT,   -- spatial variance
    processed   BOOLEAN  DEFAULT FALSE
);
SELECT create_hypertable('satellite_images', 'captured_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sat_channel ON satellite_images (channel, captured_at DESC);
-- Prevent duplicate ingestion of the same tile at the same timestamp.
-- captured_at is included so the index aligns with the hypertable partition key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sat_unique_tile
    ON satellite_images (captured_at, channel, zoom_level, tile_x1, tile_y1);

-- Per-zone cloud features extracted from images
CREATE TABLE IF NOT EXISTS cloud_features (
    id              BIGSERIAL PRIMARY KEY,
    captured_at     TIMESTAMPTZ NOT NULL,
    zone_name       VARCHAR(50),
    cloud_index     FLOAT,
    cloud_index_ir  FLOAT,
    cloud_std_vis   FLOAT,
    motion_u        FLOAT,   -- optical-flow x component (pixels/frame)
    motion_v        FLOAT,   -- optical-flow y component (pixels/frame)
    channel         VARCHAR(20)
);
SELECT create_hypertable('cloud_features', 'captured_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_cf_zone ON cloud_features (zone_name, captured_at DESC);

-- Open-Meteo NWP observations and forecasts
CREATE TABLE IF NOT EXISTS weather_data (
    id           BIGSERIAL PRIMARY KEY,
    captured_at  TIMESTAMPTZ NOT NULL,
    zone_name    VARCHAR(50),
    cloud_cover  FLOAT,
    cloud_cover_low  FLOAT,
    cloud_cover_mid  FLOAT,
    cloud_cover_high FLOAT,
    ghi          FLOAT,   -- shortwave_radiation W/m²
    direct_rad   FLOAT,
    diffuse_rad  FLOAT,
    temperature  FLOAT,
    wind_speed   FLOAT,
    wind_dir     FLOAT,
    precipitation FLOAT,
    source       VARCHAR(20)  -- 'forecast' | 'archive'
);
SELECT create_hypertable('weather_data', 'captured_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_wd_zone ON weather_data (zone_name, captured_at DESC);

-- Model-produced solar forecasts
CREATE TABLE IF NOT EXISTS solar_forecasts (
    id                BIGSERIAL PRIMARY KEY,
    produced_at       TIMESTAMPTZ NOT NULL,
    valid_at          TIMESTAMPTZ NOT NULL,
    zone_name         VARCHAR(50),
    cloud_cover_pred  FLOAT,
    ghi_pred          FLOAT,
    confidence        FLOAT,
    model_version     VARCHAR(20)
);
SELECT create_hypertable('solar_forecasts', 'produced_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sf_zone_valid ON solar_forecasts (zone_name, valid_at DESC);
