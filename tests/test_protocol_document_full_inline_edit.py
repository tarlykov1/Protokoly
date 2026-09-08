from pathlib import Path


def test_document_view_exposes_header_footer_and_task_inline_fields():
    template = Path("app/web/templates/protocol_card.html").read_text(encoding="utf-8")
    ui = Path("app/web/templates/components/ui.html").read_text(encoding="utf-8")

    for field in (
        "organization_name",
        "document_type",
        "title",
        "number",
        "meeting_date",
        "meeting_time",
        "event_title",
        "event_type",
        "meeting_format",
        "meeting_location",
        "project_label",
        "responsible_department",
        "chairperson_snapshot",
        "secretary_snapshot",
        "initiator",
        "responsible",
        "agenda_basis",
        "description",
        "footer_notes",
    ):
        assert f'data-protocol-field="{field}"' in template

    assert 'data-signatory-field="role"' in template
    assert 'data-signatory-field="name_snapshot"' in template
    assert 'data-signatory-field="position_snapshot"' in template
    assert 'data-inline-field="title"' in ui
    assert 'data-inline-field="description"' in ui
    assert 'data-inline-field="deadline"' in ui


def test_document_view_has_print_docx_and_pdf_actions():
    template = Path("app/web/templates/protocol_card.html").read_text(encoding="utf-8")
    script = Path("app/web/static/js/protocol-document-ux.js").read_text(encoding="utf-8")

    assert "Печать" in template
    assert "Сохранить DOCX" in template
    assert "Сохранить PDF" in template
    assert 'href="/protocols/{{ protocol.id }}/export/docx?mode=print"' in template
    assert "[data-protocol-print]" in script
    assert "[data-protocol-pdf]" in script
    assert "window.print()" in script


def test_document_inline_edit_uses_existing_editor_save_endpoint():
    script = Path("app/web/static/js/protocol-document-ux.js").read_text(encoding="utf-8")

    assert "`/protocols/${protocolId}/editor/save`" in script
    assert "{protocol: {[element.dataset.protocolField]: value}}" in script
    assert "{tasks: [{id: Number(task.dataset.taskId), [element.dataset.inlineField]: value}]}" in script
    assert "await requestSave({signatories})" in script
    assert "event.key === 'Escape'" in script
