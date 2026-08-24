"""Dependency-free Office Open XML exporter for immutable report datasets."""

from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.reporting.models import ReportDataset


class ExcelReportExporter:
    """Serializes an already calculated dataset; it deliberately has no database access."""

    HEADERS = [
        "№ поручения",
        "Протокол / МЕМО",
        "Дата мероприятия",
        "Проект",
        "Раздел",
        "Текст",
        "Ответственный",
        "Остальные исполнители",
        "Подразделение",
        "Первоначальный срок",
        "Текущий срок",
        "Дата закрытия",
        "Статус",
        "Результат",
        "Просрочка, дней",
        "Bitrix task ID",
        "Bitrix24",
        "Протокол",
    ]

    @staticmethod
    def _cell(value, style=0, hyperlink=None):
        text = (
            ""
            if value is None
            else (value.strftime("%d.%m.%Y") if isinstance(value, date) else str(value))
        )
        return f'<c t="inlineStr" s="{style}"><is><t>{escape(text)}</t></is></c>', hyperlink

    def _view(self, dataset: ReportDataset, report_type: str):
        if report_type == "departments":
            headers = ["Подразделение", "Всего", "Выполнено", "В срок", "С нарушением", "В работе", "Просрочено", "% исполнения", "% в срок"]
            rows = [[x["name"], x["total"], x["completed"], x["on_time"], x["late"], x["in_progress"], x["overdue"], x["completion_percent"], x["on_time_percent"]] for x in dataset.departments]
            return headers, rows, []
        if report_type == "assignees":
            headers = ["№", "Мероприятие", "Проект", "Раздел", "Поручение", "Исполнитель", "Срок", "Дата закрытия", "Статус", "Отчёт", "Просрочка", "Ссылка"]
            rows, urls = [], []
            for row in dataset.rows:
                for assignee in row.assignees or ("",):
                    rows.append([row.number, row.event, row.project, row.section, row.text, assignee, row.deadline, row.closed_at, row.status_label, row.result, row.days_overdue or "", "Bitrix24" if row.bitrix_url else "Протокол"])
                    urls.append(row.bitrix_url or row.protocol_url)
            return headers, rows, urls
        rows = [[r.number, r.protocol, r.meeting_date, r.project, r.section, r.text,
                 "\n".join(r.assignees), "\n".join(r.departments), r.event,
                 r.original_deadline, r.deadline, r.closed_at, r.status_label, r.result,
                 r.days_overdue or "", "Да" if r.carried_over and r.overdue else "",
                 "Bitrix24" if r.bitrix_url else "", "Протокол"] for r in dataset.rows]
        return self.HEADERS, rows, []

    def export(self, dataset: ReportDataset, title="Отчёт по поручениям", user="system", report_type="tasks") -> bytes:
        headers, data_rows, view_urls = self._view(dataset, report_type)
        labels = {"tasks": "По поручениям", "assignees": "По исполнителям", "departments": "По подразделениям"}
        table = [
            [title, labels.get(report_type, "")],
            ["Период", f"{dataset.query.period_start or '—'} — {dataset.query.period_end or '—'}"],
            ["Фильтры", "; ".join(f"{key}: {value}" for key, value in dataset.query.as_dict().items())],
            ["Сформирован", datetime.now().strftime("%d.%m.%Y %H:%M"), "Пользователь", user],
            [],
            headers,
        ]
        links = []
        for index, values in enumerate(data_rows):
            table.append(values)
            excel_row = len(table)
            if report_type == "tasks":
                row = dataset.rows[index]
                if row.bitrix_url:
                    links.append((f"Q{excel_row}", row.bitrix_url))
                links.append((f"R{excel_row}", row.protocol_url))
            elif view_urls[index]:
                links.append((f"L{excel_row}", view_urls[index]))
        rows = []
        for row_number, values in enumerate(table, 1):
            style = 1 if row_number in (1, 6) else 0
            cells = "".join(self._cell(value, style)[0] for value in values)
            rows.append(f'<row r="{row_number}">{cells}</row>')
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{escape(url)}" TargetMode="External"/>'
            for i, (_, url) in enumerate(links, 1)
        )
        hyperlinks = "".join(
            f'<hyperlink ref="{ref}" r:id="rId{i}"/>' for i, (ref, _) in enumerate(links, 1)
        )
        last_column = chr(64 + len(headers))
        widths = [16, 30, 18, 22, 22, 55, 28, 28, 24, 18, 18, 18, 24, 40, 16, 18, 16, 16][:len(headers)]
        sheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetViews><sheetView workbookViewId="0"><pane ySplit="6" topLeftCell="A7" state="frozen"/></sheetView></sheetViews><cols>{"".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))}</cols><sheetData>{"".join(rows)}</sheetData><autoFilter ref="A6:{last_column}{len(table)}"/><hyperlinks>{hyperlinks}</hyperlinks></worksheet>"""
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>""",
            )
            archive.writestr(
                "_rels/.rels",
                """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""",
            )
            archive.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Отчёт" sheetId="1" r:id="rId1"/></sheets></workbook>""",
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>""",
            )
            archive.writestr(
                "xl/styles.xml",
                """<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font/><font><b/><color rgb="FFFFFFFF"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17365D"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1"/></xf></cellXfs></styleSheet>""",
            )
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
            archive.writestr(
                "xl/worksheets/_rels/sheet1.xml.rels",
                f"""<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>""",
            )
        return output.getvalue()
