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

demo:
	alembic upgrade head
	python -m app.cli.seed_demo
	python -m app.cli.generate_demo_docx
	@echo "Demo URL: http://localhost:8000"

demo-deploy:
	./scripts/deploy.sh

demo-update:
	./scripts/update.sh

demo-seed:
	./scripts/seed-demo.sh

demo-backup:
	./scripts/backup.sh

demo-smoke:
	./scripts/smoke-test.sh

demo-logs:
	docker compose -f docker-compose.demo.yml --env-file .env logs -f app nginx

demo-down:
	docker compose -f docker-compose.demo.yml --env-file .env down
