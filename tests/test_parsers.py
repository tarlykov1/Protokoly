from app.parsers.protocol import ParsedDocument, ParsedParagraph, UniversalProtocolParser


def test_universal_parser_creates_basic_tasks():
    parsed = UniversalProtocolParser().parse(
        ParsedDocument("demo.docx", [ParsedParagraph(0, "Protocol"), ParsedParagraph(1, "Do work")])
    )
    assert parsed.document_title == "Protocol"
    assert parsed.tasks[0].source_text == "Do work"
