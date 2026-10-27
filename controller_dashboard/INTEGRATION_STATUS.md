# Controller dashboard integration (work in progress)

Target deployment: /webapp/app, FastAPI, existing memo_activity_dashboard.py cache.

Scope: executive discipline, task status and deadlines, controller reaction, assistants and coexecutors, kanban stage, last successful export timestamp, working calendar, protocol/MEMO sources.

Security: the dashboard must be restricted by server-side Bitrix group ACL. Never trust a browser-supplied user ID. Do not expose the MEMO cache publicly. Until access checks are wired, routes must fail closed.

The uploaded production sources were reviewed separately; production main.py and current dashboards must not be overwritten. The current preview is not production-ready: protocols, history of deadlines, read/unread comments and verified group permissions are not yet integrated.
