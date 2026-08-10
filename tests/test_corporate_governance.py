from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import Project, Protocol, ProtocolTask, ProtocolTaskControl
from app.services.auth import CurrentUser, Permission, Role
from app.services.protocols.governance import (
    dashboard_metrics,
    record_event,
    register_document,
    transition,
)


def database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def protocol(db: Session) -> Protocol:
    project = Project(name="Corporate", code="CORP")
    db.add(project)
    db.flush()
    item = Protocol(project_id=project.id, title="Совещание")
    db.add(item)
    db.flush()
    return item


def test_role_permissions_cover_all_operations():
    admin = CurrentUser("admin", Role.ADMIN)
    assert all(admin.can(permission) for permission in Permission)
    assert CurrentUser("author", Role.AUTHOR).can(Permission.CREATE)
    assert not CurrentUser("observer", Role.OBSERVER).can(Permission.EDIT)


def test_workflow_enforces_transition_permission_and_records_history():
    with database() as db:
        item = protocol(db)
        transition(db, item, "submit_review", CurrentUser("editor", Role.EDITOR))
        transition(db, item, "approve", CurrentUser("boss", Role.APPROVER))
        assert item.status == "approved"
        assert [event.event_type for event in item.history] == ["status_changed", "status_changed"]


def test_history_and_document_versions_are_sequential():
    with database() as db:
        item = protocol(db)
        record_event(db, item, "protocol_created", "author")
        assert register_document(db, item, "author").version == 1
        db.flush()
        assert register_document(db, item, "editor").version == 2
        assert item.history[0].details == {}


def test_dashboard_reports_status_execution_and_overdue_tasks():
    with database() as db:
        item = protocol(db)
        first = ProtocolTask(protocol_id=item.id, number="1", title="Готово")
        second = ProtocolTask(
            protocol_id=item.id,
            number="2",
            title="Просрочено",
            deadline=date.today() - timedelta(days=1),
        )
        db.add_all([first, second])
        db.flush()
        db.add(ProtocolTaskControl(protocol_task_id=first.id, status="completed"))
        db.flush()
        metrics = dashboard_metrics(db)
        assert metrics == {
            "statuses": {"draft": 1},
            "task_count": 2,
            "completion_percent": 50,
            "overdue_count": 1,
        }
