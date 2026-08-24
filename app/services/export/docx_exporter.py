from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.domain import (
    Protocol,
    ProtocolParticipantGroup,
    ProtocolSection,
    ProtocolTask,
    ProtocolTaskAssignment,
)


class ProtocolDocxExporter:
    """Export protocols either as a round-trip MEMO or as a reader-friendly document."""

    def __init__(self, db: Session):
        self.db = db

    def export(self, protocol_id: int, mode: str = "memo") -> bytes:
        if mode not in {"memo", "print"}:
            raise ValueError("Неизвестный режим экспорта")
        protocol = self.db.scalar(
            select(Protocol)
            .where(Protocol.id == protocol_id)
            .options(
                selectinload(Protocol.project),
                selectinload(Protocol.tasks)
                .selectinload(ProtocolTask.assignments)
                .selectinload(ProtocolTaskAssignment.employee),
                selectinload(Protocol.participant_groups).selectinload(
                    ProtocolParticipantGroup.members
                ),
                selectinload(Protocol.signatories),
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
        document.styles["Normal"].font.name = "Arial"
        document.styles["Normal"].font.size = Pt(10)
        if mode == "memo":
            self._build_memo(document, protocol, sections, tasks)
        else:
            self._build_print(document, protocol, sections, tasks)
        output = BytesIO()
        document.save(output)
        return output.getvalue()

    @staticmethod
    def _assignees(task: ProtocolTask) -> str:
        return (
            ", ".join(
                assignment.assignee_name or "—"
                for assignment in sorted(task.assignments, key=lambda item: item.sort_order)
            )
            or "—"
        )

    def _build_memo(self, document, protocol, sections, tasks) -> None:
        """Use paragraphs only: this is the canonical MemoProtocolParser contract."""
        number = (protocol.number or str(protocol.id)).replace("M-", "М – ").replace("М-", "М – ")
        document.add_paragraph(number)
        heading = document.add_paragraph("ИТОГИ")
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.runs[0].bold = True
        title = document.add_paragraph(protocol.title)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._add_header_details(document, protocol)
        if protocol.meeting_date and not protocol.meeting_location:
            document.add_paragraph(
                f"г. Санкт-Петербург «{protocol.meeting_date:%d}» "
                f"{self._month(protocol.meeting_date.month)} {protocol.meeting_date:%Y} года"
            )
        self._add_people(document, protocol)
        if protocol.description:
            document.add_paragraph("ОТМЕТИЛИ:").runs[0].bold = True
            document.add_paragraph(protocol.description)
        document.add_paragraph("РЕШИЛИ:").runs[0].bold = True
        task_groups = [
            (section.title, [t for t in tasks if t.section_id == section.id])
            for section in sections
        ]
        unsectioned = [t for t in tasks if not t.section_id]
        if unsectioned:
            task_groups.append(("Без раздела", unsectioned))
        task_index = 0
        for section_title, section_tasks in task_groups:
            document.add_paragraph(f"#{section_title}").runs[0].bold = True
            for task in section_tasks:
                task_index += 1
                # Numbering follows persisted order. The original task number remains editable in UI,
                # but contiguous MEMO numbering makes repeated imports deterministic.
                document.add_paragraph(f"{task_index}. {task.title}")
                document.add_paragraph("Исполнители:").runs[0].bold = True
                document.add_paragraph(self._assignees(task))
                document.add_paragraph("Срок:").runs[0].bold = True
                document.add_paragraph(
                    task.deadline.strftime("%d.%m.%Y") if task.deadline else "Без срока"
                )
        self._add_footer(document, protocol)

    def _build_print(self, document, protocol, sections, tasks) -> None:
        heading = document.add_paragraph(protocol.title)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.runs[0].bold = True
        document.add_paragraph(f"Протокол № {protocol.number or '—'}")
        self._add_header_details(document, protocol)
        self._add_people(document, protocol)
        document.add_paragraph("РЕШИЛИ:").runs[0].bold = True
        for section in sections:
            document.add_heading(section.title, level=2)
            for task in [t for t in tasks if t.section_id == section.id]:
                paragraph = document.add_paragraph(style="List Number")
                paragraph.add_run(task.title).bold = True
                if task.description and task.description != task.title:
                    document.add_paragraph(task.description)
                document.add_paragraph(f"Исполнители: {self._assignees(task)}")
                document.add_paragraph(
                    f"Срок: {task.deadline:%d.%m.%Y}" if task.deadline else "Срок: —"
                )
        self._add_footer(document, protocol)

    @staticmethod
    def _add_header_details(document, protocol) -> None:
        values = [
            ("Организация", protocol.organization_name),
            ("Вид мероприятия", protocol.event_type),
            ("Мероприятие", protocol.event_title),
            ("Дата", protocol.meeting_date.strftime("%d.%m.%Y") if protocol.meeting_date else None),
            ("Время", protocol.meeting_time.strftime("%H:%M") if protocol.meeting_time else None),
            ("Место", protocol.meeting_location or protocol.location),
            ("Формат", protocol.meeting_format),
            ("Тема", protocol.meeting_topic),
            ("Основание / повестка", protocol.agenda_basis),
            ("Проект", protocol.project_label),
            ("Председатель", protocol.chairperson_snapshot),
            ("Секретарь", protocol.secretary_snapshot),
        ]
        for label, value in values:
            if value:
                document.add_paragraph(f"{label}: {value}")

    @staticmethod
    def _add_people(document, protocol) -> None:
        group = next(
            (
                g
                for g in protocol.participant_groups
                if g.type == "attendees" or g.name == "Присутствовали"
            ),
            None,
        )
        if group and group.members:
            document.add_paragraph("Присутствовали:").runs[0].bold = True
            for member in group.members:
                document.add_paragraph(member.name_snapshot)

    @staticmethod
    def _add_footer(document, protocol) -> None:
        if protocol.signatories:
            document.add_paragraph("ПОДПИСИ:").runs[0].bold = True
            for item in protocol.signatories:
                position = f" ({item.position_snapshot})" if item.position_snapshot else ""
                document.add_paragraph(
                    f"{item.role}{position} __________________ {item.name_snapshot}"
                )
        for role, name in (
            ("Подготовил", protocol.prepared_by),
            ("Утвердил", protocol.approved_by),
        ):
            if name:
                document.add_paragraph(f"{role} __________________ {name}")
        if protocol.footer_notes:
            document.add_paragraph("Примечание:").runs[0].bold = True
            document.add_paragraph(protocol.footer_notes)

    @staticmethod
    def _month(month: int) -> str:
        return (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        )[month - 1]
