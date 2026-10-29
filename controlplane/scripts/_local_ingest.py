"""Throwaway local ingest API on SQLite for checkpoint scripts. Never touches a configured database."""

from __future__ import annotations

import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]


class LocalIngest:
    def __init__(
        self, api_key: str, project_id: str, env: Optional[Dict[str, str]] = None, owner_email: Optional[str] = None
    ) -> None:
        self.api_key = api_key
        self.project_id = project_id
        self.owner_email = owner_email
        self._extra_env = env or {}
        self._dir = Path(tempfile.mkdtemp(prefix="local_ingest_"))
        self._db = self._dir / "ingest.db"
        self._proc: Optional[subprocess.Popen] = None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "LocalIngest":
        env = {
            **os.environ,
            "AGENTREPLAY_INGEST_DATABASE_URL": f"sqlite+aiosqlite:///{self._db}",
            "AGENTREPLAY_INGEST_ENVIRONMENT": "development",
            "AGENTREPLAY_INGEST_CLASSIFIER_BACKEND": "none",
            "AGENTREPLAY_INGEST_LLM_RATE_LIMIT_PER_HOUR": "1000",
            **self._extra_env,
        }
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(self.port), "--log-level", "warning"],
            cwd=ROOT / "ingest",
            env=env,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.endpoint}/docs", timeout=1).status_code == 200:
                    break
            except httpx.RequestError:
                time.sleep(0.3)
        else:
            self._proc.terminate()
            raise RuntimeError("local ingest did not start")
        con = sqlite3.connect(self._db)
        con.execute(
            "INSERT INTO projects (id, name, api_key_hash, owner_email) VALUES (?, ?, ?, ?)",
            (self.project_id, "local-check", hashlib.sha256(self.api_key.encode()).hexdigest(), self.owner_email),
        )
        con.commit()
        con.close()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc.wait(timeout=10)
