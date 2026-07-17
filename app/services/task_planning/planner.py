from app.db.models.domain import Project, ProtocolTask
from app.services.task_planning.models import PlannedTask, PlanningIssue, TaskCreationPlan


class TaskPlanningService:
    def build_plan(self, project: Project | None, protocol_task: ProtocolTask) -> TaskCreationPlan:
        plan = TaskCreationPlan()
        self._validate_project(project, protocol_task, plan)
        assignments = self._unique_assignments(protocol_task, plan)
        if not protocol_task.title.strip():
            plan.errors.append(PlanningIssue("task_title_required", "Task title is required."))
        if protocol_task.bitrix_links:
            plan.errors.append(PlanningIssue("already_created", "Bitrix tasks were already created."))
        if plan.errors:
            return plan
        assert project is not None
        if protocol_task.create_as_subtasks:
            root_key = f"protocol-task:{protocol_task.id}:root"
            plan.tasks.append(PlannedTask(protocol_task.number, protocol_task.title, project.technical_user_id, "Technical user", protocol_task.deadline, "root", root_key))
            for index, assignment in enumerate(assignments, start=1):
                plan.tasks.append(self._assignment_task(protocol_task, assignment, index, "subtask", root_key))
        else:
            for index, assignment in enumerate(assignments, start=1):
                plan.tasks.append(self._assignment_task(protocol_task, assignment, index, "independent", None))
        return plan

    def _validate_project(self, project: Project | None, task: ProtocolTask, plan: TaskCreationPlan) -> None:
        if project is None:
            plan.errors.append(PlanningIssue("project_required", "Project is required."))
            return
        if not project.bitrix_group_id:
            plan.errors.append(PlanningIssue("bitrix_group_required", "Project Bitrix group ID is required."))
        if task.create_as_subtasks and not project.technical_user_id:
            plan.errors.append(PlanningIssue("technical_user_required", "Technical user is required for subtasks mode."))

    def _unique_assignments(self, task: ProtocolTask, plan: TaskCreationPlan):
        unique = []
        seen: set[int] = set()
        for assignment in sorted(task.assignments, key=lambda item: item.sort_order):
            if assignment.employee is None or assignment.employee_id is None:
                plan.errors.append(PlanningIssue("employee_required", "Assignment must reference an employee."))
                continue
            if assignment.employee_id in seen:
                plan.warnings.append(PlanningIssue("duplicate_employee", f"Duplicate employee skipped: {assignment.employee.full_name}.", False))
                continue
            seen.add(assignment.employee_id)
            if not assignment.employee.bitrix_user_id:
                plan.errors.append(PlanningIssue("employee_bitrix_id_required", f"Employee has no Bitrix ID: {assignment.employee.full_name}."))
            unique.append(assignment)
        if not unique:
            plan.errors.append(PlanningIssue("assignments_required", "At least one assignee is required."))
        return unique

    def _assignment_task(self, task, assignment, index: int, task_type: str, parent_key: str | None) -> PlannedTask:
        number = f"{task.number}/{index:02d}"
        return PlannedTask(
            number=number,
            title=assignment.individual_title or task.title,
            responsible_id=assignment.employee.bitrix_user_id,
            responsible_name=assignment.employee.full_name,
            deadline=assignment.individual_deadline or task.deadline,
            task_type=task_type,
            external_key=f"protocol-task:{task.id}:assignment:{assignment.id}:{task_type}",
            parent_external_key=parent_key,
        )
