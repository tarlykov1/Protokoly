from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceLocation:
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None


@dataclass(frozen=True)
class ParsedElement:
    order: int
    text: str
    kind: str
    location: SourceLocation
    style: str | None = None
    cells: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedParagraph:
    index: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    paragraphs: list[ParsedParagraph] = field(default_factory=list)
    elements: list[ParsedElement] = field(default_factory=list)


@dataclass(frozen=True)
class ParserChoice:
    parser_type: str
    confidence: float
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedSection:
    title: str
    original_text: str
    source_order: int = 0
    confidence: float = 0.7
    direction_raw: str | None = None
    block_raw: str | None = None


@dataclass(frozen=True)
class ParsedTask:
    source_order: int
    source_text: str
    source_location: SourceLocation
    task_number: str
    title: str
    description: str = ""
    acceptance_criteria: str = ""
    deadline: str | None = None
    raw_deadline: str | None = None
    deadline_type: str = "none"
    deadline_value: str | None = None
    priority: str | None = None
    assignee_raw: str | None = None
    assignee_resolution: list[dict[str, Any]] = field(default_factory=list)
    direction_raw: str | None = None
    block_raw: str | None = None
    parsing_confidence: float = 0.75
    warnings: list[str] = field(default_factory=list)
    section_title: str = "Без раздела"


@dataclass(frozen=True)
class ParserResult:
    document_title: str
    document_number: str | None = None
    document_date: str | None = None
    meeting_date: str | None = None
    protocol_type: str = "protocol"
    sections: list[ParsedSection] = field(default_factory=list)
    tasks: list[ParsedTask] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProtocolParser(Protocol):
    parser_type: str

    def supports(self, document: ParsedDocument) -> bool: ...
    def confidence(self, document: ParsedDocument) -> ParserChoice: ...
    def parse(self, document: ParsedDocument) -> ParserResult: ...


RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
TASK_RE = re.compile(r"^(?:[-•]\s*)?(?P<num>\d+(?:[./]\d+)*|\d{2}/\d{2})[.)]?\s+(?P<title>.+)")


def parse_deadline(
    text: str, base_year: int | None = None
) -> tuple[str | None, str | None, str, str | None, str | None]:
    base_year = base_year or date.today().year
    low = text.lower()
    if "без срока" in low:
        return None, "без срока", "none", None, None
    for phrase, dtype in [
        ("до конца недели", "relative"),
        ("до конца месяца", "relative"),
        ("еженедельно", "periodic"),
        ("постоянно", "periodic"),
    ]:
        if phrase in low:
            return None, phrase, dtype, phrase, "Срок требует ручной проверки."
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
    if m:
        y = int(m.group(3))
        y = 2000 + y if y < 100 else y
        return (
            date(y, int(m.group(2)), int(m.group(1))).isoformat(),
            m.group(0),
            "date",
            m.group(0),
            None,
        )
    m = re.search(r"(?:до\s+)?(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?", low)
    if m and m.group(2) in RU_MONTHS:
        y = int(m.group(3) or base_year)
        return (
            date(y, RU_MONTHS[m.group(2)], int(m.group(1))).isoformat(),
            m.group(0),
            "date",
            m.group(0),
            None,
        )
    return None, None, "none", None, "Срок не распознан."


def split_assignees(text: str) -> str | None:
    m = re.search(r"(?:ответственный|исполнитель|ответственные)\s*[:—-]\s*([^.;]+)", text, re.I)
    if m:
        return m.group(1).strip()
    names = re.findall(
        r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.?(?:\s+совместно\s+с\s+[А-ЯЁ][а-яё]+ым\s+[А-ЯЁ]\.[А-ЯЁ]\.?)?",
        text,
    )
    return ", ".join(names) if names else None


class UniversalProtocolParser:
    parser_type = "universal"

    def supports(self, document: ParsedDocument) -> bool:
        return bool(document.elements or document.paragraphs)

    def confidence(self, document: ParsedDocument) -> ParserChoice:
        return ParserChoice(
            self.parser_type,
            0.55,
            ["Универсальный разбор структуры DOCX"],
            ["Использован универсальный парсер."],
        )

    def parse(self, document: ParsedDocument) -> ParserResult:
        elements = document.elements or [
            ParsedElement(p.index, p.text, "paragraph", SourceLocation(paragraph_index=p.index))
            for p in document.paragraphs
        ]
        title = next((e.text for e in elements if e.text.strip()), "Untitled protocol")
        sections: list[ParsedSection] = []
        tasks: list[ParsedTask] = []
        current_section = "Без раздела"
        warnings: list[str] = []
        for e in elements:
            text = e.text.strip()
            if not text:
                continue
            if self._is_section(e):
                current_section = text
                sections.append(
                    ParsedSection(
                        text, text, e.order, 0.85 if e.style and "Heading" in e.style else 0.7
                    )
                )
                continue
            table_task = (
                e.kind == "table_row"
                and len(e.cells) >= 2
                and not any("поруч" in c.lower() for c in e.cells[:1])
            )
            m = TASK_RE.match(text)
            if m or table_task or (e.kind == "paragraph" and e.order > 0):
                num = m.group("num") if m else str(len(tasks) + 1).zfill(2)
                task_title = (
                    m.group("title") if m else (e.cells[0] if table_task else text)
                ).strip()
                assignee = (
                    e.cells[1].strip() if table_task and len(e.cells) > 1 else split_assignees(text)
                )
                deadline_text = e.cells[2].strip() if table_task and len(e.cells) > 2 else text
                deadline, raw, dtype, value, warning = parse_deadline(deadline_text)
                tw = [warning] if warning else []
                tasks.append(
                    ParsedTask(
                        e.order,
                        text,
                        e.location,
                        num,
                        task_title,
                        text,
                        "",
                        deadline,
                        raw,
                        dtype,
                        value,
                        None,
                        assignee,
                        [],
                        None,
                        None,
                        0.82 if deadline else 0.65,
                        tw,
                        current_section,
                    )
                )
        if not sections:
            sections.append(ParsedSection("Без раздела", "", 0, 0.3))
        if not tasks:
            warnings.append("Поручения не найдены.")
        return ParserResult(
            title,
            sections=sections,
            tasks=tasks,
            warnings=warnings,
            metadata={"element_count": len(elements)},
        )

    def _is_section(self, e: ParsedElement) -> bool:
        text = e.text.strip()
        if not text or TASK_RE.match(text):
            return False
        if e.style and "Heading" in e.style:
            return True
        if len(text) > 3 and text.upper() == text and any(ch.isalpha() for ch in text):
            return True
        return bool(re.match(r"^\d+\.\s+[А-ЯA-Z][^.;]{3,80}$", text))


class MemoParser(UniversalProtocolParser):
    parser_type = "memo"

    def confidence(self, document: ParsedDocument) -> ParserChoice:
        text = "\n".join(e.text for e in document.elements).lower()
        score = 0.9 if "служебная записка" in text or "memo" in text else 0.35
        return ParserChoice(self.parser_type, score, ["Поиск признаков служебной записки"])


class CeoProtocolParser(UniversalProtocolParser):
    parser_type = "ceo_protocol"

    def confidence(self, document: ParsedDocument) -> ParserChoice:
        text = "\n".join(e.text for e in document.elements).lower()
        score = 0.88 if "генеральн" in text or "ceo" in text else 0.4
        return ParserChoice(self.parser_type, score, ["Поиск признаков протокола CEO"])


class DeputyCeoProtocolParser(UniversalProtocolParser):
    parser_type = "deputy_ceo_protocol"

    def confidence(self, document: ParsedDocument) -> ParserChoice:
        text = "\n".join(e.text for e in document.elements).lower()
        score = 0.86 if "заместител" in text else 0.38
        return ParserChoice(self.parser_type, score, ["Поиск признаков протокола заместителя CEO"])


class ParserRegistry:
    def __init__(self) -> None:
        self.parsers = {
            p.parser_type: p
            for p in [
                UniversalProtocolParser(),
                MemoParser(),
                CeoProtocolParser(),
                DeputyCeoProtocolParser(),
            ]
        }

    def get(self, parser_type: str | None) -> ProtocolParser:
        return self.parsers.get(parser_type or "", self.parsers["universal"])

    def choose(
        self, document: ParsedDocument, requested: str | None = None
    ) -> tuple[ProtocolParser, ParserChoice]:
        if requested:
            parser = self.get(requested)
            choice = parser.confidence(document)
            return parser, ParserChoice(
                parser.parser_type,
                1.0,
                ["Парсер выбран пользователем", *choice.reasons],
                choice.warnings,
            )
        choices = [(p, p.confidence(document)) for p in self.parsers.values()]
        parser, choice = max(choices, key=lambda item: item[1].confidence)
        if choice.confidence < 0.6:
            parser = self.parsers["universal"]
            choice = ParserChoice(
                "universal",
                choice.confidence,
                ["Низкая уверенность автоопределения"],
                ["Парсер выбран с низкой уверенностью."],
            )
        return parser, choice
