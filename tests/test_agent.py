"""Actual LangChain graph + ChatOpenAI + OpenAI SDK over intercepted HTTP."""
from copy import deepcopy
import json
from pathlib import Path

import httpx2
import pytest

from sales_qualification import agent, cli
from sales_qualification.agent import SalesRunError, run
from sales_qualification.workspace import Workspace

FIXTURE = Path(__file__).parents[1] / "fixtures/starter.json"
MODEL = "gpt-6.1-sol"
USAGE = {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
         "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}


def message(text="Please clarify which Mira account is intended.", **overrides):
    return {"type": "message", "id": "msg_synthetic", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}], **overrides}


def call(name, arguments, index=1):
    return {"type": "function_call", "id": f"fc_{index}", "call_id": f"call_{index}", "status": "completed",
            "name": name, "arguments": json.dumps(arguments)}


def response(output=None, *, status="completed", usage=USAGE, **overrides):
    return {"id": "resp_synthetic", "object": "response", "created_at": 1792098000, "model": MODEL,
            "status": status, "error": None, "incomplete_details": None,
            "output": [message()] if output is None else output, "usage": usage, **overrides}


class Script(httpx2.MockTransport):
    def __init__(self, responses):
        self.responses, self.requests, self.closed = responses, [], False
        super().__init__(self.handle)

    def handle(self, request):
        self.requests.append(request)
        body = self.responses[len(self.requests) - 1]
        if isinstance(body, httpx2.Response):
            return body
        body = deepcopy(body)
        body["id"] = f"resp_synthetic_{len(self.requests)}"
        return httpx2.Response(200, json=body)

    def close(self):
        self.closed = True
        super().close()


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "COMPOSIO_API_KEY", "COMPOSIO_USER_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-secret")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "workspace.json"
    path.write_bytes(FIXTURE.read_bytes())
    return Workspace(path, writable=True)


def execute(workspace, script, **kwargs):
    return run("Investigate mira@harbor.example and arrange one meeting if justified.", mode="synthetic", model=MODEL,
               workspace=workspace, request_id="test-request", openai_transport=script, **kwargs)


def test_actual_seven_response_tool_loop_preserves_identity_state_and_all_usage(workspace):
    steps = [
        ("search_people", {"query": "mira@harbor.example"}), ("get_company", {"company_id": "c-1"}),
        ("get_messages", {"email": "mira@harbor.example"}),
        ("update_qualification", {"person_id": "p-101", "status": "qualified", "reason": "Approved budget and November timeline"}),
        ("available_slots", {}),
        ("schedule_meeting", {"person_id": "p-101", "slot": "2026-10-20T14:00:00Z", "request_id": "test-request"}),
    ]
    script = Script([response([call(name, arguments, index)]) for index, (name, arguments) in enumerate(steps, 1)] +
                    [response([message("Qualified Harbor Logistics and booked the confirmed slot.")])])
    result = execute(workspace, script)
    assert isinstance(result["answer"], str) and "Harbor" in result["answer"]
    assert len(script.requests) == 7 and script.closed
    for request in script.requests:
        assert request.method == "POST" and str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False and body["background"] is False and body["parallel_tool_calls"] is False
        assert body["max_output_tokens"] == 4096
        assert "manifest" not in request.content.decode()
        assert "northstar-sales" not in request.content.decode()
    assert result["usage"] == {"requests": 7, "input_tokens": 140, "output_tokens": 35, "total_tokens": 175}
    observation = result["observation"]
    assert len(observation["model_messages"]) == 7 and len(observation["tool_calls"]) == 6
    assert observation["usage_complete"] and observation["cost_usd"] is None
    assert observation["versions"]["langchain-openai"] == "1.7.2"
    assert observation["initial_state"]["state_sha256"] != observation["final_state"]["state_sha256"]
    assert observation["initial_state"]["dataset"]["case_id"] == "starter"
    assert workspace.data["people"][0]["status"] == "qualified"
    assert workspace.data["people"][1]["status"] == "new"
    assert workspace.data["meetings"] == [{"request_id": "test-request", "person_id": "p-101", "slot": "2026-10-20T14:00:00Z"}]
    # Actual tool results are fed into the next model request, not just called by a unit test.
    assert "Harbor Logistics" in script.requests[2].content.decode()
    assert "test-request" in script.requests[-1].content.decode()


@pytest.mark.parametrize("status", ["incomplete", "in_progress", "cancelled", "failed", "queued"])
def test_nonfinal_response_cannot_dispatch_valid_looking_write(workspace, status):
    before = workspace.path.read_bytes()
    script = Script([response([call("update_qualification", {"person_id": "p-101", "status": "qualified", "reason": "Synthetic claim"})], status=status)])
    with pytest.raises(SalesRunError) as caught:
        execute(workspace, script)
    assert len(script.requests) == 1 and script.closed
    assert workspace.path.read_bytes() == before
    evidence = caught.value.observation
    assert evidence["responses"][0]["status"] == status
    assert evidence["responses"][0]["reported_usage"] == USAGE
    assert evidence["responses"][0]["protocol_error"] == "response_not_completed"
    assert evidence["tool_calls"] == []


@pytest.mark.parametrize("usage,complete", [(None, False), ({}, False), ({"input_tokens": 20}, False),
    ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, True)])
def test_raw_usage_remains_distinct_from_langchain_default_counters(workspace, usage, complete):
    result = execute(workspace, Script([response(usage=usage)]))
    assert result["observation"]["responses"][0]["reported_usage"] == usage
    assert result["observation"]["usage_complete"] is complete
    assert (result["usage"] is not None) is complete
    if not complete:
        assert result["usage"] is None
    assert result["observation"]["cost_usd"] is None


@pytest.mark.parametrize("output", [
    [message(content=[])], [message("progress", status="in_progress")],
    [message(content=[{"type": "refusal", "refusal": "Synthetic refusal"}])],
    [call("update_qualification", {"person_id": "p-101", "status": "qualified", "reason": "No"}, 1),
     call("schedule_meeting", {"person_id": "p-101", "slot": "2026-10-20T14:00:00Z", "request_id": "test-request"}, 2)],
])
def test_empty_refused_unfinished_and_parallel_output_do_not_complete(workspace, output):
    before = workspace.path.read_bytes()
    script = Script([response(output)])
    with pytest.raises(SalesRunError) as caught:
        execute(workspace, script)
    assert len(script.requests) == 1
    assert caught.value.observation["responses"][0]["output"] == output
    assert workspace.path.read_bytes() == before


def test_actual_loop_keeps_denied_send_id_and_read_only_decisions_visible(workspace):
    script = Script([
        response([call("schedule_meeting", {"person_id": "p-101", "slot": "2026-10-20T14:00:00Z", "request_id": "invented-id"})]),
        response([message("No meeting was booked because the request ID was not authorized.")]),
    ])
    result = execute(workspace, script)
    assert workspace.data["meetings"] == []
    assert "request_id_not_authorized" in script.requests[1].content.decode()
    assert "not authorized" in result["answer"]
    readonly = Workspace(workspace.path, writable=False)
    denied = Script([
        response([call("update_qualification", {"person_id": "p-101", "status": "qualified", "reason": "Synthetic"})]),
        response([message("Writes are disabled; no CRM changes were made.")]),
    ])
    execute(readonly, denied)
    assert workspace.data["people"][0]["status"] == "new"
    assert "require --allow-write" in denied.requests[1].content.decode()


def test_failure_after_commit_keeps_state_and_all_available_response_usage(workspace):
    script = Script([
        response([call("update_qualification", {"person_id": "p-101", "status": "qualified", "reason": "Approved budget and November timeline"})]),
        httpx2.Response(503, json={"error": {"message": "synthetic outage", "type": "server_error"}}),
    ])
    with pytest.raises(SalesRunError) as caught:
        execute(workspace, script)
    evidence = caught.value.observation
    assert len(script.requests) == 2 and script.closed
    assert workspace.data["people"][0]["status"] == "qualified"
    assert evidence["initial_state"]["state_sha256"] != evidence["final_state"]["state_sha256"]
    assert evidence["responses"][0]["reported_usage"] == USAGE
    assert evidence["responses"][1]["reported_usage"] is None
    assert evidence["usage_complete"] is False
    assert caught.value.http_status == 503


def test_eight_call_limit_stops_before_a_ninth_http_request(workspace):
    script = Script([response([call("search_people", {"query": "Mira"}, index)]) for index in range(8)])
    with pytest.raises(SalesRunError):
        execute(workspace, script)
    assert len(script.requests) == 8 and script.closed
    assert workspace.data["meetings"] == []


def test_state_read_failure_retains_completed_model_evidence(workspace, monkeypatch):
    original, calls = workspace.snapshot, []
    def snapshot():
        calls.append(True)
        if len(calls) == 2:
            raise OSError("synthetic final-state outage")
        return original()
    monkeypatch.setattr(workspace, "snapshot", snapshot)
    with pytest.raises(SalesRunError) as caught:
        execute(workspace, Script([response()]))
    evidence = caught.value.observation
    assert evidence["final_state"] is None and evidence["final_state_read_error"] == "OSError"
    assert evidence["responses"][0]["reported_usage"] == USAGE


def test_owned_async_companion_closes_when_the_sync_provider_fails(workspace, monkeypatch):
    original, closed = agent.AsyncOpenAI, []
    def create(**kwargs):
        client = original(**kwargs)
        close = client.close
        async def close_and_record():
            closed.append(True)
            await close()
        client.close = close_and_record
        return client
    monkeypatch.setattr(agent, "AsyncOpenAI", create)
    script = Script([httpx2.Response(503, json={"error": {"message": "synthetic", "type": "server_error"}})])
    with pytest.raises(SalesRunError):
        execute(workspace, script)
    assert closed == [True] and script.closed and len(script.requests) == 1


def test_cli_failure_is_json_stderr_without_a_success_answer(workspace, monkeypatch, capsys):
    actual = cli.run
    monkeypatch.setattr(cli, "run", lambda *args, **kwargs: actual(*args, **kwargs, openai_transport=Script([response(status="incomplete")])))
    assert cli.main(["--workspace", str(workspace.path), "Investigate Mira"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    body = json.loads(output.err)
    assert body["error"]["code"] == "agent_failed"
    assert body["observation"]["responses"][0]["status"] == "incomplete"


def test_hosted_flag_and_accounts_are_required_at_the_callable_boundary(workspace):
    with pytest.raises(ValueError, match="allow-live-actions"):
        run("Investigate Mira", mode="composio", model=MODEL, user_id="synthetic-user")
    with pytest.raises(ValueError, match="account"):
        run("Investigate Mira", mode="composio", model=MODEL, user_id="synthetic-user", allow_live_actions=True)


def test_async_host_is_rejected_before_owning_clients_or_resources(workspace, monkeypatch):
    import asyncio
    monkeypatch.setattr(agent, "OpenAI", lambda **kwargs: pytest.fail("must not create an owned client"))
    async def host():
        with pytest.raises(ValueError, match="asyncio.to_thread"):
            execute(workspace, Script([]))
    asyncio.run(host())
