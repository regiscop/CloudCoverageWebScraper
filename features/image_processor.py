"""
Module 4 — Feature extraction from satellite tile images.

Provides:
  - Cloud index (mean / std / p90) per zone bounding box
  - Optical flow vector (u, v) between two consecutive frames
  - Solar positional features via pvlib (elevation, GHI clear-sky)
  - Cyclical time encodings (hour, month)
  - Final per-zone feature vector assembly
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pvlib
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cloud index
# ---------------------------------------------------------------------------

def compute_cloud_index(img_path: str | Path, zone_bbox_pixels: tuple) -> dict:
    """
    Normalise pixel intensity to a cloud index in [0, 1].

    VIS  : brighter pixel → more cloud.
    IR   : invert temperature of brightness (cold high cloud → bright in IR).

    zone_bbox_pixels : (x_min, y_min, x_max, y_max) in pixel coordinates.
    """
    img = np.array(Image.open(img_path).convert("L"), dtype=np.float32)
    x0, y0, x1, y1 = zone_bbox_pixels
    roi = img[y0:y1, x0:x1]

    if roi.size == 0:
        logger.warning("Empty ROI for bbox %s in %s", zone_bbox_pixels, img_path)
        return {"mean": float("nan"), "std": float("nan"), "p90": float("nan")}

    return {
        "mean": float(roi.mean() / 255.0),
        "std":  float(roi.std()  / 255.0),
        "p90":  float(np.percentile(roi, 90) / 255.0),
    }


# ---------------------------------------------------------------------------
# Optical flow
# ---------------------------------------------------------------------------

def load_grayscale(img_path: str | Path) -> np.ndarray:
    img = np.array(Image.open(img_path).convert("L"), dtype=np.uint8)
    return img


def compute_optical_flow(
    img_t0: np.ndarray,
    img_t1: np.ndarray,
    zone_bbox_pixels: tuple | None = None,
) -> tuple[float, float]:
    """
    Farneback dense optical flow between two consecutive grayscale frames.

    Returns (u, v) mean displacement vector in pixels/frame over the ROI.
    If zone_bbox_pixels is None, averages over the full image.
    """
    flow = cv2.calcOpticalFlowFarneback(
        img_t0, img_t1,
        None, 0.5, 3, 15, 3, 5, 1.2, 0,
    )
    if zone_bbox_pixels is not None:
        x0, y0, x1, y1 = zone_bbox_pixels
        flow = flow[y0:y1, x0:x1]

    u = float(flow[..., 0].mean())
    v = float(flow[..., 1].mean())
    return u, v


# ---------------------------------------------------------------------------
# Solar / astronomical features (pvlib)
# ---------------------------------------------------------------------------

def solar_position_features(lat: float, lon: float, dt: datetime) -> dict:
    """Return solar elevation angle and GHI clear-sky estimate."""
    location = pvlib.location.Location(latitude=lat, longitude=lon, tz="UTC")
    times = pd.DatetimeIndex([dt])
    solar_pos = location.get_solarposition(times)
    clearsky   = location.get_clearsky(times)  # Ineichen model

    return {
        "solar_elevation": float(solar_pos["elevation"].iloc[0]),
        "ghi_clearsky":    float(clearsky["ghi"].iloc[0]),
    }


# ---------------------------------------------------------------------------
# Cyclical time encodings
# ---------------------------------------------------------------------------

def cyclical_time_features(dt: datetime) -> dict:
    hour  = dt.hour + dt.minute / 60.0
    month = dt.month
    return {
        "hour_sin":  float(np.sin(2 * np.pi * hour  / 24)),
        "hour_cos":  float(np.cos(2 * np.pi * hour  / 24)),
        "month_sin": float(np.sin(2 * np.pi * month / 12)),
        "month_cos": float(np.cos(2 * np.pi * month / 12)),
    }


# ---------------------------------------------------------------------------
# Full feature vector assembly
# ---------------------------------------------------------------------------

def build_feature_vector(
    vis_path: str | Path,
    ir_path: str | Path | None,
    prev_vis_path: str | Path | None,
    zone_bbox_pixels: tuple,
    lat: float,
    lon: float,
    dt: datetime,
    nwp_cloud_cover: float | None = None,
) -> dict:
    """
    Assemble the complete per-zone, per-timestamp feature vector described
    in §6.2 of the specifications.
    """
    vis_idx = compute_cloud_index(vis_path, zone_bbox_pixels)

    ir_idx: dict = {"mean": float("nan"), "std": float("nan"), "p90": float("nan")}
    if ir_path is not None:
        ir_idx = compute_cloud_index(ir_path, zone_bbox_pixels)

    motion_u, motion_v = float("nan"), float("nan")
    if prev_vis_path is not None:
        frame_t0 = load_grayscale(prev_vis_path)
        frame_t1 = load_grayscale(vis_path)
        # Resize to same shape if tiles differ slightly
        if frame_t0.shape != frame_t1.shape:
            frame_t1 = cv2.resize(frame_t1, (frame_t0.shape[1], frame_t0.shape[0]))
        motion_u, motion_v = compute_optical_flow(frame_t0, frame_t1, zone_bbox_pixels)

    solar = solar_position_features(lat, lon, dt)
    time_enc = cyclical_time_features(dt)

    return {
        "captured_at":       dt.isoformat(),
        "cloud_index_vis":   vis_idx["mean"],
        "cloud_std_vis":     vis_idx["std"],
        "cloud_p90_vis":     vis_idx["p90"],
        "cloud_index_ir":    ir_idx["mean"],
        "cloud_std_ir":      ir_idx["std"],
        "motion_u":          motion_u,
        "motion_v":          motion_v,
        "cloud_cover_nwp":   nwp_cloud_cover,
        "ghi_clearsky":      solar["ghi_clearsky"],
        "solar_elevation":   solar["solar_elevation"],
        **time_enc,
    }
