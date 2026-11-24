"""Request context helper for audit logging and platform query tracing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request

SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def sanitize_identifier(raw_id: str | None) -> str:
    """Validate and sanitize external request/trace IDs to prevent injection."""
    if raw_id and SAFE_ID_PATTERN.match(raw_id):
        return raw_id
    return uuid4().hex[:16]


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    trace_id: str
    ip_address: str | None = None
    user_agent: str | None = None


def extract_request_context(request: Request | None) -> RequestContext:
    """Extract standard request context and trace identity from a FastAPI request.

    Security Invariant:
    - request_id: validated client-supplied header or freshly generated server ID.
    - trace_id: ALWAYS server-generated (fresh UUIDv4) for canonical trace identity.
      Client-supplied X-Trace-Id headers are ignored to prevent trace collision/poisoning.
    """
    if request is None:
        rid = uuid4().hex[:16]
        return RequestContext(request_id=rid, trace_id=f"trc_{uuid4().hex}")

    # Check if request.state already has server-generated trace_id from middleware
    server_trace_id = getattr(request.state, "trace_id", None)
    if not server_trace_id:
        server_trace_id = f"trc_{uuid4().hex}"
        try:
            request.state.trace_id = server_trace_id
        except AttributeError:
            pass

    # Extract & validate Request ID (client-supplied or generated)
    raw_request_id = getattr(request.state, "request_id", None)
    if not raw_request_id:
        raw_request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID")
    request_id = sanitize_identifier(raw_request_id)
    try:
        request.state.request_id = request_id
    except AttributeError:
        pass

    # IP Address (handling standard proxies)
    ip_address = None
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    elif request.client:
        ip_address = request.client.host

    # User Agent
    user_agent = request.headers.get("user-agent")

    return RequestContext(
        request_id=request_id,
        trace_id=server_trace_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
