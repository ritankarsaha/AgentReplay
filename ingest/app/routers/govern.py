from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_project
from ..manifests import agent_id_for, verify_manifest_signature
from ..models import (
    AccessToken,
    Agent,
    Incident,
    Project,
    RegressionCase,
    Run,
    ScopeManifest,
    SpanModel,
    TestResult,
    TrustScore,
)

router = APIRouter(tags=["govern"])

RECENT_RUNS_WINDOW = 20
MAX_POLICY_SPANS_SCANNED = 5000
VIOLATION_KINDS = ("scope_violation", "spend_breach")


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    public_key: str


class AgentOut(BaseModel):
    id: str
    name: str
    public_key: str
    status: str
    owner_id: Optional[str]
    created_at: Optional[datetime]


class ManifestIn(BaseModel):
    manifest: Dict[str, Any]


class ManifestOut(BaseModel):
    agent_id: str
    version: int
    manifest: Dict[str, Any]
    issued_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]


class IncidentOut(BaseModel):
    id: str
    run_id: str
    agent_id: Optional[str]
    kind: str
    severity: str
    culprit_span_id: Optional[str]
    status: str
    created_at: Optional[datetime]


class TrustIn(BaseModel):
    score: int = Field(ge=300, le=850)
    band: str
    components: Dict[str, Any] = Field(default_factory=dict)
    trigger_run_id: Optional[str] = None


class TrustOut(BaseModel):
    agent_id: str
    score: int
    band: str
    components: Dict[str, Any]
    computed_at: Optional[datetime]
    trigger_run_id: Optional[str]


class TrustInputsOut(BaseModel):
    runs_count: int
    recent_failure_rate: float
    regression_pass_rate: float
    violation_times: List[datetime]


class TokenIn(BaseModel):
    id: str = Field(min_length=16, max_length=128)
    connector: str
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class TokenOut(BaseModel):
    id: str
    agent_id: str
    connector: str
    scopes: List[str]
    issued_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]


async def _agent_or_404(db: AsyncSession, project: Project, agent_id: str) -> Agent:
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.project_id == project.id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


def _agent_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        name=agent.name,
        public_key=agent.public_key,
        status=agent.status,
        owner_id=agent.owner_id,
        created_at=agent.created_at,
    )


def _manifest_out(row: ScopeManifest) -> ManifestOut:
    return ManifestOut(
        agent_id=row.agent_id,
        version=row.version,
        manifest=row.manifest,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


@router.post("/v1/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def register_agent(
    body: AgentIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> AgentOut:
    try:
        agent_id = agent_id_for(body.public_key)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Ed25519 public key")
    existing = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if existing is not None:
        if existing.project_id != project.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Public key is already registered")
        return _agent_out(existing)
    agent = Agent(
        id=agent_id,
        project_id=project.id,
        owner_id=project.owner_email,
        name=body.name,
        public_key=body.public_key,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return _agent_out(agent)


@router.get("/v1/agents", response_model=List[AgentOut])
async def list_agents(
    project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> List[AgentOut]:
    rows = (
        await db.execute(select(Agent).where(Agent.project_id == project.id).order_by(Agent.created_at))
    ).scalars()
    return [_agent_out(a) for a in rows]


@router.get("/v1/agents/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> AgentOut:
    return _agent_out(await _agent_or_404(db, project, agent_id))


@router.post(
    "/v1/agents/{agent_id}/manifests", response_model=ManifestOut, status_code=status.HTTP_201_CREATED
)
async def publish_manifest(
    agent_id: str,
    body: ManifestIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> ManifestOut:
    agent = await _agent_or_404(db, project, agent_id)
    manifest = body.manifest
    if manifest.get("agent_id") != agent.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Manifest agent_id does not match")
    if not verify_manifest_signature(agent.public_key, manifest):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid manifest signature")
    try:
        version = int(manifest["version"])
        issued_at = _parse_ts(manifest["issued_at"])
        expires_at = _parse_ts(manifest.get("expires_at"))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Malformed manifest")
    latest = (
        await db.execute(select(func.max(ScopeManifest.version)).where(ScopeManifest.agent_id == agent.id))
    ).scalar_one()
    if latest is not None and version <= latest:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Manifest version must exceed {latest}")
    row = ScopeManifest(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version=version,
        manifest=manifest,
        signature=str(manifest["signature"]),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return _manifest_out(row)


@router.get("/v1/agents/{agent_id}/manifest", response_model=ManifestOut)
async def current_manifest(
    agent_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> ManifestOut:
    agent = await _agent_or_404(db, project, agent_id)
    row = (
        await db.execute(
            select(ScopeManifest)
            .where(ScopeManifest.agent_id == agent.id, ScopeManifest.revoked_at.is_(None))
            .order_by(ScopeManifest.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active manifest")
    return _manifest_out(row)


async def _manifest_version(db: AsyncSession, agent: Agent, version: int) -> ScopeManifest:
    row = (
        await db.execute(
            select(ScopeManifest).where(ScopeManifest.agent_id == agent.id, ScopeManifest.version == version)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manifest version not found")
    return row


@router.get("/v1/agents/{agent_id}/manifests/{version}", response_model=ManifestOut)
async def get_manifest_version(
    agent_id: str,
    version: int,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> ManifestOut:
    agent = await _agent_or_404(db, project, agent_id)
    return _manifest_out(await _manifest_version(db, agent, version))


@router.post("/v1/agents/{agent_id}/manifests/{version}/revoke", response_model=ManifestOut)
async def revoke_manifest(
    agent_id: str,
    version: int,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> ManifestOut:
    agent = await _agent_or_404(db, project, agent_id)
    row = await _manifest_version(db, agent, version)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return _manifest_out(row)


@router.get("/v1/incidents", response_model=List[IncidentOut])
async def list_incidents(
    agent_id: Optional[str] = None,
    incident_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> List[IncidentOut]:
    stmt = select(Incident).where(Incident.project_id == project.id)
    if agent_id:
        stmt = stmt.where(Incident.agent_id == agent_id)
    if incident_status:
        stmt = stmt.where(Incident.status == incident_status)
    rows = (await db.execute(stmt.order_by(Incident.created_at.desc()).limit(limit))).scalars()
    return [IncidentOut.model_validate(r, from_attributes=True) for r in rows]


async def _incident_or_404(db: AsyncSession, project: Project, incident_id: str) -> Incident:
    row = (
        await db.execute(select(Incident).where(Incident.id == incident_id, Incident.project_id == project.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    return row


@router.get("/v1/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(
    incident_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> IncidentOut:
    return IncidentOut.model_validate(await _incident_or_404(db, project, incident_id), from_attributes=True)


@router.post("/v1/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve_incident(
    incident_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> IncidentOut:
    row = await _incident_or_404(db, project, incident_id)
    row.status = "resolved"
    await db.flush()
    return IncidentOut.model_validate(row, from_attributes=True)


def _trust_out(row: TrustScore) -> TrustOut:
    return TrustOut(
        agent_id=row.agent_id,
        score=row.score,
        band=row.band,
        components=row.components,
        computed_at=row.computed_at,
        trigger_run_id=row.trigger_run_id,
    )


@router.post("/v1/agents/{agent_id}/trust", response_model=TrustOut, status_code=status.HTTP_201_CREATED)
async def record_trust(
    agent_id: str,
    body: TrustIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> TrustOut:
    agent = await _agent_or_404(db, project, agent_id)
    row = TrustScore(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        score=body.score,
        band=body.band,
        components=body.components,
        computed_at=datetime.now(timezone.utc),
        trigger_run_id=body.trigger_run_id,
    )
    db.add(row)
    await db.flush()
    return _trust_out(row)


@router.get("/v1/agents/{agent_id}/trust", response_model=TrustOut)
async def latest_trust(
    agent_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> TrustOut:
    agent = await _agent_or_404(db, project, agent_id)
    row = (
        await db.execute(
            select(TrustScore)
            .where(TrustScore.agent_id == agent.id)
            .order_by(TrustScore.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No trust score computed yet")
    return _trust_out(row)


@router.get("/v1/agents/{agent_id}/trust/history", response_model=List[TrustOut])
async def trust_history(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> List[TrustOut]:
    agent = await _agent_or_404(db, project, agent_id)
    rows = (
        await db.execute(
            select(TrustScore)
            .where(TrustScore.agent_id == agent.id)
            .order_by(TrustScore.computed_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [_trust_out(r) for r in rows]


@router.get("/v1/agents/{agent_id}/trust-inputs", response_model=TrustInputsOut)
async def trust_inputs(
    agent_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> TrustInputsOut:
    """Raw measurements for the trust formula; the score itself is computed by `controlplane`."""
    agent = await _agent_or_404(db, project, agent_id)

    policy_rows = (
        await db.execute(
            select(SpanModel.run_id, SpanModel.output)
            .join(Run, Run.id == SpanModel.run_id)
            .where(Run.project_id == project.id, SpanModel.type == "policy")
            .order_by(SpanModel.started_at.desc())
            .limit(MAX_POLICY_SPANS_SCANNED)
        )
    ).all()
    run_ids: List[str] = []
    for run_id, output in policy_rows:
        details = output.get("details") if isinstance(output, dict) else None
        if isinstance(details, dict) and details.get("agent_id") == agent.id and run_id not in run_ids:
            run_ids.append(run_id)

    failure_rate = 0.0
    if run_ids:
        recent = (
            await db.execute(
                select(Run.status).where(Run.id.in_(run_ids)).order_by(Run.started_at.desc()).limit(RECENT_RUNS_WINDOW)
            )
        ).scalars().all()
        failure_rate = sum(1 for s in recent if s in ("failure", "halted")) / len(recent) if recent else 0.0

    case_ids = (
        await db.execute(
            select(RegressionCase.id).where(RegressionCase.project_id == project.id, RegressionCase.status == "active")
        )
    ).scalars().all()
    verdicts: List[bool] = []
    for case_id in case_ids:
        latest = (
            await db.execute(
                select(TestResult.pass_rate)
                .where(TestResult.case_id == case_id)
                .order_by(TestResult.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None:
            verdicts.append(latest >= 1.0)
    regression_rate = sum(verdicts) / len(verdicts) if verdicts else 1.0

    violations = (
        await db.execute(
            select(Incident.created_at).where(Incident.agent_id == agent.id, Incident.kind.in_(VIOLATION_KINDS))
        )
    ).scalars().all()

    return TrustInputsOut(
        runs_count=len(run_ids),
        recent_failure_rate=failure_rate,
        regression_pass_rate=regression_rate,
        violation_times=[_aware(v) for v in violations],
    )


def _token_out(row: AccessToken) -> TokenOut:
    return TokenOut(
        id=row.id,
        agent_id=row.agent_id,
        connector=row.connector,
        scopes=row.scopes,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


@router.post("/v1/agents/{agent_id}/tokens", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register_token(
    agent_id: str,
    body: TokenIn,
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    """Stores the token's hash (never the secret), issued by the broker."""
    agent = await _agent_or_404(db, project, agent_id)
    if (await db.get(AccessToken, body.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Token id already exists")
    row = AccessToken(
        id=body.id,
        agent_id=agent.id,
        connector=body.connector,
        scopes=sorted(set(body.scopes)),
        issued_at=datetime.now(timezone.utc),
        expires_at=body.expires_at,
    )
    db.add(row)
    await db.flush()
    return _token_out(row)


async def _token_or_404(db: AsyncSession, project: Project, token_id: str) -> AccessToken:
    row = (
        await db.execute(
            select(AccessToken)
            .join(Agent, Agent.id == AccessToken.agent_id)
            .where(AccessToken.id == token_id, Agent.project_id == project.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    return row


@router.get("/v1/tokens/{token_id}", response_model=TokenOut)
async def get_token(
    token_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> TokenOut:
    return _token_out(await _token_or_404(db, project, token_id))


@router.post("/v1/tokens/{token_id}/revoke", response_model=TokenOut)
async def revoke_token(
    token_id: str, project: Project = Depends(get_current_project), db: AsyncSession = Depends(get_db)
) -> TokenOut:
    row = await _token_or_404(db, project, token_id)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return _token_out(row)
