from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from app.config import settings

# Talking to bcrypt directly instead of going through passlib's CryptContext:
# passlib 1.7.4's bcrypt backend reads an internal `bcrypt.__about__.__version__`
# attribute that newer bcrypt releases (4.1+) removed, which crashes every
# hash/verify call. Calling bcrypt's own hashpw/checkpw sidesteps that check
# entirely and works with any current bcrypt version.

# bcrypt has a hard 72-byte limit on the password it hashes. Anything longer
# raises a ValueError and crashes the request, so we safely truncate first
# (by bytes, not characters, since multi-byte UTF-8 chars could still overflow).
def _truncate_for_bcrypt(password: str) -> bytes:
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate_for_bcrypt(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate_for_bcrypt(plain), hashed.encode("utf-8"))
    except ValueError:
        return False  # malformed/foreign hash format — treat as a failed login, not a crash


def create_access_token(data: dict, expires_minutes: Optional[int] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
