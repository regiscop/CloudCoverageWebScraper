"""
Improvement A — Integrated APScheduler pipeline.

Coordinates all recurring jobs:
  - Sat24 tile scrape        every 15 min
  - Open-Meteo weather fetch every 1 h
  - Feature engineering      every 15 min (after scrape)
  - Forecast trigger         every 1 h

Run via: python main.py scheduler
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import SCRAPE_INTERVAL_MINUTES

logger = logging.getLogger(__name__)


def job_scrape() -> None:
    logger.info("[scheduler] scrape job started")
    try:
        from scraper.sat24_scraper import scrape_once
        paths = scrape_once()
        logger.info("[scheduler] scrape done — %d tiles", len(paths))
    except Exception:
        logger.exception("[scheduler] scrape job failed")


def job_fetch_weather() -> None:
    logger.info("[scheduler] weather fetch started")
    try:
        from open_meteo.fetcher import fetch_all_forecasts
        from db.ingestion import ingest_weather_dataframe
        df = fetch_all_forecasts()
        n = ingest_weather_dataframe(df)
        logger.info("[scheduler] weather fetch done — %d rows", n)
    except Exception:
        logger.exception("[scheduler] weather fetch failed")


def job_feature_worker() -> None:
    logger.info("[scheduler] feature worker started")
    try:
        from features.pipeline_worker import process_pending_images
        n = process_pending_images()
        logger.info("[scheduler] feature worker done — %d images processed", n)
    except Exception:
        logger.exception("[scheduler] feature worker failed")


def job_trigger_forecast() -> None:
    logger.info("[scheduler] forecast trigger started")
    try:
        from model.trainer import load_models
        load_models()  # confirm model exists before importing API internals
        from output.forecast_api import trigger_forecast
        result = trigger_forecast()
        logger.info(
            "[scheduler] forecast trigger done — zones: %s",
            result.zones_updated,
        )
    except FileNotFoundError:
        logger.warning("[scheduler] no trained model found — skipping forecast trigger")
    except Exception:
        logger.exception("[scheduler] forecast trigger failed")


def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    # Scrape every N minutes, starting at next aligned slot
    scheduler.add_job(
        job_scrape,
        IntervalTrigger(minutes=SCRAPE_INTERVAL_MINUTES),
        id="scrape",
        name="Sat24 tile scrape",
        max_instances=1,
        coalesce=True,
    )

    # Feature engineering runs 2 min after each scrape slot
    scheduler.add_job(
        job_feature_worker,
        IntervalTrigger(minutes=SCRAPE_INTERVAL_MINUTES),
        id="feature_worker",
        name="Feature pipeline worker",
        max_instances=1,
        coalesce=True,
    )

    # Weather fetch at the top of every hour
    scheduler.add_job(
        job_fetch_weather,
        CronTrigger(minute=0),
        id="fetch_weather",
        name="Open-Meteo weather fetch",
        max_instances=1,
        coalesce=True,
    )

    # Forecast trigger at 5 past every hour (after weather lands)
    scheduler.add_job(
        job_trigger_forecast,
        CronTrigger(minute=5),
        id="trigger_forecast",
        name="Forecast trigger",
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        "Scheduler started — scrape every %d min, weather + forecast every hour",
        SCRAPE_INTERVAL_MINUTES,
    )
    scheduler.start()
