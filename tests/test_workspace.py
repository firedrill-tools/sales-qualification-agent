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


@pytest.mark.parametrize("person_id,slot", [
    ("p-102", "2026-10-20T14:00:00Z"),
    ("p-101", "2026-10-21T16:00:00Z"),
    ("missing", "2026-10-20T14:00:00Z"),
])
def test_changed_retry_is_rejected_without_claiming_another_booking(tmp_path, person_id, slot):
    workspace = state(tmp_path)
    original = workspace.schedule("p-101", "2026-10-20T14:00:00Z", "req-1")
    before = workspace.path.read_bytes()
    assert workspace.schedule(person_id, slot, "req-1") == {"error": "request_id_conflict"}
    assert workspace.path.read_bytes() == before
    assert workspace.data["meetings"] == [original]


def test_long_lived_adapter_retains_later_committed_crm_and_calendar_changes(tmp_path):
    stale = state(tmp_path)
    fresh = Workspace(stale.path, writable=True)
    fresh.qualify("p-101", "qualified", "Approved budget and timeline")
    meeting = fresh.schedule("p-101", "2026-10-20T14:00:00Z", "fresh-request")
    assert stale.slots() == ["2026-10-21T16:00:00Z"]
    stale.qualify("p-103", "nurture", "Budget pending")
    persisted = Workspace(stale.path).data
    assert persisted["people"][0]["status"] == "qualified"
    assert persisted["people"][2]["status"] == "nurture"
    assert persisted["meetings"] == [meeting]
    assert stale.schedule("p-102", meeting["slot"], "stale-request") == {"error": "slot_unavailable"}


def test_failed_atomic_publication_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    workspace = state(tmp_path)
    original = workspace.path.read_bytes()

    def fail_replace(*args):
        raise OSError("synthetic filesystem publication failure")

    monkeypatch.setattr("sales_qualification.workspace.os.replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        workspace.qualify("p-101", "qualified", "Approved budget and timeline")
    assert workspace.path.read_bytes() == original
    assert workspace.data["people"][0]["status"] == "new"
    assert not list(tmp_path.glob(".sales-workspace-*.tmp"))


def test_blank_request_ids_and_reasons_do_not_mutate_state(tmp_path):
    workspace = state(tmp_path)
    original = workspace.path.read_bytes()
    assert workspace.schedule("p-101", "2026-10-20T14:00:00Z", " ") == {"error": "invalid_request_id"}
    assert workspace.qualify("p-101", "qualified", " ") == {"error": "missing_reason"}
    assert workspace.path.read_bytes() == original
