from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.domain import Project, Protocol
from app.db.session import get_db

app = FastAPI(title="Protocol Management System")
templates = Jinja2Templates(directory="app/web/templates")


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    draft_count = db.scalar(select(func.count()).select_from(Protocol).where(Protocol.status == "draft")) or 0
    ready_count = db.scalar(select(func.count()).select_from(Protocol).where(Protocol.status == "ready")) or 0
    error_count = db.scalar(select(func.count()).select_from(Protocol).where(Protocol.status == "validation_required")) or 0
    protocols = db.scalars(select(Protocol).order_by(Protocol.created_at.desc()).limit(5)).all()
    return templates.TemplateResponse("home.html", {"request": request, "draft_count": draft_count, "ready_count": ready_count, "error_count": error_count, "protocols": protocols})


@app.get("/projects")
def projects(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("projects.html", {"request": request, "projects": db.scalars(select(Project).order_by(Project.name)).all()})


@app.get("/projects/new")
def new_project(request: Request):
    return templates.TemplateResponse("project_form.html", {"request": request})


@app.post("/projects")
def create_project(name: str = Form(...), code: str = Form(...), bitrix_group_id: int | None = Form(None), db: Session = Depends(get_db)):
    db.add(Project(name=name, code=code, bitrix_group_id=bitrix_group_id))
    db.commit()
    return RedirectResponse("/projects", status_code=303)


@app.get("/protocols")
def protocols(request: Request, db: Session = Depends(get_db), status: str | None = None):
    stmt = select(Protocol).order_by(Protocol.created_at.desc())
    if status:
        stmt = stmt.where(Protocol.status == status)
    return templates.TemplateResponse("protocols.html", {"request": request, "protocols": db.scalars(stmt).all(), "status": status})
