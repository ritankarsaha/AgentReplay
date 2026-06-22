from __future__ import annotations

import sys

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_project
from ..models import Project
from ..schemas import IngestResponse, SpanBatchIn
from ..tasks import enqueue_classification

router = APIRouter(tags=["spans"])


@router.post("/v1/spans", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_spans(
    batch: SpanBatchIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Wire contract for `agentreplay.exporter.BackgroundExporter` (chunk 1.4).

    `runs` rows are derived lazily from the spans in this batch — there is
    no separate run-lifecycle event from the SDK (see PROGRESS.md). Any run
    with an `agentreplay.fail()` signal in this batch (chunk 3.5) is
    enqueued for classification (chunk 3.6) — skipped if the classifier
    backend has no API key configured (the normal local-dev state today,
    see PROGRESS.md Blockers), so ingestion never fails or stalls on a
    missing key.
    """
    if batch.project_id != project.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "project_id in request body does not match the authenticated project",
        )

    accepted, failed_run_ids = await crud.ingest_batch(
        db,
        project_id=project.id,
        spans=batch.spans,
        agent_version=batch.agent_version,
        framework=batch.framework,
    )

    if failed_run_ids and get_settings().classifier_configured:
        for run_id in failed_run_ids:
            try:
                enqueue_classification(run_id)
            except Exception as exc:
                # Enqueueing must never fail the ingest request itself — a
                # down Redis broker shouldn't take down span ingestion too.
                print(
                    f"agentreplay-ingest: failed to enqueue classification for {run_id}: {exc}",
                    file=sys.stderr,
                )

    return IngestResponse(accepted=accepted)
