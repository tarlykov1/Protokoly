from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.domain import IntegrationLog, IntegrationSettings


class BitrixAPIError(RuntimeError):
    """A transport or application-level Bitrix24 REST failure."""


class TaskGateway(ABC):
    external_system = "BITRIX24"

    @abstractmethod
    def create_task(self, task_data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def get_task(self, task_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def get_user(self, name: str | None = None) -> dict[str, Any] | None: ...

    @abstractmethod
    def add_comment(self, task_id: str, comment: str) -> dict[str, Any]: ...

    def get_status(self, task_id: str) -> str | None:
        task = self.get_task(task_id)
        return str(task.get("status")) if task else None


class FakeBitrixGateway(TaskGateway):
    """Deterministic, network-free Bitrix24 implementation."""

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
        if str(task_id) not in self._tasks:
            raise KeyError(task_id)
        self._tasks[str(task_id)].update(data)
        return dict(self._tasks[str(task_id)])

    def get_user(self, name: str | None = None) -> dict[str, Any] | None:
        return None

    def add_comment(self, task_id: str, comment: str) -> dict[str, Any]:
        return {"id": f"COMMENT-{task_id}", "comment": comment}


FakeTaskGateway = FakeBitrixGateway


class Bitrix24RestGateway(TaskGateway):
    """Bitrix24 incoming-webhook REST adapter with persistent call auditing."""

    def __init__(
        self, settings: IntegrationSettings, db: Session, client: httpx.Client | None = None
    ):
        self.settings = settings
        self.db = db
        self.client = client or httpx.Client(timeout=15)

    def _base_url(self) -> str:
        if self.settings.webhook_url:
            return self.settings.webhook_url.rstrip("/")
        if self.settings.portal_url and self.settings.user_id and self.settings.encrypted_token:
            return "/".join(
                (
                    self.settings.portal_url.rstrip("/"),
                    "rest",
                    self.settings.user_id,
                    self.settings.encrypted_token.strip("/"),
                )
            )
        raise BitrixAPIError("Не заполнен URL вебхука Bitrix24")

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        log = IntegrationLog(operation=method, request=payload, status="pending")
        self.db.add(log)
        try:
            response = self.client.post(f"{self._base_url()}/{method}.json", json=payload)
            response.raise_for_status()
            body = response.json()
            if body.get("error"):
                raise BitrixAPIError(body.get("error_description") or body["error"])
            log.response = body
            log.status = "success"
            self.db.commit()
            return body.get("result")
        except Exception as exc:
            error = exc if isinstance(exc, BitrixAPIError) else BitrixAPIError(str(exc))
            log.response = {"error": str(error)}
            log.status = "error"
            self.db.commit()
            raise error from exc

    def check_connection(self) -> dict[str, Any]:
        result = self._call("user.current")
        return dict(result or {})

    def create_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        fields = {"TITLE": task_data["title"]}
        if task_data.get("responsible_id"):
            fields["RESPONSIBLE_ID"] = task_data["responsible_id"]
        if task_data.get("deadline"):
            fields["DEADLINE"] = task_data["deadline"]
        result = self._call("tasks.task.add", {"fields": fields}) or {}
        task = result.get("task", result)
        task_id = str(task.get("id") or task.get("ID"))
        return {
            "id": task_id,
            "url": f"{self.settings.portal_url.rstrip('/')}/company/personal/user/0/tasks/task/view/{task_id}/"
            if self.settings.portal_url
            else None,
            "status": task.get("status", "created"),
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        result = self._call("tasks.task.get", {"taskId": task_id}) or {}
        return result.get("task", result) or None

    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        result = self._call("tasks.task.update", {"taskId": task_id, "fields": data})
        return {"id": str(task_id), "result": result}

    def get_user(self, name: str | None = None) -> dict[str, Any] | None:
        if name is None:
            return self.check_connection()
        users = self._call("user.search", {"FILTER": {"NAME": name}}) or []
        return dict(users[0]) if users else None

    def add_comment(self, task_id: str, comment: str) -> dict[str, Any]:
        result = self._call(
            "task.commentitem.add", {"TASKID": task_id, "FIELDS": {"POST_MESSAGE": comment}}
        )
        return {"id": str(result)}


BitrixTaskGateway = Bitrix24RestGateway


def get_bitrix_gateway(db: Session) -> TaskGateway:
    settings = db.scalar(select(IntegrationSettings).where(IntegrationSettings.type == "bitrix24"))
    if not settings or not settings.enabled or settings.mode == "fake":
        return FakeBitrixGateway()
    if settings.mode == "rest":
        return Bitrix24RestGateway(settings, db)
    raise ValueError(f"Неизвестный режим интеграции: {settings.mode}")
