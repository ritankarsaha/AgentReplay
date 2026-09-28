from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..assertion_spec import (
    AssertionSpecNotConfigured,
    RunNotClassifiedError,
    generate_assertion_spec_for_run,
)
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_project
from ..models import Project
from ..schemas import (
    AssertionSpecOut,
    GenerateTestOut,
    GenerateTestRequest,
    RunDetailOut,
    RunListOut,
    run_to_detail_out,
    run_to_out,
)
from ..testgen import EntrypointFormatError, generate_test_files_for_run

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


@router.post("/v1/runs/{run_id}/assertion-spec", response_model=AssertionSpecOut)
async def create_assertion_spec(
    run_id: str,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> AssertionSpecOut:
    """Generate (and persist) a structural assertion spec for an already-classified
    failure (CLAUDE.md §4 chunk 4.3 — "one click on a classified failure", §3.6).

    Deliberately synchronous (no Celery, unlike the classifier's auto-trigger
    on every failure, chunk 3.6) — a single on-demand user action, not
    high-volume automatic processing. Always Sonnet, never NIM (CLAUDE.md
    §10). 409 if `run_id` hasn't been classified yet (chunk 3.6 must run
    first); 503 if no Anthropic key is configured.
    """
    run = await crud.get_run_with_spans(db, project_id=project.id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    try:
        spec = await generate_assertion_spec_for_run(run, db, get_settings())
    except RunNotClassifiedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except AssertionSpecNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    return AssertionSpecOut(**spec.to_dict())


@router.post("/v1/runs/{run_id}/generate-test", response_model=GenerateTestOut)
async def create_generated_test(
    run_id: str,
    body: GenerateTestRequest,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> GenerateTestOut:
    """The viewer's "Generate Test" button (CLAUDE.md §4 chunk 4.5).

    One click does the whole pipeline: generates (and persists) a chunk 4.3
    assertion spec if `run_id` doesn't have one yet, then renders the
    chunk 4.1/4.2/4.4 fixture+test file contents for the frontend to show
    with copy/download buttons. 400 on a malformed `entrypoint` (checked
    before anything else); 409 if not classified yet (chunk 3.6 must run
    first); 503 if no Anthropic key is configured AND this run still needs
    a spec generated.
    """
    run = await crud.get_run_with_spans(db, project_id=project.id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    try:
        result = await generate_test_files_for_run(run, body.entrypoint, db, get_settings())
    except EntrypointFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except RunNotClassifiedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except AssertionSpecNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    return GenerateTestOut(
        run_id=result.run_id,
        fixture_filename=result.fixture_filename,
        fixture_source=result.fixture_source,
        test_filename=result.test_filename,
        test_source=result.test_source,
        assertion_spec=result.assertion_spec,
    )
