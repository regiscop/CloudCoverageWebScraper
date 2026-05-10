import os
from dotenv import load_dotenv

load_dotenv()

# Local-first default: SQLite file in ./data/. No Postgres install required for
# a single-user run on an SPM B2B BE workstation. Override DATABASE_URL in .env
# to point at a Postgres/TimescaleDB instance for shared / production setups.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/solar_forecast.db")
DATA_DIR = os.getenv("DATA_DIR", "data/raw")
MODEL_DIR = os.getenv("MODEL_DIR", "models")
SCRAPE_INTERVAL_MINUTES = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "15"))

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# Sat24 tile API base
SAT24_BASE_URL = "https://imn-rust-lb.infoplaza.io/v4/nowcast/tiles"

CHANNELS = {
    "visible": "satellite-europe",
    "infrared": "satellite-infrared",
}

# Tiles covering BE/NL/FR-nord at zoom level 5 (SlippyMap TMS convention)
# Approximate bounding box: lat [49.5N–51.6N], lon [2.5E–6.5E]
TILES = [
    {"zoom": 5, "x1": 16, "y1": 10, "x2": 17, "y2": 11},
    {"zoom": 5, "x1": 16, "y1": 11, "x2": 17, "y2": 12},
    {"zoom": 5, "x1": 17, "y1": 10, "x2": 18, "y2": 11},
    {"zoom": 5, "x1": 17, "y1": 11, "x2": 18, "y2": 12},
]

# Open-Meteo grid points over the region of interest
GRID_POINTS = [
    {"name": "brussels",   "lat": 50.85, "lon": 4.35},
    {"name": "liege",      "lat": 50.63, "lon": 5.57},
    {"name": "ghent",      "lat": 51.05, "lon": 3.72},
    {"name": "amsterdam",  "lat": 52.37, "lon": 4.90},
    {"name": "paris_nord", "lat": 49.90, "lon": 2.30},
    {"name": "luxembourg", "lat": 49.61, "lon": 6.13},
    {"name": "cologne",    "lat": 50.94, "lon": 6.96},
    {"name": "lille",      "lat": 50.63, "lon": 3.06},
]

OPEN_METEO_VARIABLES = [
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
]

# Forecast horizons in hours used as ML targets
FORECAST_HORIZONS_H = [1, 3, 6, 12, 24, 48]

# Minimum seconds between HTTP requests to sat24 (courteous rate limiting)
SAT24_MIN_REQUEST_INTERVAL_S = 5
