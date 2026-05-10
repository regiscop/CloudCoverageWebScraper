# Development

How to set up a local environment, run the test suite, and contribute
changes.

---

## 1. Local setup

```bash
git clone https://github.com/regiscop/CloudCoverageWebScraper.git
cd CloudCoverageWebScraper

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest                              # not in requirements.txt yet

cp .env.example .env
# Set DATABASE_URL to a local Postgres (or use SQLite for unit tests only)
```

The fast path for code-only changes (no DB needed) is to run `pytest` —
nothing in the test suite touches the network or the DB.

---

## 2. Running the tests

```bash
pytest -q
```

The `tests/conftest.py` sets a placeholder `DATABASE_URL` so module imports
that touch `config.py` work even without Postgres.

Coverage today (intentionally narrow):

| Test file | Covers |
|-----------|--------|
| `tests/test_scraper_utils.py` | `build_timestamp`, `floor_to_slot`, `is_daytime`. |
| `tests/test_image_processor.py` | `compute_cloud_index`, `cyclical_time_features`. |
| `tests/test_trainer.py` | `extrapolate_cloud_motion`, `make_targets`, `temporal_split`. |

These are pure-function tests. End-to-end tests require a real DB and live
APIs and are out of scope for the current suite.

---

## 3. Code layout for contributors

```
.
├── config.py                 # all runtime config (env-driven + constants)
├── main.py                   # CLI router
├── scraper/                  # Module 1 — sat24 tile fetcher
├── open_meteo/               # Module 2 — NWP enrichment
├── db/                       # Module 3 — schema, ORM, ingestion helpers
├── features/                 # Module 4 — feature extraction + worker
├── model/                    # Module 5 — XGBoost trainer + Optuna tuner
├── output/                   # Module 6 — FastAPI app
├── scheduler/                # APScheduler glue
├── tests/                    # pytest unit tests (no DB, no network)
└── docs/                     # this folder
```

Add new code in the existing module that owns the responsibility. Resist
the urge to introduce cross-module helpers — `config.py` is the only
shared module by design.

---

## 4. House style

- **Python 3.11+.** `from __future__ import annotations` is not required;
  PEP-604 unions (`X | Y`) are fine.
- **Type hints** on all new public functions.
- **Docstrings** on modules and on any function that has non-obvious
  behaviour. Single-line docstrings are fine for trivial helpers.
- **Logging,** not `print`. Use `logging.getLogger(__name__)`.
- **No `import` inside function bodies** unless it breaks a real circular
  import. The codebase has a few legacy ones — don't add new ones.
- **Do not hard-code paths.** Read from `config.DATA_DIR`, etc.
- **DB access** goes through the helpers in `db/ingestion.py`. If you need
  a new query, add a helper there rather than opening a session at the
  call site.

### Linting / formatting

There is no enforced linter yet (tracked in `STRATEGY_AND_PLANNING.md`,
Phase C). If you run one locally, prefer `ruff format` + `ruff check`. Keep
diffs small — drive-by reformatting makes review hard.

---

## 5. Making a change

The typical loop:

1. Branch off `main` (e.g. `claude/<topic>`).
2. Edit code; add or update a test under `tests/` for any behaviour you
   touched. Pure-function tests are the bar; integration tests are nice
   to have but not required.
3. `pytest -q` locally.
4. `python -m py_compile $(git ls-files '*.py')` to catch syntax errors
   in files that aren't covered by tests.
5. Update `STRATEGY_AND_PLANNING.md` if you crossed off a planned item or
   added a new one.
6. PR against `main`. CI (once it exists, see Phase C) will run `pytest`.

### Touching the DB schema

If you change `db/models.py`, you **must** also update `db/schema.sql` to
match — they are kept in sync by hand. Add a row to a new section in
`STRATEGY_AND_PLANNING.md` if you spot drift. Alembic migrations are
planned (Phase C, item 3) but not yet wired.

### Touching the public API

`output/forecast_api.py` is the only public surface. Treat it as a contract:

- Adding a field is fine (additive).
- Removing or renaming a field needs a major version bump and a migration
  note.
- The Pydantic models (`ForecastPoint`, `ZoneForecast`, `HealthStatus`) are
  the source of truth — update them first, then the route handlers.

---

## 6. Useful one-liners

```bash
# Smoke-test imports without a DB
DATABASE_URL=postgresql://x:x@localhost/x python -c "import main"

# Start the API in autoreload mode
uvicorn output.forecast_api:app --reload

# Run a single CLI command
python main.py scrape-once
python main.py worker
python main.py tune --horizon 6 --trials 25

# Tail the most recent forecast for one zone
psql "$DATABASE_URL" -c "
  SELECT valid_at, cloud_cover_pred, ghi_pred
  FROM solar_forecasts
  WHERE zone_name = 'brussels'
  ORDER BY produced_at DESC, valid_at ASC
  LIMIT 6;"
```
