"""Local, intentionally narrow replacement for CRM, email and calendar actions."""
import json
from pathlib import Path


class Workspace:
    def __init__(self, path: Path, writable: bool = False):
        self.path = path
        self.writable = writable
        self.data = json.loads(path.read_text())

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
        person = next((p for p in self.data["people"] if p["id"] == person_id), None)
        if person is None:
            return {"error": "unknown_person"}
        person["status"] = status
        if reason not in person["notes"]:
            person["notes"].append(reason)
        self._save()
        return {"person_id": person_id, "status": status, "reason": reason}

    def schedule(self, person_id: str, slot: str, request_id: str):
        self._check_write()
        person = next((p for p in self.data["people"] if p["id"] == person_id), None)
        if person is None:
            return {"error": "unknown_person"}
        previous = next((m for m in self.data["meetings"] if m["request_id"] == request_id), None)
        if previous:
            return previous
        if slot not in self.slots():
            return {"error": "slot_unavailable"}
        record = {"request_id": request_id, "person_id": person_id, "slot": slot}
        self.data["meetings"].append(record)
        self.data["calendar_slots"].remove(slot)
        self._save()
        return record

    def _check_write(self):
        if not self.writable:
            raise PermissionError("Workspace writes require --allow-write")

    def _save(self):
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")
