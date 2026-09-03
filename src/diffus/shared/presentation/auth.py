"""HTTP Basic auth dependency, applied to every route."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from diffus.shared.config import get_settings

security = HTTPBasic()


def require_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    settings = get_settings()

    username_ok = secrets.compare_digest(credentials.username, settings.basic_auth_username)
    password_ok = secrets.compare_digest(credentials.password, settings.basic_auth_password)

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
