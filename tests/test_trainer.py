"""Tests for pure functions in model.trainer."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from model.trainer import (
    extrapolate_cloud_motion,
    make_targets,
    temporal_split,
)


def test_extrapolate_clamped_to_unit_interval():
    pred = extrapolate_cloud_motion(
        cloud_index=0.95, motion_u=10.0, motion_v=10.0, horizon_h=1
    )
    assert 0.0 <= pred <= 1.0


def test_extrapolate_zero_motion_is_persistence():
    pred = extrapolate_cloud_motion(
        cloud_index=0.42, motion_u=0.0, motion_v=0.0, horizon_h=3
    )
    assert pred == 0.42


def test_extrapolate_long_horizon_dampens_to_persistence():
    """At horizon >= 6h dampening factor is 0 → motion contribution disappears."""
    pred = extrapolate_cloud_motion(
        cloud_index=0.5, motion_u=10.0, motion_v=10.0, horizon_h=6
    )
    assert pred == 0.5


def _synthetic_hourly_df(n_hours: int = 240) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [start + timedelta(hours=i) for i in range(n_hours)]
    return pd.DataFrame({
        "captured_at":     times,
        "cloud_index_vis": [(i % 10) / 10.0 for i in range(n_hours)],
    })


def test_make_targets_creates_lead_columns_and_drops_tail():
    df = _synthetic_hourly_df(n_hours=100)
    out = make_targets(df, horizons=[1, 3, 6])
    assert "target_h01" in out.columns
    assert "target_h03" in out.columns
    assert "target_h06" in out.columns
    # The last `max(horizon)` rows must be dropped because they have no target.
    assert len(out) == 100 - 6


def test_temporal_split_is_chronological():
    df = _synthetic_hourly_df(n_hours=24 * 30)
    train, val, test = temporal_split(df, val_days=8, test_days=7)
    assert train["captured_at"].max() < val["captured_at"].min()
    assert val["captured_at"].max() < test["captured_at"].min()
