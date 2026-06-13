from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .db import get_db
from .models import Project


async def get_current_project(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Resolve the calling project from `Authorization: Bearer <api_key>`.

    Every authenticated route depends on this — it's the multi-tenancy
    boundary (CLAUDE.md §7). Returns 401 for missing/unknown keys.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or malformed Authorization header"
        )

    api_key = authorization[len("Bearer "):].strip()
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")

    project = await crud.get_project_by_api_key(db, api_key)
    if project is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    return project
