"""Run a one-page server-side diagnostic without HTTP endpoints or data storage.

Invocation in /webapp/app:
  CONTROLLER_PILOT_ALLOWED_GROUPS='123' python3 -B /tmp/controller_timeline_v6_8_probe/probe_cli_v68.py --group-id 123

Do not put REST credentials or task data in command arguments.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from live_probe_v68 import ProbeError, probe_group


def allowed_from_env() -> frozenset[int]:
    raw = os.environ.get('CONTROLLER_PILOT_ALLOWED_GROUPS', '').strip()
    if not raw:
        raise ProbeError('CONTROLLER_PILOT_ALLOWED_GROUPS не задана')
    try:
        ids = frozenset(int(part.strip()) for part in raw.split(','))
    except ValueError as exc:
        raise ProbeError('Неверный формат списка разрешённых групп') from exc
    if not ids or any(i <= 0 for i in ids):
        raise ProbeError('Список разрешённых групп должен содержать положительные ID')
    return ids


async def run(group_id: int) -> dict:
    # The adapter already exists in the installed app; no additional credentials.
    from tools.tools import fast_bitrix

    async def call(method: str, params: dict):
        return await fast_bitrix(method, params)

    return await probe_group(call, group_id=group_id, allowed_groups=allowed_from_env())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Только чтение: первая страница задач одной разрешённой группы')
    parser.add_argument('--group-id', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(run(args.group_id)), ensure_ascii=False, indent=2))
        return 0
    except ProbeError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not print raw API exceptions: they can contain addresses/headers.
        print(json.dumps({'ok': False, 'error': 'Ошибка интеграции; проверьте журнал на сервере'}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
