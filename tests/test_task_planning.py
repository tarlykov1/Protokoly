import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from app.db.models.domain import Employee, Project, ProtocolTask, ProtocolTaskAssignment
from app.services.task_planning.planner import TaskPlanningService


def employee(employee_id: int, name: str, bitrix_id: int | None):
    return Employee(id=employee_id, full_name=name, bitrix_user_id=bitrix_id)


def task(*assignments, create_as_subtasks=False):
    item = ProtocolTask(id=10, protocol_id=1, number="02", title="Prepare decision", create_as_subtasks=create_as_subtasks, status="draft")
    item.assignments = list(assignments)
    item.bitrix_links = []
    return item


def assignment(assignment_id: int, emp: Employee, order: int = 0):
    return ProtocolTaskAssignment(id=assignment_id, employee_id=emp.id, employee=emp, sort_order=order)


def project(technical_user_id=900):
    return Project(id=1, name="Demo", code="DEMO", bitrix_group_id=100, technical_user_id=technical_user_id)


def test_independent_task_numbering():
    plan = TaskPlanningService().build_plan(project(), task(assignment(1, employee(1, "Ivanov I.I.", 11)), assignment(2, employee(2, "Petrov P.P.", 12))))
    assert plan.can_create
    assert [item.number for item in plan.tasks] == ["02/01", "02/02"]
    assert plan.independent_count == 2


def test_subtask_numbering_and_root():
    plan = TaskPlanningService().build_plan(project(), task(assignment(1, employee(1, "Ivanov I.I.", 11)), create_as_subtasks=True))
    assert [item.task_type for item in plan.tasks] == ["root", "subtask"]
    assert [item.number for item in plan.tasks] == ["02", "02/01"]


def test_duplicate_assignees_are_skipped_with_warning():
    emp = employee(1, "Ivanov I.I.", 11)
    plan = TaskPlanningService().build_plan(project(), task(assignment(1, emp), assignment(2, emp)))
    assert plan.independent_count == 1
    assert plan.warnings[0].code == "duplicate_employee"


def test_missing_technical_user_blocks_subtask_mode():
    plan = TaskPlanningService().build_plan(project(technical_user_id=None), task(assignment(1, employee(1, "Ivanov I.I.", 11)), create_as_subtasks=True))
    assert not plan.can_create
    assert {error.code for error in plan.errors} == {"technical_user_required"}


def test_missing_bitrix_id_is_blocking_error():
    plan = TaskPlanningService().build_plan(project(), task(assignment(1, employee(1, "Ivanov I.I.", None))))
    assert not plan.can_create
    assert "employee_bitrix_id_required" in {error.code for error in plan.errors}
