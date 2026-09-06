from pathlib import Path

from app.core.config import Settings


def test_demo_actions_are_enabled_in_local_development_only():
    local = Settings(_env_file=None, environment="development", demo_mode=False)
    production = Settings(_env_file=None, environment="production", demo_mode=False)

    assert local.demo_mode is True
    assert production.demo_mode is False


def test_guided_demo_contains_real_examples_and_actions():
    template = Path("app/web/templates/demo_guided.html").read_text(encoding="utf-8")

    assert "Не схема процесса" in template
    assert "Примеры поручений" not in template  # examples are rendered as concrete task cards
    assert "Исправить замечания в редакторе" in template
    assert "Выполнить тестовую публикацию" in template
    assert "task.title" in template
    assert "task.deadline" in template


def test_participant_template_delete_is_visible_without_overflow_menu():
    template = Path("app/web/templates/participant_templates.html").read_text(encoding="utf-8")

    assert "Удалить список" in template
    assert "delete-template-direct" in template
    assert "dropdown-toggle" not in template


def test_government_portal_visual_layer_is_loaded_after_legacy_css():
    base = Path("app/web/templates/base.html").read_text(encoding="utf-8")
    css = Path("app/web/static/css/gov-ui.css").read_text(encoding="utf-8")

    assert base.index("/static/css/app.css") < base.index("/static/css/gov-ui.css")
    assert "--primary:#0d4cd3" in css
    assert ".sidebar" in css and "background:#fff" in css
    assert "box-shadow:none" in css
