from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol

logger = logging.getLogger(__name__)


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
DEADLINE_LABEL_RE = re.compile(
    r"^срок(?:\s+(?:исполнения|выполнения))?(?:\s+до)?\s*[:—–-]?\s*(.*)$", re.I
)
BLOCK_RE = re.compile(r"^блок\s+\d+\s*:?[\s]*(.*)$", re.I)
SERVICE_STOP_RE = re.compile(
    r"^(мемо подготовил|протокол подготовил|секретарь|председатель|подпись|приложение)"
    r"\b\s*:?.*",
    re.I,
)


def normalize_docx_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u202f", " ")
    text = text.replace("–", "—")
    return re.sub(r"[ \t]+", " ", text).strip()


def _heading_key(text: str) -> str:
    text = normalize_docx_text(text).strip(" \"«»“”‘’:")
    return re.sub(r"\s+", "", text).upper()


def _memo_text(document: ParsedDocument) -> str:
    parts = [document.filename]
    parts.extend(e.text for e in document.elements)
    if not document.elements:
        parts.extend(p.text for p in document.paragraphs)
    return "\n".join(normalize_docx_text(p) for p in parts if p)


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
        text = _memo_text(document)
        low = text.lower()
        heading_keys = {_heading_key(line) for line in text.splitlines()}
        features = [
            ("filename_memo", "мемо" in document.filename.lower()),
            ("memo", "мемо" in low),
            ("решили", "РЕШИЛИ" in heading_keys),
            ("исполнитель", bool(re.search(r"исполнител[ьи]", low))),
            ("срок", bool(re.search(r"\bсрок\b", low))),
            ("блок", bool(re.search(r"(^|\n)\s*блок\s+\d+", low))),
            ("мемо подготовил", "мемо подготовил" in low),
        ]
        found = [name for name, ok in features if ok]
        score = 0.95 if len(found) >= 4 and "решили" in found else 0.4
        return ParserChoice(self.parser_type, score, ["Признаки МЕМО: " + ", ".join(found)])

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
        first_elements = [e.text for e in norm_elements[:30]]
        start = next(
            (i for i, e in enumerate(norm_elements) if _heading_key(e.text) == "РЕШИЛИ"), None
        )
        stop = next((i for i, e in enumerate(norm_elements) if SERVICE_STOP_RE.match(e.text)), None)
        between_count = (
            max((stop if stop is not None else len(norm_elements)) - start - 1, 0)
            if start is not None
            else 0
        )
        diagnostics: dict[str, Any] = {
            "element_count": len(norm_elements),
            "first_30_normalized_elements": first_elements,
            "decision_section_index": start,
            "memo_prepared_index": stop,
            "elements_between_decision_and_prepared": between_count,
        }
        logger.info("Memo parser diagnostics: %s", diagnostics)
        if start is None:
<<<<<<< HEAD
            diagnostics["rejection_reasons"] = [
                {"index": i, "reason": "раздел РЕШИЛИ не найден"}
                for i, _ in enumerate(norm_elements)
            ]
=======
>>>>>>> origin/main
            return ParserResult(
                title,
                protocol_type="memo",
                warnings=["Раздел РЕШИЛИ не найден."],
<<<<<<< HEAD
                metadata={"parser_type": self.parser_type, "diagnostics": diagnostics},
=======
                metadata={"parser_type": self.parser_type},
>>>>>>> origin/main
            )
        tasks: list[ParsedTask] = []
        sections = [ParsedSection("Без раздела", "", 0, 0.3)]
        current_block: str | None = None
        current: dict[str, Any] | None = None
        mode: str | None = None
        expected = 1
        rejection_reasons: list[dict[str, Any]] = []

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
                rejection_reasons.append({"index": i, "text": text, "reason": "пустой элемент"})
                i += 1
                continue
            if SERVICE_STOP_RE.match(text):
                rejection_reasons.append({"index": i, "text": text, "reason": "служебная строка"})
                finish()
                break
            b = BLOCK_RE.match(text)
            if b:
                rejection_reasons.append(
                    {"index": i, "text": text, "reason": "строка блока, не поручение"}
                )
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
                if current:
                    missing = []
                    if not current["assignee_parts"]:
                        missing.append("не найден исполнитель")
                    if not current.get("deadline"):
                        missing.append("не найден срок")
                    if missing:
                        rejection_reasons.append(
                            {"index": i, "text": text, "reason": ", ".join(missing)}
                        )
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
                rejection_reasons.append(
                    {"index": i, "text": text, "reason": "не является поручением"}
                )
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
                if not value and i + 1 < len(norm_elements):
                    nxt = norm_elements[i + 1].text
                    if DATE_RE.search(nxt):
                        value = nxt
                        current["raw"].append(nxt)
                        i += 1
                deadline, raw = _parse_numeric_date(value or text)
                if deadline:
                    current["deadline"] = deadline
                    current["raw_deadline"] = raw
            elif mode == "assignee":
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
        if between_count == 0:
            rejection_reasons.append(
                {
                    "index": start,
                    "text": norm_elements[start].text,
                    "reason": "между РЕШИЛИ и Мемо подготовил нет элементов; проверьте extractor",
                }
            )
        if not tasks:
            diagnostics["rejection_reasons"] = rejection_reasons
            logger.warning("Memo parser created 0 tasks: %s", rejection_reasons)
        else:
            diagnostics["rejection_reasons"] = []
        return ParserResult(
            title,
            protocol_type="memo",
            sections=sections,
            tasks=tasks,
            metadata={"parser_type": self.parser_type, "diagnostics": diagnostics},
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
                MemoProtocolParser(),
                MemoParser(),
                CeoProtocolParser(),
                DeputyCeoProtocolParser(),
                UniversalProtocolParser(),
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
        for candidate, candidate_choice in choices:
            logger.info(
                "Parser candidate %s confidence=%.2f reasons=%s",
                candidate.parser_type,
                candidate_choice.confidence,
                candidate_choice.reasons,
            )
        specialized = [
            (p, c) for p, c in choices if p.parser_type != "universal" and c.confidence >= 0.75
        ]
        parser, choice = max(specialized or choices, key=lambda item: item[1].confidence)
        if not specialized and choice.confidence < 0.6:
            parser = self.parsers["universal"]
            choice = ParserChoice(
                "universal",
                choice.confidence,
                ["Низкая уверенность автоопределения"],
                ["Парсер выбран с низкой уверенностью."],
            )
        return parser, choice
