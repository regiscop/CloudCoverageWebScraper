"""Shared pytest fixtures.

Sets a placeholder DATABASE_URL so importing modules that read config does not
fail in CI environments where Postgres is not available. Tests that touch the
DB are out of scope for this suite — only pure-function tests live here.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://test:test@localhost:5432/test",
)

# Make the project root importable when running `pytest` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
