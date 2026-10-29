"""Credit audit: spend recorded by the ledger against the hackathon budget.

    python -m controlplane.scripts.credits [--budget 150] [--prior 0.0]

The ledger (.agentreplay/credits.jsonl) holds only calls made since it was introduced and only calls
whose cost is known: SAM reports no token usage, so those calls are counted but unpriced. `--prior`
adds spend from before the ledger existed (see PROGRESS-HACKATHON.md). Estimates, not the dashboard.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from controlplane import ledger

REPLAN_FRACTION = 0.6
LEDGER_PATH = ".agentreplay/credits.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget", type=float, default=150.0)
    parser.add_argument("--prior", type=float, default=0.0, help="USD spent before the ledger existed")
    parser.add_argument("--ledger", default=LEDGER_PATH)
    args = parser.parse_args()

    entries = ledger.load(args.ledger)
    by_purpose = defaultdict(lambda: [0, 0.0])
    unpriced = 0
    for entry in entries:
        by_purpose[entry.purpose][0] += 1
        by_purpose[entry.purpose][1] += entry.cost_usd or 0.0
        unpriced += entry.cost_usd is None

    recorded = sum(v[1] for v in by_purpose.values())
    total = recorded + args.prior
    print(f"{'purpose':14s} {'calls':>6s} {'USD':>9s}")
    for purpose, (calls, cost) in sorted(by_purpose.items()):
        print(f"{purpose:14s} {calls:>6d} {cost:>9.4f}")
    print(f"\nledger calls: {len(entries)} ({unpriced} unpriced)   ledger spend: ${recorded:.4f}   prior (manual): ${args.prior:.4f}")
    print(f"estimated total: ${total:.4f} of ${args.budget:.2f} ({total / args.budget:.1%}); remaining ${args.budget - total:.2f}")
    if total > REPLAN_FRACTION * args.budget:
        print(f"OVER {REPLAN_FRACTION:.0%} of budget: pause and re-plan")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
