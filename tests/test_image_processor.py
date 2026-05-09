"""Tests for pure functions in features.image_processor."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from features.image_processor import (
    compute_cloud_index,
    cyclical_time_features,
)


def _write_uniform_grayscale(path: Path, value: int, size: int = 32) -> None:
    arr = np.full((size, size), value, dtype=np.uint8)
    Image.fromarray(arr, mode="L").save(path)


def test_cloud_index_uniform_white(tmp_path):
    img = tmp_path / "white.jpg"
    _write_uniform_grayscale(img, 255)
    idx = compute_cloud_index(img, (0, 0, 32, 32))
    assert idx["mean"] > 0.95  # JPEG is lossy, expect close to 1.0
    assert idx["std"] < 0.05


def test_cloud_index_uniform_black(tmp_path):
    img = tmp_path / "black.jpg"
    _write_uniform_grayscale(img, 0)
    idx = compute_cloud_index(img, (0, 0, 32, 32))
    assert idx["mean"] < 0.05
    assert idx["std"] < 0.05


def test_cloud_index_empty_bbox_returns_nan(tmp_path):
    img = tmp_path / "white.jpg"
    _write_uniform_grayscale(img, 255)
    idx = compute_cloud_index(img, (10, 10, 10, 10))
    assert np.isnan(idx["mean"])


def test_cyclical_time_features_unit_circle():
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    feats = cyclical_time_features(dt)
    assert abs(feats["hour_sin"] ** 2 + feats["hour_cos"] ** 2 - 1.0) < 1e-9
    assert abs(feats["month_sin"] ** 2 + feats["month_cos"] ** 2 - 1.0) < 1e-9


def test_cyclical_time_features_midnight_january():
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    feats = cyclical_time_features(dt)
    assert abs(feats["hour_sin"]) < 1e-9
    assert abs(feats["hour_cos"] - 1.0) < 1e-9
