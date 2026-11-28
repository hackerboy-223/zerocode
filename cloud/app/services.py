import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .database import SessionLocal
from .models import AuditLog, CloudSetting, Device, ModelRoute, Provider, RoutingPolicy, UsageEvent, User
from .schemas import ChatRequest
from .security import (
    DUMMY_PASSWORD_HASH,
    decrypt_secret,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    verify_password,
)

TASK_PATTERNS = {
    "security": r"security|sécurit|pentest|audit|owasp|vulnérab|injection|xss|sqli|ssrf|cve",
    "architecture": r"architecture|architect|refactor|raisonnement|analyse|design|migration|complexe|debug",
    "sysadmin": r"linux|serveur|server|docker|nginx|réseau|network|ssh|devops|systemd|deploy",
    "coding": r"code|coder|bug|corrig|test|build|implément|projet|project|api|python|javascript|typescript|fichier|file",
}
VALID_TASKS = {"coding", "architecture", "security", "sysadmin", "vision", "fast"}


def classify_task(messages: list[dict[str, Any]]) -> str:
    last_user = next((item for item in reversed(messages) if item.get("role") == "user"), {})
    content = last_user.get("content", "")
    if isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") in {"image_url", "input_image"}
        for item in content
    ):
        return "vision"
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    lowered = content.lower()
    for task, pattern in TASK_PATTERNS.items():
        if re.search(pattern, lowered):
            return task
    return "fast"


def validate_provider_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" and not (
        get_settings().allow_local_provider_urls
        and parsed.scheme == "http"
    ):
        raise ValueError("Provider URL must use HTTPS; local HTTP is development-only")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid provider base URL")
    host = parsed.hostname.lower().rstrip(".")
    local_hosts = {"localhost", "localhost.localdomain"}
    if host in local_hosts or host.endswith((".local", ".internal")):
        if not get_settings().allow_local_provider_urls:
            raise ValueError("Local provider hosts are disabled")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global and not get_settings().allow_local_provider_urls:
        raise ValueError("Private, loopback, link-local or reserved provider IPs are disabled")

    # Reject domains that resolve to private addresses at registration time too.
    # Redirects are disabled for upstream calls; production egress policy should
    # additionally restrict provider traffic to approved destinations.
    if not get_settings().allow_local_provider_urls:
        try:
            addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("Provider hostname could not be resolved") from exc
        for item in addresses:
            resolved = ipaddress.ip_address(item[4][0])
            if not resolved.is_global:
                raise ValueError("Provider hostname resolves to a non-public address")
    return value.strip().rstrip("/")


def audit(
    db: Session,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )


def issue_login_tokens(db: Session, user: User, device_name: str) -> dict[str, Any]:
    raw_refresh = new_refresh_token()
    now = datetime.now(timezone.utc)
    device = Device(
        user_id=user.id,
        name=device_name.strip()[:120] or "ZeroCode device",
        refresh_token_hash=hash_refresh_token(raw_refresh),
        refresh_expires_at=now + timedelta(days=get_settings().refresh_token_days),
        last_seen_at=now,
    )
    db.add(device)
    db.flush()
    access, access_expires = issue_access_token(user.id, user.role, device.id)
    db.commit()
    return {
        "token_type": "bearer",
        "access_token": access,
        "access_expires_at": access_expires.isoformat(),
        "refresh_token": raw_refresh,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "plan_code": "free",
        },
    }


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    valid = verify_password(password, password_hash)
    return user if user and valid and user.is_active else None


def refresh_login(db: Session, raw_token: str) -> dict[str, Any]:
    device = db.scalar(
        select(Device).where(Device.refresh_token_hash == hash_refresh_token(raw_token))
    )
    now = datetime.now(timezone.utc)
    expires = None
    if device and device.refresh_expires_at:
        expires = device.refresh_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    if not device or device.is_revoked or not expires or expires <= now:
        raise HTTPException(status_code=401, detail="Refresh token invalid or expired")
    user = db.get(User, device.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")

    replacement = new_refresh_token()
    device.refresh_token_hash = hash_refresh_token(replacement)
    device.refresh_expires_at = now + timedelta(days=get_settings().refresh_token_days)
    device.last_seen_at = now
    access, access_expires = issue_access_token(user.id, user.role, device.id)
    db.commit()
    return {
        "token_type": "bearer",
        "access_token": access,
        "access_expires_at": access_expires.isoformat(),
        "refresh_token": replacement,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "plan_code": "free",
        },
    }


def list_candidates(
    db: Session,
    requested_model: str,
    task_type: str,
    has_tools: bool,
    has_vision: bool,
) -> list[ModelRoute]:
    query = (
        select(ModelRoute)
        .options(joinedload(ModelRoute.provider))
        .join(Provider)
        .where(ModelRoute.is_enabled.is_(True), Provider.is_enabled.is_(True))
    )
    if has_tools:
        query = query.where(ModelRoute.supports_tools.is_(True))
    if has_vision:
        query = query.where(ModelRoute.supports_vision.is_(True))
    if requested_model != "auto":
        query = query.where(ModelRoute.alias == requested_model)
        return list(db.scalars(query.order_by(ModelRoute.priority.asc())).unique())

    policy = db.get(RoutingPolicy, task_type) or db.get(RoutingPolicy, "auto")
    if policy and policy.model_aliases:
        order = {alias: index for index, alias in enumerate(policy.model_aliases)}
        rows = list(db.scalars(query.where(ModelRoute.alias.in_(policy.model_aliases))).unique())
        return sorted(rows, key=lambda item: (order.get(item.alias, 999), item.priority))

    rows = list(db.scalars(query).unique())
    return sorted(rows, key=lambda item: (0 if task_type in (item.task_types or []) else 1, item.priority))


def write_usage(
    db: Session,
    *,
    user_id: str,
    device_id: str,
    request_id: str,
    task_type: str,
    requested_model: str,
    route: ModelRoute,
    usage: dict[str, Any] | None,
    latency_ms: int,
    success: bool,
    error_code: str | None = None,
) -> None:
    usage = usage or {}
    prompt = max(0, int(usage.get("prompt_tokens") or 0))
    completion = max(0, int(usage.get("completion_tokens") or 0))
    total = max(0, int(usage.get("total_tokens") or prompt + completion))
    db.add(
        UsageEvent(
            request_id=request_id,
            user_id=user_id,
            device_id=device_id,
            task_type=task_type,
            requested_model=requested_model,
            model_alias=route.alias,
            provider_name=route.provider.name,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            latency_ms=max(0, latency_ms),
            success=success,
            error_code=error_code,
        )
    )
    db.commit()


def parse_usage_line(line: str, usage: dict[str, Any]) -> None:
    if not line.startswith("data:"):
        return
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return
    if isinstance(payload.get("usage"), dict):
        usage.update(payload["usage"])


class UpstreamError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


def record_usage_safely(**kwargs: Any) -> None:
    try:
        with SessionLocal() as session:
            write_usage(session, **kwargs)
    except Exception:
        # Usage telemetry must never break an otherwise successful model stream.
        return


async def proxy_chat(
    *,
    db: Session,
    user: User,
    device: Device,
    request: ChatRequest,
    request_id: str,
) -> tuple[dict[str, Any] | None, AsyncIterator[bytes] | None, str]:
    task_type = classify_task(request.messages)
    extra = request.model_extra or {}
    has_tools = bool(extra.get("tools"))
    candidates = list_candidates(db, request.model, task_type, has_tools, task_type == "vision")
    if not candidates:
        raise HTTPException(status_code=503, detail="No eligible model route is configured")

    def usage_args(route: ModelRoute, usage: dict[str, Any], started: float, success: bool, error: str | None = None) -> dict[str, Any]:
        return {
            "user_id": user.id,
            "device_id": device.id,
            "request_id": request_id,
            "task_type": task_type,
            "requested_model": request.model,
            "route": route,
            "usage": usage,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "success": success,
            "error_code": error,
        }

    async def stream_candidate(route: ModelRoute) -> AsyncIterator[bytes]:
        secret = decrypt_secret(route.provider.encrypted_api_key)
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if secret:
            headers["Authorization"] = "Bearer " + secret
        payload = request.upstream_payload(route.model_name)
        started = time.monotonic()
        usage: dict[str, Any] = {}
        try:
            timeout = httpx.Timeout(get_settings().upstream_timeout_seconds, connect=15)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    route.provider.base_url + "/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise UpstreamError(response.status_code)
                    async for line in response.aiter_lines():
                        parse_usage_line(line, usage)
                        yield (line + "\n").encode("utf-8")
            record_usage_safely(**usage_args(route, usage, started, True))
        except Exception:
            record_usage_safely(**usage_args(route, usage, started, False, "upstream_stream_error"))
            raise

    if request.stream:
        async def stream_with_fallback() -> AsyncIterator[bytes]:
            errors: list[str] = []
            for route in candidates:
                delivered_bytes = False
                try:
                    async for chunk in stream_candidate(route):
                        delivered_bytes = True
                        yield chunk
                    return
                except UpstreamError as exc:
                    errors.append(f"{route.alias}: HTTP {exc.status_code}")
                except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError):
                    errors.append(f"{route.alias}: connection failure")
                except Exception:
                    errors.append(f"{route.alias}: stream interrupted")
                if delivered_bytes:
                    error_payload = {
                        "error": {
                            "message": "The upstream stream was interrupted; retry this turn.",
                            "type": "upstream_stream_error",
                        }
                    }
                    yield ("data: " + json.dumps(error_payload) + "\n\n").encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return
            error_payload = {"error": {"message": "All configured model routes failed", "attempts": errors}}
            yield ("data: " + json.dumps(error_payload) + "\n\n").encode("utf-8")
            yield b"data: [DONE]\n\n"

        return None, stream_with_fallback(), task_type

    errors: list[str] = []
    for route in candidates:
        secret = decrypt_secret(route.provider.encrypted_api_key)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if secret:
            headers["Authorization"] = "Bearer " + secret
        started = time.monotonic()
        try:
            timeout = httpx.Timeout(get_settings().upstream_timeout_seconds, connect=15)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(
                    route.provider.base_url + "/chat/completions",
                    headers=headers,
                    json=request.upstream_payload(route.model_name),
                )
            if response.status_code < 200 or response.status_code >= 300:
                errors.append(f"{route.alias}: HTTP {response.status_code}")
                record_usage_safely(**usage_args(route, {}, started, False, "upstream_http_error"))
                continue
            result = response.json()
            write_usage(
                db,
                user_id=user.id,
                device_id=device.id,
                request_id=request_id,
                task_type=task_type,
                requested_model=request.model,
                route=route,
                usage=result.get("usage"),
                latency_ms=int((time.monotonic() - started) * 1000),
                success=True,
            )
            result["model"] = route.alias
            return result, None, task_type
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError):
            errors.append(f"{route.alias}: connection failure")
            record_usage_safely(**usage_args(route, {}, started, False, "upstream_connection_error"))
    raise HTTPException(status_code=502, detail={"message": "All model routes failed", "attempts": errors})
