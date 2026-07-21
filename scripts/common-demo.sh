#!/usr/bin/env bash
set -euo pipefail
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.demo.yml}
require_env(){ [[ -f .env ]] || { echo "Missing .env; copy .env.example and edit secrets" >&2; exit 1; }; set -a; source .env; set +a; }
compose(){ docker compose -f "$COMPOSE_FILE" --env-file .env "$@"; }
