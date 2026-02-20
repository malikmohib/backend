from __future__ import annotations

import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


class TokenError(Exception):
    pass


# -------------------------
# Password hashing (bcrypt)
# -------------------------
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


# -------------------------
# JWT tokens
# -------------------------
def create_access_token(*, user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_ACCESS_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def create_refresh_token(*, user_id: int, role: str | None = None) -> str:
    # role is accepted for compatibility with call sites, but not required for refresh
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.JWT_REFRESH_DAYS)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("Invalid token") from e
