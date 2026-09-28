"""`agentreplay` console script (chunk 3.4 + Day 3 backlog: local-file loading,
+ chunk 4.1: fixture generation, + chunk 4.2: pytest template generation).

    agentreplay replay <run_id> --entrypoint module.path:function_name
    agentreplay replay --file trace.json --entrypoint module.path:function_name
    agentreplay fixture <run_id> --output tests/fixtures/run_xxx.py
    agentreplay fixture --file trace.json --output tests/fixtures/run_xxx.py
    agentreplay generate-test <run_id> --entrypoint module.path:function_name --output-dir tests/fixtures
    agentreplay generate-test --file trace.json --entrypoint module.path:function_name --output-dir tests/fixtures

`replay`: fetches the recorded trace for `run_id` from the ingest API (or
loads it from a local JSON file with `--file` — no credentials needed at
all, for a trace shared offline), replays it (Mode A — CLAUDE.md §3.2:
every LLM call and `@agentreplay.tool` call served from the recording, zero
live calls, zero API key needed for the agent itself), and calls
`entrypoint` — the same agent code that produced the original run,
reproduced locally so it can be stepped through.

`fixture`: fetches the same kind of trace and writes a self-contained
Python module with the recorded entrypoint input and recorded tool
call/response pairs (CLAUDE.md §4 chunk 4.1) — the data half of the Day 4
test generator, meant to be committed to the user's repo.

`generate-test`: does what `fixture` does, plus renders a sibling pytest
file (CLAUDE.md §4 chunk 4.2) that imports the fixture, mocks every
recorded tool call from it, and calls `--entrypoint` with the recorded
input (LLM calls are left live — Mode B semantics). If the run already has
a chunk 4.3 assertion spec (`diagnosis.assertion_spec`, generated via
`POST /v1/runs/{run_id}/assertion-spec`), the generated test asserts on it
for real — structural checks (chunk 4.4) plus, if the spec includes a
`semantic_rubric`, an LLM-judge check on the agent's actual output content
(chunk 4.7); otherwise it falls back to a placeholder `assert True` — see
the printed summary line for which happened.

Deliberately a thin wrapper: all the actual logic is in
`agentreplay/replay/runner.py:replay_run()`/`replay_run_from_file()` and
`agentreplay/testgen/`'s `generate_fixture()`/`generate_fixture_from_file()`
(4.1) and `generate_test()`/`generate_test_from_file()` (4.2+4.4), none of
which have argparse/exit-code concerns — all are usable directly from
other tooling.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from .config import DEFAULT_ENDPOINT
from .replay.exceptions import ReplayDivergence, ReplayedError, TraceFetchError
from .replay.runner import replay_run, replay_run_from_file
from .testgen.fixture import generate_fixture, generate_fixture_from_file
from .testgen.generate import generate_test, generate_test_from_file


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

    fixture_parser = subparsers.add_parser(
        "fixture",
        help="Generate a test fixture module from a recorded run (CLAUDE.md §4 chunk 4.1)",
    )
    fixture_parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="The run id to fetch (GET /v1/runs/{run_id}) — omit if using --file",
    )
    fixture_parser.add_argument(
        "--file",
        default=None,
        help="Path to a local trace JSON file, as an alternative to fetching by run_id. "
        "No --endpoint/--api-key needed with this option.",
    )
    fixture_parser.add_argument(
        "--output",
        required=True,
        help="Path to write the generated fixture .py file (e.g. tests/fixtures/run_xxx.py)",
    )
    fixture_parser.add_argument(
        "--endpoint",
        default=None,
        help=f"Ingest API base URL (default: $AGENTREPLAY_ENDPOINT, else {DEFAULT_ENDPOINT})",
    )
    fixture_parser.add_argument(
        "--api-key",
        default=None,
        help="Ingest API key (default: $AGENTREPLAY_API_KEY)",
    )
    fixture_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds (default: 30)"
    )

    gen_test_parser = subparsers.add_parser(
        "generate-test",
        help="Generate a fixture + a calling pytest file from a recorded run "
        "(CLAUDE.md §4 chunks 4.1+4.2)",
    )
    gen_test_parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="The run id to fetch (GET /v1/runs/{run_id}) — omit if using --file",
    )
    gen_test_parser.add_argument(
        "--file",
        default=None,
        help="Path to a local trace JSON file, as an alternative to fetching by run_id. "
        "No --endpoint/--api-key needed with this option.",
    )
    gen_test_parser.add_argument(
        "--entrypoint",
        required=True,
        help="'module.path:function_name' to call from the generated test — receives the "
        "recorded input if it accepts a parameter, else is called with none "
        "(e.g. 'examples.langgraph_demo:main')",
    )
    gen_test_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write the fixture + test .py files into, as siblings "
        "(e.g. tests/fixtures)",
    )
    gen_test_parser.add_argument(
        "--endpoint",
        default=None,
        help=f"Ingest API base URL (default: $AGENTREPLAY_ENDPOINT, else {DEFAULT_ENDPOINT})",
    )
    gen_test_parser.add_argument(
        "--api-key",
        default=None,
        help="Ingest API key (default: $AGENTREPLAY_API_KEY)",
    )
    gen_test_parser.add_argument(
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


def _cmd_fixture(args: argparse.Namespace) -> int:
    if args.run_id and args.file:
        print("error: provide either a run_id or --file, not both", file=sys.stderr)
        return 1
    if not args.run_id and not args.file:
        print("error: provide either a run_id or --file", file=sys.stderr)
        return 1

    try:
        if args.file:
            print(f"agentreplay: loading trace from {args.file} ...")
            fixture = generate_fixture_from_file(args.file, args.output)
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
            fixture = generate_fixture(
                args.run_id,
                args.output,
                endpoint=endpoint,
                api_key=api_key,
                timeout=args.timeout,
            )
    except TraceFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nagentreplay: wrote fixture for run {fixture.run_id} to {args.output} "
        f"({len(fixture.tool_spans)} recorded tool call(s))."
    )
    return 0


def _cmd_generate_test(args: argparse.Namespace) -> int:
    if args.run_id and args.file:
        print("error: provide either a run_id or --file, not both", file=sys.stderr)
        return 1
    if not args.run_id and not args.file:
        print("error: provide either a run_id or --file", file=sys.stderr)
        return 1

    try:
        if args.file:
            print(f"agentreplay: loading trace from {args.file} ...")
            result = generate_test_from_file(args.file, args.entrypoint, args.output_dir)
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
            result = generate_test(
                args.run_id,
                args.entrypoint,
                args.output_dir,
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

    if result.assertion_spec and result.assertion_spec.get("semantic_rubric"):
        spec_note = "with generated structural + semantic assertions (chunks 4.4+4.7)"
    elif result.assertion_spec:
        spec_note = "with generated structural assertions (chunk 4.4)"
    else:
        spec_note = "with a placeholder assertion (no assertion spec yet for this run — see chunk 4.3)"
    print(
        f"\nagentreplay: wrote fixture {result.fixture_path} and test {result.test_path} "
        f"for run {result.run_id} ({len(result.fixture.tool_spans)} recorded tool call(s)), "
        f"{spec_note}."
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "fixture":
        return _cmd_fixture(args)
    if args.command == "generate-test":
        return _cmd_generate_test(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
