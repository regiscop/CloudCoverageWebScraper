"""
Module 1 — Sat24 tile scraper.

Fetches VIS and IR satellite tiles from the infoplaza tile API
and persists them locally with a JSON metadata sidecar.

Rate limiting: SAT24_MIN_REQUEST_INTERVAL_S seconds between HTTP calls
as required by §10 of the project specifications.
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import (
    SAT24_BASE_URL,
    CHANNELS,
    TILES,
    DATA_DIR,
    SCRAPE_INTERVAL_MINUTES,
    SAT24_MIN_REQUEST_INTERVAL_S,
)

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SolarForecastScraper/0.1)"}


def build_timestamp(dt: datetime) -> str:
    """Return YYYYMMDDHHMI string floored to the nearest 15-minute slot."""
    floored_minutes = (dt.minute // 15) * 15
    return dt.strftime(f"%Y%m%d%H{floored_minutes:02d}")


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
    Returns list of saved image paths.
    """
    if ts is None:
        ts = build_timestamp(datetime.now(tz=timezone.utc))

    saved: list[Path] = []
    for channel_name, channel_path in CHANNELS.items():
        for tile in TILES:
            img = fetch_tile(channel_path, ts, tile)
            if img:
                path = save_tile(img, channel_name, ts, tile)
                saved.append(path)
                logger.info("Saved %s", path)
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
