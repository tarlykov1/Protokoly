from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.domain import ImportSession, Project, Protocol
from app.db.session import get_db
from app.services.imports.service import (
    confirm_session,
    create_preview_session,
    reparse_session,
    update_session_payload,
)

app = FastAPI(title="Protocol Management System")
templates = Jinja2Templates(directory="app/web/templates")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
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
            "protocols": protocols,
        },
    )


@app.get("/projects")
def projects(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "projects.html",
        {"projects": db.scalars(select(Project).order_by(Project.name)).all()},
    )


@app.get("/projects/new")
def new_project(request: Request):
    return templates.TemplateResponse(request, "project_form.html")


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
def protocols(request: Request, db: Session = Depends(get_db), status: str | None = None):
    stmt = select(Protocol).order_by(Protocol.created_at.desc())
    if status:
        stmt = stmt.where(Protocol.status == status)
    return templates.TemplateResponse(
        request, "protocols.html", {"protocols": db.scalars(stmt).all(), "status": status}
    )


@app.get("/protocols/import")
def import_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "import_form.html",
        {"projects": db.scalars(select(Project).order_by(Project.name)).all()},
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
        {
            "session": session,
            "payload": session.parsed_payload if session else {},
            "filter": filter,
        },
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
        {"sessions": db.scalars(stmt).all(), "projects": db.scalars(select(Project)).all()},
    )
