# TODO

Lightweight backlog distilled from [`STRATEGY_AND_PLANNING.md`](STRATEGY_AND_PLANNING.md).

Use this file for day-to-day "what's next" tracking. Promote items to
`STRATEGY_AND_PLANNING.md` when they need design discussion or coordination
across modules.

_Last updated: 2026-05-11._

---

## Now — Quality of life (Phase C)

Tractable, low-risk improvements that unblock the rest of the roadmap.

- [ ] Add a GitHub Actions workflow that runs `pytest` and `ruff check` on
      every push and PR. Cache `pip` between runs.
- [ ] Replace `print(metrics.to_string(...))` in `cmd_train` (`main.py:96`)
      with structured logging.
- [ ] Wire up `alembic` migrations. The dependency is already declared but
      unused; `db/models.py` and `db/schema.sql` are kept in sync by hand.
- [ ] Add log rotation to the `logging.basicConfig` setup in `main.py`
      (default scheduler runs forever — current logs grow unbounded).
- [ ] Run `mypy --strict` over the codebase and fix the `None`-union warnings
      currently silently ignored.

## Next — Observability and reliability

- [ ] Emit Prometheus metrics from the scheduler and surface them on
      `/health`: `scrape_age_seconds`, `weather_age_seconds`,
      `forecast_runs_total`, last-error counters per job.
- [ ] Replace pickle model serialisation with `xgboost.Booster.save_model`
      (JSON). Pickle is not safe across xgboost upgrades and currently locks
      us to a single library version.
- [ ] Add an `mlflow` (or simple JSON registry) entry per trained model so
      metrics, hyperparameters, and model versions are tracked over time.
- [ ] Document the disaster-recovery procedure (rebuild DB from `DATA_DIR`)
      in `docs/OPERATIONS.md`.

## Later — Modelling (Phase D / README §9 P7)

Blocked on collecting ≥ 90 days of real satellite + NWP data.

- [ ] Implement a ConvLSTM / hybrid NWP model and compare against the
      current XGBoost baseline on walk-forward CV.
- [ ] Add residual-correction over the NWP baseline so the model only
      learns the delta. Smaller target distribution → faster convergence
      and lower variance.
- [ ] Switch to quantile regression (xgboost's `quantile` objective) to emit
      P10 / P50 / P90 intervals. Retire the ad-hoc
      `confidence = max(0.3, 1.0 - h / 48.0)` heuristic in
      `output/forecast_api.py`.

## Calibration (manual, blocked on tile inspection)

- [ ] Calibrate `TILES` in `config.py` against real sat24 tiles for the
      target geographic area. Current values are educated guesses at
      zoom 5 over BE/NL/FR-nord.
- [ ] Calibrate `ZONE_PIXEL_BBOXES` so each zone in `GRID_POINTS` maps to
      the correct pixel sub-rectangle inside the assembled tile mosaic.

---

## Done

Items shipped on this branch family. Keep this list short — collapse into
release notes when it gets long.

- [x] **Phase A — Restore the data pipeline.** Persisted tile metadata,
      fixed `/forecast/{zone}/{horizon}` horizon selection, scoped
      `load_latest_forecasts` to a single run, added the
      `(captured_at, channel, zoom_level, tile_x1, tile_y1)` unique index,
      reused sessions in the feature worker, bulk-inserted weather rows,
      cleaned up unused `schedule` dep and hard-coded Postgres password.
- [x] **Phase B — Test coverage.** Added `pytest` config and pure-function
      unit tests under `tests/` (`test_scraper_utils.py`,
      `test_image_processor.py`, `test_trainer.py`).
- [x] **Local-first execution.** Default `DATABASE_URL` now points at
      SQLite; Postgres/TimescaleDB and Docker remain optional.
- [x] Bilingual (FR/EN) HTML usage guide (`README.html`) and project
      summary (`PROJECT_SUMMARY.html`).
- [x] `docs/` folder with ARCHITECTURE, CONFIGURATION, OPERATIONS, API,
      DEVELOPMENT guides.
