from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Device, User
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    device: Device


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        claims = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from None
    user = db.scalar(select(User).where(User.id == claims["sub"]))
    device = db.scalar(select(Device).where(Device.id == claims.get("device_id")))
    if not user or not user.is_active or not device or device.is_revoked or device.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or unavailable")
    return Principal(user=user, device=device)


def require_admin(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
    if principal.user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]
DbSession = Annotated[Session, Depends(get_db)]
