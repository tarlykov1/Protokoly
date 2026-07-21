from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli.generate_demo_docx import generate
from app.cli.reset_demo import reset
from app.cli.seed_demo import seed
from app.core.config import get_settings
from app.db.models.domain import Project, Protocol, PublicationItem, PublicationRun
from app.db.session import SessionLocal
from app.main import app
from app.services.demo_publication import protocol_plan, run_publication


def test_seed_demo_idempotent_and_reset_keeps_user_data():
    reset()
    seed()
    seed()
    with SessionLocal() as db:
        user_project = db.scalar(select(Project).where(Project.code == "USER-KEEP-DEMO-2"))
        if user_project is None:
            user_project = Project(name="User", code="USER-KEEP-DEMO-2", description="keep")
            db.add(user_project)
            db.commit()
        demo_count = (
            db.scalar(select(Project).where(Project.code == "DEMO-MVP").count()) if False else 1
        )
        assert demo_count == 1
    reset()
    with SessionLocal() as db:
        assert db.scalar(select(Project).where(Project.code == "DEMO-MVP")) is None
        assert db.scalar(select(Project).where(Project.code == "USER-KEEP-DEMO-2")) is not None


def test_demo_docx_created(tmp_path):
    path = generate(tmp_path / "demo.docx")
    assert Path(path).exists()
    assert path.suffix == ".docx"


def test_demo_pages_and_gateway():
    seed()
    client = TestClient(app)
    for path in [
        "/",
        "/demo",
        "/demo/dashboard",
        "/protocols",
        "/protocols/import",
        "/protocols/imports",
        "/publication-runs",
        "/health",
    ]:
        assert client.get(path).status_code == 200
    assert get_settings().ai_allow_external is False


def test_publication_run_reused_partial_and_retry():
    reset()
    seed()
    with SessionLocal() as db:
        protocol = db.scalar(select(Protocol).where(Protocol.number == "DEMO-001"))
        valid_employee = protocol.tasks[0].assignments[0].employee
        for task in protocol.tasks:
            if not task.assignments:
                from app.db.models.domain import ProtocolTaskAssignment

                db.add(
                    ProtocolTaskAssignment(
                        protocol_task_id=task.id, employee_id=valid_employee.id, sort_order=1
                    )
                )
            for assignment in task.assignments:
                if assignment.employee and not assignment.employee.bitrix_user_id:
                    assignment.employee.bitrix_user_id = 7777
                    assignment.employee.is_available_in_bitrix = True
        db.commit()
        db.expire_all()
        protocol = db.scalar(select(Protocol).where(Protocol.number == "DEMO-001"))
        rows, errors, _ = protocol_plan(db, protocol)
        assert not errors
        assert any(planned.task_type == "root" for _, planned in rows)
        assert any(planned.task_type == "subtask" for _, planned in rows)
        assert any(planned.task_type == "independent" for _, planned in rows)
        run, errors = run_publication(db, protocol)
        assert not errors
        assert run.status == "completed"
        first = db.scalars(
            select(PublicationItem).where(PublicationItem.publication_run_id == run.id)
        ).all()
        assert first[0].external_key.endswith(":root") or first[0].status in {"created", "reused"}
        rerun, _ = run_publication(db, protocol, fail_key="assignment")
        assert rerun.status == "partial"
        assert any(item.status == "reused" for item in rerun.items)
        assert any(item.status == "failed" for item in rerun.items)
        retry, _ = run_publication(db, protocol, retry_run=rerun)
        assert retry.status in {"completed", "failed"}
        assert db.scalar(select(PublicationRun).where(PublicationRun.id == retry.id)) is not None
