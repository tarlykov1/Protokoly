from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class PlanningIssue:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class PlannedTask:
    number: str
    title: str
    responsible_id: int | None
    responsible_name: str
    deadline: date | None
    task_type: str
    external_key: str
    parent_external_key: str | None = None


@dataclass
class TaskCreationPlan:
    tasks: list[PlannedTask] = field(default_factory=list)
    errors: list[PlanningIssue] = field(default_factory=list)
    warnings: list[PlanningIssue] = field(default_factory=list)

    @property
    def root_count(self) -> int:
        return sum(task.task_type == "root" for task in self.tasks)

    @property
    def independent_count(self) -> int:
        return sum(task.task_type == "independent" for task in self.tasks)

    @property
    def subtask_count(self) -> int:
        return sum(task.task_type == "subtask" for task in self.tasks)

    @property
    def can_create(self) -> bool:
        return not self.errors
