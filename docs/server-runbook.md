# Server runbook

Owner/contact placeholder: `demo-owner@example.ru`.

- Status: `docker compose -f docker-compose.demo.yml --env-file .env ps` and `make demo-smoke`.
- Restart: `docker compose -f docker-compose.demo.yml --env-file .env restart app nginx`.
- Logs: `make demo-logs`.
- Backup: `make demo-backup`.
- Restore: `scripts/restore.sh backups/<timestamp>` and confirm with `RESTORE`.
- Disk: `df -h`, `docker system df`, and inspect `backups/` retention.
- Certificate: `openssl x509 -in certs/demo.example.ru/fullchain.pem -noout -dates`.
- Disable demo: stop services with `make demo-down` or restrict firewall/Nginx access.
- Health endpoints: `/health` checks the app process; `/ready` checks DB and migrations.
