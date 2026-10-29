"""Seed the demo trust trajectory (pre-demo -> post-incident -> post-fix) for one agent.

These are illustrative inputs run through the real formula, not measurements; the stored
components carry `"seeded": true` so the UI can label them.

    python -m controlplane.scripts.seed_trust                       # print only
    python -m controlplane.scripts.seed_trust --endpoint URL --api-key KEY --agent-id agt_...
"""

from __future__ import annotations

import argparse
from typing import Dict, List, Tuple

from controlplane.govern.trust import TrustResult, compute_trust

STAGES: List[Tuple[str, Dict]] = [
    ("pre-demo", dict(recent_failure_rate=0.40, regression_pass_rate=0.50, penalty_override=0.15, runs_count=12)),
    ("post-incident", dict(recent_failure_rate=0.40, regression_pass_rate=0.50, penalty_override=0.65, runs_count=13)),
    ("post-fix", dict(recent_failure_rate=0.40, regression_pass_rate=0.95, penalty_override=0.60, runs_count=14)),
]


def trajectory() -> List[Tuple[str, TrustResult]]:
    return [(name, compute_trust(**inputs)) for name, inputs in STAGES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint")
    parser.add_argument("--api-key")
    parser.add_argument("--agent-id")
    args = parser.parse_args()

    client = None
    if args.endpoint:
        if not (args.api_key and args.agent_id):
            parser.error("--endpoint requires --api-key and --agent-id")
        from controlplane.client import ControlPlaneClient

        client = ControlPlaneClient(args.api_key, args.endpoint)

    for name, result in trajectory():
        print(f"{name:14s} score={result.score} band={result.band} cap={result.cap_inr} INR")
        if client is not None:
            seeded = TrustResult(result.score, result.band, result.cap_inr, {**result.components, "seeded": True})
            client.record_trust(args.agent_id, seeded, trigger_run_id=f"seed:{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
