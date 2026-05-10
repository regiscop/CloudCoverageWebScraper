"""Tests for pure helpers in scraper.sat24_scraper."""

from datetime import datetime, timezone

from scraper.sat24_scraper import build_timestamp, floor_to_slot, is_daytime


def test_floor_to_slot_floors_minutes_to_15_min_grid():
    dt = datetime(2026, 5, 9, 14, 37, 42, tzinfo=timezone.utc)
    floored = floor_to_slot(dt)
    assert floored == datetime(2026, 5, 9, 14, 30, 0, tzinfo=timezone.utc)


def test_floor_to_slot_idempotent_on_aligned_input():
    dt = datetime(2026, 5, 9, 14, 30, 0, tzinfo=timezone.utc)
    assert floor_to_slot(dt) == dt


def test_build_timestamp_format():
    dt = datetime(2026, 5, 9, 14, 37, 42, tzinfo=timezone.utc)
    assert build_timestamp(dt) == "202605091430"


def test_build_timestamp_floors_to_lower_quarter():
    dt = datetime(2026, 1, 1, 0, 14, 59, tzinfo=timezone.utc)
    assert build_timestamp(dt) == "202601010000"


def test_is_daytime_summer_noon_in_belgium():
    summer_noon = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert is_daytime(summer_noon) is True


def test_is_daytime_winter_midnight_in_belgium():
    winter_midnight = datetime(2026, 12, 21, 0, 0, 0, tzinfo=timezone.utc)
    assert is_daytime(winter_midnight) is False
