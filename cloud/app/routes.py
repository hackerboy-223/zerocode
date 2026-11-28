from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from .config import get_settings
from .dependencies import AdminPrincipal, CurrentPrincipal, DbSession
from .models import AuditLog, CloudSetting, Device, ModelRoute, Provider, RoutingPolicy, UsageEvent, User
from .schemas import (
    ChatRequest,
    ClientConfigPatch,
    LoginIn,
    ModelCreate,
    ModelPatch,
    ProviderCreate,
    ProviderPatch,
    RefreshIn,
    RegisterIn,
    RoutingPolicyIn,
)
from .security import encrypt_secret, hash_password, hash_refresh_token
from .services import (
    audit,
    authenticate_user,
    issue_login_tokens,
    proxy_chat,
    refresh_login,
    validate_provider_url,
)

router = APIRouter()


@router.get("/health/live", tags=["health"])
def live() -> dict:
    return {"status": "ok", "service": "zerocode-cloud"}


@router.get("/health/ready", tags=["health"])
def ready(db: DbSession) -> dict:
    db.execute(select(1))
    return {"status": "ready", "database": "connected"}


@router.post("/auth/register", status_code=201, tags=["authentication"])
def register(payload: RegisterIn, db: DbSession) -> dict:
    if not get_settings().allow_public_signup:
        raise HTTPException(status_code=403, detail="Public registration is currently closed")
    email = str(payload.email).strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, password_hash=hash_password(payload.password), role="user", is_active=True)
    db.add(user)
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role, "message": "Account created. You can now sign in."}


@router.post("/auth/login", tags=["authentication"])
def login(payload: LoginIn, db: DbSession) -> dict:
    user = authenticate_user(db, str(payload.email), payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return issue_login_tokens(db, user, payload.device_name)


@router.post("/auth/refresh", tags=["authentication"])
def refresh(payload: RefreshIn, db: DbSession) -> dict:
    return refresh_login(db, payload.refresh_token)


@router.post("/auth/logout", tags=["authentication"])
def logout(principal: CurrentPrincipal, db: DbSession) -> dict:
    device = db.get(Device, principal.device.id)
    if device:
        device.is_revoked = True
        device.refresh_token_hash = hash_refresh_token(str(uuid4()))
        db.commit()
    return {"status": "signed_out"}


@router.get("/auth/me", tags=["authentication"])
def me(principal: CurrentPrincipal) -> dict:
    user = principal.user
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "device": {"id": principal.device.id, "name": principal.device.name},
    }


@router.get("/auth/devices", tags=["authentication"])
def devices(principal: CurrentPrincipal, db: DbSession) -> list[dict]:
    rows = db.scalars(
        select(Device).where(Device.user_id == principal.user.id).order_by(Device.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "is_current": row.id == principal.device.id,
            "is_revoked": row.is_revoked,
            "created_at": row.created_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
        }
        for row in rows
    ]


@router.delete("/auth/devices/{device_id}", tags=["authentication"])
def revoke_device(device_id: str, principal: CurrentPrincipal, db: DbSession) -> dict:
    device = db.scalar(
        select(Device).where(Device.id == device_id, Device.user_id == principal.user.id)
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_revoked = True
    device.refresh_token_hash = hash_refresh_token(str(uuid4()))
    db.commit()
    return {"status": "revoked", "device_id": device_id}


@router.get("/client/config", tags=["client"])
def client_config(principal: CurrentPrincipal, db: DbSession) -> dict:
    setting = db.get(CloudSetting, "client")
    value = setting.value if setting else {}
    models = db.scalars(
        select(ModelRoute)
        .join(Provider)
        .where(ModelRoute.is_enabled.is_(True), Provider.is_enabled.is_(True))
        .order_by(ModelRoute.priority)
    ).all()
    return {
        "config_version": setting.version if setting else 1,
        "maintenance_mode": bool(value.get("maintenance_mode", False)),
        "client_min_version": value.get("client_min_version", get_settings().client_min_version),
        "feature_flags": value.get("feature_flags", {"cloud_ai": True, "remote_config": True}),
        "models": [
            {
                "alias": item.alias,
                "task_types": item.task_types,
                "supports_tools": item.supports_tools,
                "supports_vision": item.supports_vision,
            }
            for item in models
        ],
        "account": {"plan": "free"},
    }


@router.post("/chat/completions", tags=["ai gateway"])
async def chat_completions(payload: ChatRequest, principal: CurrentPrincipal, db: DbSession):
    request_id = str(uuid4())
    setting = db.get(CloudSetting, "client")
    if setting and setting.value.get("maintenance_mode"):
        raise HTTPException(status_code=503, detail="ZeroCode Cloud is in maintenance mode")

    result, stream, task_type = await proxy_chat(
        db=db,
        user=principal.user,
        device=principal.device,
        request=payload,
        request_id=request_id,
    )
    if stream is not None:
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-ZeroCode-Request-ID": request_id,
                "X-ZeroCode-Task": task_type,
            },
        )
    return result


@router.get("/admin/providers", tags=["administration"])
def get_providers(_: AdminPrincipal, db: DbSession) -> list[dict]:
    items = db.scalars(select(Provider).order_by(Provider.name)).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "base_url": item.base_url,
            "is_enabled": item.is_enabled,
            "has_api_key": bool(item.encrypted_api_key),
        }
        for item in items
    ]


@router.post("/admin/providers", status_code=201, tags=["administration"])
def create_provider(payload: ProviderCreate, principal: AdminPrincipal, db: DbSession) -> dict:
    if db.scalar(select(Provider).where(Provider.name == payload.name)):
        raise HTTPException(status_code=409, detail="Provider name already exists")
    try:
        base_url = validate_provider_url(payload.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    secret = payload.api_key.get_secret_value() if payload.api_key else None
    provider = Provider(
        name=payload.name,
        base_url=base_url,
        encrypted_api_key=encrypt_secret(secret) if secret else None,
        is_enabled=payload.is_enabled,
    )
    db.add(provider)
    db.flush()
    audit(
        db, principal.user, "provider.create", "provider", provider.id,
        {"name": provider.name, "base_url": provider.base_url},
    )
    db.commit()
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "is_enabled": provider.is_enabled,
        "has_api_key": bool(provider.encrypted_api_key),
    }


@router.patch("/admin/providers/{provider_id}", tags=["administration"])
def update_provider(
    provider_id: str, payload: ProviderPatch, principal: AdminPrincipal, db: DbSession
) -> dict:
    provider = db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("base_url") is not None:
        try:
            provider.base_url = validate_provider_url(changes["base_url"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.api_key:
        provider.encrypted_api_key = encrypt_secret(payload.api_key.get_secret_value())
    if changes.get("is_enabled") is not None:
        provider.is_enabled = changes["is_enabled"]
    audit(db, principal.user, "provider.update", "provider", provider.id, {"fields": sorted(changes)})
    db.commit()
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "is_enabled": provider.is_enabled,
        "has_api_key": bool(provider.encrypted_api_key),
    }


@router.post("/admin/models", status_code=201, tags=["administration"])
def create_model(payload: ModelCreate, principal: AdminPrincipal, db: DbSession) -> dict:
    provider = db.get(Provider, payload.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not provider.is_enabled:
        raise HTTPException(status_code=409, detail="Enable the provider before adding a route")
    if db.scalar(select(ModelRoute).where(ModelRoute.alias == payload.alias)):
        raise HTTPException(status_code=409, detail="Model alias already exists")
    model = ModelRoute(**payload.model_dump())
    db.add(model)
    db.flush()
    audit(
        db, principal.user, "model.create", "model", model.id,
        {"alias": model.alias, "provider": provider.name},
    )
    db.commit()
    return {
        "id": model.id,
        "provider_id": provider.id,
        "provider_name": provider.name,
        **payload.model_dump(),
    }


@router.get("/admin/models", tags=["administration"])
def get_models(_: AdminPrincipal, db: DbSession) -> list[dict]:
    items = db.scalars(
        select(ModelRoute).options(joinedload(ModelRoute.provider)).order_by(ModelRoute.priority)
    ).unique().all()
    return [
        {
            "id": item.id,
            "provider_id": item.provider_id,
            "provider_name": item.provider.name,
            "alias": item.alias,
            "model_name": item.model_name,
            "task_types": item.task_types,
            "priority": item.priority,
            "supports_tools": item.supports_tools,
            "supports_vision": item.supports_vision,
            "is_enabled": item.is_enabled,
        }
        for item in items
    ]


@router.patch("/admin/models/{model_id}", tags=["administration"])
def update_model(model_id: str, payload: ModelPatch, principal: AdminPrincipal, db: DbSession) -> dict:
    model = db.get(ModelRoute, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(model, key, value)
    audit(db, principal.user, "model.update", "model", model.id, {"fields": sorted(payload.model_fields_set)})
    db.commit()
    return {
        "id": model.id,
        "alias": model.alias,
        "is_enabled": model.is_enabled,
        "priority": model.priority,
        "task_types": model.task_types,
    }


@router.put("/admin/routing/{task_type}", tags=["administration"])
def set_routing(
    task_type: str, payload: RoutingPolicyIn, principal: AdminPrincipal, db: DbSession
) -> dict:
    valid_tasks = {"auto", "coding", "architecture", "security", "sysadmin", "vision", "fast"}
    if task_type not in valid_tasks:
        raise HTTPException(status_code=422, detail="Unsupported task type")
    rows = db.scalars(
        select(ModelRoute)
        .join(Provider)
        .where(
            ModelRoute.alias.in_(payload.model_aliases),
            ModelRoute.is_enabled.is_(True),
            Provider.is_enabled.is_(True),
        )
    ).all()
    found = {item.alias for item in rows}
    missing = [alias for alias in payload.model_aliases if alias not in found]
    if missing:
        raise HTTPException(status_code=422, detail={"unknown_or_disabled_models": missing})
    policy = db.get(RoutingPolicy, task_type)
    if not policy:
        policy = RoutingPolicy(task_type=task_type, model_aliases=payload.model_aliases)
        db.add(policy)
    else:
        policy.model_aliases = payload.model_aliases
    audit(db, principal.user, "routing.update", "routing_policy", task_type, {"models": payload.model_aliases})
    db.commit()
    return {"task_type": task_type, "model_aliases": payload.model_aliases}


@router.get("/admin/routing", tags=["administration"])
def get_routing(_: AdminPrincipal, db: DbSession) -> list[dict]:
    items = db.scalars(select(RoutingPolicy).order_by(RoutingPolicy.task_type)).all()
    return [
        {
            "task_type": item.task_type,
            "model_aliases": item.model_aliases,
            "updated_at": item.updated_at.isoformat(),
        }
        for item in items
    ]


@router.patch("/admin/client-config", tags=["administration"])
def patch_client_config(
    payload: ClientConfigPatch, principal: AdminPrincipal, db: DbSession
) -> dict:
    setting = db.get(CloudSetting, "client")
    current = dict(setting.value) if setting else {}
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is not None:
            current[key] = value
    if not setting:
        setting = CloudSetting(key="client", value=current, version=1)
        db.add(setting)
    else:
        setting.value = current
        setting.version += 1
    audit(
        db, principal.user, "client_config.update", "client_config", "client",
        {"fields": sorted(changes)},
    )
    db.commit()
    return {"config_version": setting.version, **current}


@router.get("/admin/usage/summary", tags=["administration"])
def usage_summary(_: AdminPrincipal, db: DbSession) -> dict:
    totals = db.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
        )
    ).one()
    successful = db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.success.is_(True))) or 0
    failed = db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.success.is_(False))) or 0
    return {
        "requests": totals[0],
        "total_tokens": totals[1],
        "prompt_tokens": totals[2],
        "completion_tokens": totals[3],
        "successful_requests": successful,
        "failed_requests": failed,
    }


@router.get("/admin/audit-logs", tags=["administration"])
def audit_logs(_: AdminPrincipal, db: DbSession, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 500))
    items = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "actor_user_id": item.actor_user_id,
            "action": item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "details": item.details,
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]
