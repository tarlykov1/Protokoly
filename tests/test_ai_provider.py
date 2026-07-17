from app.services.ai.provider import (
    TaskAssessmentRequest,
    TaskAssessmentResult,
    apply_assessment_suggestion,
)


def test_ai_suggestion_is_not_applied_without_explicit_confirmation():
    request = TaskAssessmentRequest(title="Old", acceptance_criteria=None)
    result = TaskAssessmentResult("rule_based", "rules", "1", 80, "ok", suggested_title="New", suggested_acceptance_criteria="Done")
    assert apply_assessment_suggestion(request, result, confirm=False) == request
    assert apply_assessment_suggestion(request, result, confirm=True).title == "New"
