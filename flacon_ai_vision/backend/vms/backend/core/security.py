# vms/backend/core/security.py - JWT and auth helpers

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Callable, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from .audit import write_audit_log
from .config import settings

# Password hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer()

TOKEN_TYPE_CLAIM = "token_type"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_jwt_token(
    data: dict,
    *,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    to_encode = data.copy()
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + expires_delta
    to_encode.update(
        {
            "exp": expire,
            "iat": issued_at,
            "jti": uuid4().hex,
            TOKEN_TYPE_CLAIM: token_type,
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_jwt_token(data, token_type=ACCESS_TOKEN_TYPE, expires_delta=delta)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    delta = expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _create_jwt_token(data, token_type=REFRESH_TOKEN_TYPE, expires_delta=delta)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> Optional[dict]:
    for secret in settings.SECRET_KEYS:
        if not secret:
            continue
        try:
            return jwt.decode(token, secret, algorithms=[settings.ALGORITHM])
        except JWTError:
            continue
    return None


def verify_token(token: str, expected_type: str = ACCESS_TOKEN_TYPE) -> Optional[dict]:
    payload = decode_token(token)
    if not payload:
        return None
    token_type = str(payload.get(TOKEN_TYPE_CLAIM, ACCESS_TOKEN_TYPE))
    if expected_type and token_type != expected_type:
        return None
    return payload


def verify_refresh_token(token: str) -> Optional[dict]:
    return verify_token(token, expected_type=REFRESH_TOKEN_TYPE)


def _extract_bearer_token(raw_value: Optional[str]) -> Optional[str]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    if text.lower().startswith("bearer "):
        token = text[7:].strip()
        return token or None
    return text


def resolve_websocket_token(websocket: WebSocket) -> Optional[str]:
    token = _extract_bearer_token(websocket.query_params.get("token"))
    if token:
        return token

    auth_header = websocket.headers.get("authorization")
    token = _extract_bearer_token(auth_header)
    if token:
        return token

    protocol_header = websocket.headers.get("sec-websocket-protocol")
    if protocol_header:
        for chunk in protocol_header.split(","):
            token = _extract_bearer_token(chunk)
            if token:
                return token
    return None


async def authenticate_websocket(
    websocket: WebSocket,
    *,
    required: bool = True,
) -> Optional[dict]:
    token = resolve_websocket_token(websocket)
    if not token:
        if required:
            await websocket.close(code=4401, reason="Authentication required")
        return None

    payload = verify_token(token, expected_type=ACCESS_TOKEN_TYPE)
    if not payload:
        if required:
            await websocket.close(code=4401, reason="Invalid token")
        return None

    return payload


async def get_current_user(credentials=Depends(security)) -> dict:
    token = credentials.credentials
    payload = verify_token(token, expected_type=ACCESS_TOKEN_TYPE)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_current_user_strict(current_user: dict = Depends(get_current_user)) -> dict:
    if not current_user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required",
        )
    return current_user


ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "operator": 1,
    "supervisor": 2,
    "admin": 3,
}
ROLE_ALIASES: dict[str, str] = {
    "user": "operator",
}


def normalize_user_role(raw_role: object, is_admin: bool = False) -> str:
    if is_admin:
        return "admin"
    role = str(raw_role or "").strip().lower()
    if role in ROLE_ALIASES:
        role = ROLE_ALIASES[role]
    if role in ROLE_HIERARCHY:
        return role
    return "viewer"


def get_user_role(current_user: dict) -> str:
    return normalize_user_role(
        current_user.get("role"),
        bool(current_user.get("is_admin")),
    )


def _coerce_user_id(current_user: dict) -> Optional[int]:
    raw = current_user.get("user_id")
    if raw is None:
        return None
    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None





def _coerce_tenant_id(current_user: dict) -> Optional[int]:
    raw = current_user.get("tenant_id") or current_user.get("tenant")
    if raw is None:
        return None
    try:
        tenant_id = int(raw)
    except (TypeError, ValueError):
        return None
    return tenant_id if tenant_id > 0 else None


async def get_current_tenant_id(current_user: dict = Depends(get_current_user)) -> Optional[int]:
    return _coerce_tenant_id(current_user)


async def require_tenant_id(current_user: dict = Depends(get_current_user)) -> int:
    tenant_id = _coerce_tenant_id(current_user)
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant context missing")
    return tenant_id


def require_roles(*allowed_roles: str) -> Callable[..., dict]:
    normalized_allowed = {
        normalize_user_role(role)
        for role in allowed_roles
        if str(role or "").strip()
    }
    if not normalized_allowed:
        normalized_allowed = set(ROLE_HIERARCHY.keys())

    async def _dependency(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        current_role = get_user_role(current_user)
        if current_role not in normalized_allowed:
            write_audit_log(
                event_type="rbac",
                action="access_denied",
                method=request.method,
                path=request.url.path,
                status_code=status.HTTP_403_FORBIDDEN,
                user_id=_coerce_user_id(current_user),
                username=str(current_user.get("sub") or current_user.get("username") or ""),
                ip_address=(request.client.host if request.client else None),
                user_agent=request.headers.get("user-agent"),
                request_id=getattr(request.state, "request_id", None),
                details={
                    "required_roles": sorted(normalized_allowed),
                    "user_role": current_role,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_role}' is not allowed for this action",
            )
        return current_user

    return _dependency


require_viewer = require_roles("viewer", "operator", "supervisor", "admin")
require_operator = require_roles("operator", "supervisor", "admin")
require_supervisor = require_roles("supervisor", "admin")
