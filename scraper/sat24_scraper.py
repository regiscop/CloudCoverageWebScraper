"""
Module 1 — Sat24 tile scraper.

Fetches VIS and IR satellite tiles from the infoplaza tile API
and persists them locally with a JSON metadata sidecar.

Rate limiting: SAT24_MIN_REQUEST_INTERVAL_S seconds between HTTP calls
as required by §10 of the project specifications.

Improvement F: nocturnal fallback — VIS channel is automatically skipped
when solar elevation < 0° for the region centre; only IR + NWP are used.
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import pvlib
import pandas as pd
import requests

from config import (
    SAT24_BASE_URL,
    CHANNELS,
    TILES,
    DATA_DIR,
    SCRAPE_INTERVAL_MINUTES,
    SAT24_MIN_REQUEST_INTERVAL_S,
)
from db.ingestion import ingest_satellite_metadata

# Geographic centre of the target region (Belgium)
_REGION_LAT = 50.5
_REGION_LON = 4.5

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SolarForecastScraper/0.1)"}


def is_daytime(dt: datetime | None = None) -> bool:
    """Return True if the sun is above the horizon at the region centre."""
    if dt is None:
        dt = datetime.now(tz=timezone.utc)
    location = pvlib.location.Location(latitude=_REGION_LAT, longitude=_REGION_LON, tz="UTC")
    times = pd.DatetimeIndex([dt])
    solar_pos = location.get_solarposition(times)
    elevation = float(solar_pos["elevation"].iloc[0])
    return elevation > 0.0


def floor_to_slot(dt: datetime) -> datetime:
    """Return `dt` floored to the nearest 15-minute slot, with seconds zeroed."""
    floored_minutes = (dt.minute // 15) * 15
    return dt.replace(minute=floored_minutes, second=0, microsecond=0)


def build_timestamp(dt: datetime) -> str:
    """Return YYYYMMDDHHMI string floored to the nearest 15-minute slot."""
    floored = floor_to_slot(dt)
    return floored.strftime("%Y%m%d%H%M")


def fetch_tile(channel: str, timestamp: str, tile: dict) -> bytes | None:
    """Download a single tile JPEG; returns raw bytes or None on failure."""
    url = (
        f"{SAT24_BASE_URL}/{channel}/{timestamp}/"
        f"{tile['zoom']}/{tile['x1']}/{tile['y1']}"
        f"/{tile['x2']}/{tile['y2']}?outputtype=jpeg"
    )
    try:
        resp = requests.get(url, timeout=10, headers=_HEADERS)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        logger.warning("Tile fetch failed — %s: %s", url, exc)
        return None


def save_tile(data: bytes, channel: str, ts: str, tile: dict) -> Path:
    """Write JPEG + JSON sidecar under DATA_DIR/{channel}/{ts}/."""
    out_dir = Path(DATA_DIR) / channel / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"z{tile['zoom']}_{tile['x1']}_{tile['y1']}"

    img_path = out_dir / f"{stem}.jpg"
    img_path.write_bytes(data)

    meta = {
        "timestamp": ts,
        "channel": channel,
        "zoom": tile["zoom"],
        "x1": tile["x1"], "y1": tile["y1"],
        "x2": tile["x2"], "y2": tile["y2"],
        "saved_at": datetime.now(tz=timezone.utc).isoformat(),
        "file": str(img_path),
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(meta, indent=2))

    return img_path


def scrape_once(ts: str | None = None) -> list[Path]:
    """
    Fetch all configured tiles for all channels at timestamp `ts`
    (defaults to now floored to 15 min).

    Improvement F — nocturnal fallback:
    VIS channel is skipped at night (solar elevation ≤ 0); only IR is fetched.
    """
    now = datetime.now(tz=timezone.utc)
    captured_at = floor_to_slot(now)
    if ts is None:
        ts = build_timestamp(now)

    night = not is_daytime(now)
    if night:
        logger.info("Night-time detected — skipping VIS channel, IR only")

    saved: list[Path] = []
    for channel_name, channel_path in CHANNELS.items():
        if night and channel_name == "visible":
            continue
        for tile in TILES:
            img = fetch_tile(channel_path, ts, tile)
            if img:
                path = save_tile(img, channel_name, ts, tile)
                saved.append(path)
                logger.info("Saved %s", path)
                try:
                    ingest_satellite_metadata(
                        channel=channel_name,
                        captured_at=captured_at,
                        tile=tile,
                        file_path=path,
                    )
                except Exception:
                    # DB outage must not stop the scrape loop — files on disk
                    # are the source of truth and can be re-ingested later.
                    logger.exception("Failed to persist tile metadata for %s", path)
            # Courteous rate limiting between individual tile requests
            time.sleep(SAT24_MIN_REQUEST_INTERVAL_S)

    return saved


def scrape_loop(interval_minutes: int = SCRAPE_INTERVAL_MINUTES) -> None:
    """Blocking loop: scrape every `interval_minutes` minutes."""
    logger.info("Starting scrape loop — interval=%d min", interval_minutes)
    while True:
        start = time.monotonic()
        try:
            paths = scrape_once()
            logger.info("Round complete — %d tiles saved", len(paths))
        except Exception:
            logger.exception("Unexpected error during scrape round")

        elapsed = time.monotonic() - start
        sleep_s = max(0.0, interval_minutes * 60 - elapsed)
        logger.debug("Sleeping %.1f s until next round", sleep_s)
        time.sleep(sleep_s)
