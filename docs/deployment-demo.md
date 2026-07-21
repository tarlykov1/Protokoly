# Demo server deployment

Use this runbook to deploy the autonomous demo; it does not connect Bitrix24, OAuth, webhooks, or external REST integrations.

## Server requirements
Linux host with Docker Engine and Compose plugin, 2 CPU, 2 GB RAM, 10+ GB disk. Open firewall ports 80/443 only. PostgreSQL is private inside Docker network.

## DNS
Point `demo.example.ru` A/AAAA records to the server before TLS setup.

## Install Docker
Follow the official Docker packages for your Linux distribution and add the administrator to the `docker` group.

## Clone and configure
```bash
git clone <repo-url> protocol-management-system
cd protocol-management-system
cp .env.example .env
openssl rand -hex 32 # paste into SECRET_KEY; change POSTGRES_PASSWORD
```

Important `.env`: `APP_ENV=demo`, `DEMO_MODE=true`, `DATABASE_URL`, PostgreSQL variables, `SECRET_KEY`, `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`, `FORWARDED_ALLOW_IPS`, `MAX_UPLOAD_SIZE_MB`.

## Basic Auth
Recommended for public demos:
```bash
mkdir -p deploy/nginx/auth
htpasswd -Bc deploy/nginx/auth/.htpasswd demo-admin
```
Then enable `auth_basic` lines documented in `deploy/nginx/conf.d/app.conf`. Do not commit `.htpasswd`.

## TLS
Public server: obtain Let's Encrypt certificates externally with certbot/systemd and mount them under `certs/`. Corporate network: place internal CA-issued certificate/key under `certs/`. Do not generate certificates from this repository.

## First deploy
```bash
make demo-deploy
make demo-seed
make demo-smoke
```
Open `${PUBLIC_BASE_URL}/demo/guided` and verify `/health` and `/ready`.

## Update and rollback
Update code explicitly (for example `git fetch && git checkout <tag>`), then:
```bash
make demo-update
```
If smoke fails, restore a backup or roll back code and rerun migrations. The script prints restore guidance.

## Backup and restore
```bash
make demo-backup
scripts/restore.sh backups/<timestamp>
```
Restore requires typing `RESTORE` and overwrites database/uploads.

## Cleanup
Run expired import cleanup from host cron/systemd timer:
```bash
docker compose -f docker-compose.demo.yml --env-file .env run --rm app python -m app.cli.cleanup_imports
```

## Logs and troubleshooting
```bash
make demo-logs
docker compose -f docker-compose.demo.yml --env-file .env ps
docker compose -f docker-compose.demo.yml --env-file .env exec db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```
Check disk (`df -h`), certificate expiry (`openssl x509 -in certs/demo.example.ru/fullchain.pem -noout -dates`), Nginx config, and `.env` host/proxy values.

## Checklist before showing
- `make demo-smoke` passes.
- Basic Auth/TLS are enabled for public access.
- `SECRET_KEY` and database password are unique.
- Recent backup exists.
- `/demo/guided` opens.
