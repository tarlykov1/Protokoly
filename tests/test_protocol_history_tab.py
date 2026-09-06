from pathlib import Path


def test_protocol_history_is_hidden_in_tab_by_default():
    template = Path("app/web/templates/protocol_card.html").read_text(encoding="utf-8")

    assert 'data-bs-target="#protocol-history-tab"' in template
    assert 'class="collapse mb-3" id="protocol-history-tab"' in template
    assert "История изменений" in template
    assert "{{ history|length }}" in template


def test_protocol_details_history_event_is_localized():
    governance = Path("app/services/protocols/governance.py").read_text(encoding="utf-8")

    assert '"protocol_details_changed": "Изменение реквизитов протокола"' in governance
