# AgentReplay Regression Gate (`agentreplay/gate@v1`)

CLAUDE.md §4 Day 5, chunk 5.4. A composite GitHub Action that fetches every
`active` AgentReplay regression case for your project, runs each one
`--trials` times against **this checkout's own agent code** (Mode B — live
LLM calls, tool calls mocked from the original recorded failure), and fails
the check if any case falls below its priority's pass-rate threshold
(CLAUDE.md §3.2: P0 blocks below 3/3, P1 below 2/3, by default — see
`agentreplay.regression.gate.DEFAULT_THRESHOLDS`).

## Usage (from a consumer repo)

```yaml
# .github/workflows/agentreplay.yml
name: AgentReplay regression gate
on: pull_request

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: <your-org>/agent-replay/.github/actions/agentreplay-gate@main
        with:
          api-key: ${{ secrets.AGENTREPLAY_API_KEY }}
          trials: "3"
```

Register cases first (typically from the viewer's "Promote to regression
case" flow, or directly):

```bash
curl -X POST "$AGENTREPLAY_ENDPOINT/v1/regression-cases" \
  -H "Authorization: Bearer $AGENTREPLAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "<run_id>", "entrypoint": "myagent.main:run", "priority": "P0"}'
```

A freshly-registered case starts `proposed`, not `active` — it won't gate CI
until explicitly promoted:

```bash
curl -X PATCH "$AGENTREPLAY_ENDPOINT/v1/regression-cases/<case_id>" \
  -H "Authorization: Bearer $AGENTREPLAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

## Outputs

- `verdict` — `pass` / `warn` / `fail` / `insufficient_evidence`
- `report-path` — path to the rendered Markdown report (also written to the
  job's step summary, and posted as a sticky PR comment unless
  `post-comment: "false"`)

## Exit codes

`agentreplay ci gate` (what this action runs) exits `0` for
`pass`/`warn`/`insufficient_evidence` — visible, non-blocking — and `1` for
`fail`, which fails the check and blocks the PR.
