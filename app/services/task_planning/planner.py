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
        seen: set[tuple[str, int | str]] = set()
        for assignment in sorted(task.assignments, key=lambda item: item.sort_order):
            if assignment.employee is None or assignment.employee_id is None:
                raw_name = (assignment.individual_title or "").strip()
                if not raw_name:
                    plan.errors.append(PlanningIssue("employee_required", "Assignment must identify an assignee."))
                    continue
                key = ("raw", raw_name.casefold())
                if key in seen:
                    continue
                seen.add(key)
                plan.warnings.append(self._unmatched_warning(raw_name, "Сотрудник не найден"))
                unique.append(assignment)
                continue
            key = ("employee", assignment.employee_id)
            if key in seen:
                plan.warnings.append(PlanningIssue("duplicate_employee", f"Duplicate employee skipped: {assignment.employee.full_name}.", False))
                continue
            seen.add(key)
            if not assignment.employee.bitrix_user_id:
                plan.warnings.append(
                    self._unmatched_warning(assignment.employee.full_name, "У сотрудника отсутствует bitrix_id")
                )
            unique.append(assignment)
        if not unique:
            plan.errors.append(PlanningIssue("assignments_required", "At least one assignee is required."))
        return unique

    def _assignment_task(self, task, assignment, index: int, task_type: str, parent_key: str | None) -> PlannedTask:
        number = f"{task.number}/{index:02d}"
        employee = assignment.employee
        original_assignee = employee.full_name if employee else (assignment.individual_title or "").strip()
        responsible_id = employee.bitrix_user_id if employee else None
        match_result = "matched" if employee else "not_found"
        missing_reason = None
        if employee and not responsible_id:
            match_result = "matched_without_bitrix_id"
            missing_reason = "У сотрудника отсутствует bitrix_id"
        elif not employee:
            missing_reason = "Сотрудник не найден"
        return PlannedTask(
            number=number,
            title=task.title if not employee else (assignment.individual_title or task.title),
            responsible_id=responsible_id,
            responsible_name=original_assignee,
            deadline=assignment.individual_deadline or task.deadline,
            task_type=task_type,
            external_key=f"protocol-task:{task.id}:assignment:{assignment.id}:{task_type}",
            parent_external_key=parent_key,
            original_assignee=original_assignee,
            assignee_match_result=match_result,
            missing_bitrix_id_reason=missing_reason,
            assignee_raw=original_assignee if responsible_id is None else None,
        )

    @staticmethod
    def _unmatched_warning(name: str, reason: str) -> PlanningIssue:
        return PlanningIssue(
            "assignee_not_mapped",
            "Исполнитель не сопоставлен с пользователем Битрикс24, "
            f"будет создана задача без назначения: {name} ({reason}).",
            False,
        )
