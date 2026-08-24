from datetime import date

COMPLETED_STATUSES = {"completed", "done", "closed"}
DEFERRED_STATUSES = {"deferred", "postponed", "cancelled", "canceled"}


def is_completed(status: str) -> bool:
    return status.lower() in COMPLETED_STATUSES


def is_overdue(
    deadline: date | None, closed_at: date | None, status: str, today: date | None = None
) -> bool:
    if not deadline:
        return False
    reference = closed_at if is_completed(status) and closed_at else (today or date.today())
    return reference > deadline


def completed_in_period(closed_at: date | None, start: date, end: date) -> bool:
    return closed_at is not None and start <= closed_at <= end


def due_in_period(deadline: date | None, start: date, end: date) -> bool:
    return deadline is not None and start <= deadline <= end


def execution_on_time(deadline: date | None, closed_at: date | None, status: str) -> bool:
    return bool(is_completed(status) and deadline and closed_at and closed_at <= deadline)


def days_overdue(
    deadline: date | None, closed_at: date | None, status: str, today: date | None = None
) -> int:
    if not deadline:
        return 0
    reference = closed_at if is_completed(status) and closed_at else (today or date.today())
    return max((reference - deadline).days, 0)


def include_in_weekly_report(
    *,
    deadline: date | None,
    closed_at: date | None,
    status: str,
    period_start: date,
    period_end: date,
    deferred: bool = False,
    include_deferred: bool = False,
    is_subtask: bool = False,
    include_in_report: bool = True,
) -> bool:
    if deferred and not include_deferred:
        return False
    if is_subtask and not include_in_report:
        return False
    return (
        due_in_period(deadline, period_start, period_end)
        or completed_in_period(closed_at, period_start, period_end)
        or bool(deadline and deadline < period_start and not is_completed(status))
    )


STATUS_LABELS = {
    "completed_in_time": "Выполнено в срок",
    "completed_late": "Выполнено с нарушением срока",
    "overdue": "Просрочено",
    "in_progress": "В работе",
}


def reporting_status(
    deadline: date | None, closed_at: date | None, status: str, control_date: date
) -> str:
    """Return the sole user-facing reporting state at the selected date boundary."""
    if is_completed(status):
        if deadline and closed_at and closed_at <= deadline:
            return "completed_in_time"
        return "completed_late"
    if deadline and deadline < control_date:
        return "overdue"
    return "in_progress"
