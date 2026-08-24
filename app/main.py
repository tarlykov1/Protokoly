import logging
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import request_id_var
from app.core.security import sanitize_payload
from app.db.models.domain import (
    ImportSession,
    Project,
    Protocol,
    ProtocolTask,
    ReportRun,
    SavedReportView,
)
from app.db.session import get_db
from app.services.auth import CurrentUser, Permission, current_user, require, require_admin
from app.services.export import ProtocolDocxExporter
from app.services.imports.service import (
    confirm_session,
    create_preview_session,
    reparse_session,
    update_session_payload,
)
from app.services.operations import readiness, system_snapshot, touch_presence
from app.services.protocols.control import (
    STATUS_LABELS,
    ControlActor,
    ControlValidationError,
    InvalidStatusTransition,
    OverdueChecker,
    ProtocolControlService,
    StatusChangeForbidden,
    days_remaining,
)
from app.services.protocols.editor import (
    apply_task_data,
    editor_errors,
    match_source_name,
)
from app.services.protocols.editor import (
    create_task as create_editor_task,
)
from app.services.protocols.governance import (
    EVENT_LABELS,
    dashboard_metrics,
    record_event,
    register_document,
    transition,
)
from app.services.reporting.excel_exporter import ExcelReportExporter
from app.services.reporting.query import parse_report_query
from app.services.reporting.service import ReportService
from app.services.validation import ProtocolValidationService

app = FastAPI(title="Protocol Management System")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
templates = Jinja2Templates(directory="app/web/templates")
logger = logging.getLogger("protokoly.http")


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "").strip()[:128] or str(uuid4())
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled request error request_id=%s path=%s", request_id, request.url.path
        )
        response = JSONResponse(
            {
                "title": "Не удалось выполнить операцию",
                "detail": "Внутренняя ошибка сервера",
                "request_id": request_id,
            },
            status_code=500,
        )
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


@app.exception_handler(StarletteHTTPException)
async def controlled_http_error(request: Request, exc: StarletteHTTPException):
    payload = {
        "title": "Не удалось выполнить операцию",
        "detail": str(exc.detail),
        "request_id": getattr(request.state, "request_id", str(uuid4())),
    }
    if "application/json" in request.headers.get("accept", "") or request.url.path.startswith(
        ("/ready", "/system/diagnostics")
    ):
        return JSONResponse(payload, status_code=exc.status_code)
    return templates.TemplateResponse(request, "error.html", payload, status_code=exc.status_code)


def readiness_percent(protocol):
    return ProtocolValidationService().validate(protocol).readiness_percent


def common_context(active_page=None, breadcrumb=None, **extra):
    return {"active_page": active_page, "breadcrumb": breadcrumb, "app_version": "v0.6 UX"} | extra


def task_attention(task, assessment=None):
    reasons = []
    if not task.title:
        reasons.append("нет формулировки")
    if not task.assignments:
        reasons.append("без исполнителя")
    if not task.deadline:
        reasons.append("без срока")
    if assessment and assessment.overall_score is not None and assessment.overall_score < 70:
        reasons.append("низкая AI-оценка")
    return reasons


templates.env.globals["readiness_percent"] = readiness_percent


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        return readiness(db)
    except Exception as exc:
        raise HTTPException(503, f"Приложение не готово: {exc}") from exc


@app.get("/system/health")
def system_health(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "system_health.html",
        common_context("Состояние системы", "Состояние системы", snapshot=system_snapshot(db)),
    )


@app.get("/system/diagnostics")
def system_diagnostics(_: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    return sanitize_payload(system_snapshot(db))


@app.get("/system/integration-issues")
def integration_issues(
    request: Request,
    unresolved: bool = True,
    operation: str = "",
    _: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.db.models.domain import IntegrationLog

    stmt = select(IntegrationLog).where(IntegrationLog.status == "error")
    if unresolved:
        stmt = stmt.where(IntegrationLog.resolved_at.is_(None))
    if operation:
        stmt = stmt.where(IntegrationLog.operation.ilike(f"%{operation}%"))
    issues = db.scalars(stmt.order_by(IntegrationLog.id.desc()).limit(200)).all()
    return templates.TemplateResponse(
        request,
        "integration_issues.html",
        common_context(
            "Интеграции",
            "Проблемы интеграций",
            issues=issues,
            operation=operation,
            unresolved=unresolved,
        ),
    )


@app.post("/system/integration-issues/{issue_id}/resolve")
def resolve_integration_issue(
    issue_id: int, _: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    from datetime import UTC, datetime

    from app.db.models.domain import IntegrationLog

    issue = db.get(IntegrationLog, issue_id)
    if not issue:
        raise HTTPException(404, "Проблема не найдена")
    issue.resolved_at = datetime.now(UTC)
    db.commit()
    return RedirectResponse("/system/integration-issues", status_code=303)


@app.post("/protocols/{protocol_id}/presence")
def protocol_presence(
    protocol_id: int,
    request: Request,
    actor: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not db.get(Protocol, protocol_id):
        raise HTTPException(404, "Протокол не найден")
    return {
        "editors": touch_presence(db, protocol_id, actor.username, request.state.request_id),
        "ttl_seconds": 90,
    }


@app.get("/")
def home_redirect():
    return RedirectResponse("/dashboard", status_code=307)


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    corporate = dashboard_metrics(db)
    draft_count = (
        db.scalar(select(func.count()).select_from(Protocol).where(Protocol.status == "draft")) or 0
    )
    ready_count = (
        db.scalar(select(func.count()).select_from(Protocol).where(Protocol.status == "ready")) or 0
    )
    error_count = (
        db.scalar(
            select(func.count())
            .select_from(Protocol)
            .where(Protocol.status == "validation_required")
        )
        or 0
    )
    protocols = db.scalars(select(Protocol).order_by(Protocol.created_at.desc()).limit(5)).all()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "draft_count": draft_count,
            "ready_count": ready_count,
            "error_count": error_count,
            "project_count": db.scalar(select(func.count()).select_from(Project)) or 0,
            "protocol_count": db.scalar(select(func.count()).select_from(Protocol)) or 0,
            "task_count": db.scalar(select(func.count()).select_from(ProtocolTask)) or 0,
            "import_review_count": db.scalar(
                select(func.count())
                .select_from(ImportSession)
                .where(ImportSession.status != "confirmed")
            )
            or 0,
            "publication_count": db.scalar(select(func.count()).select_from(PublicationRun))
            if "PublicationRun" in globals()
            else 0,
            "protocols": protocols,
            "status_counts": corporate["statuses"],
            "completion_percent": corporate["completion_percent"],
            "overdue_count": corporate["overdue_count"],
        },
    )


def report_context(request: Request, db: Session, report_type: str = "dashboard"):
    query = parse_report_query(request.url.query)
    dataset = ReportService(db).build(query)
    actor = current_user(request)
    views = db.scalars(
        select(SavedReportView)
        .where(or_(SavedReportView.owner == actor.username, SavedReportView.shared.is_(True)))
        .order_by(SavedReportView.name)
    ).all()
    return common_context(
        "Отчёты и аналитика",
        "Отчёты и аналитика",
        dataset=dataset,
        report_type=report_type,
        projects=db.scalars(select(Project).order_by(Project.name)).all(),
        views=views,
    )


@app.get("/reports")
@app.get("/reports/dashboard")
def reports_dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "reports_dashboard.html", report_context(request, db)
    )


@app.get("/reports/tasks")
@app.get("/reports/assignees")
@app.get("/reports/departments")
def reports_table(request: Request, db: Session = Depends(get_db)):
    report_type = request.url.path.rsplit("/", 1)[-1]
    return templates.TemplateResponse(
        request, "reports_table.html", report_context(request, db, report_type)
    )


@app.get("/reports/management")
def reports_management(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "reports_dashboard.html", report_context(request, db, "management")
    )


@app.get("/reports/control")
def reports_control(
    request: Request, _: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    return templates.TemplateResponse(
        request, "reports_table.html", report_context(request, db, "control")
    )


@app.post("/reports/views")
def save_report_view(
    name: str = Form(...),
    report_type: str = Form("tasks"),
    filters_json: str = Form("{}"),
    shared: bool = Form(False),
    actor: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    import json

    try:
        filters = json.loads(filters_json)
    except ValueError:
        raise HTTPException(422, "Некорректные фильтры") from None
    if shared and actor.role.value != "administrator":
        raise HTTPException(403, "Общие представления создаёт администратор")
    db.add(
        SavedReportView(
            name=name,
            owner=actor.username,
            filters_json=filters,
            report_type=report_type,
            shared=shared,
        )
    )
    db.commit()
    return RedirectResponse("/reports", status_code=303)


@app.get("/reports/export.xlsx")
def reports_export(
    request: Request, actor: CurrentUser = Depends(current_user), db: Session = Depends(get_db)
):
    query = parse_report_query(request.url.query)
    dataset = ReportService(db).build(query)
    report_type = request.query_params.get("view", "tasks")
    if report_type not in {"tasks", "assignees", "departments"}:
        raise HTTPException(422, "Неизвестный вид отчёта")
    run = ReportRun(
        report_type=report_type, user=actor.username, filters_json=query.as_dict(), status="running"
    )
    db.add(run)
    db.flush()
    directory = Path("var/reports")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"report-{run.id}.xlsx"
    try:
        path.write_bytes(ExcelReportExporter().export(dataset, user=actor.username, report_type=report_type))
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.file_path = str(path)
        run.file_url = f"/reports/archive/{run.id}/download"
        db.commit()
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        db.commit()
        raise
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@app.get("/reports/archive")
def reports_archive(
    request: Request, actor: CurrentUser = Depends(current_user), db: Session = Depends(get_db)
):
    stmt = select(ReportRun).order_by(ReportRun.created_at.desc())
    if actor.role.value != "administrator":
        stmt = stmt.where(ReportRun.user == actor.username)
    return templates.TemplateResponse(
        request,
        "reports_archive.html",
        common_context("Отчёты и аналитика", "Архив отчётов", runs=db.scalars(stmt).all()),
    )


@app.get("/reports/archive/{run_id}/download")
def report_download(
    run_id: int, actor: CurrentUser = Depends(current_user), db: Session = Depends(get_db)
):
    run = db.get(ReportRun, run_id)
    if not run or (run.user != actor.username and actor.role.value != "administrator"):
        raise HTTPException(404, "Отчёт не найден")
    if run.status != "completed" or not run.file_path or not Path(run.file_path).is_file():
        raise HTTPException(409, "Файл отчёта недоступен")
    return FileResponse(run.file_path, filename=Path(run.file_path).name)


@app.get("/projects")
def projects(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "projects.html",
        common_context(
            "Проекты", "Проекты", projects=db.scalars(select(Project).order_by(Project.name)).all()
        ),
    )


@app.get("/projects/new")
def new_project(request: Request):
    return templates.TemplateResponse(
        request, "project_form.html", common_context("Проекты", "Новый проект")
    )


@app.post("/projects")
def create_project(
    name: str = Form(...),
    code: str = Form(...),
    bitrix_group_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    db.add(Project(name=name, code=code, bitrix_group_id=bitrix_group_id))
    db.commit()
    return RedirectResponse("/projects", status_code=303)


@app.get("/protocols")
def protocols(
    request: Request,
    db: Session = Depends(get_db),
    status: str | None = None,
    project_id: int | None = None,
    q: str | None = None,
    sort: str = "date",
    readiness: str | None = None,
):
    stmt = select(Protocol)
    if status:
        stmt = stmt.where(Protocol.status == status)
    if project_id:
        stmt = stmt.where(Protocol.project_id == project_id)
    if q:
        stmt = stmt.where(Protocol.title.ilike(f"%{q}%"))
    if sort == "title":
        stmt = stmt.order_by(Protocol.title)
    else:
        stmt = stmt.order_by(Protocol.created_at.desc())
    items = db.scalars(stmt).all()
    if readiness == "ready":
        items = [p for p in items if readiness_percent(p) >= 80]
    elif readiness == "attention":
        items = [p for p in items if readiness_percent(p) < 80]
    return templates.TemplateResponse(
        request,
        "protocols.html",
        common_context(
            "Протоколы",
            "Протоколы",
            protocols=items,
            projects=db.scalars(select(Project).order_by(Project.name)).all(),
            status=status,
            project_id=project_id,
            q=q or "",
            sort=sort,
            readiness=readiness,
        ),
    )


@app.get("/protocols/import")
def import_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "import_form.html",
        common_context(
            "Проекты", "Проекты", projects=db.scalars(select(Project).order_by(Project.name)).all()
        ),
    )


@app.get("/protocols/new")
def new_protocol(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "protocol_form.html",
        common_context(
            "Протоколы",
            "Новый протокол",
            projects=db.scalars(
                select(Project).where(Project.is_active.is_(True)).order_by(Project.name)
            ).all(),
        ),
    )


@app.get("/protocols/create")
def protocol_create_wizard(request: Request, db: Session = Depends(get_db)):
    """Render the manual protocol wizard; nothing is persisted until confirmation."""
    employees = db.scalars(
        select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name)
    ).all()
    participant_templates = db.scalars(
        select(ParticipantGroupTemplate).order_by(ParticipantGroupTemplate.name)
    ).all()
    return templates.TemplateResponse(
        request,
        "protocol_create_wizard.html",
        common_context(
            "Протоколы",
            "Создание протокола",
            projects=db.scalars(
                select(Project).where(Project.is_active.is_(True)).order_by(Project.name)
            ).all(),
            employees=employees,
            participant_templates=participant_templates,
            employees_json=[{"id": item.id, "name": item.full_name} for item in employees],
            templates_json=[{"id": item.id, "name": item.name} for item in participant_templates],
        ),
    )


@app.post("/protocols/create")
def complete_protocol_wizard(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Atomically create all aggregates collected by the five-step wizard."""
    required = {"title": "Название", "number": "Номер", "project_id": "Проект"}
    missing = [label for key, label in required.items() if not payload.get(key)]
    if missing:
        raise HTTPException(status_code=422, detail="Не заполнено: " + ", ".join(missing))
    project = db.get(Project, int(payload["project_id"]))
    if not project:
        raise HTTPException(status_code=422, detail="Проект не найден")
    try:
        meeting_date = (
            date.fromisoformat(payload["meeting_date"]) if payload.get("meeting_date") else None
        )
        protocol = Protocol(
            project_id=project.id,
            number=str(payload["number"]).strip(),
            title=str(payload["title"]).strip(),
            meeting_date=meeting_date,
            location=(payload.get("location") or "").strip() or None,
            initiator=(payload.get("initiator") or "").strip() or None,
            responsible=(payload.get("responsible") or "").strip() or None,
            description=(payload.get("description") or "").strip() or None,
            status="draft",
            source_type="manual",
        )
        db.add(protocol)
        db.flush()
        record_event(db, protocol, "protocol_created", "system")
        groups = {}
        for index, item in enumerate(payload.get("groups", [])):
            name = (
                item.get("name") or ("Присутствовали" if index == 0 else f"Список {index}")
            ).strip()
            group_type = item.get("type", "custom")
            group = None
            if group_type == "attendees":
                group = db.scalar(
                    select(ProtocolParticipantGroup).where(
                        ProtocolParticipantGroup.protocol_id == protocol.id,
                        ProtocolParticipantGroup.type == "attendees",
                    )
                )
            if group is None:
                group = ProtocolParticipantGroup(
                    protocol_id=protocol.id, name=name, type=group_type
                )
                db.add(group)
                db.flush()
            employee_ids = {int(value) for value in item.get("employee_ids", []) if value}
            template_id = item.get("template_id")
            if template_id:
                template = db.get(ParticipantGroupTemplate, int(template_id))
                employee_ids.update(
                    member.employee_id for member in (template.members if template else [])
                )
            for employee_id in employee_ids:
                employee = db.get(Employee, employee_id)
                if employee:
                    group.members.append(
                        ProtocolParticipantGroupMember(
                            employee_id=employee.id,
                            name_snapshot=employee.full_name,
                            source="wizard",
                        )
                    )
            groups[item.get("client_id", name)] = group
        sections = {}
        for index, item in enumerate(payload.get("sections", [])):
            section = ProtocolSection(
                protocol_id=protocol.id, title=item.get("title", "Раздел").strip(), sort_order=index
            )
            db.add(section)
            db.flush()
            sections[item.get("client_id", str(index))] = section
        for index, item in enumerate(payload.get("tasks", [])):
            section = sections.get(item.get("section_id"))
            task = ProtocolTask(
                protocol_id=protocol.id,
                section_id=section.id if section else None,
                number=str(index + 1),
                position=index,
                title=(item.get("text") or item.get("title") or "").strip(),
                deadline=date.fromisoformat(item["deadline"]) if item.get("deadline") else None,
                priority=item.get("priority") or "normal",
                create_as_subtasks=item.get("task_mode") == "subtasks",
                is_controlled=bool(item.get("controlled")),
                validation_status="draft",
            )
            db.add(task)
            db.flush()
            if item.get("employee_id"):
                employee = db.get(Employee, int(item["employee_id"]))
                if employee:
                    task.assignments.append(ProtocolTaskAssignment(employee_id=employee.id))
            elif item.get("group_id") and (group := groups.get(item["group_id"])):
                for order, member in enumerate(group.members):
                    task.assignments.append(
                        ProtocolTaskAssignment(
                            employee_id=member.employee_id,
                            source_participant_group_id=group.id,
                            sort_order=order,
                        )
                    )
        db.commit()
        db.refresh(protocol)
    except (TypeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Некорректные данные мастера") from exc
    return {
        "id": protocol.id,
        "status": protocol.status,
        "redirect_url": f"/protocols/{protocol.id}?created=1",
    }


@app.post("/protocols")
def create_protocol(
    project_id: int = Form(...),
    number: str = Form(...),
    title: str = Form(...),
    meeting_date: date = Form(...),
    initiator: str = Form(...),
    responsible: str = Form(...),
    participants: str = Form(""),
    description: str = Form(""),
    actor: CurrentUser = Depends(require(Permission.CREATE)),
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=422, detail="Проект не найден")
    protocol = Protocol(
        project_id=project_id,
        number=number.strip(),
        title=title.strip(),
        meeting_date=meeting_date,
        initiator=initiator.strip(),
        responsible=responsible.strip(),
        participants=participants.strip() or None,
        description=description.strip() or None,
        status="draft",
        source_type="manual",
    )
    db.add(protocol)
    db.flush()
    record_event(db, protocol, "protocol_created", actor.username)
    db.commit()
    db.refresh(protocol)
    return RedirectResponse(f"/protocols/{protocol.id}?created=1", status_code=303)


@app.post("/protocols/import/preview")
def import_preview(
    project_id: int = Form(...),
    parser_type: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    session = create_preview_session(db, project_id, file, parser_type)
    return RedirectResponse(f"/protocols/import/{session.id}/preview", status_code=303)


@app.get("/protocols/import/{session_id}/preview")
def import_session_preview(
    session_id: int, request: Request, db: Session = Depends(get_db), filter: str = "all"
):
    session = db.get(ImportSession, session_id)
    return templates.TemplateResponse(
        request,
        "import_preview.html",
        common_context(
            "Импорт",
            "Предпросмотр",
            session=session,
            payload=session.parsed_payload if session else {},
            filter=filter,
        ),
    )


@app.post("/protocols/import/{session_id}/update")
def import_session_update(session_id: int, payload: str = Form(...), db: Session = Depends(get_db)):
    session = db.get(ImportSession, session_id)
    update_session_payload(db, session, payload)
    return RedirectResponse(f"/protocols/import/{session_id}/preview", status_code=303)


@app.post("/protocols/import/{session_id}/reparse")
def import_session_reparse(
    session_id: int,
    confirm_replace: bool = Form(False),
    db: Session = Depends(get_db),
):
    session = db.get(ImportSession, session_id)
    reparse_session(db, session, confirm_replace)
    return RedirectResponse(f"/protocols/import/{session_id}/preview", status_code=303)


@app.post("/protocols/import/{session_id}/confirm")
def import_session_confirm(session_id: int, db: Session = Depends(get_db)):
    protocol = confirm_session(db, db.get(ImportSession, session_id))
    return RedirectResponse(f"/protocols?status={protocol.status}", status_code=303)


@app.post("/protocols/import/{session_id}/cancel")
def import_session_cancel(session_id: int, db: Session = Depends(get_db)):
    session = db.get(ImportSession, session_id)
    session.status = "cancelled"
    db.commit()
    return RedirectResponse("/protocols/imports", status_code=303)


@app.get("/protocols/imports")
def import_sessions(
    request: Request,
    db: Session = Depends(get_db),
    project_id: int | None = None,
    status: str | None = None,
    parser_type: str | None = None,
):
    stmt = select(ImportSession).order_by(ImportSession.created_at.desc())
    if project_id:
        stmt = stmt.where(ImportSession.project_id == project_id)
    if status:
        stmt = stmt.where(ImportSession.status == status)
    if parser_type:
        stmt = stmt.where(ImportSession.parser_type == parser_type)
    return templates.TemplateResponse(
        request,
        "import_sessions.html",
        common_context(
            "Импорт",
            "Журнал импорта",
            sessions=db.scalars(stmt).all(),
            projects=db.scalars(select(Project)).all(),
        ),
    )


from app.cli.generate_demo_docx import generate as generate_demo_docx
from app.cli.reset_demo import reset as reset_demo_data
from app.cli.seed_demo import seed as seed_demo_data
from app.core.config import get_settings
from app.db.models.domain import (
    Employee,
    EmployeeList,
    EmployeeSourceSettings,
    IntegrationLog,
    IntegrationSettings,
    ParticipantGroupTemplate,
    ParticipantGroupTemplateMember,
    ProtocolParticipantGroup,
    ProtocolParticipantGroupMember,
    ProtocolSection,
    ProtocolTaskAssignment,
    ProtocolTaskLink,
    PublicationRun,
    TaskAssessment,
)
from app.services.demo_publication import (
    assess_task,
    protocol_plan,
    run_publication,
    save_assessment,
    validate_task,
)
from app.services.employees import (
    BitrixEmployeeProvider,
    DatabaseEmployeeProvider,
    EmployeeDirectoryService,
    ManualEmployeeProvider,
)
from app.services.protocols.participants import (
    copy_members,
    copy_template,
    create_group,
    replace_members,
    save_group_as_template,
    selected_groups,
)
from app.services.tasks.gateway import Bitrix24RestGateway, BitrixAPIError, get_bitrix_gateway
from app.services.tasks.publication import PublicationNotAllowedError, PublicationService
from app.services.tasks.sync import BitrixTaskSyncService


@app.get("/demo-docx")
def demo_docx():
    path = generate_demo_docx()
    return FileResponse(
        path,
        filename="demo_protocol.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def demo_context(db: Session):
    project = db.scalar(select(Project).where(Project.code == "DEMO-MVP"))
    protocol = (
        db.scalar(
            select(Protocol)
            .where(Protocol.project_id == project.id)
            .order_by(Protocol.created_at.desc())
        )
        if project
        else None
    )
    tasks = protocol.tasks if protocol else []
    ready = sum(1 for task in tasks if task.assignments and task.deadline and task.title)
    progress = int(100 * ready / max(len(tasks), 1))
    return {"project": project, "protocol": protocol, "tasks": tasks, "progress": progress}


def require_demo_mode():
    if not get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="Demo actions are disabled")


@app.get("/demo")
def demo_wizard(request: Request, db: Session = Depends(get_db)):
    ctx = demo_context(db)
    return templates.TemplateResponse(
        request, "demo.html", ctx | {"message": request.query_params.get("message")}
    )


@app.post("/demo/seed")
def demo_seed():
    require_demo_mode()
    seed_demo_data()
    return RedirectResponse("/demo?message=Демонстрационные данные подготовлены", status_code=303)


@app.post("/demo/reset")
def demo_reset(confirm: str = Form("")):
    require_demo_mode()
    if confirm != "yes":
        return RedirectResponse("/demo?message=Для сброса требуется подтверждение", status_code=303)
    reset_demo_data()
    return RedirectResponse("/demo?message=Демонстрационные данные сброшены", status_code=303)


@app.get("/demo/docx")
def demo_docx_new():
    require_demo_mode()
    return demo_docx()


@app.get("/demo/guided")
def demo_guided(request: Request, db: Session = Depends(get_db), step: int = 1):
    ctx = demo_context(db)
    steps = [
        ("Проект", "Показываем подготовленный контур без ручной настройки."),
        ("Протокол", "Открываем пример протокола или загружаем DOCX."),
        ("Распознавание", "Проверяем найденные поручения и предупреждения."),
        ("Редактирование", "Уточняем исполнителей, сроки и критерии приемки."),
        ("Проверка", "Запускаем контроль качества и локальную AI-оценку."),
        ("План задач", "Смотрим будущую структуру задач и подзадач."),
        ("Тестовая публикация", "Создаем только имитацию задач."),
        ("Результат", "Подводим итог и фиксируем следующий этап."),
    ]
    step = min(max(step, 1), len(steps))
    return templates.TemplateResponse(
        request, "demo_guided.html", ctx | {"steps": steps, "step": step}
    )


@app.get("/demo/complete")
def demo_complete(request: Request, db: Session = Depends(get_db)):
    ctx = demo_context(db)
    runs = db.scalars(
        select(PublicationRun).order_by(PublicationRun.started_at.desc()).limit(1)
    ).all()
    created = sum(run.successful_items for run in runs) if runs else 0
    return templates.TemplateResponse(request, "demo_complete.html", ctx | {"created": created})


@app.get("/demo/dashboard")
def demo_dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "demo_dashboard.html",
        {
            "protocols": db.scalars(
                select(Protocol).order_by(Protocol.created_at.desc()).limit(10)
            ).all(),
            "runs": db.scalars(
                select(PublicationRun).order_by(PublicationRun.started_at.desc()).limit(5)
            ).all(),
            "projects_count": db.scalar(select(func.count()).select_from(Project)) or 0,
            "protocols_count": db.scalar(select(func.count()).select_from(Protocol)) or 0,
            "tasks_count": db.scalar(select(func.count()).select_from(ProtocolTask)) or 0,
            "ready_count": db.scalar(
                select(func.count())
                .select_from(ProtocolTask)
                .where(ProtocolTask.deadline.is_not(None))
            )
            or 0,
            "review_count": db.scalar(
                select(func.count())
                .select_from(ProtocolTask)
                .where(ProtocolTask.deadline.is_(None))
            )
            or 0,
            "publication_count": db.scalar(select(func.count()).select_from(PublicationRun)) or 0,
            "imports": db.scalars(
                select(ImportSession).order_by(ImportSession.created_at.desc()).limit(5)
            ).all(),
            "problem_tasks": db.scalars(
                select(ProtocolTask).where(ProtocolTask.deadline.is_(None)).limit(5)
            ).all(),
            **demo_context(db),
        },
    )


@app.get("/protocols/{protocol_id}")
def protocol_card(protocol_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Protocol, protocol_id)
    if not p:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    sections = db.scalars(
        select(ProtocolSection)
        .where(ProtocolSection.protocol_id == protocol_id)
        .order_by(ProtocolSection.sort_order)
    ).all()
    assessments = {
        a.protocol_task_id: a
        for a in db.scalars(
            select(TaskAssessment)
            .where(TaskAssessment.protocol_task_id.in_([t.id for t in p.tasks] or [0]))
            .order_by(TaskAssessment.created_at.desc())
        ).all()
    }
    validation = ProtocolValidationService().validate(p)
    by_task = {}
    for issue in validation.issues:
        by_task.setdefault(issue.task_id, []).append(issue)
    rows = []
    without_assignee = without_deadline = 0
    for t in p.tasks:
        task_issues = by_task.get(t.id, [])
        e = [issue.message for issue in task_issues if issue.critical]
        w = [issue.message for issue in task_issues if not issue.critical]
        without_assignee += 0 if t.assignments else 1
        without_deadline += 0 if t.deadline else 1
        rows.append((t, e, w, assessments.get(t.id)))
    progress = validation.readiness_percent
    return templates.TemplateResponse(
        request,
        "protocol_card.html",
        {
            "protocol": p,
            "sections": sections,
            "rows": rows,
            "progress": progress,
            "errors": len(validation.errors),
            "warnings": len(validation.warnings),
            "validation": validation,
            "without_assignee": without_assignee,
            "without_deadline": without_deadline,
            "control_progress": ProtocolControlService.progress(list(p.tasks)),
            "created": request.query_params.get("created") == "1",
            "history": p.history,
            "event_labels": EVENT_LABELS,
            "document_versions": p.document_versions,
            "current_user": current_user(request),
        },
    )


@app.get("/protocols/{protocol_id}/export/docx")
def export_protocol_docx(
    protocol_id: int,
    request: Request,
    mode: str = "memo",
    version: int | None = None,
    db: Session = Depends(get_db),
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    try:
        content = ProtocolDocxExporter(db).export(protocol_id, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # A link containing version reads an existing registry entry; a normal export creates one.
    if version is None:
        register_document(db, protocol, current_user(request).username)
        db.commit()
    number = (protocol.number or str(protocol.id)).replace("/", "_").replace("\\", "_")
    headers = {"Content-Disposition": f'attachment; filename="protocol_{number}.docx"'}
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.post("/protocols/{protocol_id}/workflow")
def change_protocol_workflow(
    protocol_id: int,
    action: str = Form(...),
    actor: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    try:
        if action == "publish":
            validation = ProtocolValidationService().validate(protocol)
            if not validation.can_publish:
                raise HTTPException(
                    status_code=409,
                    detail="Публикация заблокирована: устраните критические ошибки протокола",
                )
        transition(db, protocol, action, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса") from exc
    db.commit()
    return RedirectResponse(f"/protocols/{protocol_id}", status_code=303)


@app.get("/protocols/{protocol_id}/control")
def protocol_control(
    protocol_id: int,
    request: Request,
    db: Session = Depends(get_db),
    filter: str = "all",
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    tasks = list(protocol.tasks)
    OverdueChecker(db).check(tasks)
    service = ProtocolControlService(db)
    filters = {
        "in_progress": {"in_progress", "waiting_control"},
        "completed": {"completed"},
        "overdue": {"overdue"},
        "attention": {"overdue", "rejected"},
    }
    visible_tasks = (
        [task for task in tasks if task.control and task.control.status in filters[filter]]
        if filter in filters
        else tasks
    )
    return templates.TemplateResponse(
        request,
        "protocol_control.html",
        common_context(
            "Протоколы",
            "Контроль исполнения",
            protocol=protocol,
            tasks=visible_tasks,
            progress=service.progress(tasks),
            status_labels=STATUS_LABELS,
            days_remaining=days_remaining,
            current_filter=filter,
        ),
    )


@app.post("/protocols/{protocol_id}/control/tasks/{task_id}/status")
def change_protocol_task_status(
    protocol_id: int,
    task_id: int,
    request: Request,
    status: str = Form(...),
    comment: str | None = Form(None),
    db: Session = Depends(get_db),
):
    task = db.get(ProtocolTask, task_id)
    if not task or task.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Поручение не найдено")
    actor = ControlActor(
        request.headers.get("x-user", "operator"),
        request.headers.get("x-role", "operator"),
    )
    try:
        ProtocolControlService(db).change_status(task, status, actor, comment)
    except StatusChangeForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(f"/protocols/{protocol_id}/control", status_code=303)


@app.post("/protocol-tasks/{task_id}/control")
def update_task_control(
    task_id: int,
    status: str = Form(...),
    comment: str | None = Form(None),
    actual_date: date | None = Form(None),
    db: Session = Depends(get_db),
):
    task = db.get(ProtocolTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Поручение не найдено")
    try:
        ProtocolControlService(db).update_control(task, status, comment, actual_date)
    except ControlValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/protocols/{task.protocol_id}/control", status_code=303)


@app.post("/protocols/{protocol_id}/validate-all")
def validate_all(protocol_id: int, db: Session = Depends(get_db)):
    p = db.get(Protocol, protocol_id)
    checked = errors = warnings = 0
    for t in p.tasks:
        e, w = validate_task(t)
        checked += 1
        errors += len(e)
        warnings += len(w)
    db.commit()
    return {
        "checked": checked,
        "errors": errors,
        "warnings": warnings,
        "ready_to_publish": errors == 0,
    }


@app.get("/protocols/{protocol_id}/editor")
def protocol_editor(
    protocol_id: int,
    request: Request,
    db: Session = Depends(get_db),
    filter: str = "all",
    q: str = "",
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    sections = db.scalars(
        select(ProtocolSection)
        .where(ProtocolSection.protocol_id == protocol_id)
        .order_by(ProtocolSection.sort_order, ProtocolSection.id)
    ).all()
    rows = [
        (task, editor_errors(task))
        for task in sorted(protocol.tasks, key=lambda item: (item.position, item.id))
    ]
    filters = {
        "errors": lambda row: bool(row[1]),
        "without_assignee": lambda row: not row[0].assignments,
        "without_deadline": lambda row: not row[0].deadline,
        "ready": lambda row: not row[1],
    }
    if filter in filters:
        rows = [row for row in rows if filters[filter](row)]
    if q.strip():
        query = q.strip().casefold()
        rows = [row for row in rows if query in row[0].title.casefold()]
    return templates.TemplateResponse(
        request,
        "protocol_editor.html",
        common_context(
            "Протоколы",
            "Редактор протокола",
            protocol=protocol,
            sections=sections,
            rows=rows,
            employees=db.scalars(
                select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name)
            ).all(),
            participant_groups=db.scalars(
                select(ProtocolParticipantGroup)
                .where(ProtocolParticipantGroup.protocol_id == protocol_id)
                .order_by(ProtocolParticipantGroup.type, ProtocolParticipantGroup.name)
            ).all(),
            participant_templates=db.scalars(
                select(ParticipantGroupTemplate).order_by(ParticipantGroupTemplate.name)
            ).all(),
            current_filter=filter,
            search_query=q,
            error_count=sum(bool(editor_errors(task)) for task in protocol.tasks),
        ),
    )


@app.post("/protocols/{protocol_id}/editor/save")
def save_protocol_editor(
    protocol_id: int,
    payload: dict = Body(...),
    actor: CurrentUser = Depends(require(Permission.EDIT)),
    db: Session = Depends(get_db),
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    expected_version = payload.get("version")
    if expected_version is not None and int(expected_version) != protocol.version:
        raise HTTPException(status_code=409, detail="Протокол был изменён другим пользователем.")
    protocol_data = payload.get("protocol", {})
    for field in ("title", "number", "initiator", "responsible", "participants", "description"):
        if field in protocol_data:
            cleaned = str(protocol_data[field]).strip()
            setattr(protocol, field, cleaned or ("" if field == "title" else None))
    if "meeting_date" in protocol_data:
        value = protocol_data["meeting_date"]
        protocol.meeting_date = date.fromisoformat(value) if value else None
    tasks = {task.id: task for task in protocol.tasks}
    sections = {
        section.id: section
        for section in db.scalars(
            select(ProtocolSection).where(ProtocolSection.protocol_id == protocol_id)
        ).all()
    }
    for section_data in payload.get("sections", []):
        section = sections.get(int(section_data["id"]))
        if section:
            section.title = section_data["title"].strip() or section.title
            if "sort_order" in section_data:
                section.sort_order = int(section_data["sort_order"])
    for task_data in payload.get("tasks", []):
        task = tasks.get(int(task_data["id"]))
        if task:
            old_title, old_deadline = task.title, task.deadline
            old_assignees = sorted(a.employee_id for a in task.assignments if a.employee_id)
            try:
                apply_task_data(db, task, task_data)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if "position" in task_data:
                task.position = int(task_data["position"])
            if task.title != old_title:
                record_event(db, protocol, "task_text_changed", actor.username, task_id=task.id)
            if task.deadline != old_deadline:
                record_event(db, protocol, "task_deadline_changed", actor.username, task_id=task.id)
            new_assignees = sorted(a.employee_id for a in task.assignments if a.employee_id)
            if new_assignees != old_assignees:
                record_event(
                    db, protocol, "task_assignees_changed", actor.username, task_id=task.id
                )
    protocol.version += 1
    for task_data in payload.get("tasks", []):
        task = tasks.get(int(task_data["id"]))
        if task:
            task.version += 1
    db.commit()
    return {"saved": True}


@app.post("/protocols/{protocol_id}/participant-groups")
def add_participant_group(
    protocol_id: int, payload: dict = Body(...), db: Session = Depends(get_db)
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    try:
        source = payload.get("source", "empty")
        group = create_group(
            db,
            protocol,
            payload.get("name", ""),
            group_type="template_copy" if source == "template" else "custom",
        )
        replace_members(db, group, payload.get("employee_ids", []))
        if source == "attendees":
            attendees = db.scalar(
                select(ProtocolParticipantGroup).where(
                    ProtocolParticipantGroup.protocol_id == protocol_id,
                    ProtocolParticipantGroup.type == "attendees",
                )
            )
            if attendees:
                copy_members(db, attendees, group)
        elif source == "template":
            template = db.get(ParticipantGroupTemplate, int(payload.get("template_id") or 0))
            if not template:
                raise ValueError("Шаблон не найден")
            replace_members(
                db, group, [member.employee_id for member in template.members], source="template"
            )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": group.id, "name": group.name}


@app.post("/protocols/{protocol_id}/participant-groups/{group_id}/manual-member")
def add_manual_group_member(
    protocol_id: int, group_id: int, payload: dict = Body(...), db: Session = Depends(get_db)
):
    """Create a directory employee and add them to a local protocol list in one action."""
    group = db.get(ProtocolParticipantGroup, group_id)
    if not group or group.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Список не найден")
    full_name = str(payload.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="ФИО обязательно")
    employee = Employee(
        full_name=full_name,
        position=str(payload.get("position") or "").strip() or None,
        department=str(payload.get("department") or "").strip() or None,
        source_system="manual",
        is_active=True,
    )
    db.add(employee)
    db.flush()
    group.members.append(
        ProtocolParticipantGroupMember(
            employee_id=employee.id, name_snapshot=employee.full_name, source="manual"
        )
    )
    db.commit()
    return {"id": employee.id, "full_name": employee.full_name}


@app.put("/protocols/{protocol_id}/participant-groups/{group_id}")
def edit_participant_group(
    protocol_id: int, group_id: int, payload: dict = Body(...), db: Session = Depends(get_db)
):
    group = db.get(ProtocolParticipantGroup, group_id)
    if not group or group.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Список не найден")
    if "name" in payload and group.type != "attendees":
        group.name = payload["name"].strip() or group.name
    replace_members(db, group, payload.get("employee_ids", []))
    db.commit()
    return {"updated": True}


@app.delete("/protocols/{protocol_id}/participant-groups/{group_id}")
def remove_participant_group(protocol_id: int, group_id: int, db: Session = Depends(get_db)):
    group = db.get(ProtocolParticipantGroup, group_id)
    if not group or group.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Список не найден")
    if group.type == "attendees":
        raise HTTPException(status_code=422, detail="Системный список удалить нельзя")
    db.delete(group)
    db.commit()
    return {"deleted": True}


@app.post("/protocols/{protocol_id}/participant-groups/{group_id}/copy-attendees")
def copy_attendees(protocol_id: int, group_id: int, db: Session = Depends(get_db)):
    target = db.get(ProtocolParticipantGroup, group_id)
    source = db.scalar(
        select(ProtocolParticipantGroup).where(
            ProtocolParticipantGroup.protocol_id == protocol_id,
            ProtocolParticipantGroup.type == "attendees",
        )
    )
    if not target or target.protocol_id != protocol_id or not source:
        raise HTTPException(status_code=404, detail="Список не найден")
    copy_members(db, source, target)
    db.commit()
    return {"copied": len(source.members)}


@app.post("/protocols/{protocol_id}/participant-groups/{group_id}/duplicate")
def duplicate_participant_group(protocol_id: int, group_id: int, db: Session = Depends(get_db)):
    """Create an independent local copy of a participant list."""
    source = db.get(ProtocolParticipantGroup, group_id)
    protocol = db.get(Protocol, protocol_id)
    if not source or source.protocol_id != protocol_id or not protocol:
        raise HTTPException(status_code=404, detail="Список не найден")
    existing_names = {group.name for group in protocol.participant_groups}
    base_name = f"{source.name} — копия"
    name = base_name
    suffix = 2
    while name in existing_names:
        name = f"{base_name} {suffix}"
        suffix += 1
    duplicate = create_group(db, protocol, name, group_type="custom")
    copy_members(db, source, duplicate)
    db.commit()
    return {"id": duplicate.id, "name": duplicate.name}


@app.post("/protocols/{protocol_id}/participant-groups/from-template/{template_id}")
def add_group_from_template(protocol_id: int, template_id: int, db: Session = Depends(get_db)):
    protocol, template = (
        db.get(Protocol, protocol_id),
        db.get(ParticipantGroupTemplate, template_id),
    )
    if not protocol or not template:
        raise HTTPException(status_code=404, detail="Протокол или шаблон не найден")
    group = copy_template(db, protocol, template)
    db.commit()
    return {"id": group.id}


@app.post("/protocols/{protocol_id}/participant-groups/{group_id}/save-template")
def save_participant_template(
    protocol_id: int, group_id: int, payload: dict = Body(default={}), db: Session = Depends(get_db)
):
    group = db.get(ProtocolParticipantGroup, group_id)
    if not group or group.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Список не найден")
    try:
        template = save_group_as_template(db, group, payload.get("name"))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Шаблон с таким названием уже существует"
        ) from exc
    return {"id": template.id, "name": template.name}


@app.post("/protocols/{protocol_id}/editor/tasks")
def add_editor_task(
    protocol_id: int,
    request: Request,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    key = request.headers.get("Idempotency-Key", "").strip()[:128]
    if key:
        existing = db.scalar(select(ProtocolTask).where(ProtocolTask.idempotency_key == key))
        if existing:
            return {"id": existing.id, "duplicate": True}
    task = create_editor_task(db, protocol, payload)
    task.idempotency_key = key or None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ProtocolTask).where(ProtocolTask.idempotency_key == key))
        if not existing:
            raise
        return {"id": existing.id, "duplicate": True}
    return {"id": task.id, "duplicate": False}


@app.post("/protocols/{protocol_id}/editor/tasks/{task_id}/duplicate")
def duplicate_editor_task(protocol_id: int, task_id: int, db: Session = Depends(get_db)):
    source = db.get(ProtocolTask, task_id)
    if not source or source.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Поручение не найдено")
    duplicate = create_editor_task(
        db,
        source.protocol,
        {
            "number": f"{source.number} копия",
            "title": source.title,
            "description": source.description,
            "deadline": str(source.deadline or ""),
            "section_id": source.section_id,
            "priority": source.priority,
            "create_as_subtasks": source.create_as_subtasks,
            "is_controlled": source.is_controlled,
            "parent_task_id": source.parent_task_id,
            "employee_ids": [
                a.employee_id
                for a in source.assignments
                if a.employee_id and not a.source_participant_group_id
            ],
            "participant_group_ids": [
                selection.participant_group_id for selection in source.participant_group_selections
            ],
        },
    )
    if source.control:
        from app.db.models.domain import ProtocolTaskControl

        duplicate.control = ProtocolTaskControl(
            status=source.control.status,
            planned_date=source.control.planned_date,
            actual_date=source.control.actual_date,
            result_comment=source.control.result_comment,
            last_synced_at=source.control.last_synced_at,
        )
    db.commit()
    return {"id": duplicate.id}


@app.delete("/protocols/{protocol_id}/editor/tasks/{task_id}")
def delete_editor_task(protocol_id: int, task_id: int, db: Session = Depends(get_db)):
    task = db.get(ProtocolTask, task_id)
    if not task or task.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Поручение не найдено")
    db.delete(task)
    db.commit()
    return {"deleted": True}


@app.post("/protocols/{protocol_id}/editor/sections")
def add_editor_section(protocol_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    if not db.get(Protocol, protocol_id):
        raise HTTPException(status_code=404, detail="Протокол не найден")
    order = (
        db.scalar(
            select(func.max(ProtocolSection.sort_order)).where(
                ProtocolSection.protocol_id == protocol_id
            )
        )
        or 0
    )
    section = ProtocolSection(
        protocol_id=protocol_id, title=payload.get("title", "Новый раздел"), sort_order=order + 1
    )
    db.add(section)
    db.commit()
    return {"id": section.id}


@app.delete("/protocols/{protocol_id}/editor/sections/{section_id}")
def delete_editor_section(protocol_id: int, section_id: int, db: Session = Depends(get_db)):
    section = db.get(ProtocolSection, section_id)
    if not section or section.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Раздел не найден")
    for task in db.scalars(select(ProtocolTask).where(ProtocolTask.section_id == section_id)).all():
        task.section_id = None
    db.delete(section)
    db.commit()
    return {"deleted": True}


@app.post("/protocols/{protocol_id}/editor/bulk")
def bulk_edit_tasks(protocol_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    ids = {int(value) for value in payload.get("task_ids", [])}
    changes = payload.get("changes", {})
    tasks = db.scalars(
        select(ProtocolTask).where(
            ProtocolTask.protocol_id == protocol_id, ProtocolTask.id.in_(ids or {0})
        )
    ).all()
    for task in tasks:
        data = dict(changes)
        if "employee_id" in data:
            employee_id = data.pop("employee_id")
            data["employee_ids"] = [
                *(a.employee_id for a in task.assignments if a.employee_id),
                employee_id,
            ]
        apply_task_data(db, task, data)
    db.commit()
    return {"updated": len(tasks)}


@app.get("/employees/search")
def employee_search(q: str = "", db: Session = Depends(get_db)):
    employees = db.scalars(
        select(Employee)
        .where(Employee.is_active.is_(True), Employee.full_name.ilike(f"%{q.strip()}%"))
        .order_by(Employee.full_name)
        .limit(20)
    ).all()
    return [{"id": employee.id, "full_name": employee.full_name} for employee in employees]


@app.post("/protocols/{protocol_id}/editor/tasks/{task_id}/match-assignee")
def match_editor_assignee(
    protocol_id: int, task_id: int, payload: dict = Body(...), db: Session = Depends(get_db)
):
    task = db.get(ProtocolTask, task_id)
    if not task or task.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Поручение не найдено")
    try:
        match_source_name(db, task, payload["source_name"], int(payload["employee_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return {"matched": True}


@app.post("/protocols/{protocol_id}/editor/tasks/{task_id}/create-assignee")
def create_editor_assignee(
    protocol_id: int, task_id: int, payload: dict = Body(...), db: Session = Depends(get_db)
):
    """Create a manual directory record and explicitly bind an imported name."""
    task = db.get(ProtocolTask, task_id)
    if not task or task.protocol_id != protocol_id:
        raise HTTPException(status_code=404, detail="Поручение не найдено")
    full_name = str(payload.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="Укажите ФИО сотрудника")
    employee = Employee(full_name=full_name, source_system="manual", is_active=True)
    db.add(employee)
    db.flush()
    match_source_name(db, task, str(payload.get("source_name") or full_name), employee.id)
    db.commit()
    return {"matched": True, "employee_id": employee.id, "bitrix_user_id": employee.bitrix_user_id}


@app.get("/protocols/{protocol_id}/editor/publication")
def editor_publication(protocol_id: int, db: Session = Depends(get_db)):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    if any(editor_errors(task) for task in protocol.tasks):
        return RedirectResponse(f"/protocols/{protocol_id}/editor?filter=errors", status_code=303)
    return RedirectResponse(f"/protocols/{protocol_id}/publication-plan", status_code=303)


@app.post("/protocols/{protocol_id}/assess-all")
async def assess_all(protocol_id: int, db: Session = Depends(get_db)):
    p = db.get(Protocol, protocol_id)
    for t in p.tasks:
        save_assessment(db, t, await assess_task(t))
    db.commit()
    return RedirectResponse(f"/protocols/{protocol_id}", status_code=303)


@app.get("/protocols/{protocol_id}/publication-plan")
def publication_plan(protocol_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Protocol, protocol_id)
    if not p:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    rows, errors, warnings = protocol_plan(db, p)
    links = db.scalars(
        select(ProtocolTaskLink)
        .where(ProtocolTaskLink.protocol_task_id.in_([task.id for task in p.tasks] or [0]))
        .order_by(ProtocolTaskLink.id)
    ).all()
    assignee_counts: dict[str, int] = {}
    for _, planned in rows:
        assignee_counts[planned.responsible_name] = (
            assignee_counts.get(planned.responsible_name, 0) + 1
        )
    group_breakdown = [
        (
            task,
            [
                (group.name, [member.name_snapshot for member in group.members])
                for group in selected_groups(db, task)
            ],
        )
        for task in p.tasks
        if selected_groups(db, task)
    ]
    section_count = (
        db.scalar(
            select(func.count())
            .select_from(ProtocolSection)
            .where(ProtocolSection.protocol_id == protocol_id)
        )
        or 0
    )
    service = PublicationService(db, get_bitrix_gateway(db))
    settings = service.settings_for(p)
    preview = service.preview(p)
    return templates.TemplateResponse(
        request,
        "publication_plan.html",
        {
            "protocol": p,
            "rows": rows,
            "errors": errors,
            "warnings": warnings,
            "demo_mode": get_settings().demo_mode,
            "links": links,
            "assignee_counts": assignee_counts,
            "group_breakdown": group_breakdown,
            "section_count": section_count,
            "settings": settings,
            "preview": preview,
        },
    )


@app.get("/protocols/{protocol_id}/bitrix-projects")
def search_bitrix_projects(protocol_id: int, q: str = "", db: Session = Depends(get_db)):
    if not db.get(Protocol, protocol_id):
        raise HTTPException(status_code=404, detail="Протокол не найден")
    try:
        return {"projects": get_bitrix_gateway(db).list_projects(q or None)}
    except BitrixAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/protocols/{protocol_id}/publication-settings")
def save_publication_settings(
    protocol_id: int,
    bitrix_project_id: int | None = Form(None),
    task_creator_id: int | None = Form(None),
    default_responsible_id: int | None = Form(None),
    parent_task_mode: str = Form("separate"),
    root_task_title: str | None = Form(None),
    observers: str = Form(""),
    accomplices: str = Form(""),
    create_checklist: bool = Form(False),
    add_protocol_link: bool = Form(False),
    sync_enabled: bool = Form(False),
    db: Session = Depends(get_db),
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    settings = PublicationService(db, get_bitrix_gateway(db)).settings_for(protocol)
    settings.bitrix_project_id = bitrix_project_id
    settings.task_creator_id = task_creator_id
    settings.default_responsible_id = default_responsible_id
    settings.parent_task_mode = parent_task_mode
    settings.root_task_title = root_task_title
    settings.observers = [int(x.strip()) for x in observers.split(",") if x.strip()]
    settings.accomplices = [int(x.strip()) for x in accomplices.split(",") if x.strip()]
    settings.create_checklist = create_checklist
    settings.add_protocol_link = add_protocol_link
    settings.sync_enabled = sync_enabled
    db.commit()
    return RedirectResponse(f"/protocols/{protocol_id}/publication-plan", status_code=303)


@app.post("/protocols/{protocol_id}/publish")
def publish_protocol(
    protocol_id: int, update_existing: bool = Form(False), db: Session = Depends(get_db)
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    service = PublicationService(db, get_bitrix_gateway(db))
    try:
        result = service.publish(protocol, update_existing=update_existing)
    except PublicationNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BitrixAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка Bitrix24: {exc}") from exc
    suffix = "?message=" + result.warnings[0] if result.warnings else ""
    return RedirectResponse(f"/protocols/{protocol_id}/publication-plan{suffix}", status_code=303)


@app.post("/protocols/{protocol_id}/sync-bitrix")
def sync_protocol_bitrix(
    protocol_id: int,
    actor: CurrentUser = Depends(require(Permission.PUBLISH)),
    db: Session = Depends(get_db),
):
    protocol = db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Протокол не найден")
    result = BitrixTaskSyncService(db, get_bitrix_gateway(db)).sync(protocol)
    record_event(
        db, protocol, "bitrix_synced", actor.username, updated=result.updated, errors=result.errors
    )
    db.commit()
    return RedirectResponse(
        f"/protocols/{protocol_id}/control?sync_updated={result.updated}&sync_errors={result.errors}",
        status_code=303,
    )


def _bitrix_settings(db: Session) -> IntegrationSettings:
    settings = db.scalar(select(IntegrationSettings).where(IntegrationSettings.type == "bitrix24"))
    if settings is None:
        settings = IntegrationSettings(type="bitrix24", enabled=True, mode="fake")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@app.get("/settings/integrations")
def integration_settings_page(request: Request, db: Session = Depends(get_db)):
    employee_source = db.scalar(select(EmployeeSourceSettings).order_by(EmployeeSourceSettings.id))
    if employee_source is None:
        employee_source = EmployeeSourceSettings(provider_type="manual", parameters={})
        db.add(employee_source)
        db.commit()
        db.refresh(employee_source)
    return templates.TemplateResponse(
        request,
        "integration_settings.html",
        common_context(
            "Интеграции",
            "Настройки / Интеграции",
            settings=_bitrix_settings(db),
            employee_source=employee_source,
            logs=db.scalars(
                select(IntegrationLog).order_by(IntegrationLog.id.desc()).limit(20)
            ).all(),
            message=request.query_params.get("message"),
            error=request.query_params.get("error"),
        ),
    )


def _employee_source(db: Session) -> EmployeeSourceSettings:
    source = db.scalar(select(EmployeeSourceSettings).order_by(EmployeeSourceSettings.id))
    if source is None:
        source = EmployeeSourceSettings(provider_type="manual", parameters={})
        db.add(source)
        db.commit()
        db.refresh(source)
    return source


def _configured_employee_provider(db: Session):
    source = _employee_source(db)
    parameters = source.parameters or {}
    if source.provider_type == "manual":
        return ManualEmployeeProvider()
    if source.provider_type == "database":
        db_type = parameters.get("db_type", "postgresql")
        if db_type == "sqlite":
            url = f"sqlite:///{parameters.get('database', '')}"
        else:
            from urllib.parse import quote_plus

            user = quote_plus(parameters.get("username", ""))
            password = quote_plus(parameters.get("password", ""))
            credentials = f"{user}:{password}@" if user else ""
            driver = "postgresql+psycopg" if db_type == "postgresql" else db_type
            url = f"{driver}://{credentials}{parameters.get('host', '')}/{parameters.get('database', '')}"
        return DatabaseEmployeeProvider(url, parameters)
    if source.provider_type == "bitrix":
        settings = _bitrix_settings(db)
        gateway = Bitrix24RestGateway(settings, db)
        return BitrixEmployeeProvider(gateway.list_users)
    raise ValueError("Неизвестный источник сотрудников")


@app.post("/settings/integrations/employees")
def save_employee_source(
    provider_type: str = Form(...),
    db_type: str = Form("postgresql"),
    host: str = Form(""),
    database: str = Form(""),
    schema: str = Form(""),
    table: str = Form(""),
    id_field: str = Form("id"),
    name_field: str = Form("full_name"),
    email_field: str = Form("email"),
    username: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    if provider_type not in {"manual", "database", "bitrix"}:
        raise HTTPException(status_code=422, detail="Неизвестный тип источника")
    source = _employee_source(db)
    source.provider_type = provider_type
    old_password = (source.parameters or {}).get("password", "")
    source.parameters = {
        "db_type": db_type,
        "host": host.strip(),
        "database": database.strip(),
        "schema": schema.strip(),
        "table": table.strip(),
        "id_field": id_field.strip(),
        "name_field": name_field.strip(),
        "email_field": email_field.strip(),
        "username": username.strip(),
        "password": password or old_password,
    }
    db.commit()
    return RedirectResponse(
        "/settings/integrations?message=Источник сотрудников сохранён", status_code=303
    )


@app.post("/settings/integrations/employees/check")
def check_employee_source(db: Session = Depends(get_db)):
    ok, message = _configured_employee_provider(db).test_connection()
    key = "message" if ok else "error"
    return RedirectResponse(f"/settings/integrations?{key}={message}", status_code=303)


@app.post("/settings/integrations/employees/sync")
def sync_employee_source(db: Session = Depends(get_db)):
    source = _employee_source(db)
    try:
        count = EmployeeDirectoryService(db).sync(_configured_employee_provider(db), source)
    except Exception as exc:
        source.last_sync_status = "error"
        source.last_sync_message = str(exc)
        db.commit()
        return RedirectResponse(
            f"/settings/integrations?error=Ошибка синхронизации: {exc}", status_code=303
        )
    return RedirectResponse(
        f"/employees?message=Синхронизировано сотрудников: {count}", status_code=303
    )


@app.post("/settings/integrations/bitrix24")
def save_bitrix_settings(
    enabled: bool = Form(False),
    mode: str = Form(...),
    portal_url: str = Form(""),
    webhook_url: str = Form(""),
    user_id: str = Form(""),
    token: str = Form(""),
    db: Session = Depends(get_db),
):
    if mode not in {"fake", "rest"}:
        raise HTTPException(status_code=422, detail="Допустимы режимы fake и rest")
    settings = _bitrix_settings(db)
    settings.enabled, settings.mode = enabled, mode
    settings.portal_url = portal_url.strip().rstrip("/") or None
    settings.webhook_url = webhook_url.strip().rstrip("/") or None
    settings.user_id = user_id.strip() or None
    if token.strip():
        settings.encrypted_token = token.strip()
    db.commit()
    return RedirectResponse("/settings/integrations?message=Настройки сохранены", status_code=303)


@app.post("/settings/integrations/bitrix24/check")
def check_bitrix_connection(db: Session = Depends(get_db)):
    settings = _bitrix_settings(db)
    if settings.mode == "fake":
        message = "Соединение успешно: используется локальный fake-режим"
    else:
        try:
            user = Bitrix24RestGateway(settings, db).check_connection()
            name = " ".join(filter(None, (user.get("NAME"), user.get("LAST_NAME"))))
            message = f"Соединение успешно: {name or user.get('ID', 'Bitrix24')}"
        except BitrixAPIError as exc:
            return RedirectResponse(
                f"/settings/integrations?error=Ошибка подключения: {exc}", status_code=303
            )
    return RedirectResponse(f"/settings/integrations?message={message}", status_code=303)


@app.post("/protocols/{protocol_id}/demo-publish")
def demo_publish(
    protocol_id: int, fail_key: str | None = Form(None), db: Session = Depends(get_db)
):
    run, errors = run_publication(db, db.get(Protocol, protocol_id), fail_key=fail_key)
    if not run:
        return RedirectResponse(f"/protocols/{protocol_id}/publication-plan", status_code=303)
    return RedirectResponse(f"/publication-runs/{run.id}", status_code=303)


@app.get("/publication-runs")
def publication_runs(
    request: Request,
    db: Session = Depends(get_db),
    status: str | None = None,
    protocol_id: int | None = None,
):
    stmt = select(PublicationRun).order_by(PublicationRun.started_at.desc())
    if status:
        stmt = stmt.where(PublicationRun.status == status)
    if protocol_id:
        stmt = stmt.where(PublicationRun.protocol_id == protocol_id)
    return templates.TemplateResponse(
        request,
        "publication_runs.html",
        {"runs": db.scalars(stmt).all(), "protocols": db.scalars(select(Protocol)).all()},
    )


@app.get("/publication-runs/{run_id}")
def publication_run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "publication_run.html", {"run": db.get(PublicationRun, run_id)}
    )


@app.post("/publication-runs/{run_id}/retry-failed")
def retry_failed(run_id: int, db: Session = Depends(get_db)):
    old = db.get(PublicationRun, run_id)
    run, _ = run_publication(db, old.protocol, retry_run=old)
    return RedirectResponse(f"/publication-runs/{run.id}", status_code=303)


@app.get("/protocol-tasks/{task_id}/edit")
def edit_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "task_edit.html",
        {
            "task": db.get(ProtocolTask, task_id),
            "employees": db.scalars(select(Employee).order_by(Employee.full_name)).all(),
            "lists": db.scalars(select(EmployeeList).order_by(EmployeeList.name)).all(),
            "sections": db.scalars(select(ProtocolSection)).all(),
            "status_labels": STATUS_LABELS,
        },
    )


@app.post("/protocol-tasks/{task_id}/edit")
def save_task(
    task_id: int,
    number: str = Form(...),
    section_id: int | None = Form(None),
    title: str = Form(...),
    description: str | None = Form(None),
    acceptance_criteria: str | None = Form(None),
    deadline: str | None = Form(None),
    priority: str | None = Form(None),
    create_as_subtasks: bool = Form(False),
    employee_ids: list[int] = Form([]),
    original_text: str | None = Form(None),
    db: Session = Depends(get_db),
):
    t = db.get(ProtocolTask, task_id)
    t.number = number
    t.section_id = section_id
    t.title = title
    t.description = description
    t.acceptance_criteria = acceptance_criteria
    t.deadline = deadline or None
    t.priority = priority
    t.create_as_subtasks = create_as_subtasks
    t.original_text = original_text
    for a in list(t.assignments):
        db.delete(a)
    db.flush()
    for i, eid in enumerate(employee_ids, 1):
        db.add(ProtocolTaskAssignment(protocol_task_id=t.id, employee_id=eid, sort_order=i))
    db.commit()
    return RedirectResponse(f"/protocols/{t.protocol_id}", status_code=303)


@app.get("/employees")
def employees(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    source: str | None = None,
    department: str | None = None,
):
    service = EmployeeDirectoryService(db)
    items = service.search(q, source, department)
    return templates.TemplateResponse(
        request,
        "employees.html",
        common_context(
            "Сотрудники",
            "Сотрудники",
            employees=items,
            q=q,
            source=source,
            department=department,
            sources=db.scalars(select(Employee.source_system).distinct()).all(),
            departments=db.scalars(
                select(Employee.department).where(Employee.department.is_not(None)).distinct()
            ).all(),
            message=request.query_params.get("message"),
        ),
    )


@app.get("/employees/new")
def new_employee(request: Request):
    return templates.TemplateResponse(
        request,
        "employee_form.html",
        common_context("Сотрудники", "Новый сотрудник", employee=None),
    )


@app.post("/employees")
def create_employee(
    full_name: str = Form(...),
    position: str = Form(""),
    department: str = Form(""),
    email: str = Form(""),
    bitrix_user_id: int | None = Form(None),
    source_system: str = Form("manual"),
    db: Session = Depends(get_db),
):
    employee = EmployeeDirectoryService(db).create(
        full_name=full_name.strip(),
        position=position.strip() or None,
        department=department.strip() or None,
        email=email.strip() or None,
        bitrix_user_id=bitrix_user_id,
        source_system=source_system.strip() or "manual",
    )
    return RedirectResponse(f"/employees/{employee.id}", status_code=303)


@app.get("/employees/{employee_id}")
def employee_card(employee_id: int, request: Request, db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return templates.TemplateResponse(
        request,
        "employee_card.html",
        common_context("Сотрудники", employee.full_name, employee=employee),
    )


@app.get("/employees/{employee_id}/edit")
def edit_employee(employee_id: int, request: Request, db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return templates.TemplateResponse(
        request,
        "employee_form.html",
        common_context("Сотрудники", "Редактирование", employee=employee),
    )


@app.post("/employees/{employee_id}")
def update_employee(
    employee_id: int,
    full_name: str = Form(...),
    position: str = Form(""),
    department: str = Form(""),
    email: str = Form(""),
    bitrix_user_id: int | None = Form(None),
    source_system: str = Form("manual"),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    EmployeeDirectoryService(db).update(
        employee,
        full_name=full_name.strip(),
        position=position.strip() or None,
        department=department.strip() or None,
        email=email.strip() or None,
        bitrix_user_id=bitrix_user_id,
        source_system=source_system.strip() or "manual",
    )
    return RedirectResponse(f"/employees/{employee.id}", status_code=303)


@app.post("/employees/{employee_id}/delete")
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    try:
        EmployeeDirectoryService(db).delete(employee)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Сотрудник используется в протоколах или списках"
        ) from exc
    return RedirectResponse("/employees?message=Сотрудник удалён", status_code=303)


@app.get("/employee-lists")
def employee_lists(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "participant_templates.html",
        common_context(
            "Шаблоны списков участников",
            "Шаблоны списков участников",
            templates=db.scalars(
                select(ParticipantGroupTemplate).order_by(ParticipantGroupTemplate.name)
            ).all(),
            employees=db.scalars(
                select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name)
            ).all(),
        ),
    )


@app.post("/employee-lists")
def create_participant_template(payload: dict = Body(...), db: Session = Depends(get_db)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название шаблона обязательно")
    template = ParticipantGroupTemplate(name=name)
    db.add(template)
    db.flush()
    seen = set()
    for value in payload.get("employee_ids", []):
        employee_id = int(value)
        employee = db.get(Employee, employee_id)
        if employee and employee_id not in seen:
            template.members.append(
                ParticipantGroupTemplateMember(
                    employee_id=employee.id, name_snapshot=employee.full_name
                )
            )
            seen.add(employee_id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Шаблон с таким названием уже существует"
        ) from exc
    return {"id": template.id, "name": template.name}


@app.delete("/employee-lists/{template_id}")
def delete_participant_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(ParticipantGroupTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    db.delete(template)
    db.commit()
    return {"deleted": True}


@app.put("/employee-lists/{template_id}")
def update_participant_template(
    template_id: int, payload: dict = Body(...), db: Session = Depends(get_db)
):
    """Edit the reusable source; protocol-local copies remain unchanged."""
    template = db.get(ParticipantGroupTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    name = str(payload.get("name", template.name)).strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название шаблона обязательно")
    template.name = name
    if "employee_ids" in payload:
        template.members.clear()
        db.flush()
        seen: set[int] = set()
        for value in payload.get("employee_ids") or []:
            employee = db.get(Employee, int(value))
            if employee and employee.id not in seen:
                template.members.append(
                    ParticipantGroupTemplateMember(
                        employee_id=employee.id, name_snapshot=employee.full_name
                    )
                )
                seen.add(employee.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Шаблон с таким названием уже существует"
        ) from exc
    return {"id": template.id, "name": template.name}


@app.post("/employee-lists/{template_id}/copy")
def copy_participant_template(
    template_id: int, payload: dict = Body(default={}), db: Session = Depends(get_db)
):
    source = db.get(ParticipantGroupTemplate, template_id)
    if not source:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    base_name = str(payload.get("name") or f"{source.name} — копия").strip()
    name, suffix = base_name, 2
    while db.scalar(
        select(ParticipantGroupTemplate.id).where(ParticipantGroupTemplate.name == name)
    ):
        name, suffix = f"{base_name} ({suffix})", suffix + 1
    duplicate = ParticipantGroupTemplate(name=name)
    duplicate.members = [
        ParticipantGroupTemplateMember(
            employee_id=member.employee_id, name_snapshot=member.name_snapshot
        )
        for member in source.members
    ]
    db.add(duplicate)
    db.commit()
    return {"id": duplicate.id, "name": duplicate.name}
