"""认证与安全：PBKDF2 口令哈希 + JWT 令牌（httpOnly Cookie）+ FastAPI 依赖。

- 口令：hashlib.pbkdf2_hmac（标准库，10 万次迭代 + 16 字节随机盐），无第三方依赖
- 令牌：PyJWT HS256，仅放于 HttpOnly Cookie，绝不落 localStorage / URL
"""

import datetime as dt
import hashlib
import secrets

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt_hex = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_hex.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_hex}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_hex.encode(), int(iterations))
        return dk.hex() == hash_hex
    except (ValueError, AttributeError):
        return False


def create_token(user: User) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + dt.timedelta(days=settings.TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def client_ip(request: Request) -> str:
    """客户端 IP：优先取反向代理透传的 X-Forwarded-For 首段，回退直连地址。"""
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _extract_token(request: Request) -> str | None:
    # 1) httpOnly Cookie（首选）
    token = request.cookies.get(settings.COOKIE_NAME)
    if token:
        return token
    # 2) Authorization: Bearer（兼容 API 调试 / 脚本）
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """认证依赖：未登录抛 401（前端据此弹出登录页）。"""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="登录状态无效")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不存在或已停用")
    return user


def require_roles(*roles: str):
    """角色门禁依赖工厂：require_roles('admin') 等。"""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="没有执行该操作的权限")
        return user

    return dependency


def set_auth_cookie(response, token: str) -> None:
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


def clear_auth_cookie(response) -> None:
    response.delete_cookie(key=settings.COOKIE_NAME, path="/")
