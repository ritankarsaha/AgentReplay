"""`agentreplay` console script (chunk 3.4 + Day 3 backlog: local-file loading).

    agentreplay replay <run_id> --entrypoint module.path:function_name
    agentreplay replay --file trace.json --entrypoint module.path:function_name

Fetches the recorded trace for `run_id` from the ingest API (or loads it
from a local JSON file with `--file` — no credentials needed at all, for a
trace shared offline), replays it (Mode A — CLAUDE.md §3.2: every LLM call
and `@agentreplay.tool` call served from the recording, zero live calls,
zero API key needed for the agent itself), and calls `entrypoint` — the
same agent code that produced the original run, reproduced locally so it
can be stepped through.

Deliberately a thin wrapper: all the actual logic is in
`agentreplay/replay/runner.py:replay_run()`/`replay_run_from_file()`, which
have no argparse/exit-code concerns and are usable directly from other
tooling.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from .config import DEFAULT_ENDPOINT
from .replay.exceptions import ReplayDivergence, ReplayedError, TraceFetchError
from .replay.runner import replay_run, replay_run_from_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentreplay")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay_parser = subparsers.add_parser(
        "replay", help="Replay a recorded run locally (Mode A — CLAUDE.md §3.2)"
    )
    replay_parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="The run id to replay (GET /v1/runs/{run_id}) — omit if using --file",
    )
    replay_parser.add_argument(
        "--file",
        default=None,
        help="Path to a local trace JSON file, as an alternative to fetching by run_id "
        "(e.g. a redacted export shared for a bug report). No --endpoint/--api-key needed "
        "with this option.",
    )
    replay_parser.add_argument(
        "--entrypoint",
        required=True,
        help="'module.path:function_name' of a zero-arg callable to run under replay "
        "(e.g. 'examples.langgraph_demo:main')",
    )
    replay_parser.add_argument(
        "--endpoint",
        default=None,
        help=f"Ingest API base URL (default: $AGENTREPLAY_ENDPOINT, else {DEFAULT_ENDPOINT})",
    )
    replay_parser.add_argument(
        "--api-key",
        default=None,
        help="Ingest API key (default: $AGENTREPLAY_API_KEY)",
    )
    replay_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds (default: 30)"
    )

    return parser


def _present_result(result) -> int:  # type: ignore[no-untyped-def]
    remaining = result.session.remaining_count()
    print(f"\nagentreplay: replay complete. {remaining} recorded call(s) unused.")
    if remaining:
        print(
            "  (the entrypoint didn't take every code path the recording covered — "
            "not necessarily an error, but worth checking)"
        )
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    if args.run_id and args.file:
        print("error: provide either a run_id or --file, not both", file=sys.stderr)
        return 1
    if not args.run_id and not args.file:
        print("error: provide either a run_id or --file", file=sys.stderr)
        return 1

    try:
        if args.file:
            print(f"agentreplay: loading trace from {args.file} ...")
            result = replay_run_from_file(args.file, args.entrypoint)
        else:
            endpoint = args.endpoint or os.environ.get("AGENTREPLAY_ENDPOINT", DEFAULT_ENDPOINT)
            api_key = args.api_key or os.environ.get("AGENTREPLAY_API_KEY")
            if not api_key:
                print(
                    "error: no API key. Pass --api-key or set AGENTREPLAY_API_KEY.",
                    file=sys.stderr,
                )
                return 1
            print(f"agentreplay: fetching run {args.run_id} from {endpoint} ...")
            result = replay_run(
                args.run_id,
                args.entrypoint,
                endpoint=endpoint,
                api_key=api_key,
                timeout=args.timeout,
            )
    except TraceFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        # resolve_entrypoint()'s validation errors (bad spec, missing module/function).
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ReplayDivergence as exc:
        print(
            "\nREPLAY DIVERGENCE — your agent diverged from the recorded trace:\n",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 2
    except ReplayedError as exc:
        print(
            f"\nREPLAYED FAILURE — the recorded call originally failed: {exc}", file=sys.stderr
        )
        return 2

    return _present_result(result)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "replay":
        return _cmd_replay(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
