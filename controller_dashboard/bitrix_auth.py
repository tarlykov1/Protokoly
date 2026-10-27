"""Fail-closed OAuth identity and workgroup membership checks for embedded Bitrix24 dashboards.

Never trust client-submitted user IDs or unsigned proxy identity headers.
"""
import asyncio
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from fastapi import HTTPException


def call_bitrix(host: str, method: str, access_token: str, params=None):
    if not host or '/' in host or ':' in host or '.' not in host:
        raise HTTPException(503, "Bitrix portal is not configured")
    if method not in ('user.current', 'sonet_group.user.get'):
        raise ValueError("Unsupported method")
    payload = dict(params or {}, auth=access_token)
    request = Request(
        f"https://{host}/rest/{method}.json",
        data=urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read(1000000))
    except Exception as error:
        raise HTTPException(401, "Bitrix verification failed") from error
    if data.get("error") or "result" not in data:
        raise HTTPException(403, "Bitrix access denied")
    return data["result"]


async def verify_user_and_group(host: str, token: str, group_id: int):
    user = await asyncio.to_thread(call_bitrix, host, "user.current", token)
    if not isinstance(user, dict) or not str(user.get("ID", "")).isdigit():
        raise HTTPException(403, "User not confirmed")
    members = await asyncio.to_thread(
        call_bitrix, host, "sonet_group.user.get", token, {"ID": group_id}
    )
    user_id = str(user["ID"])
    if not isinstance(members, list) or not any(
        str(member.get("USER_ID")) == user_id for member in members
        if isinstance(member, dict)
    ):
        raise HTTPException(403, "No group access")
    return user_id
