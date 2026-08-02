"""Provider boundary for synchronising task execution results with Bitrix24."""

from abc import ABC, abstractmethod


class BitrixTaskStatusGateway(ABC):
    @abstractmethod
    def get_task_status(self, task_id: str) -> str | None: ...

    @abstractmethod
    def get_task_result(self, task_id: str) -> str | None: ...

    @abstractmethod
    def update_task_comment(self, task_id: str, comment: str) -> None: ...


class FakeBitrixTaskStatusGateway(BitrixTaskStatusGateway):
    """In-memory implementation used until the Bitrix24 REST adapter is connected."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, str | None]] = {}

    def get_task_status(self, task_id: str) -> str | None:
        return self.tasks.get(str(task_id), {}).get("status")

    def get_task_result(self, task_id: str) -> str | None:
        return self.tasks.get(str(task_id), {}).get("result")

    def update_task_comment(self, task_id: str, comment: str) -> None:
        self.tasks.setdefault(str(task_id), {})["comment"] = comment
