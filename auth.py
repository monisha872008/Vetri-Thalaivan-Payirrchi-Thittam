"""Password hashing, JWT tokens and the user store."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

import config
from storage import users_store


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def get_user(username: str) -> Optional[dict]:
    return users_store.load().get((username or "").strip().lower())


def create_user(username: str, email: str, password: str, full_name: Optional[str] = None) -> dict:
    users = users_store.load()
    key = username.strip().lower()
    if key in users:
        raise ValueError("Username already taken")
    if any(u.get("email", "").lower() == email.lower() for u in users.values()):
        raise ValueError("Email already registered")
    user = {
        "username": username.strip(),
        "email": email.strip().lower(),
        "full_name": full_name or username.strip(),
        "password_hash": hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    users[key] = user
    users_store.save(users)
    return user


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = get_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user


def create_access_token(username: str, expires_minutes: Optional[int] = None) -> str:
    minutes = expires_minutes if expires_minutes is not None else config.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    payload = {"sub": username.strip().lower(), "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Return the payload, or None if the token is invalid/expired."""
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except jwt.PyJWTError:
        return None
