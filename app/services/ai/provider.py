from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True)
class TaskAssessmentRequest:
    title: str
    description: str | None = None
    acceptance_criteria: str | None = None
    deadline: str | None = None
    assignees: tuple[str, ...] = ()
    direction: str | None = None
    block: str | None = None
    protocol_type: str | None = None
    anonymized_context: str | None = None


@dataclass(frozen=True)
class TaskAssessmentResult:
    provider: str
    model: str
    prompt_version: str
    overall_score: int | None
    summary: str
    suggested_title: str | None = None
    suggested_description: str | None = None
    suggested_acceptance_criteria: str | None = None


class TaskAssessmentProvider(Protocol):
    async def assess(self, request: TaskAssessmentRequest) -> TaskAssessmentResult: ...


class DisabledAssessmentProvider:
    async def assess(self, request: TaskAssessmentRequest) -> TaskAssessmentResult:
        return TaskAssessmentResult("disabled", "", "0", None, "AI assessment is disabled.")


def apply_assessment_suggestion(request: TaskAssessmentRequest, result: TaskAssessmentResult, *, confirm: bool) -> TaskAssessmentRequest:
    if not confirm:
        return request
    return replace(
        request,
        title=result.suggested_title or request.title,
        description=result.suggested_description or request.description,
        acceptance_criteria=result.suggested_acceptance_criteria or request.acceptance_criteria,
    )
