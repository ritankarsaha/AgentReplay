# AgentReplay

**The flight recorder for AI agents.** When an agent fails in production, you
usually can't reproduce it. AgentReplay records every LLM call and tool call,
replays the failure deterministically on your machine, and turns it into a
regression test that gates your CI.

```
production failure → deterministic replay → regression test → CI gate
```

- **Record** — one `agentreplay.init()` call patches the Anthropic and OpenAI
  clients (and anything OpenAI-compatible, e.g. NVIDIA NIM). No framework
  lock-in; a LangGraph adapter adds node-level structure.
- **Diagnose** — failed runs are classified against the MAST failure taxonomy
  with a diagnosis and the culprit span highlighted in the dashboard.
- **Replay** — `agentreplay replay <run_id>` re-runs the failure locally with
  zero live API calls. If your code diverges from the recording you get a diff.
- **Test** — one click generates a pytest file with a fixture of the recorded
  tool responses and an assertion spec (structural checks, optional LLM judge).
- **Gate** — a GitHub Action runs those tests against every PR (live LLM calls,
  mocked tools, N trials) and blocks the merge on regression.

## Quickstart (about 5 minutes)

1. Sign in to the dashboard, create a project, and copy its API key (shown once).
2. Install and instrument:

```bash
pip install agentreplay
export AGENTREPLAY_API_KEY=ar_...
agentreplay doctor          # checks your key + connectivity, sends a test span
```

```python
import agentreplay

agentreplay.init()          # reads AGENTREPLAY_API_KEY

# ... your agent, unchanged ...

agentreplay.shutdown()      # flush before exit (also runs automatically at exit)
```

Your runs appear in the dashboard. See **[QUICKSTART.md](QUICKSTART.md)** for
tools, failures, redaction, replay, test generation and CI.

## Repository layout and licensing

| Path | What | License |
|---|---|---|
| `agentreplay/` | Python SDK + CLI (recorder, replay engine, test generator, regression runner) | Apache-2.0 |
| `examples/`, `tests/`, `.github/actions/` | Examples, SDK tests, the `agentreplay-gate` Action | Apache-2.0 |
| `ingest/` | Hosted API: ingest, classifier, regression-case storage | Source-available ([ingest/LICENSE](ingest/LICENSE)) |
| `web/` | Dashboard (Next.js) | Source-available ([web/LICENSE](web/LICENSE)) |

The SDK is open source; the hosted service components are source-available for
review. See [NOTICE](NOTICE).

## Status

Early alpha. The record → classify → replay → generate-test → CI-gate loop works
end to end. Known limits: streaming responses are recorded as a placeholder
(not assembled), Python only, and the dashboard has no UI yet for promoting a
failure to a CI regression case (use the API; see QUICKSTART).

## Security

Traces can contain sensitive data. Use the `redact=` hook to scrub it
client-side (by field name; it does not scan free text) before anything leaves your process — see QUICKSTART. Report
vulnerabilities per [SECURITY.md](SECURITY.md).
