import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.core.security import sanitize_payload
from app.db.models.domain import IntegrationLog, IntegrationSettings


class BitrixAPIError(RuntimeError):
    """A transport or application-level Bitrix24 REST failure."""


class BitrixRejectedError(BitrixAPIError):
    """Bitrix returned an explicit application error, so creation was rejected."""


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

    def find_task_by_key(self, key: str) -> dict[str, Any] | None:
        return None

    def get_status(self, task_id: str) -> str | None:
        task = self.get_task(task_id)
        return str(task.get("status")) if task else None

    def list_projects(self, query: str | None = None) -> list[dict[str, Any]]:
        return []


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

    def find_task_by_key(self, key: str) -> dict[str, Any] | None:
        matches = [task for task in self._tasks.values() if task.get("xml_id") == key]
        return dict(matches[0]) if len(matches) == 1 else None

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

    def list_projects(self, query: str | None = None) -> list[dict[str, Any]]:
        projects = [{"id": "10", "name": "Тестовый проект"}]
        return [p for p in projects if not query or query.lower() in p["name"].lower()]


FakeTaskGateway = FakeBitrixGateway


class Bitrix24RestGateway(TaskGateway):
    """Bitrix24 incoming-webhook REST adapter with persistent call auditing."""

    def __init__(
        self, settings: IntegrationSettings, db: Session, client: httpx.Client | None = None
    ):
        self.settings = settings
        self.db = db
        self.client = client or httpx.Client(
            timeout=15, limits=httpx.Limits(max_connections=5, max_keepalive_connections=2)
        )
        if client is None:
            db.info.setdefault("owned_http_clients", []).append(self.client)

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

    def _call(self, method, payload=None, *, full_response=False):
        from app.core.config import get_settings
        from app.core.locks import OperationBusy, operation_lock
        for _ in range(100):
            for slot in range(get_settings().bitrix_parallel_requests):
                lock = operation_lock(self.db, f"bitrix-rest-slot:{slot}")
                try:
                    lock.__enter__()
                except OperationBusy:
                    continue
                try:
                    return self._call_unlocked(method, payload, full_response=full_response)
                finally:
                    lock.__exit__(None, None, None)
            time.sleep(0.1)
        raise BitrixAPIError("Лимит параллельных запросов Битрикс24. Повторите позже")

    def _call_unlocked(
        self, method: str, payload: dict[str, Any] | None = None, *, full_response: bool = False
    ) -> Any:
        payload = payload or {}
        log = IntegrationLog(
            operation=method,
            request=sanitize_payload(payload),
            status="pending",
            request_id=get_request_id(),
        )
        self.db.add(log)
        # Never blindly retry writes: a timeout can arrive after Bitrix committed.
        read_methods = {
            "user.current",
            "user.get",
            "user.search",
            "sonet_group.get",
            "tasks.task.get",
        }
        max_attempts = 3 if method in read_methods else 1
        for attempt in range(1, max_attempts + 1):
            log.attempts = attempt
            cause = None
            try:
                response = self.client.post(f"{self._base_url()}/{method}.json", json=payload)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise BitrixAPIError("Некорректный ответ Bitrix24")
                if body.get("error"):
                    raise BitrixRejectedError(body.get("error_description") or body["error"])
                log.response = sanitize_payload(body)
                log.status = "success"
                return body if full_response else body.get("result")
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                cause = exc
                retryable, error = True, BitrixAPIError("Bitrix24 временно недоступен")
            except httpx.HTTPStatusError as exc:
                cause = exc
                retryable = exc.response.status_code in {429, 502, 503, 504}
                error = BitrixAPIError(f"Bitrix24 вернул HTTP {exc.response.status_code}")
            except ValueError as exc:
                cause = exc
                retryable, error = False, BitrixAPIError("Некорректный JSON в ответе Bitrix24")
            except BitrixAPIError as exc:
                cause = exc
                retryable, error = False, exc
            if retryable and attempt < max_attempts:
                time.sleep((0.5, 1.0, 2.0)[attempt - 1])
            else:
                log.response = sanitize_payload({"error": str(error)})
                log.status = "error"
                raise error from cause

    def check_connection(self) -> dict[str, Any]:
        result = self._call("user.current")
        return dict(result or {})

    def _list_all(self, method: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = dict(payload or {})
        items = []
        seen = set()
        while True:
            body = self._call(method, payload, full_response=True)
            page = body.get("result") or []
            if not isinstance(page, list):
                raise BitrixAPIError("Некорректный список в ответе Bitrix24")
            items.extend(dict(item) for item in page)
            next_start = body.get("next")
            if next_start is None:
                return items
            if str(next_start) in seen or len(seen) >= 10000:
                raise BitrixAPIError("Bitrix24 повторяет страницу списка")
            seen.add(str(next_start))
            payload["start"] = next_start

    def list_users(self) -> list[dict[str, Any]]:
        return self._list_all("user.get")

    def list_projects(self, query: str | None = None) -> list[dict[str, Any]]:
        payload = {"FILTER": {"%NAME": query}} if query else {}
        result = self._list_all("sonet_group.get", payload)
        return [
            {"id": str(item.get("ID") or item.get("id")), "name": item.get("NAME") or ""}
            for item in result
        ]

    def create_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "title": "TITLE",
            "description": "DESCRIPTION",
            "responsible_id": "RESPONSIBLE_ID",
            "created_by": "CREATED_BY",
            "deadline": "DEADLINE",
            "group_id": "GROUP_ID",
            "accomplices": "ACCOMPLICES",
            "auditors": "AUDITORS",
            "parent_id": "PARENT_ID",
            "xml_id": "XML_ID",
        }
        fields = {
            target: task_data[source]
            for source, target in mapping.items()
            if task_data.get(source) not in (None, "", [])
        }
        fields.update(
            {
                key: value
                for key, value in task_data.get("custom_fields", {}).items()
                if key.startswith("UF_")
            }
        )
        result = self._call("tasks.task.add", {"fields": fields}) or {}
        task = result.get("task", result)
        task_id = task.get("id") or task.get("ID")
        if not task_id:
            raise BitrixAPIError(
                "Bitrix24 не вернул ID созданной задачи; проверьте портал перед повтором"
            )
        task_id = str(task_id)
        return {
            "id": task_id,
            "url": f"{self.settings.portal_url.rstrip('/')}/company/personal/user/0/tasks/task/view/{task_id}/"
            if self.settings.portal_url
            else None,
            "status": task.get("status", "created"),
        }

    def find_task_by_key(self, key: str) -> dict[str, Any] | None:
        result = self._call("tasks.task.list", {"filter": {"=XML_ID": key}, "select": ["ID", "XML_ID", "STATUS"]}) or {}
        matches = [task for task in result.get("tasks", []) if task.get("xmlId", task.get("XML_ID")) == key]
        if len(matches) != 1:
            return None
        task = matches[0]
        return {"id": str(task.get("id") or task["ID"]), "status": task.get("status")}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        result = self._call("tasks.task.get", {"taskId": task_id}) or {}
        task = result.get("task", result) or None
        if not task:
            return None
        normalized = {str(key).lower(): value for key, value in task.items()}
        normalized["id"] = str(normalized.get("id", task_id))
        return normalized

    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "title": "TITLE",
            "description": "DESCRIPTION",
            "responsible_id": "RESPONSIBLE_ID",
            "created_by": "CREATED_BY",
            "deadline": "DEADLINE",
            "group_id": "GROUP_ID",
            "accomplices": "ACCOMPLICES",
            "auditors": "AUDITORS",
            "parent_id": "PARENT_ID",
            "xml_id": "XML_ID",
        }
        fields = {mapping[key]: value for key, value in data.items() if key in mapping}
        fields.update(
            {
                key: value
                for key, value in data.get("custom_fields", {}).items()
                if key.startswith("UF_")
            }
        )
        result = self._call("tasks.task.update", {"taskId": task_id, "fields": fields})
        return {"id": str(task_id), "result": result}

    def get_user(self, name: str | None = None) -> dict[str, Any] | None:
        if name is None:
            return self.check_connection()
        users = self._call("user.search", {"FILTER": {"NAME": name}}) or []
        return dict(users[0]) if len(users) == 1 else None

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
