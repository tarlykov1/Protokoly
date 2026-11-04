from custom_webhooks.ExcelEOSProtocols import (
    create_report as eos_create_report, upload_dashboard_excel as eos_upload_dashboard_excel
)
from custom_webhooks.ExcelMEMO import (
    create_report as memo_create_report, upload_dashboard_excel as memo_upload_dashboard_excel
)

def _map(params, user_id):
    kind=params.get('report_type')
    if kind=='eos':
        mode=params.get('mode') or 'assignments'
        return eos_create_report, dict(
            user_id=user_id, report_name='Дашборд протокольных поручений',
            report_type='assignment' if mode in ('assignments','assignment') else 'executor',
            group_selection=params.get('group_ids') or ['all'],
            responsible_ids=params.get('user_ids') or [],
            event_filter=params.get('event_filter'),
            date_from=params.get('date_from'), date_to=params.get('date_to'))
    return memo_create_report, dict(
        user_id=user_id, report_type=params.get('mode') or 'all',
        event_filter=params.get('event_filter'), responsible_ids=params.get('user_ids') or [],
        date_from=params.get('date_from'), date_to=params.get('date_to'))

async def build_dashboard(params,user_id):
    fn,kwargs=_map(params,user_id)
    return await fn(**kwargs,dashboard_only=True)

async def upload_original_excel(params,user_id,cached_excel_path):
    if params.get('report_type')=='eos':
        return await eos_upload_dashboard_excel(user_id,cached_excel_path)
    return await memo_upload_dashboard_excel(user_id,cached_excel_path)
