"""Run the whole demo story N times, each from a cold start (fresh ingest, database, blobs, keys).

    ingest/.venv/bin/python -m controlplane.scripts.rehearse --mode replay --runs 3   # no network, free
    ingest/.venv/bin/python -m controlplane.scripts.rehearse --mode fallback --runs 3 # live, recording as backstop
    ingest/.venv/bin/python -m controlplane.scripts.rehearse --mode record            # re-record the cassette

A run is clean when every beat check passes. Across runs the deterministic outcomes (flight, price,
booking ref, trust path, ...) must be identical; in replay mode the model-written outcomes must be too.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List

from dotenv import load_dotenv

from controlplane import ledger
from controlplane.demo import API_KEY, BEATS, DEFAULT_CASSETTE, PROJECT_ID, DemoOptions, DemoResult, ingest_env, run_demo
from controlplane.scripts._local_ingest import LocalIngest

LEDGER_PATH = ".agentreplay/credits.jsonl"


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["live", "record", "replay", "fallback"], default="replay")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cassette", default=DEFAULT_CASSETTE)
    parser.add_argument("--buyer", choices=["scripted", "meta"], default="scripted")
    parser.add_argument("--no-llm", action="store_true", help="skip every model-written beat")
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    args = parser.parse_args()

    if args.mode == "record" and args.runs != 1:
        parser.error("--mode record takes exactly one run")
    needs_key = not args.no_llm and args.mode != "replay"
    if needs_key and not os.environ.get("META_API_KEY"):
        print(f"--mode {args.mode} needs META_API_KEY (or use --mode replay / --no-llm)", file=sys.stderr)
        return 2

    options = DemoOptions(mode=args.mode, cassette_path=args.cassette, buyer=args.buyer, llm=not args.no_llm)
    if args.mode != "replay":
        ledger.LEDGER.configure(LEDGER_PATH)
    say = (lambda line: None) if args.quiet else print

    results: List[DemoResult] = []
    wall: List[float] = []
    for index in range(1, args.runs + 1):
        say(f"\n=== run {index}/{args.runs} ({args.mode}, cold start) ===")
        started = time.perf_counter()
        with LocalIngest(API_KEY, PROJECT_ID, ingest_env(options), owner_email=options.owner) as ingest:
            results.append(run_demo(ingest, options, say))
        wall.append(time.perf_counter() - started)

    print("\nrun  clean  seconds  live calls  spend USD  fallbacks  failed checks")
    for index, (res, seconds) in enumerate(zip(results, wall), start=1):
        failed = [f"beat {c.beat}: {c.label}" for c in res.checks if not c.ok]
        print(
            f"{index:<4} {'yes' if res.clean else 'NO':<6} {seconds:<8.1f} {res.spend['calls']:<11} "
            f"{res.spend['cost_usd']:<10.4f} {len(res.cassette['fallbacks']):<10} {'; '.join(failed) or '-'}"
        )

    first = results[0]
    same = all(r.outcomes == first.outcomes for r in results)
    if args.mode == "replay":
        same = same and all(r.llm_outcomes == first.llm_outcomes for r in results)
    print(f"\ndeterministic outcomes identical across runs: {'yes' if same else 'NO'}")
    for key, value in first.outcomes.items():
        print(f"  {key}: {value}")
    covered = sorted({c.beat for c in first.checks if c.beat})
    print(f"beats covered: {covered} of {sorted(BEATS)}")
    for res in results:
        for slot, reason in res.cassette["fallbacks"]:
            print(f"  fallback used for {slot}: {reason}")

    clean = all(r.clean for r in results) and same
    print("PASS" if clean else "FAIL")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
