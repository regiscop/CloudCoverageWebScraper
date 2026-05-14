# CLAUDE.md

Project context for AI coding agents working in this repository.

This file is consulted automatically by Claude Code at the start of a session.
Keep it short and current — if a section is no longer accurate, fix it in the
same PR that changes the underlying behaviour.

---

## 1. What this project is

**Solar Cloud Coverage Forecaster.** A local-first pipeline that predicts solar
production for the next 24–48 hours over Belgium and neighbouring countries by
fusing sat24.com satellite tiles with Open-Meteo NWP data.

- Geographic scope: Belgium · Netherlands · Northern France · Luxembourg · Western Germany.
- Forecast horizons: H+1, H+3, H+6, H+12, H+24, H+48.
- Default execution: SQLite + APScheduler on a single workstation. Postgres /
  TimescaleDB + Docker are optional advanced modes.

For a deeper tour read, in this order:

1. [`README.md`](README.md) — quick start and CLI reference.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — data flow, module map, storage.
3. [`STRATEGY_AND_PLANNING.md`](STRATEGY_AND_PLANNING.md) — historical audit and roadmap.
4. [`TODO.md`](TODO.md) — current backlog.

---

## 2. Repository layout

```
config.py                  # single source of runtime config (env + constants)
main.py                    # CLI entry point — one subcommand per action
scraper/sat24_scraper.py   # Module 1 — sat24 tile fetcher
open_meteo/fetcher.py      # Module 2 — NWP fetcher (forecast + backfill)
db/                        # Module 3 — schema.sql, SQLAlchemy models, ingestion helpers
features/                  # Module 4 — image_processor primitives + pipeline_worker
model/trainer.py           # Module 5 — XGBoost trainer + Optuna tuner
output/forecast_api.py     # Module 6 — FastAPI app
scheduler/pipeline.py      # APScheduler glue
tests/                     # pytest unit tests — no DB, no network
docs/                      # ARCHITECTURE / CONFIGURATION / OPERATIONS / API / DEVELOPMENT
```

Add new code in the module that owns the responsibility. `config.py` is the
only shared module by design — resist cross-module helpers.

---

## 3. House rules for agents

- **Python 3.11+.** PEP-604 unions (`X | Y`) are fine.
- **Type hints** on new public functions.
- **`logging.getLogger(__name__)`**, never `print`.
- **All timestamps are UTC** end-to-end. Floor to 15-min slots via
  `scraper.sat24_scraper.floor_to_slot` so re-runs and the unique index
  agree on the same key.
- **DB access** goes through helpers in `db/ingestion.py`. Don't open sessions
  at call sites — add a helper instead.
- **Don't hard-code paths.** Read `config.DATA_DIR`, `config.MODEL_DIR`, etc.
- **No `import` inside function bodies** unless it breaks a real circular
  import. A few legacy ones exist in `main.py` — don't add new ones.
- **`db/models.py` and `db/schema.sql` are kept in sync by hand.** If you
  touch one, update the other in the same commit. Alembic is on the roadmap
  but not wired yet.
- **Public REST contract** lives in `output/forecast_api.py`. Adding a field
  is fine; renaming or removing one needs a major version bump.

---

## 4. Verifying changes

```bash
pytest -q                                    # unit tests — no DB, no network
python -m py_compile $(git ls-files '*.py')  # catch syntax errors in untested files
```

`tests/conftest.py` sets a placeholder `DATABASE_URL` so imports work without
a real database. End-to-end testing requires a live DB and live APIs and is
currently manual.

If you touch UI / API behaviour, exercise it locally:

```bash
python main.py init-db
python main.py serve            # http://127.0.0.1:8000/docs
```

---

## 5. Git & branch conventions

- Branch off `main` with a topic prefix (`claude/<topic>`).
- Keep diffs small; no drive-by reformatting.
- After crossing off a backlog item, update [`TODO.md`](TODO.md) and the
  corresponding entry in [`STRATEGY_AND_PLANNING.md`](STRATEGY_AND_PLANNING.md)
  in the same PR.
- PRs target `main`. CI is on the roadmap (Phase C) but not yet wired.

---

## 6. Things to know that aren't obvious from the code

- The sat24 tile API is undocumented (Infoplaza). The rate limit
  (`SAT24_MIN_REQUEST_INTERVAL_S`, default 5 s) is a courtesy, not a published
  limit. Don't lower it.
- VIS imagery is unusable at night — the scraper skips VIS tiles outside
  daylight via `pvlib`, and the model falls back to IR + NWP for nocturnal
  horizons.
- Tile geo-referencing uses SlippyMap/TMS conventions. `TILES` in
  `config.py` and `ZONE_PIXEL_BBOXES` in `features/pipeline_worker.py`
  are placeholders — they need manual inspection against real tiles to
  calibrate for production.
- Files on disk under `DATA_DIR` are the source of truth. The DB can be
  rebuilt from disk via a re-ingestion pass; the unique index on
  `(captured_at, channel, zoom_level, tile_x1, tile_y1)` makes it idempotent.
- `docker-compose.yml` reads the Postgres password from `$POSTGRES_PASSWORD`
  — set it in `.env` before `docker compose up`.

---

## 7. When in doubt

- Architectural questions → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
- "How do I run X?" → [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
- Config / env vars → [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
- REST contract → [`docs/API.md`](docs/API.md).
- Development workflow → [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
- Backlog and priorities → [`TODO.md`](TODO.md) and
  [`STRATEGY_AND_PLANNING.md`](STRATEGY_AND_PLANNING.md).
