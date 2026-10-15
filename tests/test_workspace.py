import json
from pathlib import Path
import pytest
from sales_qualification.workspace import Workspace
from sales_qualification.agent import synthetic_tools, run

FIXTURE = Path(__file__).parents[1] / "fixtures" / "starter.json"


def state(tmp_path, writable=True):
    path = tmp_path / "workspace.json"
    path.write_text(FIXTURE.read_text())
    return Workspace(path, writable)


def test_similar_names_are_distinct(tmp_path):
    workspace = state(tmp_path)
    people = workspace.people("Mira Chen")
    assert len(people) == 2
    assert {p["company_id"] for p in people} == {"c-1", "c-2"}
    assert workspace.messages("mira@harbor.example")[0]["id"] == "e-1"


def test_qualification_updates_exact_record_and_is_idempotent(tmp_path):
    workspace = state(tmp_path)
    workspace.qualify("p-101", "qualified", "Approved budget and November timeline")
    workspace.qualify("p-101", "qualified", "Approved budget and November timeline")
    result = json.loads(workspace.path.read_text())
    assert result["people"][0]["status"] == "qualified"
    assert len(result["people"][0]["notes"]) == 1
    assert result["people"][1]["status"] == "new"


def test_meeting_retries_do_not_double_book(tmp_path):
    workspace = state(tmp_path)
    first = workspace.schedule("p-101", "2026-10-20T14:00:00Z", "req-1")
    assert workspace.schedule("p-101", "2026-10-20T14:00:00Z", "req-1") == first
    assert workspace.schedule("p-102", "2026-10-20T14:00:00Z", "req-2") == {"error": "slot_unavailable"}
    assert len(workspace.data["meetings"]) == 1


def test_read_only_and_invalid_targets(tmp_path):
    workspace = state(tmp_path, writable=False)
    with pytest.raises(PermissionError):
        workspace.qualify("p-101", "qualified", "test")
    workspace.writable = True
    assert workspace.qualify("missing", "qualified", "test") == {"error": "unknown_person"}
    assert workspace.qualify("p-101", "unverified", "test") == {"error": "invalid_status"}


def test_langchain_tools_and_key_boundary(tmp_path, monkeypatch):
    workspace = state(tmp_path)
    assert {t.name for t in synthetic_tools(workspace)} == {
        "search_people", "get_company", "get_messages", "available_slots",
        "update_qualification", "schedule_meeting"}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        run("qualify Mira", mode="synthetic", model="gpt-6.1-sol", workspace=workspace)
