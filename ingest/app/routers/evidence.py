from __future__ import annotations

import hashlib
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentreplay.testgen.fixture import FixtureData, render_fixture_module
from agentreplay.testgen.test_template import render_test_module, slugify_run_id

from ..db import get_db
from ..deps import get_current_project, require_viewer_service
from ..models import Agent, Blob, Filing, Incident, Project, RegressionCase, Run, TestResult

router = APIRouter(tags=["evidence"])

MAX_BLOB_BYTES = 2_000_000
ALLOWED_BLOB_MIMES = {"image/png", "image/jpeg", "text/html"}
RESULTS_SHOWN = 10


class BlobOut(BaseModel):
    sha256: str
    mime: str
    size: int
    uri: str


class ShareOut(BaseModel):
    share_token: Optional[str]


class GeneratedTestOut(BaseModel):
    case_id: str
    fixture_filename: str
    fixture_source: str
    test_filename: str
    test_source: str


class PublicIncidentOut(BaseModel):
    incident: Dict[str, Any]
    agent: Optional[Dict[str, Any]]
    run: Optional[Dict[str, Any]]
    filings: List[Dict[str, Any]]
    case: Optional[Dict[str, Any]]


@router.post("/v1/blobs", response_model=BlobOut, status_code=status.HTTP_201_CREATED)
async def put_blob(
    request: Request, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> BlobOut:
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_BLOB_MIMES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported blob type {mime!r}")
    data = await request.body()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty body")
    if len(data) > MAX_BLOB_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Blob exceeds {MAX_BLOB_BYTES} bytes")
    digest = hashlib.sha256(data).hexdigest()
    if (await db.get(Blob, (project.id, digest))) is None:
        db.add(Blob(project_id=project.id, sha256=digest, mime=mime, size=len(data), data=data))
        await db.flush()
    return BlobOut(sha256=digest, mime=mime, size=len(data), uri=f"blob://sha256/{digest}")


def _blob_response(blob: Blob) -> Response:
    headers = {"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}
    if blob.mime == "text/html":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    return Response(content=blob.data, media_type=blob.mime, headers=headers)


@router.get("/v1/blobs/{sha256}")
async def get_blob(
    sha256: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> Response:
    blob = await db.get(Blob, (project.id, sha256))
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blob not found")
    return _blob_response(blob)


async def _incident_or_404(db: AsyncSession, project: Project, incident_id: str) -> Incident:
    row = (
        await db.execute(select(Incident).where(Incident.id == incident_id, Incident.project_id == project.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    return row


@router.post("/v1/incidents/{incident_id}/share", response_model=ShareOut)
async def enable_share(
    incident_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> ShareOut:
    incident = await _incident_or_404(db, project, incident_id)
    if incident.share_token is None:
        incident.share_token = secrets.token_urlsafe(24)
        await db.flush()
    return ShareOut(share_token=incident.share_token)


@router.delete("/v1/incidents/{incident_id}/share", response_model=ShareOut)
async def disable_share(
    incident_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> ShareOut:
    incident = await _incident_or_404(db, project, incident_id)
    incident.share_token = None
    await db.flush()
    return ShareOut(share_token=None)


def _dump(row: Any, fields: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in fields:
        value = getattr(row, name)
        out[name] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


@router.get(
    "/v1/public/incidents/{token}",
    response_model=PublicIncidentOut,
    dependencies=[Depends(require_viewer_service)],
)
async def public_incident(token: str, db: AsyncSession = Depends(get_db)) -> PublicIncidentOut:
    """Read-only bundle for a shared incident. Raw spans and project identifiers are never included."""
    incident = (await db.execute(select(Incident).where(Incident.share_token == token))).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shared incident not found")

    agent = await db.get(Agent, incident.agent_id) if incident.agent_id else None
    run = await db.get(Run, incident.run_id)
    filings = (
        await db.execute(select(Filing).where(Filing.incident_id == incident.id).order_by(Filing.type))
    ).scalars().all()
    case = (
        await db.execute(select(RegressionCase).where(RegressionCase.incident_id == incident.id).limit(1))
    ).scalar_one_or_none()

    case_out = None
    if case is not None:
        results = (
            await db.execute(
                select(TestResult)
                .where(TestResult.case_id == case.id)
                .order_by(TestResult.created_at.desc())
                .limit(RESULTS_SHOWN)
            )
        ).scalars().all()
        case_out = {
            **_dump(case, ["title", "status", "priority", "entrypoint", "assertion_spec"]),
            "results": [_dump(r, ["agent_version", "trials", "passes", "verdict", "judged_at"]) for r in results],
        }

    return PublicIncidentOut(
        incident=_dump(incident, ["id", "kind", "severity", "status", "details", "created_at"]),
        agent=_dump(agent, ["id", "name"]) if agent else None,
        run=_dump(run, ["id", "status", "started_at", "agent_version"]) if run else None,
        filings=[_dump(f, ["type", "packet", "trace_hash", "simulated", "created_at"]) for f in filings],
        case=case_out,
    )


@router.get("/v1/public/incidents/{token}/blobs/{sha256}", dependencies=[Depends(require_viewer_service)])
async def public_blob(token: str, sha256: str, db: AsyncSession = Depends(get_db)) -> Response:
    incident = (await db.execute(select(Incident).where(Incident.share_token == token))).scalar_one_or_none()
    if incident is None or sha256 not in (incident.details or {}).get("assets", []):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blob not found")
    blob = await db.get(Blob, (incident.project_id, sha256))
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blob not found")
    return _blob_response(blob)


@router.get("/v1/regression-cases/{case_id}/generated-test", response_model=GeneratedTestOut)
async def generated_test(
    case_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> GeneratedTestOut:
    case = (
        await db.execute(
            select(RegressionCase).where(RegressionCase.id == case_id, RegressionCase.project_id == project.id)
        )
    ).scalar_one_or_none()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    slug = slugify_run_id(case.id)
    fixture = FixtureData(run_id=case.id, recorded_input=case.recorded_input, tool_spans=list(case.tool_spans or []))
    return GeneratedTestOut(
        case_id=case.id,
        fixture_filename=f"fixture_{slug}.py",
        fixture_source=render_fixture_module(fixture),
        test_filename=f"test_{slug}.py",
        test_source=render_test_module(
            fixture_module=f"fixture_{slug}",
            entrypoint=case.entrypoint,
            run_id=case.id,
            assertion_spec=case.assertion_spec,
        ),
    )
