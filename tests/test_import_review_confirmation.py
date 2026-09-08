from pathlib import Path


def test_imperfect_docx_import_is_deferred_to_editor_validation():
    package_init = Path("app/services/imports/__init__.py").read_text(encoding="utf-8")

    assert "review-first" in package_init
    assert "review_payload[\"errors\"] = []" in package_init
    assert "_SENTINEL_ASSIGNEE" in package_init
    assert "db.delete(assignment)" in package_init
    assert "session.errors_payload = original_errors" in package_init


def test_only_zero_recognised_tasks_remains_a_hard_import_gate():
    service = Path("app/services/imports/service.py").read_text(encoding="utf-8")
    package_init = Path("app/services/imports/__init__.py").read_text(encoding="utf-8")

    assert "не распознано ни одного поручения" in service
    assert 'if not payload.get("tasks")' in package_init
    assert "return _original_confirm_session(db, session)" in package_init
