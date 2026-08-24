from dataclasses import dataclass

from app.db.models.domain import Protocol, ProtocolTask


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "critical"
    task_id: int | None = None
    task_number: str | None = None

    @property
    def critical(self) -> bool:
        return self.severity == "critical"


@dataclass(frozen=True)
class ProtocolValidationResult:
    issues: tuple[ValidationIssue, ...]
    readiness_percent: int

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.critical)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.critical)

    @property
    def can_publish(self) -> bool:
        return not self.errors


class ProtocolValidationService:
    """Single source of protocol and instruction validation for every UI and workflow."""

    def validate_task(self, task: ProtocolTask) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []

        def add(code: str, message: str, severity: str = "critical") -> None:
            issues.append(
                ValidationIssue(
                    code,
                    message,
                    severity=severity,
                    task_id=task.id,
                    task_number=task.number,
                )
            )

        if not (task.number or "").strip():
            add("number_required", "Не указан номер")
        if not (task.title or "").strip():
            add("title_required", "Не заполнено поручение")
        if not task.assignments:
            add("assignee_required", "Отсутствует исполнитель")
        elif task.protocol.source_type == "docx_import" and any(
            not assignment.employee_id for assignment in task.assignments
        ):
            add("employee_not_found", "Пользователь не найден")
        if not task.deadline:
            add("deadline_required", "Отсутствует срок", "warning")
        if not task.section_id:
            add("section_required", "Отсутствует раздел", "warning")
        return tuple(issues)

    def validate(self, protocol: Protocol) -> ProtocolValidationResult:
        issues = [issue for task in protocol.tasks for issue in self.validate_task(task)]
        # Requisites are advisory in an early draft and become critical when the document
        # enters approval/publication stages.
        # Review is the gate immediately before approval. Already-approved legacy records
        # predate these nullable columns and remain publishable after migration.
        strict = protocol.status == "review"
        severity = "critical" if strict else "warning"
        for code, value, message in (
            ("protocol_title_required", protocol.title, "Не указано название протокола"),
            ("protocol_date_required", protocol.meeting_date, "Не указана дата заседания"),
            (
                "protocol_number_required",
                protocol.number if protocol.document_type == "protocol" else True,
                "Не указан номер протокола",
            ),
        ):
            if not value:
                issues.append(ValidationIssue(code, message, severity))
        # Failed publication attempts remain unresolved until a later successful run.
        runs = sorted(getattr(protocol, "publication_runs", ()) or (), key=lambda run: run.id)
        if runs and runs[-1].failed_items:
            for item in runs[-1].items:
                if item.status == "failed":
                    task = item.protocol_task
                    issues.append(
                        ValidationIssue(
                            "bitrix_publication_error",
                            f"Ошибка публикации Bitrix24: {item.error_message or 'неизвестная ошибка'}",
                            task_id=item.protocol_task_id,
                            task_number=task.number if task else None,
                        )
                    )
        tasks = list(protocol.tasks)
        if not tasks:
            readiness = 0
        else:
            completed = 0
            for task in tasks:
                completed += bool((task.title or "").strip())
                completed += bool(task.assignments)
                completed += bool(task.deadline)
                completed += bool(task.section_id)
                completed -= any(not assignment.employee_id for assignment in task.assignments)
            readiness = max(0, int(100 * completed / (len(tasks) * 4)))
            if any(issue.code == "bitrix_publication_error" for issue in issues):
                readiness = min(readiness, 99)
        return ProtocolValidationResult(tuple(issues), readiness)
