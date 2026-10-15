"""Versioned workspace inputs; selection and fresh-path initialization never call a model."""
from hashlib import sha256
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from .models import Contract
from .workspace import read_workspace

_packaged = Path(__file__).with_name("sample_data") / "manifest.json"
DEFAULT_MANIFEST = _packaged if _packaged.exists() else Path(__file__).resolve().parents[2] / "fixtures/manifest.json"


class Case(Contract):
    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Profile(Contract):
    name: Literal["starter", "busy", "ambiguous", "boundary"]
    cases: list[Case] = Field(min_length=1)


class Manifest(Contract):
    dataset_id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    profiles: list[Profile]

    @model_validator(mode="after")
    def unique_population(self):
        cases = [case for group in self.profiles for case in group.cases]
        if sorted(group.name for group in self.profiles) != ["ambiguous", "boundary", "busy", "starter"]:
            raise ValueError("Each of the four profiles is required exactly once")
        if len({case.case_id for case in cases}) != len(cases) or len({case.path for case in cases}) != len(cases):
            raise ValueError("Case and source identities must be unique")
        return self


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    with path.open("rb") as source:
        snapshot = source.read(128 * 1024 + 1)
    if len(snapshot) > 128 * 1024:
        raise ValueError("Manifest exceeds 128 KiB")
    return Manifest.model_validate_json(snapshot)


def select_case(case_id: str, path: Path = DEFAULT_MANIFEST):
    manifest = load_manifest(path)
    root = path.parent.resolve()
    for group in manifest.profiles:
        for case in group.cases:
            if case.case_id != case_id:
                continue
            source = (root / case.path).resolve()
            if not source.is_relative_to(root):
                raise ValueError("Workspace source escapes its manifest directory")
            snapshot, state = read_workspace(source)
            if sha256(snapshot).hexdigest() != case.sha256:
                raise ValueError(f"Dataset digest mismatch for {case_id}; qualify a new version")
            identity = {"dataset_id": manifest.dataset_id, "version": manifest.version, "profile": group.name, "case_id": case_id}
            if state["dataset"] != identity:
                raise ValueError("Workspace identity disagrees with manifest")
            return snapshot, state, case.sha256
    raise ValueError(f"Dataset case not found: {case_id}")


def initialize_case(case_id: str, workspace: Path, path: Path = DEFAULT_MANIFEST):
    snapshot, state, digest = select_case(case_id, path)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects an existing run and copies the checked snapshot,
    # even if the source changes after qualification.
    descriptor = os.open(workspace, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(snapshot)
    return {"workspace": str(workspace), "state_sha256": digest, "dataset": state["dataset"]}


def list_cases(path: Path = DEFAULT_MANIFEST):
    manifest = load_manifest(path)
    for group in manifest.profiles:
        for case in group.cases:
            select_case(case.case_id, path)
    return {"dataset_id": manifest.dataset_id, "version": manifest.version,
            "case_count": sum(len(group.cases) for group in manifest.profiles),
            "profiles": [{"name": group.name, "case_ids": [case.case_id for case in group.cases]} for group in manifest.profiles]}
