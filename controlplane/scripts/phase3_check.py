"""One demo run (beats 1-10) on a throwaway local ingest, optionally kept up for the viewer.

    ingest/.venv/bin/python -m controlplane.scripts.phase3_check               # live Muse Spark
    ingest/.venv/bin/python -m controlplane.scripts.phase3_check --mode replay # from the recording
    ingest/.venv/bin/python -m controlplane.scripts.phase3_check --no-llm      # deterministic parts only
    ingest/.venv/bin/python -m controlplane.scripts.phase3_check --serve       # then keep the ingest up for the viewer
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from dotenv import load_dotenv

from controlplane import ledger
from controlplane.demo import API_KEY, DEFAULT_CASSETTE, PROJECT_ID, DemoOptions, ingest_env, run_demo
from controlplane.scripts._local_ingest import LocalIngest


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["live", "record", "replay", "fallback"], default="live")
    parser.add_argument("--cassette", default=DEFAULT_CASSETTE)
    parser.add_argument("--no-llm", action="store_true", help="skip every model-written beat")
    parser.add_argument("--serve", action="store_true", help="keep the local ingest running afterwards for the viewer")
    parser.add_argument("--owner", default="demo@example.com", help="viewer email that owns the project")
    parser.add_argument("--viewer-token", default="local-viewer-token", help="service token the viewer presents")
    args = parser.parse_args()

    llm = not args.no_llm
    if llm and args.mode != "replay" and not os.environ.get("META_API_KEY"):
        print("META_API_KEY not set; running with --no-llm")
        llm = False
    if args.mode != "replay":
        ledger.LEDGER.configure(".agentreplay/credits.jsonl")

    options = DemoOptions(mode=args.mode, cassette_path=args.cassette, llm=llm, owner=args.owner, viewer_token=args.viewer_token)
    with LocalIngest(API_KEY, PROJECT_ID, ingest_env(options), owner_email=args.owner) as ingest:
        result = run_demo(ingest, options)
        print("\nnarrative:", result.narrative)
        if result.scoreboard_table:
            print(result.scoreboard_table)
        print(f"spend this run: {result.spend}")
        print("PASS" if result.clean else "FAIL")
        if args.serve:
            print(f"\nviewer env: INGEST_API_URL={ingest.endpoint} INGEST_SERVICE_TOKEN={args.viewer_token}")
            print(f"owner: {args.owner}  project: {PROJECT_ID}  incident: {result.incident_id}  share: /share/{result.share_token}")
            print("Ctrl-C to stop.")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
    return 0 if result.clean else 1


if __name__ == "__main__":
    sys.exit(main())
