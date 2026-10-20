# Simulate this agent with Firedrill

Firedrill is a simulation platform for AI agents. Your coding agent can prepare
and operate these simulations; the application and its model run in your own
repository or CI.

Start in the repository root, not inside `firedrill/`:

```sh
npx firedrill-run init
```

Authorize Firedrill and select a project/environment. Installation choices are
optional; skip them when using the locked `firedrill/` toolchain below. This setup
does not invoke the target agent or grant it access to real business accounts.

The separate optional execution toolchain exact-pins released CLI and TypeScript SDK **2.2.2**, verified October 19, 2026. It requires Node 22+ and does not change the Python application's locked provider/framework dependencies. This uses the supported command target; no Firedrill import is required inside the agent.

## Prepare and select scope

From the repository root with `uv` on PATH:

```sh
uv sync --locked --dev
npm ci --prefix firedrill --ignore-scripts --no-audit --no-fund
firedrill_cli=firedrill/node_modules/@firedrill-run/cli/bin/firedrill.mjs
node "$firedrill_cli" validate firedrill/scenario.json --json --non-interactive
```

Offline validation allocates no batch. Authorize and select the actual project/environment with `npx firedrill-run init` in a human terminal. Automation supplies `FIREDRILL_TOKEN`, `FIREDRILL_PROJECT_ID` and `FIREDRILL_ENVIRONMENT_ID` through its secret store. The application independently requires `OPENAI_API_KEY` and an enabled `OPENAI_MODEL` or recipe `configuration.parameters.model`. Keep credentials out of recipes and source.

## Execute the actual sales application

With an authorized provider budget:

```sh
node firedrill/simulate.mjs --preview
node "$firedrill_cli" simulate firedrill/scenario.json --scenario starter-read --json --non-interactive
```

The adapter initializes a hash-bound private case and invokes the actual `qualify-lead` CLI, LangChain graph and OpenAI Responses runtime. Three bounded scenarios cover read-only lead research, explicitly authorized synthetic qualification/booking, and duplicate-email ambiguity. The full recipe has one repetition and concurrency one. `node firedrill/simulate.mjs` executes that same full recipe using the SDK.

Write permission is a required literal caller boolean independent of case identity/task text. Only true adds the application's `--allow-write` grant; the model cannot change it. The adapter fixes `--mode synthetic` and exposes no live-action, account-file or hosted-mode switch. The existing Composio application path remains separately available and requires its original connected test-account authorization; this integration does not intercept or emulate Composio's backend. Local CRM/calendar records and meetings are fictional, with no real outbound delivery.

Each invocation retains a distinct `.runs/firedrill/attempt-*` workspace after success or failure. New attempts never reset earlier state. Actual CLI output is under `application`; runner-local state paths are under `localState` and are not uploaded artifacts. Failed partial stdout/stderr and the private directory remain explicit. Preserve caller request IDs and inspect committed effects before any application-level retry. Local state reset does not undo SaaS effects or provider retention/billing.

The target accepts invocation `2026-10-17-target-invocation.1`, ID-only scenario context and explicit case/task/write input. Controller/evaluation data and unsupported Firedrill Tool bindings are rejected. Operator/CI credentials are removed before application dispatch. The current local dependency seam needs no Firedrill synthetic Tool. Application call/output bounds and adapter/runner deadlines are not provider billing guarantees or proof of remote cancellation.

## MCP, recovery and CI

Configure remote OAuth operator MCP **https://mcp.firedrill.run/mcp** with the [host-specific setup](https://docs.firedrill.run/guides/coding-agents); no local MCP package is required. Host OAuth and CLI/SDK login are separate. MCP prepares/queues/inspects; the local runner executes the real application. Attach an existing batch with `node firedrill/simulate.mjs --run BATCH_ID`.

Preserve the operation ID and private journal after uncertainty. Use `--resume OPERATION_ID` for that execution or `--result BATCH_ID` for a retained read. A fresh simulation is new work and a new adapter invocation gets fresh synthetic state. Runner exit codes preserve errors, pending work/assessment and optional gates; execution completion is not correctness. This recipe requests no grading or gate.

Ordinary CI is offline. Use the official [live CI generator](https://docs.firedrill.run/guides/ci) only after actual scope, protected secrets and model budgets are configured. Authenticated persisted happy/negative runs, live model quality/cost, real Composio account/schema/effect qualification, and licensing remain separate gates.

References: [SDK](https://docs.firedrill.run/sdk/typescript), [command targets](https://docs.firedrill.run/guides/callbacks), [operator MCP](https://docs.firedrill.run/guides/control-mcp).

Before application dispatch, each private workspace saves the validated outer run/attempt/scenario IDs in `invocation.json`. This maps interrupted runs to local state; it is separate from the SDK recovery journal and grants no application authority.

## Offline verification

After installing the application dependencies and locked integration toolchain,
run `npm test --prefix firedrill` to exercise the adapter checks. These checks are
optional for first use and call no paid model. The Node 22+ requirement above is
for the Firedrill clients; it does not lower any application runtime requirement
in the root README.
