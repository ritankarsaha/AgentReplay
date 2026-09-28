from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..db import get_db
from ..deps import get_current_project
from ..models import Project
from ..schemas import LoginEventIn, LoginEventListOut, LoginEventOut, login_event_to_out

router = APIRouter(tags=["auth-events"])


@router.post("/v1/auth-events", response_model=LoginEventOut, status_code=status.HTTP_201_CREATED)
async def create_login_event(
    body: LoginEventIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> LoginEventOut:
    """Records one viewer Google sign-in (`web/auth.ts`'s `events.signIn`).

    Best-effort from the caller's side by convention (the viewer must never
    let a logging failure block a real sign-in) -- this endpoint itself is
    a normal write, no special handling needed here.
    """
    event = await crud.insert_login_event(
        db,
        project_id=project.id,
        email=body.email,
        name=body.name,
        image=body.image,
        provider=body.provider,
    )
    return login_event_to_out(event)


@router.get("/v1/auth-events", response_model=LoginEventListOut)
async def list_login_events(
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> LoginEventListOut:
    """Backs the viewer's `/logins` table -- who has signed in, most recent first."""
    events = await crud.list_login_events(db, project_id=project.id, limit=limit)
    return LoginEventListOut(events=[login_event_to_out(e) for e in events])
