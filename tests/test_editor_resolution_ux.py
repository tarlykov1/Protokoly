from fastapi.testclient import TestClient

from app.main import app


def test_editor_resolution_helper_is_loaded_and_uses_in_app_modal():
    client = TestClient(app)

    base = client.get('/dashboard').text
    script = client.get('/static/js/editor-resolution-ux.js').text

    assert '/static/js/editor-resolution-ux.js' in base
    assert 'Уточнить исполнителя' in script
    assert 'Найдите сотрудника в справочнике' in script
    assert 'Создать и назначить' in script
    assert 'match-assignee' in script
    assert 'create-assignee' in script
    assert "prompt('ФИО нового сотрудника'" not in script


def test_control_status_labels_are_human_readable():
    client = TestClient(app)
    script = client.get('/static/js/editor-resolution-ux.js').text

    assert "pending: 'Ожидает выполнения'" in script
    assert "in_progress: 'В работе'" in script
    assert "completed: 'Выполнено'" in script
    assert "overdue: 'Просрочено'" in script
    assert "rejected: 'Возвращено на доработку'" in script
    assert "document.querySelectorAll('.protocol-validation code').forEach(code => code.remove())" in script
