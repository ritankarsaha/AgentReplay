# Operator guide: deploying the public service

Everything below is a one-time checklist for whoever runs the hosted service.
Nothing here is applied automatically.

## 1. Secrets

Generate one shared token and set it on **both** sides:

```bash
openssl rand -base64 32
```

| Where | Variable |
|---|---|
| Fly (ingest `app` + `worker`) | `AGENTREPLAY_INGEST_VIEWER_SERVICE_TOKEN` |
| Vercel (viewer) | `INGEST_SERVICE_TOKEN` (replaces the old `INGEST_API_KEY`) |
| Vercel (viewer) | `AUTH_ADMIN_EMAILS` -- who can open `/logins` |
| Vercel (viewer) | `NEXT_PUBLIC_AGENTREPLAY_ENDPOINT` -- optional, display only |

## 2. Database migration (irreversible with data intact)

`0006_hash_api_keys_and_project_owner` replaces plaintext `projects.api_key`
with a SHA-256 hash (backfilled, so existing keys keep working) and **drops the
plaintext column**. Back up first (Supabase dashboard -> Database -> Backups),
then from `ingest/`: `alembic upgrade head`. Review `migrations/sql/0006_*.sql`.

Existing projects have `owner_email = NULL`: they keep working through their API
key, but won't appear in anyone's dashboard until you assign an owner:

```sql
UPDATE projects SET owner_email = 'you@example.com' WHERE id = 'resume-bot';
```

## 3. Deploy order

1. Migrate the database.
2. Deploy ingest (`flyctl deploy --config ingest/fly.toml --dockerfile ingest/Dockerfile .`
   from the repo root).
3. Deploy the viewer with the new env vars. (The new viewer talks to endpoints
   the old ingest doesn't have, so ingest must go first.)
4. Publish the SDK (below).

## 4. Publish the SDK to PyPI

```bash
python -m pip install build twine
python -m build            # dist/agentreplay-0.1.0*.whl + .tar.gz
twine check dist/*
twine upload dist/*        # irreversible: a version can never be re-uploaded
```

The `agentreplay` name must be available on PyPI -- check before you build
anything around it. Until published, `pip install agentreplay` in the docs and
dashboard will fail.

## 5. Known operational limits

- Rate limits are in-process: with N Fly machines the real limit is N x the
  configured one. Move the counters to Redis if you need exact limits.
- Open signup (any Google account) is on unless `AUTH_ALLOWED_EMAILS` is set.
  Set it for a private beta.
- Supabase free tier auto-pauses after inactivity and takes every route down;
  use a paid plan for a public service.
- LLM-backed features (classification, test generation) cost you money per
  call; the per-project hourly cap is the only brake.
