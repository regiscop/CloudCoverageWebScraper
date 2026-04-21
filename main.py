"""
Solar Cloud Coverage Forecaster — CLI entry point.

Usage:
  python main.py scrape           # run scraper loop (blocking)
  python main.py scrape-once      # single scrape round
  python main.py fetch-weather    # fetch Open-Meteo forecasts now
  python main.py backfill         # backfill last 90 days of NWP data
  python main.py train            # train XGBoost models
  python main.py tune             # Optuna hyperparameter search (Improvement C)
  python main.py worker           # process pending images into features (Improvement B)
  python main.py scheduler        # run full APScheduler pipeline (Improvement A)
  python main.py serve            # start the FastAPI server
  python main.py init-db          # create DB tables (non-TimescaleDB envs)
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _load_training_data() -> "pd.DataFrame":
    from datetime import datetime, timedelta, timezone
    from db.ingestion import load_cloud_features, load_weather_data
    from config import GRID_POINTS
    import pandas as pd

    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=90)

    logger.info("Loading training data from DB…")
    frames = []
    for point in GRID_POINTS:
        cf = load_cloud_features(point["name"], start, now)
        wd = load_weather_data(point["name"], start, now)
        if cf.empty:
            logger.warning("No cloud features for %s — skipping", point["name"])
            continue
        merged = pd.merge_asof(
            cf.sort_values("captured_at"),
            wd[["captured_at", "cloud_cover", "shortwave_radiation"]].sort_values("captured_at"),
            on="captured_at",
            direction="nearest",
            tolerance=pd.Timedelta("1h"),
        )
        merged["zone_name"] = point["name"]
        frames.append(merged)

    if not frames:
        logger.error("No training data. Run 'backfill' and collect sat images first.")
        sys.exit(1)

    import pandas as pd
    return pd.concat(frames, ignore_index=True)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_scrape(args):
    from scraper.sat24_scraper import scrape_loop
    scrape_loop()


def cmd_scrape_once(args):
    from scraper.sat24_scraper import scrape_once
    paths = scrape_once()
    logger.info("Scraped %d tiles", len(paths))


def cmd_fetch_weather(args):
    from open_meteo.fetcher import fetch_all_forecasts
    from db.ingestion import ingest_weather_dataframe
    df = fetch_all_forecasts()
    n = ingest_weather_dataframe(df)
    logger.info("Inserted %d weather rows", n)


def cmd_backfill(args):
    from open_meteo.fetcher import backfill_90_days
    from db.ingestion import ingest_weather_dataframe
    df = backfill_90_days()
    n = ingest_weather_dataframe(df)
    logger.info("Backfill complete — %d rows inserted", n)


def cmd_train(args):
    from model.trainer import run_training_pipeline
    df = _load_training_data()
    logger.info("Training on %d rows", len(df))
    metrics = run_training_pipeline(df)
    print(metrics.to_string(index=False))


def cmd_tune(args):
    """Improvement C — Optuna walk-forward hyperparameter search."""
    from model.trainer import run_optuna_tuning
    df = _load_training_data()
    logger.info("Starting Optuna tuning on %d rows (horizon=H+%d, trials=%d)…",
                len(df), args.horizon, args.trials)
    best = run_optuna_tuning(df, horizon=args.horizon, n_trials=args.trials)
    print("Best params:", best)


def cmd_worker(args):
    """Improvement B — Process pending satellite images into cloud features."""
    from features.pipeline_worker import process_pending_images
    n = process_pending_images()
    logger.info("Worker done — %d feature rows inserted", n)


def cmd_scheduler(args):
    """Improvement A — Start the integrated APScheduler pipeline."""
    from scheduler.pipeline import start_scheduler
    start_scheduler()


def cmd_serve(args):
    import uvicorn
    from config import API_HOST, API_PORT
    uvicorn.run("output.forecast_api:app", host=API_HOST, port=API_PORT, reload=False)


def cmd_init_db(args):
    from db.models import create_tables
    create_tables()
    logger.info("Tables created (SQLAlchemy — no TimescaleDB hypertables).")
    logger.info("For TimescaleDB, run: psql -f db/schema.sql")


# ── Argument parser ───────────────────────────────────────────────────────────

COMMANDS = {
    "scrape":        cmd_scrape,
    "scrape-once":   cmd_scrape_once,
    "fetch-weather": cmd_fetch_weather,
    "backfill":      cmd_backfill,
    "train":         cmd_train,
    "tune":          cmd_tune,
    "worker":        cmd_worker,
    "scheduler":     cmd_scheduler,
    "serve":         cmd_serve,
    "init-db":       cmd_init_db,
}


def main():
    parser = argparse.ArgumentParser(
        description="Solar Cloud Coverage Forecaster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  {k}" for k in COMMANDS),
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    for name in COMMANDS:
        sp = sub.add_parser(name)
        if name == "tune":
            sp.add_argument("--horizon", type=int, default=1,
                            help="Forecast horizon in hours to optimise (default: 1)")
            sp.add_argument("--trials", type=int, default=50,
                            help="Number of Optuna trials (default: 50)")

    args = parser.parse_args()
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
