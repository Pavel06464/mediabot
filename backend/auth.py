import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta

from fastapi import Request, HTTPException
from bson import ObjectId

from database import db

JWT_ALGO = "HS256"


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode("utf-8")[:72], h.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGO)


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGO])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        return {"id": str(user["_id"]), "email": user["email"]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Сессия истекла, войдите заново")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Неверный токен")


async def seed_admin():
    email = os.environ.get("ADMIN_EMAIL", "admin@mediabot.local").lower()
    pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": email})
    if not existing:
        await db.users.insert_one({
            "email": email,
            "password_hash": hash_password(pw),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif not verify_password(pw, existing["password_hash"]):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(pw)}})
