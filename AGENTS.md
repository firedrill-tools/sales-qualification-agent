# Agent working notes

- Entry point: `qualify-lead`; model loop: `src/sales_qualification/agent.py`.
- `--mode synthetic` calls local LangChain tools in `src/sales_qualification/agent.py`; `--mode composio` calls hosted Composio tools. They are distinct paths.
- Local state: one JSON workspace. Copy `fixtures/starter.json` to a fresh path for each run. Sequential writes only; no transaction or cross-process locking.
- Synthetic writes need `--allow-write`. Hosted Composio calls need `--allow-live-actions`, `COMPOSIO_API_KEY`, `COMPOSIO_USER_ID`, and connected **test** accounts.
- No Firedrill integration is present until the new interface is released and verified. Do not copy retired API calls.
- Do not claim model success from offline tests. Never commit provider tokens or real customer data.
