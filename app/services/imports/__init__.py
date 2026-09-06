"""Import workflow package.

The user-facing import flow is deliberately review-first: once at least one
assignment was recognised, imperfect DOCX data must be allowed into the
editor. Critical validation still blocks publication later, where the user can
see and correct the exact fields in context.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from . import service as _service

_original_confirm_session = _service.confirm_session
_SENTINEL_ASSIGNEE = "__IMPORT_ASSIGNEE_NOT_RECOGNISED__"


def _valid_date_or_none(value):
    if not value or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _confirm_session_for_review(db, session):
    """Confirm a partially recognised DOCX and defer field fixes to the editor.

    The legacy confirmation routine used parser diagnostics as a hard gate.
    That made the preview useful but then prevented the user from reaching the
    editor to fix exactly those diagnostics. Here we keep the original routine
    for persistence, but feed it a safe review copy of the payload. The real
    parser diagnostics remain stored on the import session.
    """
    payload = session.parsed_payload or {}
    if not payload.get("tasks"):
        return _original_confirm_session(db, session)

    original_payload = deepcopy(payload)
    original_errors = deepcopy(session.errors_payload or [])
    review_payload = deepcopy(payload)
    review_payload["errors"] = []

    review_payload["meeting_date"] = _valid_date_or_none(review_payload.get("meeting_date"))
    review_payload["document_date"] = _valid_date_or_none(review_payload.get("document_date"))

    for task in review_payload.get("tasks", []):
        task["deadline"] = _valid_date_or_none(task.get("deadline"))
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
