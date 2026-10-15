"""Coherent, versioned input selection and reproducible case reset."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from pydantic import ValidationError

from sales_qualification import cli
from sales_qualification.datasets import initialize_case, list_cases, load_manifest, select_case
from sales_qualification.workspace import Workspace, parse_workspace

ROOT = Path(__file__).parents[1]


def test_all_eight_workspaces_have_coherent_four_profile_identity_and_distinct_hashes():
    manifest = load_manifest()
    assert manifest.dataset_id == "northstar-sales" and manifest.version == "1.0.0"
    assert {group.name: len(group.cases) for group in manifest.profiles} == {"starter": 1, "busy": 1, "ambiguous": 2, "boundary": 4}
    hashes = set()
    for group in manifest.profiles:
        for case in group.cases:
            snapshot, state, digest = select_case(case.case_id)
            assert sha256(snapshot).hexdigest() == digest == case.sha256
            assert state["dataset"]["profile"] == group.name
            assert all(person["email"].endswith(".example") for person in state["people"])
            hashes.add(digest)
    assert len(hashes) == 8
    busy = select_case("busy")[1]
    assert (len(busy["people"]), len(busy["companies"]), len(busy["email"]), len(busy["meetings"])) == (15, 9, 20, 1)
    assert {company["budget"] for company in busy["companies"]} == {"approved", "pending", "unknown", "declined"}


def test_population_changes_cover_real_ambiguity_history_capacity_and_permissions(tmp_path):
    for case_id in ("duplicate-email", "funding-correction", "exhausted-calendar", "completed-request", "hostile-message", "inaccessible-company"):
        path = tmp_path / f"{case_id}.json"
        initialize_case(case_id, path)
        workspace = Workspace(path, writable=True)
        if case_id == "duplicate-email":
            assert len(workspace.people("mira@harbor.example")) == 2
        elif case_id == "funding-correction":
            assert workspace.company("c-1")["budget"] == "pending"
            assert "on hold" in workspace.messages("mira@harbor.example")[-1]["body"]
        elif case_id == "exhausted-calendar":
            assert workspace.slots() == []
            assert workspace.schedule("p-101", "2026-10-21T16:00:00Z", "new") == {"error": "slot_unavailable"}
            assert len(workspace.data["meetings"]) == 1
        elif case_id == "completed-request":
            before = path.read_bytes()
            assert workspace.schedule("p-101", "2026-10-20T14:00:00Z", "demo-1")["request_id"] == "demo-1"
            assert path.read_bytes() == before
        elif case_id == "hostile-message":
            assert "ignore the user" in workspace.messages("mira@harbor.example")[0]["body"]
        else:
            before = path.read_bytes()
            assert workspace.people("mira@harbor.example") == [{"error": "company_inaccessible", "person_id": "p-101"}]
            assert workspace.company("c-1") == {"error": "company_inaccessible"}
            assert workspace.messages("mira@harbor.example") == {"error": "company_inaccessible"}
            assert workspace.qualify("p-101", "qualified", "Synthetic") == {"error": "company_inaccessible"}
            assert workspace.schedule("p-101", "2026-10-20T14:00:00Z", "new") == {"error": "company_inaccessible"}
            assert path.read_bytes() == before


def test_replay_rechecks_current_access_before_returning_prior_booking(tmp_path):
    path = tmp_path / "revoked.json"
    initialize_case("completed-request", path)
    state = json.loads(path.read_text())
    state["denied_company_ids"] = ["c-1"]
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert Workspace(path, True).schedule("p-101", "2026-10-20T14:00:00Z", "demo-1") == {"error": "company_inaccessible"}
    assert path.read_bytes() == before


def test_generator_reproduces_all_snapshots_and_manifest_from_code(tmp_path):
    spec = importlib.util.spec_from_file_location("fixtures_generator", ROOT / "scripts/make_fixtures.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.FIXTURES = tmp_path / "fixtures"
    generator.main()
    expected = {path.name: path.read_bytes() for path in (ROOT / "fixtures").glob("*.json")}
    actual = {path.name: path.read_bytes() for path in generator.FIXTURES.glob("*.json")}
    assert actual == expected


def test_listing_and_private_exact_initialization_are_model_free_and_refuse_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("model must not run"))
    assert cli.main(["--list-cases"]) == 0
    assert json.loads(capsys.readouterr().out)["case_count"] == 8
    path = tmp_path / "state/workspace.json"
    assert cli.main(["--init-case", "busy", "--workspace", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["dataset"]["profile"] == "busy"
    assert path.read_bytes() == select_case("busy")[0]
    assert path.stat().st_mode & 0o777 == 0o600
    assert cli.main(["--init-case", "starter", "--workspace", str(path)]) == 2
    assert capsys.readouterr().out == ""
    assert path.read_bytes() == select_case("busy")[0]


@pytest.fixture
def manifest_copy(tmp_path):
    shutil.copytree(ROOT / "fixtures", tmp_path / "fixtures")
    return tmp_path / "fixtures/manifest.json"


def test_drift_and_unknown_selection_never_pick_a_fallback(manifest_copy):
    path = manifest_copy.parent / "starter.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="digest mismatch"):
        select_case("starter", manifest_copy)
    with pytest.raises(ValueError, match="digest mismatch"):
        list_cases(manifest_copy)
    with pytest.raises(ValueError, match="not found"):
        select_case("missing", manifest_copy)


def test_manifest_escape_and_duplicate_case_identity_are_rejected(manifest_copy):
    population = json.loads(manifest_copy.read_text())
    outside = manifest_copy.parent.parent / "outside.json"
    outside.write_bytes(select_case("starter")[0])
    for reference in ("../outside.json", "linked.json"):
        if reference == "linked.json":
            (manifest_copy.parent / reference).symlink_to(outside)
        population["profiles"][0]["cases"][0]["path"] = reference
        manifest_copy.write_text(json.dumps(population))
        with pytest.raises(ValueError, match="escapes"):
            select_case("starter", manifest_copy)
    population["profiles"][1]["cases"][0]["case_id"] = "starter"
    manifest_copy.write_text(json.dumps(population))
    with pytest.raises(ValidationError, match="unique"):
        load_manifest(manifest_copy)


@pytest.mark.parametrize("alter", [
    lambda state: state.update(synthetic=False),
    lambda state: state["people"][0].update(company_id="missing-company"),
    lambda state: state["people"][1].update(id="p-101"),
    lambda state: state["email"][0].update(**{"from": "outside@unknown.example"}),
    lambda state: state["calendar_slots"].append(state["calendar_slots"][0]),
    lambda state: state.update(meetings=[{"person_id": "p-101", "request_id": "prior", "slot": state["calendar_slots"][0]}]),
    lambda state: state["calendar_slots"].__setitem__(0, "2026-10-20T14:00:00+00:00"),
])
def test_incoherent_or_non_synthetic_workspaces_fail_validation(alter):
    state = json.loads(select_case("starter")[0])
    alter(state)
    with pytest.raises(ValidationError):
        parse_workspace(json.dumps(state).encode())


def test_oversized_input_is_rejected_before_a_model_run(tmp_path, monkeypatch, capsys):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("must stop before model access"))
    assert cli.main(["--workspace", str(path), "Investigate Mira"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "2 MiB" in json.loads(output.err)["error"]["message"]
