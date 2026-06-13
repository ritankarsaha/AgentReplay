from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..db import get_db
from ..deps import get_current_project
from ..models import Project
from ..schemas import RunDetailOut, RunListOut, run_to_detail_out, run_to_out

router = APIRouter(tags=["runs"])


@router.get("/v1/runs", response_model=RunListOut)
async def list_runs(
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> RunListOut:
    """List runs for the authenticated project, most recent first.

    Manual verification for the Day 1 checkpoint ("spans land in Postgres")
    and the data source for the Day 2 run-list viewer.
    """
    runs = await crud.list_runs(db, project_id=project.id, limit=limit)
    return RunListOut(runs=[run_to_out(r) for r in runs])


@router.get("/v1/runs/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: str,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> RunDetailOut:
    run = await crud.get_run_with_spans(db, project_id=project.id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run_to_detail_out(run)
