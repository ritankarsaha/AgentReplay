"""Measure MAST classification and semantic-judge quality per backend on the labeled synthetic cases.

    ingest/.venv/bin/python -m controlplane.scripts.benchmark [--trials 3] [--backends meta nim anthropic]

Needs the ingest virtualenv (it reuses the real classifier prompt). Backends without a key are
reported as skipped, never scored. Results are written to .agentreplay/benchmarks/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from controlplane.learn import benchmark


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=benchmark.TRIALS)
    parser.add_argument("--backends", nargs="+", default=["meta", "nim", "anthropic"])
    args = parser.parse_args()

    results = benchmark.run_benchmark(args.backends, trials=args.trials)
    print(benchmark.render(results, args.trials))
    for result in results:
        for confusion in result.classifier_confusions:
            print(f"  [{result.backend}] {confusion['case']}: expected {confusion['expected']}, got {confusion['got']}")

    out_dir = Path(".agentreplay/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"benchmark-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps({"trials": args.trials, "results": [asdict(r) for r in results]}, indent=2))
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
