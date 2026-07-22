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


MEMO_TASK_RE = re.compile(r"^\s*(?P<num>\d{1,3})\s*[.)](?!\d)\s*(?P<title>.*)$")
DATE_RE = re.compile(r"\b([0-3]?\d)[.\-/]([01]?\d)[.\-/](\d{2}|\d{4})\b")
ASSIGNEE_LABEL_RE = re.compile(
    r"^(исполнитель|исполнители|ответственный|ответственные)\s*:?\s*(.*)$", re.I
)
DEADLINE_LABEL_RE = re.compile(r"^срок(?:\s+(?:исполнения|выполнения))?\s*:?\s*(.*)$", re.I)
BLOCK_RE = re.compile(r"^блок\s+\d+\s*:?[\s]*(.*)$", re.I)
SERVICE_STOP_RE = re.compile(
    r"^(мемо подготовил|протокол подготовил|секретарь|председатель|подпись|приложение)\s*:", re.I
)


def normalize_docx_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u202f", " ")
    text = text.replace("–", "—")
    return re.sub(r"[ \t]+", " ", text).strip()


def _heading_key(text: str) -> str:
    return re.sub(r"\s+", "", normalize_docx_text(text).rstrip(":")).upper()


def _parse_numeric_date(text: str) -> tuple[str | None, str | None]:
    m = DATE_RE.search(text)
    if not m:
        return None, None
    day, month, year = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat(), m.group(0)
    except ValueError:
        return None, None


def split_assignee_names(value: str) -> list[str]:
    value = normalize_docx_text(value).strip(" ;,")
    if not value:
        return []
    chunks = re.split(r"[,;\n]+", value)
    names: list[str] = []
    for chunk in chunks:
        chunk = normalize_docx_text(chunk).strip(" ;,")
        if chunk:
            names.append(chunk)
    return names


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


class MemoProtocolParser(UniversalProtocolParser):
    parser_type = "memo_protocol"

    def confidence(self, document: ParsedDocument) -> ParserChoice:
        text = "\n".join(normalize_docx_text(e.text) for e in document.elements or [])
        low = text.lower()
        features = [
            ("итоги", "ИТОГИ" in text.upper()),
            ("отметили", "ОТМЕТИЛИ" in text.upper()),
            ("решили", "РЕШИЛИ" in text.upper() or "Р Е Ш И Л И" in text.upper()),
            ("исполнитель", bool(re.search(r"исполнител[ьи]", low))),
            ("срок", "срок" in low),
        ]
        found = [name for name, ok in features if ok]
        score = 0.95 if len(found) >= 4 else 0.4
        return ParserChoice(self.parser_type, score, ["Признаки МЕМО/ИТОГИ: " + ", ".join(found)])

    def parse(self, document: ParsedDocument) -> ParserResult:
        elements = document.elements or [
            ParsedElement(p.index, p.text, "paragraph", SourceLocation(paragraph_index=p.index))
            for p in document.paragraphs
        ]
        norm_elements = [
            ParsedElement(
                e.order,
                normalize_docx_text(e.text),
                e.kind,
                e.location,
                e.style,
                tuple(normalize_docx_text(c) for c in e.cells),
            )
            for e in elements
        ]
        title = next((e.text for e in norm_elements if e.text), "Untitled memo")
        start = next(
            (i for i, e in enumerate(norm_elements) if _heading_key(e.text) == "РЕШИЛИ"), None
        )
        if start is None:
            return super().parse(document)
        tasks: list[ParsedTask] = []
        sections = [ParsedSection("Без раздела", "", 0, 0.3)]
        current_block: str | None = None
        current: dict[str, Any] | None = None
        mode: str | None = None
        expected = 1

        def finish() -> None:
            nonlocal current, expected
            if not current:
                return
            title_text = normalize_docx_text(" ".join(current["text_parts"]))
            assignees = split_assignee_names("\n".join(current["assignee_parts"]))
            deadline = current.get("deadline")
            warnings: list[str] = []
            if not assignees:
                warnings.append("Исполнитель не распознан.")
            if not deadline:
                warnings.append("Срок не распознан.")
            if len(title_text) < 10:
                warnings.append("Текст поручения подозрительно короткий.")
            if int(current["num"]) != expected:
                warnings.append("Нарушена последовательность номеров.")
            expected = int(current["num"]) + 1
            tasks.append(
                ParsedTask(
                    current["order"],
                    "\n".join(current["raw"]),
                    current["location"],
                    current["num"],
                    title_text,
                    title_text,
                    "",
                    deadline,
                    current.get("raw_deadline"),
                    "date" if deadline else "none",
                    current.get("raw_deadline"),
                    None,
                    ", ".join(assignees) if assignees else None,
                    [{"raw_name": n} for n in assignees],
                    None,
                    current.get("block"),
                    0.94 if not warnings else 0.78,
                    warnings,
                    current.get("block") or "Без раздела",
                )
            )
            current = None

        i = start + 1
        while i < len(norm_elements):
            e = norm_elements[i]
            text = e.text
            if not text:
                i += 1
                continue
            if SERVICE_STOP_RE.match(text):
                finish()
                break
            b = BLOCK_RE.match(text)
            if b:
                finish()
                mode = None
                name = b.group(1).strip(" :")
                if not name and i + 1 < len(norm_elements):
                    nxt = norm_elements[i + 1].text.strip(" :")
                    if nxt and not MEMO_TASK_RE.match(nxt):
                        name = nxt
                        i += 1
                current_block = name or None
                if current_block and current_block not in [s.title for s in sections]:
                    sections.append(
                        ParsedSection(current_block, text, e.order, 0.9, block_raw=current_block)
                    )
                i += 1
                continue
            m = MEMO_TASK_RE.match(text)
            if m:
                finish()
                mode = "text"
                current = {
                    "num": m.group("num"),
                    "text_parts": [],
                    "assignee_parts": [],
                    "raw": [text],
                    "order": e.order,
                    "location": e.location,
                    "block": current_block,
                }
                rest = m.group("title").strip()
                if rest:
                    current["text_parts"].append(rest)
                i += 1
                continue
            if not current:
                i += 1
                continue
            current["raw"].append(text)
            am = ASSIGNEE_LABEL_RE.match(text)
            dm = DEADLINE_LABEL_RE.match(text)
            if am:
                mode = "assignee"
                if am.group(2):
                    current["assignee_parts"].append(am.group(2))
            elif dm:
                mode = "deadline"
                value = dm.group(1)
                deadline, raw = _parse_numeric_date(value or text)
                if deadline:
                    current["deadline"] = deadline
                    current["raw_deadline"] = raw
            elif mode == "assignee":
                # stop collecting assignees when a date-like deadline line appears without label
                deadline, raw = _parse_numeric_date(text)
                if deadline:
                    current["deadline"] = deadline
                    current["raw_deadline"] = raw
                    mode = "deadline"
                else:
                    current["assignee_parts"].append(text)
            elif mode == "deadline":
                deadline, raw = _parse_numeric_date(text)
                if deadline:
                    current["deadline"] = deadline
                    current["raw_deadline"] = raw
            else:
                current["text_parts"].append(text)
            i += 1
        finish()
        return ParserResult(
            title,
            protocol_type="memo",
            sections=sections,
            tasks=tasks,
            metadata={
                "parser_type": self.parser_type,
                "element_count": len(norm_elements),
                "decision_section_index": start,
            },
        )


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
                MemoProtocolParser(),
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
