"""Attach group-734 aggregate views to the ALREADY isolated pilot router.

The only data endpoint uses the same Bearer authorization as pilot history.
No live Bitrix REST calls are made from HTTP handlers.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

try:
    from .group734_v71 import SnapshotError, read_snapshot
except ImportError:  # local standalone tests
    from group734_v71 import SnapshotError, read_snapshot


def register_routes(router: APIRouter, authorize: Callable[[str | None], None], root: Path) -> None:
    @router.get("/overview/group734/data")
    def group734_data(authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return read_snapshot(root / "data" / "group734_summary_v71.json")
        except SnapshotError as exc:
            raise HTTPException(503, str(exc)) from None

    @router.get("/overview/group734/")
    def group734_page():
        return FileResponse(root / "dashboard_group734_v71.html", media_type="text/html",
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'none'"})

    @router.get("/overview/group734/app.js")
    def group734_js():
        return FileResponse(root / "dashboard_group734_v71.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-store"})

    @router.get("/overview/group734/styles.css")
    def group734_css():
        return FileResponse(root / "dashboard_group734_v71.css", media_type="text/css",
                            headers={"Cache-Control": "no-store"})
