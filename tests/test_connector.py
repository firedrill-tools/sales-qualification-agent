"""Actual Composio/LangChain wrapping and HTTP lifecycle with a synthetic advertised tool."""
from copy import deepcopy
import json

import httpx
import pytest

from sales_qualification.agent import SalesRunError, run
from sales_qualification.connector import composio_tools
from test_agent import Script, call, message, response, MODEL

ACCOUNTS = {"attio": "ca-test-crm", "gmail": "ca-test-mail", "googlecalendar": "ca-test-calendar"}
CONFIG = {"execute": {"enable_multi_execute": True}, "preload": {"tools": []}, "search": {"enable": True},
          "user_id": "synthetic-user", "instant": False,
          "connected_accounts": {key: [value] for key, value in ACCOUNTS.items()},
          "toolkits": {"enabled": ["attio", "gmail", "googlecalendar"]}}
# This deliberately fictional schema tests the adapter without claiming a real
# provider action/version or connected test-account behavior has been qualified.
TOOL = {"slug": "SYNTHETIC_READ_CONTACT", "name": "Read synthetic contact", "description": "Read one fictional contact",
        "input_parameters": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
        "output_parameters": {}, "toolkit": {"slug": "attio", "name": "Attio", "logo": ""}, "tags": ["readOnlyHint"],
        "no_auth": False, "available_versions": ["synthetic-1"], "version": "synthetic-1", "is_deprecated": False, "scopes": [],
        "deprecated": {"available_versions": ["synthetic-1"], "displayName": "Read synthetic contact", "is_deprecated": False,
                       "toolkit": {"logo": ""}, "version": "synthetic-1"}}


class Connector(httpx.MockTransport):
    def __init__(self, *, fail=None, malformed_config=False, wrong_scope=None):
        self.requests, self.closed, self.fail, self.malformed_config = [], False, fail, malformed_config
        self.wrong_scope = wrong_scope
        super().__init__(self.handle)

    def handle(self, request):
        self.requests.append(request)
        stage = "create" if request.method == "POST" and request.url.path.endswith("/session") else (
            "delete" if request.method == "DELETE" else "tools" if request.method == "GET" else "execute")
        if self.fail == stage:
            return httpx.Response(503, json={"error": {"message": "synthetic connector outage"}})
        if stage == "create":
            config = deepcopy(CONFIG)
            if self.wrong_scope == "user":
                config["user_id"] = "other-user"
            elif self.wrong_scope == "account":
                config["connected_accounts"]["gmail"] = ["ca-other-account"]
            elif self.wrong_scope == "toolkit":
                config["toolkits"]["enabled"].append("github")
            return httpx.Response(200, json={"session_id": "synthetic-session", "config": {} if self.malformed_config else config,
                "config_version": 1, "mcp": {"type": "http", "url": "https://backend.composio.dev/mcp"},
                "tool_router_tools": ["SYNTHETIC_READ_CONTACT"]})
        if stage == "tools":
            return httpx.Response(200, json={"items": [TOOL], "current_page": 1, "total_items": 1, "total_pages": 1, "next_cursor": None})
        if stage == "delete":
            return httpx.Response(200, json={"session_id": "synthetic-session", "deleted": True})
        return httpx.Response(200, json={"result_type": "completed", "data": {"contact_id": "p-101", "email": "mira@harbor.example"},
                                        "error": None, "log_id": "synthetic-log"})

    def close(self):
        self.closed = True
        super().close()


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "synthetic-not-a-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-a-secret")
    for name in ("COMPOSIO_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


def hosted(openai, connector, **kwargs):
    return run("Investigate the selected test contact, report only.", mode="composio", model=MODEL,
        user_id="synthetic-user", allow_live_actions=True, connected_accounts=ACCOUNTS,
        openai_transport=openai, composio_transport=connector, **kwargs)


def test_actual_native_tool_executes_within_scoped_session_and_deletes_it():
    connector = Connector()
    openai = Script([response([call("SYNTHETIC_READ_CONTACT", {"email": "mira@harbor.example"})]),
                     response([message("The synthetic contact was found; no changes were requested.")])])
    result = hosted(openai, connector)
    assert connector.closed and openai.closed
    assert [request.method for request in connector.requests] == ["POST", "GET", "POST", "DELETE"]
    assert str(connector.requests[0].url) == "https://backend.composio.dev/api/v3.1/tool_router/session"
    body = json.loads(connector.requests[0].content)
    assert body["toolkits"] == {"enable": ["attio", "gmail", "googlecalendar"]}
    assert body["connected_accounts"] == {key: [value] for key, value in ACCOUNTS.items()}
    assert body["tags"] == {"enable": ["readOnlyHint"]}
    assert body["manage_connections"] == {"enable": False}
    assert body["workbench"] == {"enable": False} and body["proxy_execute"] == {"enable": False}
    assert all(value["tags"]["enable"] == ["readOnlyHint"] for value in body["tools"].values())
    executed = connector.requests[2]
    assert executed.url.path == "/api/v3.1/tool_router/session/synthetic-session/execute"
    assert json.loads(executed.content)["tool_slug"] == "SYNTHETIC_READ_CONTACT"
    assert json.loads(executed.content)["arguments"] == {"email": "mira@harbor.example"}
    assert "p-101" in openai.requests[1].content.decode()
    assert result["observation"]["connector"]["cleanup"] == "deleted"
    assert result["observation"]["connector"]["session_id"] == "synthetic-session"
    assert result["observation"]["initial_state"] is None and result["observation"]["final_state"] is None
    assert "synthetic-not-a-secret" not in json.dumps(result)


def test_hosted_write_scope_enables_only_crm_updates_and_calendar_creates():
    transport, observation = Connector(), {"connector": {}}
    with composio_tools("synthetic-user", ACCOUNTS, allow_write=True, observation=observation, transport=transport):
        pass
    tools = json.loads(transport.requests[0].content)["tools"]
    assert tools["attio"]["tags"]["enable"] == ["readOnlyHint", "updateHint"]
    assert tools["googlecalendar"]["tags"]["enable"] == ["readOnlyHint", "createHint"]
    assert tools["gmail"]["tags"]["enable"] == ["readOnlyHint"]
    assert observation["connector"]["cleanup"] == "deleted"


@pytest.mark.parametrize("stage", ["create", "tools", "execute", "delete"])
def test_connector_errors_have_no_http_retry_and_never_fall_back_to_workspace(stage):
    connector = Connector(fail=stage)
    model = Script([response([call("SYNTHETIC_READ_CONTACT", {"email": "mira@harbor.example"})]), response()])
    with pytest.raises(SalesRunError) as caught:
        hosted(model, connector)
    evidence = caught.value.observation
    assert connector.closed
    calls = evidence["connector"]["http_calls"]
    assert len([call for call in calls if call["status"] == 503]) == 1
    assert evidence["initial_state"] is None and evidence["final_state"] is None
    if stage == "create":
        assert len(connector.requests) == 1 and len(model.requests) == 0
        assert evidence["connector"]["cleanup"] == "creation_outcome_unknown"
    elif stage == "delete":
        assert evidence["connector"]["cleanup"] == "failed"
        assert evidence["responses"][-1]["status"] == "completed"
        assert evidence["model_messages"][-1]["content"]
    else:
        assert connector.requests[-1].method == "DELETE"
        assert evidence["connector"]["cleanup"] == "deleted"


def test_session_id_seen_on_http_response_is_cleaned_if_sdk_response_parsing_fails():
    connector = Connector(malformed_config=True)
    with pytest.raises(SalesRunError) as caught:
        hosted(Script([]), connector)
    assert [request.method for request in connector.requests] == ["POST", "DELETE"]
    assert caught.value.observation["connector"]["cleanup"] == "deleted"


def test_model_failure_also_deletes_the_owned_connector_session():
    connector = Connector()
    with pytest.raises(SalesRunError) as caught:
        hosted(Script([response(status="incomplete")]), connector)
    assert connector.requests[-1].method == "DELETE" and connector.closed
    assert caught.value.observation["connector"]["cleanup"] == "deleted"


@pytest.mark.parametrize("scope", ["user", "account", "toolkit"])
def test_wrong_scope_echo_deletes_session_before_tools_or_model_are_used(scope):
    connector, model = Connector(wrong_scope=scope), Script([])
    with pytest.raises(SalesRunError) as caught:
        hosted(model, connector)
    assert [request.method for request in connector.requests] == ["POST", "DELETE"]
    assert model.requests == []
    assert caught.value.observation["connector"]["cleanup"] == "deleted"
    assert "session_scope_echo_validated" not in caught.value.observation["connector"]
