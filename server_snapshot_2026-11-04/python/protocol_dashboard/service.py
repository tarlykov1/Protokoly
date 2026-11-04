from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timezone
from . import store
from .adapter import build_dashboard, upload_original_excel

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='protocol-dashboard')

def _work_dashboard(report_id):
    meta=store.load(report_id); params=meta['params']; user_id=meta['user_id']
    try:
        store.update(report_id,status='processing',progress=10,stage='Получение данных из Битрикс24')
        result=asyncio.run(build_dashboard(params,user_id))
        if result.get('status') not in ('ok','no_data'):
            raise RuntimeError(result.get('message') or 'Ошибка формирования')
        rows=result.get('dashboard_rows') or []
        columns = rows[0].get('_excel_headers', []) if rows else []
        for row in rows:
            row.pop('_excel_headers', None)
        generated_at=datetime.now(timezone.utc).isoformat()
        store.save_data(report_id,{
            'rows':rows,
            'meta':{
                'excel_status':'not_requested',
                'file_url':None,
                'cached_excel_path':result.get('cached_excel_path'),
                'generated_at':generated_at,
                'columns':columns,
                'params':params,
            }
        })
        store.update(
            report_id,status='ready',progress=100,stage='Дашборд готов',
            records=len(rows),excel_status='not_requested',file_url=None,
            generated_at=generated_at
        )
    except Exception as exc:
        store.update(report_id,status='error',progress=100,stage='Ошибка',error=str(exc))

def _work_excel(report_id):
    meta=store.load(report_id); params=meta['params']; user_id=meta['user_id']
    try:
        store.update(report_id,excel_status='processing',excel_stage='Формирование исходного Excel v40/v24')
        data=store.load_data(report_id)
        cached_path=(data.get('meta') or {}).get('cached_excel_path')
        result=asyncio.run(upload_original_excel(params,user_id,cached_path))
        if result.get('status')!='ok' or not result.get('file_url'):
            raise RuntimeError(result.get('message') or 'Excel не сформирован')
        store.update(report_id,excel_status='ready',excel_stage='Excel готов',file_url=result['file_url'])
        data=store.load_data(report_id); data.setdefault('meta',{})['file_url']=result['file_url']; data['meta']['excel_status']='ready'; store.save_data(report_id,data)
    except Exception as exc:
        store.update(report_id,excel_status='error',excel_stage='Ошибка Excel',excel_error=str(exc))

def enqueue_dashboard(report_id):
    store.cleanup(); _executor.submit(_work_dashboard,report_id)

def enqueue_excel(report_id):
    _executor.submit(_work_excel,report_id)
