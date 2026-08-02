"""Execution control for published protocol instructions."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.db.models.domain import (
    Protocol,
    ProtocolTask,
    ProtocolTaskControl,
    ProtocolTaskStatusHistory,
)

CONTROL_STATUSES = {"pending", "in_progress", "completed", "overdue", "rejected"}

STATUS_LABELS = {
    "new": "Не начато",
    "in_progress": "В работе",
    "waiting_control": "На контроле",
    "completed": "Выполнено",
    "overdue": "Просрочено",
    "cancelled": "Отменено",
}
TRANSITIONS = {
    "new": {"in_progress", "cancelled"},
    "in_progress": {"waiting_control", "completed", "cancelled"},
    "waiting_control": {"completed", "in_progress"},
    "overdue": {"in_progress", "waiting_control", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class InvalidStatusTransition(ValueError):
    pass


class StatusChangeForbidden(PermissionError):
    pass


class ControlValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ControlActor:
    username: str
    role: str = "user"


@dataclass(frozen=True)
class ProtocolProgress:
    total: int
    completed: int
    in_progress: int
    overdue: int
    percent: int


class StatusPermissionPolicy:
    """Replaceable authorization policy for status changes."""

    allowed_roles = {"operator", "admin", "administrator"}

    def can_change(self, actor: ControlActor, protocol: Protocol) -> bool:
        return actor.role.lower() in self.allowed_roles or protocol.created_by == actor.username


class ProtocolControlService:
    def __init__(self, db: Session, permission_policy: StatusPermissionPolicy | None = None):
        self.db = db
        self.permission_policy = permission_policy or StatusPermissionPolicy()

    @staticmethod
    def can_transition(old_status: str, new_status: str) -> bool:
        # "returned" is the UI action for returning an instruction to work.
        new_status = "in_progress" if new_status == "returned" else new_status
        return new_status in TRANSITIONS.get(old_status, set())

    def change_status(
        self,
        task: ProtocolTask,
        new_status: str,
        actor: ControlActor,
        comment: str | None = None,
        *,
        check_permission: bool = True,
    ) -> ProtocolTaskStatusHistory:
        new_status = "in_progress" if new_status == "returned" else new_status
        if check_permission and not self.permission_policy.can_change(actor, task.protocol):
            raise StatusChangeForbidden("Недостаточно прав для изменения статуса")
        if not self.can_transition(task.status, new_status):
            raise InvalidStatusTransition(f"Переход {task.status} → {new_status} запрещён")
        history = ProtocolTaskStatusHistory(
            protocol_task_id=task.id,
            old_status=task.status,
            new_status=new_status,
            comment=comment.strip() if comment and comment.strip() else None,
            changed_by=actor.username,
        )
        task.status = new_status
        self.db.add(history)
        self.db.commit()
        self.db.refresh(history)
        return history

    def mark_overdue(self, tasks: list[ProtocolTask], today: date | None = None) -> int:
        today = today or date.today()
        changed = 0
        for task in tasks:
            if task.deadline and task.deadline < today and task.status not in {"completed", "cancelled", "overdue"}:
                old_status = task.status
                task.status = "overdue"
                self.db.add(ProtocolTaskStatusHistory(
                    protocol_task_id=task.id,
                    old_status=old_status,
                    new_status="overdue",
                    comment="Срок исполнения истёк",
                    changed_by="system",
                ))
                changed += 1
        if changed:
            self.db.commit()
        return changed

    def update_control(
        self,
        task: ProtocolTask,
        status: str,
        comment: str | None = None,
        actual_date: date | None = None,
    ) -> ProtocolTaskControl:
        if status not in CONTROL_STATUSES:
            raise ControlValidationError("Неизвестный статус контроля")
        comment = comment.strip() if comment else None
        if status in {"completed", "rejected"} and not comment:
            raise ControlValidationError("Для завершения или отклонения обязателен комментарий")
        control = task.control or ProtocolTaskControl(
            protocol_task=task, planned_date=task.deadline
        )
        control.status = status
        control.result_comment = comment
        control.actual_date = actual_date
        task.status = status  # compatibility with the earlier execution-history UI
        self.db.add(control)
        self._complete_protocol_if_ready(task.protocol)
        self.db.commit()
        self.db.refresh(control)
        return control

    def _complete_protocol_if_ready(self, protocol: Protocol) -> None:
        tasks = list(protocol.tasks)
        if tasks and all(task.control and task.control.status == "completed" for task in tasks):
            protocol.status = "completed"
        elif protocol.status == "published":
            protocol.status = "control"

    @staticmethod
    def progress(tasks: list[ProtocolTask]) -> ProtocolProgress:
        total = len(tasks)
        statuses = [task.control.status if task.control else task.status for task in tasks]
        completed = statuses.count("completed")
        overdue = statuses.count("overdue")
        active = sum(status in {"in_progress", "waiting_control"} for status in statuses)
        return ProtocolProgress(total, completed, active, overdue, int(completed * 100 / total) if total else 0)


class OverdueChecker:
    """Marks non-completed controls whose planned deadline has passed."""

    def __init__(self, db: Session):
        self.db = db

    def check(self, tasks: list[ProtocolTask], today: date | None = None) -> int:
        today = today or date.today()
        changed = 0
        for task in tasks:
            control = task.control
            deadline = control.planned_date if control else task.deadline
            if deadline and deadline < today and (not control or control.status != "completed"):
                if control is None:
                    control = ProtocolTaskControl(protocol_task=task, planned_date=deadline)
                if control.status != "overdue":
                    control.status = "overdue"
                    task.status = "overdue"
                    self.db.add(control)
                    changed += 1
        if changed:
            self.db.commit()
        return changed


def days_remaining(task: ProtocolTask, today: date | None = None) -> int | None:
    return (task.deadline - (today or date.today())).days if task.deadline else None


def can_transition(old_status: str, new_status: str) -> bool:
    """Public functional API for transition checks."""
    return ProtocolControlService.can_transition(old_status, new_status)


def calculate_execution_state(tasks: list[ProtocolTask]) -> ProtocolProgress:
    """Calculate aggregate execution state without database access."""
    return ProtocolControlService.progress(tasks)


def find_overdue_tasks(
    tasks: list[ProtocolTask], today: date | None = None
) -> list[ProtocolTask]:
    """Return instructions whose deadline has passed and which are not final."""
    today = today or date.today()
    return [
        task
        for task in tasks
        if task.deadline
        and task.deadline < today
        and task.status not in {"completed", "cancelled"}
    ]
