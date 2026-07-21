.PHONY: install lint test migrate run check

install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

lint:
	ruff check .

test:
	pytest -q

migrate:
	alembic upgrade head
	alembic current
	alembic heads

run:
	uvicorn app.main:app --reload

check:
	./scripts/check.sh
