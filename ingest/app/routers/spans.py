from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..db import get_db
from ..deps import get_current_project
from ..models import Project
from ..schemas import IngestResponse, SpanBatchIn

router = APIRouter(tags=["spans"])


@router.post("/v1/spans", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_spans(
    batch: SpanBatchIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Wire contract for `agentreplay.exporter.BackgroundExporter` (chunk 1.4).

    `runs` rows are derived lazily from the spans in this batch — there is
    no separate run-lifecycle event from the SDK (see PROGRESS.md).
    """
    if batch.project_id != project.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "project_id in request body does not match the authenticated project",
        )

    accepted = await crud.ingest_batch(
        db,
        project_id=project.id,
        spans=batch.spans,
        agent_version=batch.agent_version,
        framework=batch.framework,
    )
    return IngestResponse(accepted=accepted)
