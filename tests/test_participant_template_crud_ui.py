from fastapi.testclient import TestClient

from app.main import app


def test_participant_template_page_loads_crud_script_after_bootstrap():
    client = TestClient(app)
    response = client.get('/employee-lists')

    assert response.status_code == 200
    html = response.text
    assert 'id="new-template"' in html
    assert 'class="edit-composition' in html or 'Шаблонов пока нет' in html
    assert html.index('bootstrap.bundle.min.js') < html.index('/static/js/participant-templates.js')
