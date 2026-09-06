from pathlib import Path


def test_participant_template_script_loads_after_bootstrap_bundle():
    base = Path("app/web/templates/base.html").read_text(encoding="utf-8")
    page = Path("app/web/templates/participant_templates.html").read_text(encoding="utf-8")

    assert '{% block scripts %}{% endblock %}' in base
    assert base.index("bootstrap.bundle.min.js") < base.index("{% block scripts %}")
    assert '{% block scripts %}<script src="/static/js/participant-templates.js"></script>{% endblock %}' in page
    assert page.index("{% endblock %}\n{% block scripts %}") > page.index('id="composition-modal"')
