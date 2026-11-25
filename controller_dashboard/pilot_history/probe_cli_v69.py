"""Read-only v6.9 group pagination. Requires configured group allowlist.

Usage: CONTROLLER_PILOT_ALLOWED_GROUPS=446 python3 -B probe_cli_v69.py --group-id 446
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from full_group_probe_v69 import MAX_PAGES, ProbeError, probe_full_group
from probe_cli_v68 import allowed_from_env, call_client


async def main_async(group_id: int, max_pages: int) -> dict:
    try:
        from tools.tools import fast_bitrix
    except Exception as exc:
        raise ProbeError(f"Ошибка импорта клиента ({type(exc).__name__})") from None

    async def invoke(method: str, params: dict):
        # v6.8 call_client already sends raw=True and supports sync/async.
        return await call_client(fast_bitrix, method, params)

    return await probe_full_group(
        invoke, group_id=group_id, allowed_groups=allowed_from_env(),
        max_pages=max_pages,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Чтение до 10 страниц одной разрешённой группы Б24")
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()
    try:
        result = asyncio.run(main_async(args.group_id, args.max_pages))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ProbeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": "Неожиданная ошибка диагностики",
            "kind": type(exc).__name__,
        }, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
