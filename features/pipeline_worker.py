"""
Improvement B — Automatic feature engineering pipeline worker.

Scans DATA_DIR for satellite tile images that have not yet been processed,
computes cloud index + optical flow for each zone, and inserts the resulting
feature rows into the cloud_features table.

Designed to be called periodically (via the scheduler) rather than as a
long-running file-watcher, keeping the logic simple and restartable.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import cv2
import pandas as pd

from config import DATA_DIR, GRID_POINTS, TILES
from db.ingestion import ingest_cloud_features_bulk
from db.models import SatelliteImage, get_session
from features.image_processor import (
    compute_cloud_index,
    load_grayscale,
    compute_optical_flow,
)

logger = logging.getLogger(__name__)

# Pixel bounding box per zone on a zoom-5 tile (placeholder — calibrate against
# actual tile pixel dimensions once real tiles are available).
# Format: (x_min, y_min, x_max, y_max) in pixels within the tile image.
ZONE_PIXEL_BBOXES: dict[str, tuple[int, int, int, int]] = {
    "brussels":   (40, 30, 90, 80),
    "liege":      (80, 30, 130, 80),
    "ghent":      (20, 20, 70, 70),
    "amsterdam":  (40, 0,  90, 50),
    "paris_nord": (0,  50, 50, 100),
    "luxembourg": (100, 50, 150, 100),
    "cologne":    (120, 20, 170, 70),
    "lille":      (10,  35, 60, 85),
}


def _load_metadata(json_path: Path) -> dict:
    return json.loads(json_path.read_text())


def _find_unprocessed_images(session) -> list[SatelliteImage]:
    return (
        session.query(SatelliteImage)
        .filter(SatelliteImage.processed == False)  # noqa: E712
        .order_by(SatelliteImage.captured_at)
        .all()
    )


def _find_previous_vis(session, captured_at: datetime, tile_key: str) -> str | None:
    """Return file_path of the most recent VIS image before captured_at for the same tile."""
    row = (
        session.query(SatelliteImage)
        .filter(
            SatelliteImage.channel == "visible",
            SatelliteImage.captured_at < captured_at,
            SatelliteImage.file_path.like(f"%{tile_key}%"),
            SatelliteImage.processed == True,  # noqa: E712
        )
        .order_by(SatelliteImage.captured_at.desc())
        .first()
    )
    return row.file_path if row else None


def _whole_image_mean(img_path: Path) -> float:
    """Mean intensity over the full image, normalised to [0, 1]."""
    from PIL import Image
    import numpy as np
    arr = np.array(Image.open(img_path).convert("L"))
    return float(arr.mean() / 255.0)


def process_image(record: SatelliteImage, session) -> int:
    """
    Process a single satellite image record: compute cloud index per zone,
    optical flow vs previous frame, and insert into cloud_features.
    Returns number of feature rows inserted.

    All cloud_features rows for this image are bulk-inserted in a single
    statement and committed alongside the SatelliteImage update — one
    transaction per image instead of one per zone.
    """
    img_path = Path(record.file_path)
    if not img_path.exists():
        logger.warning("Image file not found: %s", img_path)
        return 0

    tile_key = f"z{record.zoom_level}_{record.tile_x1}_{record.tile_y1}"
    is_vis = record.channel == "visible"

    records: list[dict] = []
    for point in GRID_POINTS:
        zone = point["name"]
        bbox = ZONE_PIXEL_BBOXES.get(zone)
        if bbox is None:
            continue

        idx = compute_cloud_index(img_path, bbox)

        motion_u, motion_v = None, None
        if is_vis:
            prev_path = _find_previous_vis(session, record.captured_at, tile_key)
            if prev_path and Path(prev_path).exists():
                frame_t0 = load_grayscale(prev_path)
                frame_t1 = load_grayscale(img_path)
                if frame_t0.shape != frame_t1.shape:
                    frame_t1 = cv2.resize(
                        frame_t1, (frame_t0.shape[1], frame_t0.shape[0])
                    )
                motion_u, motion_v = compute_optical_flow(frame_t0, frame_t1, bbox)

        records.append({
            "captured_at":    record.captured_at,
            "zone_name":      zone,
            "cloud_index":    idx["mean"] if is_vis else None,
            "cloud_index_ir": idx["mean"] if not is_vis else None,
            "cloud_std_vis":  idx["std"]  if is_vis else None,
            "motion_u":       motion_u,
            "motion_v":       motion_v,
            "channel":        record.channel,
        })

    ingest_cloud_features_bulk(records, session=session)

    record.processed = True
    record.cloud_index = _whole_image_mean(img_path)
    session.commit()

    return len(records)


def process_pending_images() -> int:
    """Process all unprocessed satellite images. Returns total feature rows inserted."""
    session = get_session()
    total = 0
    try:
        pending = _find_unprocessed_images(session)
        logger.info("Found %d unprocessed satellite images", len(pending))
        for record in pending:
            try:
                n = process_image(record, session)
                total += n
            except Exception:
                logger.exception("Failed to process image id=%s", record.id)
    finally:
        session.close()
    return total
