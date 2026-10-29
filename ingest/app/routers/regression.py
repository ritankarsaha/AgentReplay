from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..assertion_spec import AssertionSpecNotConfigured, RunNotClassifiedError
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_project
from ..models import Project
from ..security import rate_limiter
from ..regression import (
    InvalidStatusTransition,
    apply_status_transition,
    create_case_from_capture,
    create_case_from_run,
)
from ..schemas import (
    CaptureProductionRequest,
    RegisterCaseRequest,
    RegisterResultRequest,
    RegressionCaseListOut,
    RegressionCaseOut,
    TestResultListOut,
    TestResultOut,
    UpdateCaseStatusRequest,
    regression_case_to_out,
    test_result_to_out,
)
from ..testgen import EntrypointFormatError

router = APIRouter(tags=["regression"])


@router.post(
    "/v1/regression-cases", response_model=RegressionCaseOut, status_code=status.HTTP_201_CREATED
)
async def register_case(
    body: RegisterCaseRequest,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> RegressionCaseOut:
    """Promote a recorded run's failure into a `proposed` regression case.

    Generates an assertion spec first if the run doesn't have one yet. 400 on
    a malformed `entrypoint`; 404 if the run doesn't exist; 409 if not
    classified yet; 503 if no Sonnet/NIM key is configured.
    """
    run = await crud.get_run_with_spans(db, project_id=project.id, run_id=body.run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    rate_limiter.check(
        f"llm:{project.id}", limit=get_settings().llm_rate_limit_per_hour,
        window_seconds=3600, label="LLM-backed requests",
    )

    try:
        case = await create_case_from_run(
            run,
            db,
            get_settings(),
            entrypoint=body.entrypoint,
            title=body.title,
            priority=body.priority,
            created_by=body.created_by,
        )
    except EntrypointFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except RunNotClassifiedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except AssertionSpecNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    return regression_case_to_out(case)


@router.post(
    "/v1/regression-cases/capture-production",
    response_model=RegressionCaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def capture_production_case(
    body: CaptureProductionRequest,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> RegressionCaseOut:
    """Capture a production incident into a `proposed` case with no source run.
    400 on a malformed `entrypoint`.
    """
    try:
        case = await create_case_from_capture(
            db,
            project_id=project.id,
            entrypoint=body.entrypoint,
            recorded_input=body.recorded_input,
            tool_spans=body.tool_spans,
            assertion_spec=body.assertion_spec,
            title=body.title,
            priority=body.priority,
            source_case_key=body.source_case_key,
            incident_id=body.incident_id,
            external_url=body.external_url,
            observed_at=body.observed_at,
            failure_class=body.failure_class,
            created_by=body.created_by,
        )
    except EntrypointFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    return regression_case_to_out(case)


@router.get("/v1/regression-cases", response_model=RegressionCaseListOut)
async def list_cases(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    incident_id: Optional[str] = None,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> RegressionCaseListOut:
    """List regression cases, optionally filtered by `status` and `incident_id`."""
    cases = await crud.list_regression_cases(
        db, project_id=project.id, status=status_filter, incident_id=incident_id, limit=limit
    )
    return RegressionCaseListOut(cases=[regression_case_to_out(c) for c in cases])


@router.get("/v1/regression-cases/{case_id}", response_model=RegressionCaseOut)
async def get_case(
    case_id: str,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> RegressionCaseOut:
    case = await crud.get_regression_case(db, project_id=project.id, case_id=case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regression case not found")
    return regression_case_to_out(case)


@router.patch("/v1/regression-cases/{case_id}", response_model=RegressionCaseOut)
async def update_case_status(
    case_id: str,
    body: UpdateCaseStatusRequest,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> RegressionCaseOut:
    """Transition a case's status. 409 on a not-allowed transition, 400 for an
    unknown status value.
    """
    case = await crud.get_regression_case(db, project_id=project.id, case_id=case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regression case not found")

    try:
        apply_status_transition(case, body.status)
    except InvalidStatusTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    await db.commit()
    await db.refresh(case)
    return regression_case_to_out(case)


@router.post(
    "/v1/regression-cases/{case_id}/results",
    response_model=TestResultOut,
    status_code=status.HTTP_201_CREATED,
)
async def register_result(
    case_id: str,
    body: RegisterResultRequest,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> TestResultOut:
    """Record one N-trial run's outcome for a case — history/audit only, the
    verdict is already decided client-side by `agentreplay ci gate`.
    """
    case = await crud.get_regression_case(db, project_id=project.id, case_id=case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regression case not found")

    result = await crud.insert_test_result(
        db,
        case_id=case.id,
        agent_version=body.agent_version,
        trials=body.trials,
        passes=body.passes,
        verdict=body.verdict,
        details=[t.model_dump() for t in body.details],
    )
    return test_result_to_out(result)


@router.get("/v1/regression-cases/{case_id}/results", response_model=TestResultListOut)
async def list_results(
    case_id: str,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> TestResultListOut:
    case = await crud.get_regression_case(db, project_id=project.id, case_id=case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regression case not found")

    results = await crud.list_test_results(db, case_id=case.id, limit=limit)
    return TestResultListOut(results=[test_result_to_out(r) for r in results])
