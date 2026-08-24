from datetime import date
from io import BytesIO
from zipfile import ZipFile

from app.services.reporting.excel_exporter import ExcelReportExporter
from app.services.reporting.metrics import include_in_weekly_report
from app.services.reporting.models import ReportDataset, ReportQuery, TaskReportRow

START = date(2026, 9, 8)
END = date(2026, 9, 14)


def included(deadline, closed=None, status="new", **kwargs):
    return include_in_weekly_report(
        deadline=deadline,
        closed_at=closed,
        status=status,
        period_start=START,
        period_end=END,
        **kwargs,
    )


def test_weekly_due_open():
    assert included(date(2026, 9, 10))


def test_weekly_due_closed():
    assert included(date(2026, 9, 10), date(2026, 9, 11), "completed")


def test_weekly_future_due_closed_now():
    assert included(date(2026, 9, 30), date(2026, 9, 12), "completed")


def test_weekly_old_overdue_open():
    assert included(date(2026, 9, 1))


def test_weekly_old_overdue_closed_now():
    assert included(date(2026, 9, 1), date(2026, 9, 12), "completed")


def test_weekly_deferred_excluded():
    assert not included(date(2026, 9, 10), deferred=True)


def test_weekly_unmarked_subtask_excluded():
    assert not included(date(2026, 9, 10), is_subtask=True, include_in_report=False)


def test_weekly_marked_subtask_included():
    assert included(date(2026, 9, 10), is_subtask=True, include_in_report=True)


def test_excel_uses_exact_dataset_and_preserves_business_number():
    row = TaskReportRow(
        1,
        "06.1",
        1,
        "Протокол",
        "protocol",
        START,
        "Проект",
        "Раздел",
        "Текст",
        "Иванов",
        "",
        "Отдел",
        START,
        END,
        None,
        "new",
        "",
        0,
        "",
        "",
        "",
        "/protocols/1",
    )
    dataset = ReportDataset(ReportQuery(period_start=START, period_end=END), [row], {"tasks": 1})
    data = ExcelReportExporter().export(dataset)
    with ZipFile(BytesIO(data)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "06.1" in sheet
    assert 'autoFilter ref="A6:R7"' in sheet
