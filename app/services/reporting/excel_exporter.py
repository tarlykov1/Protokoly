"""Corporate Office Open XML reports rendered from the canonical reporting dataset."""

from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.reporting.models import ReportDataset


class ExcelReportExporter:
    """Serialize calculated rows without querying or reimplementing reporting rules."""

    CELL_TEXT_LIMIT = 30_000
    HEADERS = [
        "№ поручения", "Мероприятие", "Протокол / МЕМО", "Дата документа",
        "Проект / группа", "Поручение", "Исполнители", "Плановый срок",
        "Фактическая дата результата", "Дата закрытия", "Статус", "Выполнено",
        "Отчёт", "Теги", "Просрочка, дней", "Ссылка", "Раздел", "ID",
    ]
    ASSIGNEE_HEADERS = [
        "№ поручения", "Мероприятие", "Протокол", "Дата документа", "Проект / группа",
        "Исполнитель", "Срок", "Дата закрытия", "Статус", "Отчёт", "Теги", "Ссылка", "ID",
    ]

    @staticmethod
    def _column(index: int) -> str:
        value = ""
        while index:
            index, rem = divmod(index - 1, 26)
            value = chr(65 + rem) + value
        return value

    @staticmethod
    def _text(value) -> str:
        if value is None or str(value).strip().lower() in {"none", "null", "undefined"}:
            return ""
        return value.strftime("%d.%m.%Y") if isinstance(value, date) else str(value)

    def _view(self, dataset: ReportDataset, report_type: str):
        if report_type == "departments":
            headers = ["Подразделение", "Всего", "Выполнено", "В срок", "С нарушением", "В работе", "Просрочено", "% исполнения", "% в срок"]
            rows = [[x["name"], x["total"], x["completed"], x["on_time"], x["late"], x["in_progress"], x["overdue"], x["completion_percent"], x["on_time_percent"]] for x in dataset.departments]
            return headers, rows, []
        if report_type == "assignees":
            rows, urls = [], []
            for row in dataset.rows:
                links = dict(row.assignee_links)
                for assignee in row.assignees or ("",):
                    rows.append([
                        row.number, row.event, row.protocol, row.meeting_date, row.project, assignee,
                        row.deadline, row.closed_at, row.status_label, row.result,
                        "\n".join(dict.fromkeys(tag for tag in row.tags if tag.strip())),
                        "Открыть", row.bitrix_task_id or row.task_id,
                    ])
                    urls.append(links.get(assignee) or row.bitrix_url or row.protocol_url)
            return self.ASSIGNEE_HEADERS, rows, urls
        rows = []
        for row in dataset.rows:
            rows.append([
                row.number, row.event, row.protocol, row.meeting_date, row.project, row.text,
                "\n".join(row.assignees), row.deadline, row.closed_at, row.closed_at,
                row.status_label, f"{row.completed_parts}/{row.required_parts}", row.result,
                "\n".join(dict.fromkeys(tag for tag in row.tags if tag.strip())),
                row.days_overdue or "", "Открыть", row.section,
                row.assignment_root_id or row.task_id,
            ])
        return self.HEADERS, rows, []

    def _sheet_xml(self, table, hyperlinks, widths, freeze=6):
        rows_xml = []
        for row_number, values in enumerate(table, 1):
            cells = []
            for column_number, value in enumerate(values, 1):
                ref = f"{self._column(column_number)}{row_number}"
                style = 1 if row_number in {1, 6} else 2
                cells.append(f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{escape(self._text(value))}</t></is></c>')
            rows_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
        hyperlink_parts, external_index = [], 0
        for ref, target, internal in hyperlinks:
            if not target:
                continue
            if internal:
                hyperlink_parts.append(f'<hyperlink ref="{ref}" location={quoteattr(target)}/>')
            else:
                external_index += 1
                hyperlink_parts.append(f'<hyperlink ref="{ref}" r:id="rId{external_index}"/>')
        hyperlink_xml = "".join(hyperlink_parts)
        max_col = self._column(max((len(r) for r in table), default=1))
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetViews><sheetView workbookViewId="0" tabSelected="1"><selection activeCell="A1" sqref="A1"/><pane ySplit="{freeze}" topLeftCell="A{freeze + 1}" state="frozen"/></sheetView></sheetViews><cols>{"".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))}</cols><sheetData>{"".join(rows_xml)}</sheetData><autoFilter ref="A6:{max_col}{len(table)}"/><hyperlinks>{hyperlink_xml}</hyperlinks><pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>'''

    def export(self, dataset: ReportDataset, title="Отчёт по поручениям", user="system", report_type="tasks") -> bytes:
        headers, data_rows, view_urls = self._view(dataset, report_type)
        labels = {"tasks": "По поручениям", "assignees": "По исполнителям", "departments": "По подразделениям"}
        table = [[title, labels.get(report_type, "")], ["Период", f"{dataset.query.period_start or '—'} — {dataset.query.period_end or '—'}"], ["Проект / группа", dataset.query.project or "Все"], ["Сформирован", datetime.now().strftime("%d.%m.%Y %H:%M"), "Пользователь", user], [], headers]
        links = []
        continuations = [["Строка", "№ поручения", "Продолжение отчёта"]]
        performer_tasks = [["№ поручения", "Исполнитель", "Задача"]]
        for index, values in enumerate(data_rows):
            excel_row = len(table) + 1
            values = list(values)
            if report_type == "tasks":
                source = dataset.rows[index]
                report_col = 13
                report = self._text(values[report_col - 1])
                if len(report) > self.CELL_TEXT_LIMIT:
                    continuation_row = len(continuations) + 1
                    values[report_col - 1] = report[:self.CELL_TEXT_LIMIT - 80] + "\nПродолжение →"
                    continuations.append([excel_row, source.number, report[self.CELL_TEXT_LIMIT - 80:]])
                    links.append((f"M{excel_row}", f"'Полные отчеты'!C{continuation_row}", True))
                if len(source.assignee_links) > 1:
                    first = len(performer_tasks) + 1
                    for person, url in source.assignee_links:
                        performer_tasks.append([source.number, person, "Открыть"])
                        if url:
                            # Relationships are created per sheet below.
                            pass
                    links.append((f"P{excel_row}", f"'Задачи исполнителей'!A{first}", True))
                else:
                    links.append((f"P{excel_row}", source.bitrix_url or source.protocol_url, False))
                links.append((f"R{excel_row}", source.assignment_root_url or source.bitrix_url or source.protocol_url, False))
            elif report_type == "assignees" and view_urls[index]:
                links.extend([(f"L{excel_row}", view_urls[index], False), (f"M{excel_row}", view_urls[index], False)])
            table.append(values)

        sheets = [("Задачи", table, links)]
        if len(continuations) > 1:
            sheets.append(("Полные отчеты", continuations, []))
        if len(performer_tasks) > 1:
            performer_links = []
            lookup = {(r.number, person): url for r in dataset.rows for person, url in r.assignee_links}
            for i, values in enumerate(performer_tasks[1:], 2):
                url = lookup.get((values[0], values[1]), "")
                if url:
                    performer_links.append((f"C{i}", url, False))
            sheets.append(("Задачи исполнителей", performer_tasks, performer_links))

        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
            archive.writestr("[Content_Types].xml", f'''<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{overrides}</Types>''')
            archive.writestr("_rels/.rels", '''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
            sheet_defs = "".join(f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>' for i, (name, _, _) in enumerate(sheets, 1))
            archive.writestr("xl/workbook.xml", f'''<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView activeTab="0"/></bookViews><sheets>{sheet_defs}</sheets></workbook>''')
            rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
            rels += f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            archive.writestr("xl/_rels/workbook.xml.rels", f'''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>''')
            archive.writestr("xl/styles.xml", '''<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="10"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17365D"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEAF2F8"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1"/></xf><xf fillId="3" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs></styleSheet>''')
            for i, (_, sheet_table, sheet_links) in enumerate(sheets, 1):
                widths = [16, 30, 28, 18, 24, 55, 30, 18, 18, 18, 24, 14, 55, 24, 16, 16, 22, 14][:max(len(r) for r in sheet_table)]
                archive.writestr(f"xl/worksheets/sheet{i}.xml", self._sheet_xml(sheet_table, sheet_links, widths, 6 if i == 1 else 1))
                external = [(ref, target) for ref, target, internal in sheet_links if not internal and target]
                if external:
                    relationships = "".join(f'<Relationship Id="rId{j}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target={quoteattr(url)} TargetMode="External"/>' for j, (_, url) in enumerate(external, 1))
                    archive.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels", f'''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>''')
        return output.getvalue()
