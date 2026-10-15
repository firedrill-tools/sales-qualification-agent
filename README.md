# Sales qualification agent

A LangChain/OpenAI agent investigates a sales lead across CRM people and companies, inbound email and availability. The default application path uses a small synthetic workspace so the same task can be run safely without connected SaaS accounts. A separate Composio path exposes real hosted tools to the same LangChain agent when connected test accounts are available.

## Run locally

Requires Python 3.12, `uv` and an OpenAI key for model runs.

```sh
uv sync --dev
cp fixtures/starter.json workspace.json
OPENAI_API_KEY=... uv run qualify-lead --workspace workspace.json --allow-write \
  'Qualify mira@harbor.example from her message, and book an available slot if justified. Use request ID demo-1.'
uv run pytest
```

Without `--allow-write`, local tools reject mutations. Copy the starter fixture again to reset state. Each operation reloads the latest committed state, and individual writes replace the file atomically. Use one writer at a time for a workspace file; this does not provide a concurrent read/modify/write transaction or lock. The model response is printed; inspect `workspace.json` for committed changes. If a key is missing the command exits before a model call.

## Composio connector path

This path uses `composio==0.27.0`, `composio-langchain==0.27.0` and Composio's `attio`, `gmail`, and `googlecalendar` toolkits. It calls hosted Composio actions; it does **not** route them through the local workspace or intercept a hosted MCP transport. Action availability, exact schemas, auth scopes and response shapes require a connected test account and have not yet been qualified. Do not connect production accounts.

```sh
OPENAI_API_KEY=... COMPOSIO_API_KEY=... COMPOSIO_USER_ID=test-user \
  uv run qualify-lead --mode composio --allow-live-actions \
  'Investigate the lead identified by a test email address; report findings only.'
```

The Composio mode has no synthetic fallback. Hosted actions may change remote data, so the explicit flag and test accounts are required. For a controlled simulation connection, replace the application-side tool adapter at `synthetic_tools` with a supported service after the new Firedrill release is verified; this is not full Composio hosted-connector compatibility.

## Evidence and limits

`scenarios/README.md` lists a routine case, duplicate identities, incomplete budget, retries and denied writes. The 11 offline checks verify local record identity, exact meeting replay/conflict semantics, reads from a long-lived adapter after later commits, preservation of unrelated changes, read-only boundaries and atomic-publication failure recovery. A reused meeting ID with a different person or slot is rejected without returning another person's booking. Blank evidence reasons or request IDs are rejected. These checks do not exercise the actual LangChain/OpenAI model adapter; its completion/evidence path and four-profile versioned datasets remain follow-up development work. No live model or Composio execution has been performed because the needed keys and connected test accounts are not available here. Model quality, tool choice, usage and hosted connector behavior remain unmeasured.

No license has been selected for public publication.

Explore related applications in the [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog). Product and setup references: [Firedrill](https://firedrill.run/) and the [official developer documentation](https://docs.firedrill.run/). Use documentation matching the qualified release; this repository records its current integration limits above.
