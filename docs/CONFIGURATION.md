# Configuration reference

All configuration is read in `config.py` and wired from environment variables
(via `python-dotenv` / `os.getenv`). A `.env` file at the project root is
loaded automatically; in production, use real environment variables instead.

For the docker-compose deployment, additional Postgres credentials are read
directly by `docker-compose.yml`.

---

## 1. Environment variables

### 1.1 Application (`config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://user:password@localhost:5432/solar_forecast` | SQLAlchemy URL for the PostgreSQL/TimescaleDB instance. Use the `postgresql+psycopg2://` form to be explicit about the driver. |
| `DATA_DIR` | `data/raw` | Filesystem location for saved tile JPEGs and JSON sidecars. Must be writable by the scraper process. |
| `SCRAPE_INTERVAL_MINUTES` | `15` | Period of the blocking scrape loop and the scheduler's `scrape` + `feature_worker` jobs. |
| `API_HOST` | `0.0.0.0` | FastAPI bind address. |
| `API_PORT` | `8000` | FastAPI bind port. |
| `OPENMETEO_CACHE_TTL` | `3600` (read in `open_meteo.fetcher`) | TTL in seconds for the Open-Meteo HTTP cache. |

### 1.2 docker-compose only

These are consumed by `docker-compose.yml`; the `db` service uses them to
initialise Postgres, and the application services use them to build their
`DATABASE_URL`.

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `solar_forecast` | Database name created on first boot. |
| `POSTGRES_USER` | `solar` | DB role used by the application. |
| `POSTGRES_PASSWORD` | **required** (no default) | DB role password. The compose file fails fast with a clear error if unset — there is no checked-in default. |

### 1.3 Not yet wired

`OPENMETEO_CACHE_TTL` is documented in `.env.example` but not yet read by
`open_meteo.fetcher` (which hard-codes `expire_after=3600`). Wiring it is a
follow-up task.

---

## 2. Code-level configuration

These constants live in `config.py` and are intentionally not env-driven —
they describe the geographic scope of the project. Edit the file and restart
the scheduler/API to apply changes.

### 2.1 `SAT24_BASE_URL`

`https://imn-rust-lb.infoplaza.io/v4/nowcast/tiles` — the (undocumented)
sat24 tile endpoint. Don't change unless Infoplaza moves the endpoint.

### 2.2 `CHANNELS`

```python
CHANNELS = {
    "visible":  "satellite-europe",
    "infrared": "satellite-infrared",
}
```

Key = internal label stored in the DB and used to choose the directory under
`DATA_DIR`. Value = path segment in the sat24 URL. Add a third channel by
extending this dict and the matching DB enum tolerance (the column is a
plain `VARCHAR(20)`).

### 2.3 `TILES`

```python
TILES = [
    {"zoom": 5, "x1": 16, "y1": 10, "x2": 17, "y2": 11},
    …
]
```

SlippyMap/TMS coordinates of the rectangles to fetch. The defaults
approximately cover lat [49.5N, 51.6N] × lon [2.5E, 6.5E]. **These are
placeholders — calibrate against actual tile pixel content for your area
before relying on the cloud index.**

### 2.4 `GRID_POINTS`

```python
GRID_POINTS = [
    {"name": "brussels", "lat": 50.85, "lon": 4.35},
    …
]
```

The list of zones. `name` is the FK-like identifier used across all tables
(`zone_name`) and in the API. Coordinates are passed to Open-Meteo and to
`pvlib.location.Location`.

### 2.5 `OPEN_METEO_VARIABLES`

The hourly variables fetched per grid point. Order matters — values are
mapped back to columns in `_parse_response` by index. To add a variable:
append it here, then add the matching column to `WeatherData` /
`schema.sql` and to `_WEATHER_COL_MAP` in `db/ingestion.py`.

### 2.6 `FORECAST_HORIZONS_H`

```python
FORECAST_HORIZONS_H = [1, 3, 6, 12, 24, 48]
```

Lead times (hours) for which the trainer creates `target_h{HH}` columns and
the API serves predictions. Must be a subset of the values used at training
time.

### 2.7 `SAT24_MIN_REQUEST_INTERVAL_S`

Default `5`. Minimum sleep between sat24 HTTP calls (per §10 of the project
spec). **Do not lower this without Infoplaza's permission.**

---

## 3. ZONE_PIXEL_BBOXES

Defined in `features/pipeline_worker.py`, this maps each zone to a pixel
bounding box inside a tile image. The defaults are placeholders. To
calibrate:

1. Fetch one real tile for `(zoom, x1, y1)`.
2. Identify the pixel coordinates of each city/region.
3. Update the dict and restart the worker.

Until this is calibrated, the per-zone cloud index is essentially
zone-labelled noise.

---

## 4. Sample `.env`

```
# DB (host install)
DATABASE_URL=postgresql+psycopg2://solar:CHANGE_ME@localhost:5432/solar_forecast

# DB (docker-compose) — POSTGRES_PASSWORD is mandatory
POSTGRES_DB=solar_forecast
POSTGRES_USER=solar
POSTGRES_PASSWORD=CHANGE_ME

# Scraper
SCRAPE_INTERVAL_MINUTES=15
DATA_DIR=data/raw

# API
API_HOST=0.0.0.0
API_PORT=8000
```
