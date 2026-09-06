from pathlib import Path


def test_shared_ui_statuses_are_localized():
    ui = Path("app/web/templates/components/ui.html").read_text(encoding="utf-8")
    for token, label in {
        "pending": "Ожидает выполнения",
        "in_progress": "В работе",
        "waiting_control": "Ожидает контроля",
        "overdue": "Просрочено",
        "rejected": "Возвращено на доработку",
        "validation_required": "Требует проверки",
        "needs_review": "Требует проверки",
        "in_person": "Очно",
        "hybrid": "Смешанный",
    }.items():
        assert f"'{token}':'{label}'" in ui

    assert "human_label(t.status)" in ui
    assert "else t.status" not in ui


def test_global_ui_localizer_covers_technical_values():
    js = Path("app/web/static/js/app.js").read_text(encoding="utf-8")
    for token in (
        "pending",
        "in_progress",
        "waiting_control",
        "overdue",
        "rejected",
        "needs_review",
        "validation_required",
        "memo_protocol",
        "in_person",
    ):
        assert token in js

    assert "точность распознавания" in js
    assert "Этап обработки" in js
