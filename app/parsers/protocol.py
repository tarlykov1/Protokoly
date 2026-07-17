from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ParsedParagraph:
    index: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    paragraphs: list[ParsedParagraph]


@dataclass(frozen=True)
class ParsedTask:
    number: str
    title: str
    original_text: str
    source_paragraph: int | None = None


@dataclass(frozen=True)
class ParsedSection:
    title: str
    original_text: str
    tasks: list[ParsedTask] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedProtocol:
    title: str
    sections: list[ParsedSection]


class ProtocolParser(Protocol):
    def supports(self, document: ParsedDocument) -> bool: ...
    def parse(self, document: ParsedDocument) -> ParsedProtocol: ...


class UniversalProtocolParser:
    def supports(self, document: ParsedDocument) -> bool:
        return bool(document.paragraphs)

    def parse(self, document: ParsedDocument) -> ParsedProtocol:
        title = document.paragraphs[0].text if document.paragraphs else "Untitled protocol"
        tasks = [
            ParsedTask(str(i).zfill(2), p.text, p.text, p.index)
            for i, p in enumerate(document.paragraphs[1:], start=1)
            if p.text.strip()
        ]
        return ParsedProtocol(title=title, sections=[ParsedSection("General", title, tasks)])


class MemoParser(UniversalProtocolParser):
    pass


class CeoProtocolParser(UniversalProtocolParser):
    pass


class DeputyCeoProtocolParser(UniversalProtocolParser):
    pass
