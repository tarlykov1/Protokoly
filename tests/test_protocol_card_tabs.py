from pathlib import Path


def test_protocol_card_separates_service_tabs_from_document_paper():
    template = Path("app/web/templates/protocol_card.html").read_text(encoding="utf-8")

    assert "Этап обработки" in template
    assert "Workflow" not in template
    assert "?view=history" in template
    assert "?view=versions" in template
    assert "История изменений" in template
    assert "Версии DOCX" in template
    assert 'class="protocol-document"' in template
    assert "protocol-paper" in template

    readiness_pos = template.index("protocol-readiness-summary")
    tabs_pos = template.index("protocol-tabs")
    paper_pos = template.index('<section class="protocol-document">')
    attendees_pos = template.index("Присутствовали:", paper_pos)
    decisions_pos = template.index("РЕШИЛИ:", attendees_pos)
    assert readiness_pos < tabs_pos < paper_pos < attendees_pos < decisions_pos
    assert template.count("ui.readiness(progress,'Готовность протокола')") == 1


def test_protocol_card_localizes_meeting_format_and_hides_validation_codes():
    template = Path("app/web/templates/protocol_card.html").read_text(encoding="utf-8")

    assert "'in_person':'Очно'" in template
    assert "'video':'ВКС'" in template
    assert "'hybrid':'Смешанный'" in template
    assert "<code>{{ issue.code }}</code>" not in template


def test_history_event_labels_cover_protocol_editor_changes():
    governance = Path("app/services/protocols/governance.py").read_text(encoding="utf-8")

    assert '"protocol_details_changed": "Изменение реквизитов протокола"' in governance
    assert '"protocol_signatories_changed": "Изменение подписной части"' in governance
