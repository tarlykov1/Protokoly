"""Import workflow package.

The user-facing import flow is deliberately review-first: once at least one
assignment was recognised, imperfect DOCX data must be allowed into the
editor. Critical validation still blocks publication later, where the user can
see and correct the exact fields in context.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from datetime import date

from . import service as _service

_original_confirm_session = _service.confirm_session
_SENTINEL_ASSIGNEE = "__IMPORT_ASSIGNEE_NOT_RECOGNISED__"


def _json_safe_date_or_none(value):
    """Validate an ISO date without putting ``date`` objects into JSON payloads."""
    if not value:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        date.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return text


def _called_from_http_confirm_route() -> bool:
    """Limit the relaxed behavior to the user-facing confirmation endpoint.

    The lower-level service remains strict for callers that intentionally use
    it as a validation gate. The HTTP workflow is review-first because that is
    where users need to reach the editor to correct an imperfect document.
    """
    frame = inspect.currentframe()
    caller = frame.f_back.f_back if frame and frame.f_back else None
    return bool(caller and caller.f_globals.get("__name__") == "app.main")


def _confirm_session_for_review(db, session):
    """Confirm a partially recognised DOCX and defer field fixes to the editor."""
    payload = session.parsed_payload or {}
    if not payload.get("tasks"):
        return _original_confirm_session(db, session)

    errors = list(session.errors_payload or payload.get("errors") or [])
    has_missing_assignee = any(
        not str(task.get("assignee_raw") or "").strip() for task in payload.get("tasks", [])
    )

    # Keep the established strict service contract for direct/internal callers.
    # Only the UI confirmation route relaxes parser diagnostics so the user can
    # actually open the editor and fix them there.
    if (errors or has_missing_assignee) and not _called_from_http_confirm_route():
        return _original_confirm_session(db, session)
    if not errors and not has_missing_assignee:
        return _original_confirm_session(db, session)

    original_payload = deepcopy(payload)
    original_errors = deepcopy(session.errors_payload or [])
    review_payload = deepcopy(payload)
    review_payload["errors"] = []

    review_payload["meeting_date"] = _json_safe_date_or_none(
        review_payload.get("meeting_date")
    )
    review_payload["document_date"] = _json_safe_date_or_none(
        review_payload.get("document_date")
    )

    for task in review_payload.get("tasks", []):
        task["deadline"] = _json_safe_date_or_none(task.get("deadline"))
        if not str(task.get("assignee_raw") or "").strip():
            # The persistence function historically requires a raw assignee.
            # Use a temporary marker and remove the resulting placeholder row
            # immediately after creation so the editor correctly shows
            # "Без исполнителя" instead of inventing a person.
            task["assignee_raw"] = _SENTINEL_ASSIGNEE
            task["assignee_resolution"] = []

    session.parsed_payload = review_payload
    session.errors_payload = []

    try:
        protocol = _original_confirm_session(db, session)
        for task in protocol.tasks:
            for assignment in list(task.assignments):
                if assignment.individual_title == _SENTINEL_ASSIGNEE:
                    db.delete(assignment)

        # Keep the original diagnostics for audit/history. They are no longer
        # a gate for opening the editor; protocol validation remains the gate
        # for review/approval/publication.
        session.parsed_payload = original_payload
        session.errors_payload = original_errors
        db.commit()
        db.refresh(protocol)
        return protocol
    except Exception:
        db.rollback()
        session.parsed_payload = original_payload
        session.errors_payload = original_errors
        raise


# ``app.main`` imports confirm_session from ``app.services.imports.service``.
# Importing this package happens first, so replace only that callable while
# leaving the rest of the established service API untouched.
_service.confirm_session = _confirm_session_for_review

__all__ = []
