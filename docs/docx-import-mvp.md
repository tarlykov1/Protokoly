# DOCX Import MVP

The DOCX import is intentionally two-stage: preview first, database creation only after explicit confirmation.

## Endpoints

- `GET /protocols/import` — upload form.
- `POST /protocols/import/preview` — validate and store DOCX, parse it, create an `ImportSession`.
- `GET /protocols/import/{session_id}/preview` — review parsed metadata, sections, tasks, assignees, deadlines, warnings, and duplicate hints.
- `POST /protocols/import/{session_id}/update` — persist manual corrections in JSON payload.
- `POST /protocols/import/{session_id}/reparse` — rerun selected parser after explicit confirmation; previous payload is kept in `parse_history`.
- `POST /protocols/import/{session_id}/confirm` — create protocol, sections, tasks, and assignments.
- `POST /protocols/import/{session_id}/cancel` — cancel without creating protocol rows.
- `GET /protocols/imports` — import journal.

## File safety

Only `.docx` files are accepted. The service checks MIME type, ZIP signature, DOCX internals, and maximum size. Stored filenames are generated UUID values; original filenames are never used as paths. Files are stored under `var/imports`, outside static assets. SHA-256 checksums are saved for duplicate detection.

## Parser selection

Users may select a parser manually. Without manual selection, `ParserRegistry` evaluates parser confidence and falls back to the universal parser when confidence is low. Parser choices include confidence, reasons, and low-confidence warnings.

## Supported structures

The parser walks paragraphs and tables in document order. It recognizes Word headings, uppercase section rows, numbered tasks (`1.`, `1.1.`, `01/02`), table tasks, assignee columns, and deadline columns.

## Deadlines

Absolute dates are converted to ISO date strings. Relative or periodic expressions such as `до конца недели`, `до конца месяца`, `еженедельно`, and `постоянно` keep `raw_deadline`, `deadline_type`, `deadline_value`, and warning data. The parser does not invent dates for ambiguous relative deadlines.

## Employees and classifiers

Assignees are resolved against existing employees, aliases, and employee lists. Results use `found`, `multiple_matches`, `not_found`, and `not_in_bitrix`. The MVP never creates employees automatically.

Directions and blocks are matched exactly or by normalized code/name. A block is accepted only for the resolved direction.

## Cleanup

Expired unconfirmed sessions are cleaned by `cleanup_expired_import_sessions()` or `python -m app.cli.cleanup_imports`. Confirmed source files are preserved.
