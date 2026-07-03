# -*- coding: utf-8 -*-
"""
认证与安全工具 — JWT / API Key / 密码哈希。
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---- API Key ----

def generate_api_key() -> str:
    """生成 API Key: mem_ + 32 字节随机 hex"""
    return f"mem_{secrets.token_hex(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_agent_id() -> str:
    return f"agent_{uuid.uuid4().hex[:16]}"


def generate_user_id() -> str:
    return f"user_{uuid.uuid4().hex[:12]}"


def generate_session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:12]}"


def generate_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def generate_scene_id() -> str:
    return f"scene_{uuid.uuid4().hex[:8]}"


# ---- JWT ----

def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.auth.jwt_expire_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(to_encode, settings.auth.jwt_secret_key, algorithm=settings.auth.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.auth.jwt_secret_key, algorithms=[settings.auth.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None
