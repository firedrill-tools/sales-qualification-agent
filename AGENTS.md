# Agent working notes

- Entry point: `qualify-lead`; model loop: `src/sales_qualification/agent.py`.
- `--mode synthetic` calls local LangChain tools in `src/sales_qualification/agent.py`; `--mode composio` calls hosted Composio tools. They are distinct paths.
- Local state: one JSON workspace. Copy `fixtures/starter.json` to a fresh path for each run. Operations reload committed state; each publication is atomic, but callers must still serialize writers because there is no transaction or cross-process locking. Exact meeting replays may return the original; altered person/slot bindings must fail without changing state.
- Synthetic writes need `--allow-write`. Hosted Composio calls need `--allow-live-actions`, `COMPOSIO_API_KEY`, `COMPOSIO_USER_ID`, and connected **test** accounts.
- No Firedrill integration is present until the new interface is released and verified. Do not copy retired API calls.
- Do not claim model success from offline tests. Never commit provider tokens or real customer data.

- Offline gate: `uv sync --locked --dev && uv run --no-sync pytest -q && uv build`. Eleven local workspace/tool checks pass. Actual LangChain/OpenAI completion/usage qualification and the four versioned dataset profiles remain independent follow-up work; do not call the hosted connector or live-model gate complete.
