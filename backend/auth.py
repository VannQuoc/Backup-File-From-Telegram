from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security_scheme = HTTPBearer(auto_error=False)


def hash_password_sha256(plain_password: str) -> str:
    return hashlib.sha256(plain_password.encode("utf-8")).hexdigest().lower()


def verify_admin_password(
    input_password_or_hash: str,
    expected_sha256: str,
    *,
    allow_raw_sha256: bool = True,
) -> bool:
    """Verifies admin password against the SHA-256 hex string configured in .env."""
    cleaned_expected = expected_sha256.strip().lower()
    candidate = input_password_or_hash.strip()
    hashed_input = hash_password_sha256(candidate)

    if hmac.compare_digest(hashed_input, cleaned_expected):
        return True

    if allow_raw_sha256 and len(candidate) == 64:
        try:
            int(candidate, 16)
            return hmac.compare_digest(candidate.lower(), cleaned_expected)
        except ValueError:
            return False

    return False


def create_session_token(secret: str, ttl_seconds: int = 86400 * 7) -> str:
    payload = {
        "sub": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{b64_payload}.{signature}"


def verify_session_token(token: str | None, secret: str) -> bool:
    if not token or "." not in token:
        return False
    b64_payload, signature = token.split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        b64_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return False
    try:
        padding = "=" * (-len(b64_payload) % 4)
        payload_bytes = base64.urlsafe_b64decode(b64_payload + padding)
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = int(payload.get("exp", 0))
        return exp > int(time.time())
    except Exception:
        return False


def require_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)] = None,
) -> str:
    config = request.app.state.config
    token: str | None = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif "token" in request.query_params:
        token = request.query_params.get("token")

    if not verify_session_token(token, config.web_session_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
        )
    return "admin"
