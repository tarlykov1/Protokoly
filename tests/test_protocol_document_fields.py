from datetime import date, time
from io import BytesIO

from docx import Document
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.domain import Project, Protocol, ProtocolSignatory
from app.services.export import ProtocolDocxExporter


def test_docx_contains_structured_header_footer_and_never_none():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Документы", code="DOC")
        db.add(project)
        db.flush()
        protocol = Protocol(
            project_id=project.id,
            document_type="protocol",
            title="Совещание по проекту",
            number="12",
            meeting_date=date(2026, 8, 24),
            meeting_time=time(10, 30),
            meeting_location="Переговорная 1",
            organization_name="Организация",
            chairperson_snapshot="Иванов И.И.",
            secretary_snapshot="Петров П.П.",
            footer_notes="Разослать участникам",
        )
        protocol.signatories.append(
            ProtocolSignatory(
                role="Председатель",
                name_snapshot="Иванов И.И.",
                position_snapshot="Директор",
                sort_order=0,
            )
        )
        db.add(protocol)
        db.commit()
        content = ProtocolDocxExporter(db).export(protocol.id, mode="print")
    text = "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    assert "Место: Переговорная 1" in text
    assert "Председатель (Директор) __________________ Иванов И.И." in text
    assert "Примечание:" in text
    assert "None" not in text


def test_signatories_keep_explicit_order():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="Документы", code="ORDER")
        db.add(project)
        db.flush()
        protocol = Protocol(project_id=project.id, title="Порядок")
        protocol.signatories = [
            ProtocolSignatory(role="Секретарь", name_snapshot="Второй", sort_order=2),
            ProtocolSignatory(role="Председатель", name_snapshot="Первый", sort_order=1),
        ]
        db.add(protocol)
        db.commit()
        db.expire_all()
        loaded = db.get(Protocol, protocol.id)
        assert [item.name_snapshot for item in loaded.signatories] == ["Первый", "Второй"]
