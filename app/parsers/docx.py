from __future__ import annotations

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.parsers.protocol import ParsedDocument, ParsedElement, ParsedParagraph, SourceLocation


def iter_docx_elements(doc: DocxDocument):
    p_idx = 0
    t_idx = 0
    order = 0
    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            p = Paragraph(child, doc)
            yield ParsedElement(
                order,
                p.text.strip(),
                "paragraph",
                SourceLocation(paragraph_index=p_idx),
                p.style.name if p.style else None,
            )
            p_idx += 1
            order += 1
        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            for r_idx, row in enumerate(table.rows):
                cells = tuple(cell.text.strip() for cell in row.cells)
                yield ParsedElement(
                    order,
                    " | ".join(c for c in cells if c),
                    "table_row",
                    SourceLocation(table_index=t_idx, row_index=r_idx),
                    None,
                    cells,
                )
                order += 1
            t_idx += 1


def parse_docx(path: str) -> ParsedDocument:
    doc = Document(path)
    elements = list(iter_docx_elements(doc))
    paragraphs = [
        ParsedParagraph(e.location.paragraph_index or 0, e.text)
        for e in elements
        if e.kind == "paragraph" and e.text.strip()
    ]
    return ParsedDocument(filename=path, paragraphs=paragraphs, elements=elements)
