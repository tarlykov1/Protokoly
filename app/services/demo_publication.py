import json
from datetime import UTC, datetime
from hashlib import sha1

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import (
    BitrixTaskLink,
    Protocol,
    ProtocolTask,
    PublicationItem,
    PublicationRun,
    TaskAssessment,
)
from app.services.ai.provider import TaskAssessmentResult
from app.services.task_planning.planner import TaskPlanningService


def validate_task(task: ProtocolTask):
    errors = []
    warnings = []
    if not task.title or not task.title.strip():
        errors.append("Нет формулировки")
    if not task.assignments:
        errors.append("Нет исполнителя")
    if not task.deadline:
        warnings.append("Не указан срок")
    for a in task.assignments:
        if a.employee and not a.employee.bitrix_user_id:
            errors.append(f"Нет Bitrix ID у {a.employee.full_name}")
    task.status = "ready" if not errors else "validation_required"
    return errors, warnings


async def assess_task(task: ProtocolTask) -> TaskAssessmentResult:
    # local deterministic rule-based assessment
    score = 100
    if not task.description:
        score -= 15
    if not task.acceptance_criteria:
        score -= 20
    if not task.deadline:
        score -= 10
    if not task.assignments:
        score -= 25
    return TaskAssessmentResult(
        "rule_based",
        "local",
        "demo-v1",
        max(score, 0),
        "Локальная детерминированная оценка без внешних API.",
        task.title,
        task.description,
        task.acceptance_criteria,
    )


def save_assessment(db: Session, task: ProtocolTask, result: TaskAssessmentResult):
    db.add(
        TaskAssessment(
            protocol_task_id=task.id,
            provider=result.provider,
            model=result.model,
            prompt_version=result.prompt_version,
            overall_score=result.overall_score,
            clarity_score=result.overall_score,
            completeness_score=result.overall_score,
            smart_score=result.overall_score,
            acceptance_criteria_score=result.overall_score,
            summary=result.summary,
            recommendations_json=json.dumps(
                ["Уточните срок и критерии приемки, если они отсутствуют"], ensure_ascii=False
            ),
        )
    )


class FakeTaskGateway:
    def create(
        self,
        db: Session,
        planned,
        task_id: int | None,
        assignment_id: int | None,
        fail_key: str | None = None,
    ):
        payload = {
            "title": planned.title,
            "responsible_id": planned.responsible_id,
            "deadline": str(planned.deadline) if planned.deadline else None,
            "parent_external_key": planned.parent_external_key,
        }
        if fail_key and fail_key in planned.external_key:
            return (
                "failed",
                None,
                payload,
                {"simulation": True, "error": "Имитированная ошибка"},
                "Имитированная ошибка",
            )
        link = db.scalar(
            select(BitrixTaskLink).where(BitrixTaskLink.external_key == planned.external_key)
        )
        if link:
            return (
                "reused",
                str(link.bitrix_task_id),
                payload,
                {"simulation": True, "reused": True},
                None,
            )
        ext = int(sha1(planned.external_key.encode()).hexdigest()[:8], 16) % 900000 + 100000
        db.add(
            BitrixTaskLink(
                protocol_task_id=task_id or 0,
                assignment_id=assignment_id,
                bitrix_task_id=ext,
                task_type=planned.task_type,
                external_key=planned.external_key,
                sync_status="simulated",
                last_synced_at=datetime.now(UTC),
            )
        )
        return "created", str(ext), payload, {"simulation": True, "created": True}, None


def protocol_plan(db: Session, protocol: Protocol):
    planner = TaskPlanningService()
    rows = []
    errors = []
    warnings = []
    for task in protocol.tasks:
        plan = planner.build_plan(protocol.project, task)
        rows += [(task, p) for p in plan.tasks]
        errors += [f"{task.number}: {e.message}" for e in plan.errors]
        warnings += [f"{task.number}: {w.message}" for w in plan.warnings]
    return rows, errors, warnings


def run_publication(
    db: Session,
    protocol: Protocol,
    *,
    retry_run: PublicationRun | None = None,
    fail_key: str | None = None,
):
    rows, errors, warnings = protocol_plan(db, protocol)
    if errors and retry_run is None:
        return None, errors
    run = PublicationRun(
        protocol_id=protocol.id,
        gateway_type="fake",
        mode="demo",
        status="running",
        created_by="demo",
    )
    db.add(run)
    db.flush()
    if retry_run:
        keys = {i.external_key for i in retry_run.items if i.status == "failed"}
        rows = [r for r in rows if r[1].external_key in keys]
    order = {"root": 0, "subtask": 1, "independent": 2}
    rows.sort(key=lambda r: order.get(r[1].task_type, 9))
    gw = FakeTaskGateway()
    ok = fail = 0
    for task, planned in rows:
        assignment_id = (
            int(planned.external_key.split(":assignment:")[1].split(":")[0])
            if ":assignment:" in planned.external_key
            else None
        )
        status, ext, req, resp, err = gw.create(db, planned, task.id, assignment_id, fail_key)
        db.add(
            PublicationItem(
                publication_run_id=run.id,
                protocol_task_id=task.id,
                assignment_id=assignment_id,
                external_key=planned.external_key,
                parent_external_key=planned.parent_external_key,
                simulated_external_id=ext,
                status=status,
                request_payload=req,
                response_payload=resp,
                error_message=err,
            )
        )
        ok += status in ("created", "reused")
        fail += status == "failed"
    run.total_items = ok + fail
    run.successful_items = ok
    run.failed_items = fail
    run.finished_at = datetime.now(UTC)
    run.status = "completed" if fail == 0 else ("partial" if ok else "failed")
    run.error_summary = "; ".join(errors) if errors else None
    db.commit()
    return run, []
