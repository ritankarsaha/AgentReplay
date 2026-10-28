from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_current_project
from ..models import Project, Run, SpanModel
from ..pricing import span_cost_usd

router = APIRouter(tags=["usage"])

MAX_SPANS_SCANNED = 20_000


class ModelCost(BaseModel):
    calls: int
    priced_calls: int
    cost_usd: float


class CostsOut(BaseModel):
    total_cost_usd: float
    by_model: Dict[str, ModelCost]
    unpriced_calls: int
    credit_budget_usd: float
    credit_remaining_usd: float
    credit_used_pct: float
    scanned_spans: int
    truncated: bool


@router.get("/v1/usage/costs", response_model=CostsOut)
async def get_costs(
    since: Optional[datetime] = Query(default=None, description="Only spans started at/after this time"),
    project: Project = Depends(get_current_project),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CostsOut:
    stmt = (
        select(SpanModel.input, SpanModel.output)
        .join(Run, Run.id == SpanModel.run_id)
        .where(Run.project_id == project.id, SpanModel.type == "llm")
        .order_by(SpanModel.started_at.desc())
        .limit(MAX_SPANS_SCANNED + 1)
    )
    if since is not None:
        stmt = stmt.where(SpanModel.started_at >= since)
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > MAX_SPANS_SCANNED
    rows = rows[:MAX_SPANS_SCANNED]

    calls: Dict[str, int] = defaultdict(int)
    priced: Dict[str, int] = defaultdict(int)
    cost: Dict[str, float] = defaultdict(float)
    unpriced = 0
    for span_input, span_output in rows:
        model = (
            (span_output or {}).get("model") if isinstance(span_output, dict) else None
        ) or (span_input.get("model") if isinstance(span_input, dict) else None) or "unknown"
        calls[model] += 1
        value = span_cost_usd(span_input, span_output)
        if value is None:
            unpriced += 1
        else:
            priced[model] += 1
            cost[model] += value

    total = round(sum(cost.values()), 6)
    budget = settings.meta_credit_budget_usd
    return CostsOut(
        total_cost_usd=total,
        by_model={
            m: ModelCost(calls=calls[m], priced_calls=priced[m], cost_usd=round(cost[m], 6))
            for m in calls
        },
        unpriced_calls=unpriced,
        credit_budget_usd=budget,
        credit_remaining_usd=round(budget - total, 6),
        credit_used_pct=round(100 * total / budget, 2) if budget else 0.0,
        scanned_spans=len(rows),
        truncated=truncated,
    )
