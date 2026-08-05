from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.domain import Protocol, ProtocolSection, ProtocolTask, ProtocolTaskAssignment


class ProtocolDocxExporter:
    """Build a DOCX protocol that keeps the MЕМО-like section/task structure."""

    def __init__(self, db: Session):
        self.db = db

    def export(self, protocol_id: int) -> bytes:
        protocol = self.db.scalar(
            select(Protocol)
            .where(Protocol.id == protocol_id)
            .options(
                selectinload(Protocol.project),
                selectinload(Protocol.tasks)
                .selectinload(ProtocolTask.assignments)
                .selectinload(ProtocolTaskAssignment.employee),
            )
        )
        if protocol is None:
            raise ValueError("Протокол не найден")

        sections = self.db.scalars(
            select(ProtocolSection)
            .where(ProtocolSection.protocol_id == protocol_id)
            .order_by(ProtocolSection.sort_order, ProtocolSection.id)
        ).all()
        tasks = sorted(protocol.tasks, key=lambda task: (task.position, task.id))

        document = Document()
        styles = document.styles
        styles["Normal"].font.name = "Arial"
        styles["Normal"].font.size = Pt(10)

        heading = document.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = heading.add_run(protocol.title)
        run.bold = True
        run.font.size = Pt(14)

        meta = document.add_paragraph()
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta.add_run(f"Протокол № {protocol.number or '—'}").bold = True
        if protocol.meeting_date:
            meta.add_run(f" от {protocol.meeting_date.strftime('%d.%m.%Y')}")

        details = document.add_table(rows=0, cols=2)
        details.style = "Table Grid"
        for label, value in (
            ("Проект", protocol.project.name if protocol.project else "—"),
            ("Инициатор", protocol.initiator or "—"),
            ("Ответственный", protocol.responsible or "—"),
            ("Участники", protocol.participants or "—"),
        ):
            row = details.add_row().cells
            row[0].text = label
            row[1].text = value

        document.add_paragraph()
        for index, section in enumerate(sections, start=1):
            paragraph = document.add_paragraph()
            paragraph.style = "Heading 2"
            paragraph.add_run(f"{index}. {section.title}").bold = True
            self._add_task_table(
                document, [task for task in tasks if task.section_id == section.id]
            )

        unsectioned = [task for task in tasks if not task.section_id]
        if unsectioned:
            paragraph = document.add_paragraph()
            paragraph.style = "Heading 2"
            paragraph.add_run("Без раздела").bold = True
            self._add_task_table(document, unsectioned)

        output = BytesIO()
        document.save(output)
        return output.getvalue()

    def _add_task_table(self, document: Document, tasks: list[ProtocolTask]) -> None:
        table = document.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        headers = ("№", "Поручение", "Исполнители", "Срок", "Порядок")
        for cell, text in zip(table.rows[0].cells, headers, strict=True):
            cell.text = text
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True
        if not tasks:
            row = table.add_row().cells
            row[1].text = "Поручений нет"
            return
        for order, task in enumerate(tasks, start=1):
            row = table.add_row().cells
            row[0].text = task.number
            row[1].text = task.title
            if task.description:
                row[1].add_paragraph(task.description)
            row[2].text = ", ".join(
                assignment.assignee_name or "—"
                for assignment in sorted(task.assignments, key=lambda item: item.sort_order)
            ) or "—"
            row[3].text = task.deadline.strftime("%d.%m.%Y") if task.deadline else "—"
            row[4].text = str(order)
