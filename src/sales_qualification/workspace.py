"""Local, intentionally narrow replacement for CRM, email and calendar actions."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class Workspace:
    def __init__(self, path: Path, writable: bool = False):
        self.path = path
        self.writable = writable
        self.data  # Validate that the caller's selected file can be loaded.

    @property
    def data(self):
        # Each operation observes the latest committed state. A long-lived
        # adapter must not restore an older in-memory workspace over later work.
        return json.loads(self.path.read_text())

    def people(self, query: str):
        q = query.casefold()
        return [p for p in self.data["people"] if q in p["name"].casefold() or q in p["email"].casefold()]

    def company(self, company_id: str):
        return next((c for c in self.data["companies"] if c["id"] == company_id), None)

    def messages(self, email: str):
        return [m for m in self.data["email"] if m["from"].casefold() == email.casefold()]

    def slots(self):
        return self.data["calendar_slots"]

    def qualify(self, person_id: str, status: str, reason: str):
        self._check_write()
        if status not in {"qualified", "nurture", "disqualified"}:
            return {"error": "invalid_status"}
        if not reason.strip():
            return {"error": "missing_reason"}
        state = self.data
        person = next((p for p in state["people"] if p["id"] == person_id), None)
        if person is None:
            return {"error": "unknown_person"}
        person["status"] = status
        if reason not in person["notes"]:
            person["notes"].append(reason)
        self._save(state)
        return {"person_id": person_id, "status": status, "reason": reason}

    def schedule(self, person_id: str, slot: str, request_id: str):
        self._check_write()
        if not request_id.strip() or len(request_id) > 100:
            return {"error": "invalid_request_id"}
        state = self.data
        previous = next((meeting for meeting in state["meetings"] if meeting["request_id"] == request_id), None)
        if previous:
            if previous["person_id"] != person_id or previous["slot"] != slot:
                return {"error": "request_id_conflict"}
            return previous
        person = next((p for p in state["people"] if p["id"] == person_id), None)
        if person is None:
            return {"error": "unknown_person"}
        if slot not in state["calendar_slots"]:
            return {"error": "slot_unavailable"}
        record = {"request_id": request_id, "person_id": person_id, "slot": slot}
        state["meetings"].append(record)
        state["calendar_slots"].remove(slot)
        self._save(state)
        return record

    def _check_write(self):
        if not self.writable:
            raise PermissionError("Workspace writes require --allow-write")

    def _save(self, state):
        # Individual publications are atomic. Callers still serialize writers;
        # this is not a cross-process read/modify/write transaction or lock.
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=".sales-workspace-", suffix=".tmp",
                                    encoding="utf8", delete=False) as output:
                temporary = Path(output.name)
                output.write(json.dumps(state, indent=2) + "\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
