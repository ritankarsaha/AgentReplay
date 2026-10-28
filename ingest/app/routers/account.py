from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import Settings, get_settings
from ..db import get_db
from ..deps import ViewerUser, get_viewer_user

router = APIRouter(tags=["account"])


class ProjectOut(BaseModel):
    id: str
    name: str
    api_key_prefix: Optional[str]
    created_at: datetime


class ProjectListOut(BaseModel):
    projects: List[ProjectOut]


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ProjectWithKeyOut(ProjectOut):
    # The only time the plaintext key is ever returned.
    api_key: str


def _out(p) -> ProjectOut:
    return ProjectOut(
        id=p.id, name=p.name, api_key_prefix=p.api_key_prefix, created_at=p.created_at
    )


@router.get("/v1/account/projects", response_model=ProjectListOut)
async def list_my_projects(
    user: ViewerUser = Depends(get_viewer_user), db: AsyncSession = Depends(get_db)
) -> ProjectListOut:
    projects = await crud.list_projects_for_owner(db, owner_email=user.email)
    return ProjectListOut(projects=[_out(p) for p in projects])


@router.post(
    "/v1/account/projects", response_model=ProjectWithKeyOut, status_code=status.HTTP_201_CREATED
)
async def create_my_project(
    body: CreateProjectRequest,
    user: ViewerUser = Depends(get_viewer_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProjectWithKeyOut:
    existing = await crud.list_projects_for_owner(db, owner_email=user.email)
    if len(existing) >= settings.max_projects_per_user:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Project limit reached ({settings.max_projects_per_user}). Contact us for more.",
        )
    project, api_key = await crud.create_project(db, name=body.name.strip(), owner_email=user.email)
    return ProjectWithKeyOut(**_out(project).model_dump(), api_key=api_key)


@router.post("/v1/account/projects/{project_id}/rotate-key", response_model=ProjectWithKeyOut)
async def rotate_my_project_key(
    project_id: str,
    user: ViewerUser = Depends(get_viewer_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectWithKeyOut:
    """Issue a new key; the old one stops working immediately."""
    project = await crud.get_project_for_owner(db, project_id=project_id, owner_email=user.email)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    api_key = await crud.rotate_project_key(db, project)
    return ProjectWithKeyOut(**_out(project).model_dump(), api_key=api_key)
