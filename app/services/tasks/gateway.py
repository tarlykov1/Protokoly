from abc import ABC, abstractmethod
from typing import Any


class TaskGateway(ABC):
    """External task provider contract used by publication."""

    external_system = "BITRIX24"

    @abstractmethod
    def create_task(self, task_data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def get_task(self, task_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def get_status(self, task_id: str) -> str | None: ...


class FakeTaskGateway(TaskGateway):
    """Small deterministic gateway for local runs and tests; performs no network calls."""

    def __init__(self, start_at: int = 10001) -> None:
        self._next_id = start_at
        self._tasks: dict[str, dict[str, Any]] = {}

    def create_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        task_id = f"TASK-{self._next_id}"
        self._next_id += 1
        task = {
            **task_data,
            "id": task_id,
            "url": f"https://fake.tasks.local/{task_id}",
            "status": "created",
        }
        self._tasks[task_id] = task
        return dict(task)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self._tasks.get(str(task_id))
        return dict(task) if task else None

    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        task = self._tasks.get(str(task_id))
        if task is None:
            raise KeyError(task_id)
        task.update(data)
        return dict(task)

    def get_status(self, task_id: str) -> str | None:
        task = self._tasks.get(str(task_id))
        return str(task["status"]) if task else None


class BitrixTaskGateway(TaskGateway):
    """Bitrix24 adapter seam. REST transport will be supplied in a later release."""

    def _not_implemented(self):
        raise NotImplementedError("Bitrix24 REST integration is not configured")

    def create_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        return self._not_implemented()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._not_implemented()

    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._not_implemented()

    def get_status(self, task_id: str) -> str | None:
        return self._not_implemented()
