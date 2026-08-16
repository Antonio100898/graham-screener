"""Write protection for when the app is reachable beyond localhost.

Reading is harmless — it is public SEC data. Writing is not: POST /sync starts a
1.4 GB download and fills ~15 GB of disk, so anyone who found a tunnel URL could
run that in a loop. When SCREENER_TOKEN is set, every mutating request must carry
it. Unset (the default), nothing changes and localhost stays frictionless.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse

HEADER = "X-Screener-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def token() -> str | None:
    return os.environ.get("SCREENER_TOKEN") or None


async def require_token(request: Request, call_next):
    expected = token()
    if expected and request.method not in SAFE_METHODS:
        supplied = request.headers.get(HEADER) or request.query_params.get("token") or ""
        # constant-time compare: a timing side channel on a shared secret is cheap to avoid
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                {"detail": "this instance is shared; changes need the access token"},
                status_code=401,
            )
    return await call_next(request)
