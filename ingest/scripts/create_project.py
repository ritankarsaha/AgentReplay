"""Create a project + API key (operator tool; end users self-serve in the viewer).

Usage:
    python scripts/create_project.py "Resume Bot" [owner-email]

Prints the project_id and api_key to pass to `agentreplay.init()` (or the
AGENTREPLAY_PROJECT_ID / AGENTREPLAY_API_KEY env vars). With `owner-email`
the project also shows up in that user's viewer account. The key is shown
once; only its hash is stored.
"""
from __future__ import annotations

import asyncio
import sys

from app import crud
from app.db import Base, SessionLocal, engine


async def main(name: str, owner_email: str | None) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        project, api_key = await crud.create_project(session, name=name, owner_email=owner_email)
        await session.commit()

    print(f"project_id: {project.id}")
    print(f"api_key:    {api_key}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("usage: python scripts/create_project.py <name> [owner-email]", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2].lower() if len(sys.argv) == 3 else None))
