from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .config import Settings, get_settings
from .db import get_db
from .models import Project


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or malformed Authorization header"
        )
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    return token


def _is_viewer_token(token: str, settings: Settings) -> bool:
    expected = settings.viewer_service_token
    return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


@dataclass
class ViewerUser:
    """A signed-in viewer user, vouched for by the viewer's server-side token."""

    email: str


async def get_viewer_user(
    authorization: Optional[str] = Header(default=None),
    x_viewer_email: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> ViewerUser:
    """Account-level auth: only the Next.js viewer (holding the service token)
    may call these, on behalf of the Auth.js-verified `X-Viewer-Email`."""
    if not _is_viewer_token(_bearer(authorization), settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not x_viewer_email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing X-Viewer-Email")
    return ViewerUser(email=x_viewer_email.strip().lower())


async def require_viewer_service(
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not _is_viewer_token(_bearer(authorization), settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


async def get_current_project(
    authorization: Optional[str] = Header(default=None),
    x_viewer_email: Optional[str] = Header(default=None),
    x_project_id: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Project:
    """Resolve the calling project -- the multi-tenancy boundary (CLAUDE.md §7).

    Two ways in, both `Authorization: Bearer <token>`:
    - a project API key (SDK, CLI, CI gate): looked up by sha256 digest;
    - the viewer service token plus `X-Viewer-Email`/`X-Project-Id`: the
      project must be owned by that user. A non-owner gets the same 404 a
      missing project would, so project ids can't be probed.
    """
    token = _bearer(authorization)

    if _is_viewer_token(token, settings):
        if not x_viewer_email or not x_project_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Missing X-Viewer-Email or X-Project-Id"
            )
        project = await crud.get_project_for_owner(
            db, project_id=x_project_id, owner_email=x_viewer_email.strip().lower()
        )
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        return project

    project = await crud.get_project_by_api_key(db, token)
    if project is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return project
