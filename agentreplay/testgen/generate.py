
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from ..replay.loader import fetch_run, load_run_from_file
from ..replay.runner import resolve_entrypoint
from .fixture import FixtureData, build_fixture_data, write_fixture_module
from .test_template import render_test_module, slugify_run_id, write_test_module


@dataclass
class GeneratedTest:
    """What `generate_test()`/`generate_test_from_file()` produced."""

    run_id: str
    fixture_path: Path
    test_path: Path
    fixture: FixtureData
    assertion_spec: Optional[dict]


def _write_generated_test(
    run_id: str, data: dict, entrypoint: str, output_dir: Union[str, Path]
) -> GeneratedTest:
    output_dir = Path(output_dir)
    slug = slugify_run_id(run_id)

    fixture = build_fixture_data(run_id, data.get("spans", []))
    fixture_path = write_fixture_module(fixture, output_dir / f"fixture_{slug}.py")

    assertion_spec = (data.get("diagnosis") or {}).get("assertion_spec")
    test_source = render_test_module(
        fixture_module=f"fixture_{slug}",
        entrypoint=entrypoint,
        run_id=run_id,
        assertion_spec=assertion_spec,
    )
    test_path = write_test_module(test_source, output_dir / f"test_{slug}.py")

    return GeneratedTest(
        run_id=run_id,
        fixture_path=fixture_path,
        test_path=test_path,
        fixture=fixture,
        assertion_spec=assertion_spec,
    )


def generate_test(
    run_id: str,
    entrypoint: str,
    output_dir: Union[str, Path],
    *,
    endpoint: str,
    api_key: str,
    timeout: float = 30.0,
) -> GeneratedTest:
    """Fetch `run_id` from the ingest API; write its fixture + pytest file into `output_dir`.

    Validates `entrypoint` (raises `ValueError`, same contract as
    `resolve_entrypoint()`) before writing anything — fail fast on a typo'd
    spec rather than only discovering it when the generated test later
    runs. Raises `TraceFetchError` on a bad run_id/credentials/network
    failure. If `run_id` has a chunk 4.3 assertion spec, the generated test
    asserts on it (chunk 4.4); otherwise it falls back to chunk 4.2's
    placeholder `assert True`.
    """
    resolve_entrypoint(entrypoint)  # validate only; the rendered test resolves it again at run time

    data = fetch_run(run_id, endpoint=endpoint, api_key=api_key, timeout=timeout)
    return _write_generated_test(run_id, data, entrypoint, output_dir)


def generate_test_from_file(
    trace_file: Union[str, Path], entrypoint: str, output_dir: Union[str, Path]
) -> GeneratedTest:
    """Load a trace from a local JSON file; write its fixture + pytest file into `output_dir`.

    Offline equivalent of `generate_test()` — no `endpoint`/`api_key` needed
    at all. The file must include a `diagnosis` key (the same shape
    `GET /v1/runs/{run_id}` returns) for chunk 4.4's real assertions to
    render — a bare `{"spans": [...]}` file falls back to the chunk 4.2
    placeholder, same as an un-classified/un-spec'd run fetched live.
    """
    resolve_entrypoint(entrypoint)  # validate only; the rendered test resolves it again at run time

    data = load_run_from_file(trace_file)
    run_id = data.get("id") or str(trace_file)
    return _write_generated_test(run_id, data, entrypoint, output_dir)
