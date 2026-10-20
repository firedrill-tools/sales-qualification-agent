# Sales qualification agent with LangChain and Composio

A LangChain/OpenAI agent researches one lead across CRM people/companies, inbound email and calendar availability, then updates qualification or arranges follow-up when requested. The default tools operate on a fictional local workspace. A separate path uses actual Composio provider-wrapped tools and native session HTTP calls for explicitly connected test accounts. It does not intercept hosted MCP or simulate Composio's backend.

## Simulate with Firedrill

[Firedrill](https://firedrill.run/) is a simulation platform for AI agents.
Start from this repository’s root:

```sh
npx firedrill-run init
```

Sign in and choose your project, then follow the [simulation run guide](firedrill/README.md)
for application dependencies, a preview and the reviewed scenarios. Your agent runs
locally or in your CI; model credentials stay separate from Firedrill sign-in.
The included recipes record outcomes without an automatic quality score or CI gate.

## Run one local task

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Listing and initialization require no provider key:

```sh
uv sync --locked --dev
uv run --no-sync qualify-lead --list-cases
uv run --no-sync qualify-lead --init-case starter --workspace run-output/workspace.json
# Set OPENAI_API_KEY through your secret manager, then explicitly run one task:
uv run --no-sync qualify-lead --workspace run-output/workspace.json --allow-write --request-id demo-1 \
  'Qualify mira@harbor.example from her message, and book one available slot if justified.'
```

`OPENAI_MODEL` or `--model` selects the model (default `gpt-6.1-sol`). The actual request uses OpenAI Responses through `langchain-openai` 1.7.2 / OpenAI Python 3.31.0. A real model request can incur cost. There is no local-model fallback or automatic batch campaign. Eight model calls are allowed, each with a 30-second HTTP timeout, 4,096 output tokens, `store=false` and `background=false`. HTTP retries are disabled. `OPENAI_BASE_URL` and `COMPOSIO_BASE_URL` configure the respective SDK endpoints; their defaults are `https://api.openai.com/v1` and `https://backend.composio.dev`. HTTP observations retain the actual scheme/host/port without URL credentials or query strings. These are per-request bounds, not a total workflow deadline or billing cap. Dependencies may add their own HTTP calls.

Without `--allow-write`, synthetic mutations are rejected. `--request-id` binds meeting tools to a caller-owned ID; otherwise the CLI generates one and includes it in output. Preserve that ID when explicitly retrying a task. Exact person/slot retries return the original booking; altered bindings are rejected without mutation. A model-created replacement ID is denied. Parallel model tool calls are disabled and a returned parallel batch is rejected before dispatch, preserving this store's sequential-operation boundary.

## Versioned inputs and reset

`fixtures/manifest.json` defines `northstar-sales` 1.0.0, with eight distinct workspaces across all four profiles. Every selected snapshot has a SHA-256 and a matching declared identity. All people, organizations, email and calendar relationships are fictional and internally validated.

| Profile | Cases | Coverage |
|---|---:|---|
| Starter | 1 | Similar names, one ready lead and an incomplete-budget inquiry |
| Busy | 1 | 15 people, 9 companies, 20 messages, distinct industries/budgets and an existing meeting |
| Ambiguous | 2 | Duplicate email across different accounts; later funding/timeline correction |
| Boundary | 4 | Exhausted calendar, already completed request, hostile message instructions, denied company access |

`--init-case CASE --workspace NEW_PATH` copies exactly the verified bytes with exclusive private-file creation. It refuses overwrite. `--manifest PATH` can select an explicit population for initialization/listing; unknown cases, duplicate identities, path/symlink escapes and digest drift fail. The wheel bundles all eight cases. `uv run --no-sync python scripts/make_fixtures.py` reproduces all fixtures and hashes from code; qualify a new dataset version when changing inputs.

A caller-owned custom workspace must use `synthetic=true`, `schema_version=1` and the documented shape in the fixtures. Preflight reads at most 2 MiB plus one byte and rejects inconsistent relationships, duplicate identities, noncanonical UTC slots or a booked slot still listed as available. Declared dataset metadata on a modified workspace is not proof of pristine reset: compare the observed initial hash with the manifest.

The workspace file owns CRM status/notes, availability and meetings. Each operation reloads committed state; each publication replaces the file atomically. Callers must still serialize writers to a given path; atomic replacement is not a concurrent transaction or lock. Use a fresh path for every independent case. Reset covers this local state, not a connected SaaS account. Company access denials apply to reads, writes and replayed bookings. There is no local outbound email delivery, calendar invite delivery, background job or automatic file deletion.

## Completion and evidence

Success is one JSON object on stdout with a nonblank terminal assistant answer and no remaining or malformed tool call. HTTP observation checks `completed` response/message status before LangChain can execute tools; nonfinal, refused, erroneous or parallel-call output is rejected. An API return alone is not completion.

Output retains request/prompt hashes, caller request ID, actual dependency versions, initial/final local state hashes and declared dataset identity, response IDs/models/statuses/raw output items, raw reported usage, normalized LangChain messages and tool input/output observations. Usage aggregates all responses only when every counter is present and nonnegative. Missing/partial usage stays unknown; reported zero remains distinct from absent data. LangChain's defaulted counters remain separate from raw provider counters. `cost_usd` remains null: these observations do not establish a billed price.

Exit `1` emits JSON stderr with available evidence and no accepted answer. Failures after a committed CRM update retain final state and prior usage. If final state cannot be read, it stays null with a read-error marker; no rollback is implied. Exit `2` is invalid input/configuration. The callable is synchronous; async hosts use `asyncio.to_thread(run, ...)`. The application closes both owned OpenAI clients and their HTTP transport on success/failure. The CLI saves no journal automatically. Callers own redirected output; keep private responses, account IDs and credentials out of Git.

## Composio connector path

This path qualifies `composio==0.27.0` / `composio-langchain==0.27.0` session and tool wrapping. Create a private JSON file mapping exactly one connected **test** account to each toolkit:

```json
{"attio":"ca-your-test-crm","gmail":"ca-your-test-mail","googlecalendar":"ca-your-test-calendar"}
```

With `OPENAI_API_KEY`, `COMPOSIO_API_KEY` and `COMPOSIO_USER_ID` set through your secret manager:

```sh
uv run --no-sync qualify-lead --mode composio --allow-live-actions \
  --composio-accounts /private/path/test-accounts.json --request-id test-review-1 \
  'Investigate the selected test lead; report findings only.'
```

`--allow-live-actions` is required by both the CLI and callable boundary. Without `--allow-write`, the session requests read-only tools. With it, requested overrides allow Attio reads/updates and calendar reads/creates; Gmail remains read-only. Account management, remote workbench/sandbox and proxy execution are disabled; automatic local file upload/download is disabled. Explicit user/account/toolkit bindings are checked against the created session's configuration before loading tools or calling the model. Identifiers alone cannot prove an account is a test environment or that OAuth grants are appropriate; connect and qualify test accounts separately.

A run owns its newly created session. It deletes the session on success and failure, including a tool-schema failure after creation. A failed cleanup retains the session ID and exits unsuccessfully; a failed create with no known ID leaves creation outcome unknown. Session deletion does not roll back SaaS changes, prove cancellation of remote work, or reset remote records. A remote task can complete an action before an observation fails. Keep request/output evidence and inspect the connected account before retrying; local meeting idempotency is not a promise about arbitrary hosted actions.

The application has no local-workspace fallback in Composio mode. Its evidence records the native HTTP lifecycle and selected account/session identity, not remote final business state. Hosted tool availability, real action schemas/versions, OAuth scopes, backend enforcement, side effects and cleanup still need connected-account proof. Offline tests use a deliberately fictional advertised tool schema, not a claimed real Attio action. Do not connect production accounts.

## Offline checks and CI

```sh
uv sync --locked --dev
uv run --no-sync pytest -q
uv run --no-sync qualify-lead --list-cases
uv build --wheel
uv run --no-sync python scripts/check_wheel.py
```

The 59 checks retain the actual LangChain graph, ChatOpenAI/OpenAI adapters and Composio provider wrappers while replacing only HTTP transports. They cover a seven-response research/update/booking loop, terminal/error/usage handling, bounded calls, permissions, state recovery, explicit connector scope and session deletion. Dataset checks reproduce every fixture byte-for-byte and exercise model-free reset. The package gate verifies listing and initialization outside the checkout. No paid provider request occurs; scripted outputs do not prove live model judgment, prompt-injection resistance, or connected SaaS behavior.

[Scenario briefs](scenarios/README.md) describe desired observations without sending expected answers to the target. Exact checks suit record identity, bookings, permissions and state effects; clarification and conservative answers can be valid. Missing evaluation and provider outages must not become an agent-quality score.

## Firedrill and publication

The intended seam is this one-task CLI plus explicit dependency configuration and observed state. The synthetic tool adapter can later use a supported released service through a thin connection. The included [Firedrill integration](firedrill/README.md) uses the real CLI with local synthetic data. Authenticated persisted reports and live CI remain unverified. Live OpenAI/Composio proof, public visibility and licensing remain pending.

Implementation references: [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai), [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [Composio LangChain provider](https://docs.composio.dev/docs/providers/langchain) and [session configuration](https://docs.composio.dev/docs/configuring-sessions).

Explore related applications in the [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog). Product and setup references: [Firedrill](https://firedrill.run/) and the [official developer documentation](https://docs.firedrill.run/). Use documentation matching the qualified release.

## Current Firedrill connection — 2026-10-19

The [agent-first integration](firedrill/README.md) exact-pins CLI/SDK 2.2.2 and calls the actual LangChain sales CLI in explicit synthetic mode. Caller write permission stays independent of task/case selection; each invocation gets private state. The separate hosted Composio path remains available in the application and requires its existing live-account gates. Earlier pending-release notes are historical; authenticated persisted and live proofs remain pending.
