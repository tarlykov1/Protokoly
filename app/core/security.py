from __future__ import annotations

import logging
import secrets
import time
import uuid
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

CSRF_SESSION_KEY = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
logger = logging.getLogger("app.requests")


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def csrf_protect(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    if "session" not in request.scope:
        request.scope["session"] = {}
    expected = request.session.get(CSRF_SESSION_KEY)
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        body = await request.body()
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type:
            supplied = (parse_qs(body.decode()).get("csrf_token") or [""])[0]
        elif b'name="csrf_token"' in body:
            marker = b'name="csrf_token"'
            supplied = body.split(marker, 1)[1].split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0].decode(errors="ignore")
        else:
            supplied = ""
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; font-src 'self' https://cdn.jsdelivr.net data:; connect-src 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


class RequestIDLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            logger.exception(
                "request failed",
                extra={"request_id": request_id, "method": request.method, "path": request.url.path},
            )
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        response.headers["X-Request-ID"] = request_id
        return response


def csrf_exception_handler(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 403:
        return JSONResponse({"detail": exc.detail}, status_code=403)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

import base64
import hashlib
import hmac
import json


class SimpleSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret_key: str, max_age: int, same_site: str = "lax", https_only: bool = False):
        super().__init__(app)
        self.secret_key = secret_key.encode()
        self.max_age = max_age
        self.same_site = same_site
        self.https_only = https_only

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.secret_key, payload, hashlib.sha256).hexdigest()

    def _decode(self, value: str) -> dict:
        try:
            raw, sig = value.split('.', 1)
            payload = base64.urlsafe_b64decode(raw.encode())
            if not hmac.compare_digest(self._sign(payload), sig):
                return {}
            return json.loads(payload.decode())
        except Exception:
            return {}

    def _encode(self, data: dict) -> str:
        payload = json.dumps(data, separators=(',', ':')).encode()
        raw = base64.urlsafe_b64encode(payload).decode()
        return f"{raw}.{self._sign(payload)}"

    async def dispatch(self, request: Request, call_next):
        request.scope['session'] = self._decode(request.cookies.get('session', ''))
        try:
            await csrf_protect(request)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        response = await call_next(request)
        response.set_cookie(
            'session',
            self._encode(request.session),
            max_age=self.max_age,
            httponly=True,
            samesite=self.same_site,
            secure=self.https_only,
        )
        return response
