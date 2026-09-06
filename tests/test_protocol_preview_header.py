from pathlib import Path


def test_protocol_preview_renders_saved_header_fields():
    template = Path("app/web/templates/protocol_card.html").read_text(encoding="utf-8")

    for field in (
        "protocol.organization_name",
        "protocol.event_title",
        "protocol.event_type",
        "protocol.meeting_format",
        "protocol.meeting_location",
        "protocol.project_label",
        "protocol.responsible_department",
        "protocol.chairperson_snapshot",
        "protocol.secretary_snapshot",
        "protocol.initiator",
        "protocol.responsible",
        "protocol.agenda_basis",
        "protocol.description",
    ):
        assert field in template

    assert "Тема / основание / повестка" in template
    assert "Вводная часть" in template
