from docx import Document

from app.parsers.protocol import ParsedDocument, ParsedParagraph


def parse_docx(path: str) -> ParsedDocument:
    doc = Document(path)
    paragraphs = [ParsedParagraph(index=i, text=p.text.strip()) for i, p in enumerate(doc.paragraphs) if p.text.strip()]
    return ParsedDocument(filename=path, paragraphs=paragraphs)
