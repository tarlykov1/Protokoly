#!/usr/bin/env bash
set -euo pipefail

ruff check .
pytest -q
alembic upgrade head
alembic current
alembic heads
python -c "import app.main; print('import ok')"
