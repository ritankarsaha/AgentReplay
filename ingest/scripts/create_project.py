"""Create a project + API key for local development / the Day 1 checkpoint.

Usage:
    python scripts/create_project.py "Resume Bot" resume-bot

Prints the project_id and api_key to pass to `agentreplay.init()`
(or AGENTREPLAY_PROJECT_ID / AGENTREPLAY_API_KEY env vars).
"""
from __future__ import annotations

import asyncio
import secrets
import sys

from app.db import Base, SessionLocal, engine
from app.models import Project


async def main(name: str, project_id: str) -> None:
    api_key = f"ar_{secrets.token_urlsafe(24)}"

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        session.add(Project(id=project_id, name=name, api_key=api_key))
        await session.commit()

    print(f"project_id: {project_id}")
    print(f"api_key:    {api_key}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python scripts/create_project.py <name> <project_id>", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
