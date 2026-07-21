from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.domain import ImportSession, Project, Protocol, ProtocolTask
from app.db.session import get_db
from app.services.imports.service import (
    confirm_session,
    create_preview_session,
    reparse_session,
    update_session_payload,
)

app = FastAPI(title="Protocol Management System")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
templates = Jinja2Templates(directory="app/web/templates")


def readiness_percent(protocol):
    tasks = list(getattr(protocol, "tasks", []) or [])
    if not tasks:
        return 0
    ready = 0
    for task in tasks:
        score = 0
        score += 1 if task.title else 0
        score += 1 if task.assignments else 0
        score += 1 if task.deadline else 0
        score += 1 if task.status in {"ready", "validated", "done"} or protocol.status == "ready" else 0
        score += 1 if protocol.status not in {"validation_required", "error"} else 0
        ready += score / 5
    return int(100 * ready / len(tasks))


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
def ready():
    return {"status": "ready"}


@app.get("/")
def home_redirect():
    return RedirectResponse("/dashboard", status_code=307)


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
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
        },
    )


@app.get("/projects")
def projects(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "projects.html",
        common_context("Проекты", "Проекты", projects=db.scalars(select(Project).order_by(Project.name)).all()),
    )


@app.get("/projects/new")
def new_project(request: Request):
    return templates.TemplateResponse(request, "project_form.html", common_context("Проекты", "Новый проект"))


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
        common_context("Проекты", "Проекты", projects=db.scalars(select(Project).order_by(Project.name)).all()),
    )


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
        common_context("Импорт", "Предпросмотр", session=session, payload=session.parsed_payload if session else {}, filter=filter),
    )


@app.post("/protocols/import/{session_id}/update")
def import_session_update(session_id: int, payload: str = Form(...), db: Session = Depends(get_db)):
    session = db.get(ImportSession, session_id)
    update_session_payload(db, session, payload)
    return RedirectResponse(f"/protocols/import/{session_id}/preview", status_code=303)


@app.post("/protocols/import/{session_id}/reparse")
def import_session_reparse(
    session_id: int,
    parser_type: str = Form("universal"),
    confirm_replace: bool = Form(False),
    db: Session = Depends(get_db),
):
    session = db.get(ImportSession, session_id)
    reparse_session(db, session, parser_type, confirm_replace)
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
        common_context("Импорт", "Журнал импорта", sessions=db.scalars(stmt).all(), projects=db.scalars(select(Project)).all()),
    )


from fastapi.responses import FileResponse

from app.cli.generate_demo_docx import generate as generate_demo_docx
from app.cli.reset_demo import reset as reset_demo_data
from app.cli.seed_demo import seed as seed_demo_data
from app.core.config import get_settings
from app.db.models.domain import (
    Employee,
    EmployeeList,
    ProtocolSection,
    ProtocolTaskAssignment,
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
    return templates.TemplateResponse(request, "demo.html", ctx | {"message": request.query_params.get("message")})


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
    runs = db.scalars(select(PublicationRun).order_by(PublicationRun.started_at.desc()).limit(1)).all()
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
            "ready_count": db.scalar(select(func.count()).select_from(ProtocolTask).where(ProtocolTask.deadline.is_not(None))) or 0,
            "review_count": db.scalar(select(func.count()).select_from(ProtocolTask).where(ProtocolTask.deadline.is_(None))) or 0,
            "publication_count": db.scalar(select(func.count()).select_from(PublicationRun)) or 0,
            "imports": db.scalars(select(ImportSession).order_by(ImportSession.created_at.desc()).limit(5)).all(),
            "problem_tasks": db.scalars(select(ProtocolTask).where(ProtocolTask.deadline.is_(None)).limit(5)).all(),
            **demo_context(db),
        },
    )


@app.get("/protocols/{protocol_id}")
def protocol_card(protocol_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Protocol, protocol_id)
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
    rows = []
    errors = warnings = without_assignee = without_deadline = 0
    for t in p.tasks:
        e, w = validate_task(t)
        errors += len(e)
        warnings += len(w)
        without_assignee += 0 if t.assignments else 1
        without_deadline += 0 if t.deadline else 1
        rows.append((t, e, w, assessments.get(t.id)))
    progress = int(
        100
        * sum(1 for t, _, _, _ in rows if t.assignments and t.deadline and t.title)
        / max(len(rows), 1)
    )
    return templates.TemplateResponse(
        request,
        "protocol_card.html",
        {
            "protocol": p,
            "sections": sections,
            "rows": rows,
            "progress": progress,
            "errors": errors,
            "warnings": warnings,
            "without_assignee": without_assignee,
            "without_deadline": without_deadline,
        },
    )


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
    rows, errors, warnings = protocol_plan(db, p)
    return templates.TemplateResponse(
        request,
        "publication_plan.html",
        {
            "protocol": p,
            "rows": rows,
            "errors": errors,
            "warnings": warnings,
            "demo_mode": get_settings().demo_mode,
        },
    )


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
def employees(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "simple_list.html",
        {
            "title": "Сотрудники",
            "items": [
                e.full_name for e in db.scalars(select(Employee).order_by(Employee.full_name)).all()
            ],
        },
    )


@app.get("/employee-lists")
def employee_lists(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "simple_list.html",
        {
            "title": "Списки сотрудников",
            "items": [
                employee_list.name for employee_list in db.scalars(select(EmployeeList).order_by(EmployeeList.name)).all()
            ],
        },
    )
