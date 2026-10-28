# AgentReplay quickstart

## 1. Get an API key

Sign in to the dashboard with Google → **Projects** → create a project. Copy the
API key immediately: only a hash is stored, so it can't be shown again (you can
rotate it any time, which invalidates the old one).

```bash
pip install agentreplay          # extras: agentreplay[anthropic], [openai], [langgraph]
export AGENTREPLAY_API_KEY=ar_...
# Only if you self-host or aren't using the default hosted API:
# export AGENTREPLAY_ENDPOINT=https://your-ingest.example.com
agentreplay doctor
```

`doctor` verifies the key and endpoint and sends a test span (you'll see a
`doctor-…` run in the dashboard). Run it first whenever nothing shows up.

## 2. Record an agent

```python
import agentreplay
agentreplay.init()   # patches anthropic / openai clients that are installed
```

Call it once, before you create your LLM clients' first request. Spans are
batched and sent in a background thread; call `agentreplay.shutdown()` at the
end of short scripts so nothing is left unsent (it also runs at exit).

Optional arguments: `environment=`, `agent_version=` (defaults to the git
SHA), `framework=`, `enabled=False` (no-op mode for tests), `redact=`.
`AGENTREPLAY_PROJECT_ID` is optional — the API key identifies the project.

### Tools

LLM calls are recorded automatically. Wrap your tool functions so they're
recorded too, and so replay can mock them instead of hitting live systems:

```python
@agentreplay.tool
def search_orders(customer_id: str) -> list[dict]:
    ...
```

### LangGraph

```python
from agentreplay.adapters.langgraph import AgentReplayCallbackHandler
graph.invoke(state, config={"callbacks": [AgentReplayCallbackHandler()]})
```

### Marking failures

Unhandled exceptions are not detected automatically unless you opt in:

```python
with agentreplay.track():        # or @agentreplay.track
    run_agent()

agentreplay.fail("refund issued without approval")   # explicit failure
```

A failed run is classified automatically (MAST category, diagnosis, culprit
span) and shown in the dashboard.

## 3. Protect user data

Prompts and tool I/O are stored as recorded. Scrub them before they leave the
process with a `redact=` callback (a function from a span's input/output dict to
a dict):

```python
agentreplay.init(redact=agentreplay.redact_fields())          # masks default sensitive keys
agentreplay.init(redact=agentreplay.redact_fields(["ssn", "card_no"]))  # your own key names
```

**What this does and doesn't do:** `redact_fields` masks the *value of any dict
key* whose name matches (email, phone, ssn, password, api_key, access_token, …,
case-insensitive, recursively). It does **not** scan free text, so an email address
written inside a prompt string is not detected. If your prompts embed personal
data, pass your own function that scrubs those strings.

## 4. Replay a failure locally

```bash
agentreplay replay <run_id> --entrypoint "myagent.main:run"
```

The entrypoint is a callable that takes no arguments. Every LLM and tool call is
served from the recording, so this makes zero live API calls. If your code now
makes a different call than the recording, you get a `ReplayDivergence` with a
diff instead of silent drift.

## 5. Generate a regression test

In the dashboard, open a failed run → **Generate Test** and enter your entrypoint
(`module.path:function`), or from the CLI:

```bash
agentreplay generate-test <run_id> --entrypoint "myagent.main:run" --output-dir tests/regressions
pytest tests/regressions
```

The test replays your agent with recorded tool outputs and asserts the behaviour
a fixed agent must have (tools it must/must not call, step limits, no exception,
optional LLM-judge rubric). It fails until the bug is fixed.

## 6. Gate pull requests

Promote a classified failure to a regression case and activate it (new cases
start as `proposed` and never gate CI until activated):

```bash
curl -X POST "$AGENTREPLAY_ENDPOINT/v1/regression-cases" \
  -H "Authorization: Bearer $AGENTREPLAY_API_KEY" -H "Content-Type: application/json" \
  -d '{"run_id": "<run_id>", "entrypoint": "myagent.main:run", "priority": "P0"}'

curl -X PATCH "$AGENTREPLAY_ENDPOINT/v1/regression-cases/<case_id>" \
  -H "Authorization: Bearer $AGENTREPLAY_API_KEY" -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

(`$AGENTREPLAY_ENDPOINT` is the API base URL; the default hosted one is
`https://agentreplay-ingest.fly.dev`.) Then add the Action — see
[.github/actions/agentreplay-gate/README.md](.github/actions/agentreplay-gate/README.md).
Each PR re-runs every active case 3 times against live LLM calls with tools
mocked; P0 cases must pass 3/3, P1 2/3.

## Limits (hosted)

- 1,000 spans per request, 5 MB per request body, one span ≤ 1 MB (larger
  spans are dropped client-side with a warning).
- 600 ingest requests/minute and 30 LLM-backed actions (test generation,
  case registration)/hour per project; excess returns `429` with `Retry-After`.
- 5 projects per account.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Nothing in the dashboard | `agentreplay doctor`; check the right project is selected in the header |
| `API key was rejected` on stderr | Key mistyped or rotated — rotate again on the Projects page |
| `429` in stderr | You hit a rate limit; batches are dropped, not retried (v1) |
| Streaming calls show no output | Known limitation: streaming is recorded as a placeholder |
