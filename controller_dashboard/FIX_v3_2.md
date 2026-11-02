# UI and access patch v3.2 — 27.10.2026

The deployed v3.1 `index.php` called only `prolog_before.php` and directly emitted a complete HTML document, so users saw the dashboard without the Bitrix24 shell. The old guard allowed only group 671 roles A/E/K and rejected Bitrix24 admins who were not members.

**Patch bundle**: `controller_dashboard_patch_v3_2.zip` (delivered separately, not yet committed as full source). Contains:
- `index.php`: full `/bitrix/header.php` and `/bitrix/footer.php`, with a same-origin iframe of `view.php`.
- `view.php`: authenticates and checks permission before serving `dashboard.html`.
- `guard.php`: allows `$USER->IsAdmin()` or workgroup member role A/E/K in 671. Separate controller ACL still required for multiple groups.
- `dashboard.html`: makes API error details visible within the viewport.

**Do not change** `api.php`, `config.php`, Python, or existing dashboards. Save backups before replacing the four PHP-side files.

This patch addresses Bitrix shell and admin access. Empty data is **not yet proven resolved**: fetch `/controller-dashboard/api.php?path=items` in an authorized Bitrix browser and report only HTTP status and `detail`, never the full task list. Reconcile PHP backend route and secret configuration if API returns 403/502/503.

Security: browser-facing API must retain its server-side workgroup ACL. Backend must demand shared secret, never trust unsigned X-Bitrix-User headers.
