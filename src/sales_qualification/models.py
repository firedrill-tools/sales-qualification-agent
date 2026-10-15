"""Synthetic CRM/email/calendar contracts and durable input identities."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetIdentity(Contract):
    dataset_id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    profile: Literal["starter", "busy", "ambiguous", "boundary"]
    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Value must not be blank")
    return value


def utc_slot(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Calendar slots must have an explicit UTC offset")
    if parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value:
        raise ValueError("Calendar slots must use canonical YYYY-MM-DDTHH:MM:SSZ")
    return value


class Person(Contract):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    company_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    status: Literal["new", "qualified", "nurture", "disqualified"]
    notes: list[str]


class Company(Contract):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    size: StrictInt = Field(gt=0)
    industry: str
    need: str
    budget: Literal["approved", "pending", "unknown", "declined"]


class Email(Contract):
    id: str = Field(min_length=1)
    from_: str = Field(alias="from", pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    subject: str
    body: str


class Meeting(Contract):
    request_id: str = Field(min_length=1, max_length=100)
    person_id: str
    slot: str
    _id_nonblank = field_validator("request_id")(nonblank)
    _valid_slot = field_validator("slot")(utc_slot)


class WorkspaceData(Contract):
    synthetic: Literal[True]
    schema_version: Literal[1]
    dataset: DatasetIdentity | None = None
    people: list[Person]
    companies: list[Company]
    email: list[Email]
    calendar_slots: list[str]
    outreach: list[dict[str, Any]] = Field(default_factory=list)
    meetings: list[Meeting]
    denied_company_ids: list[str] = Field(default_factory=list)

    @field_validator("calendar_slots")
    @classmethod
    def valid_slots(cls, slots):
        for slot in slots:
            utc_slot(slot)
        return slots

    @model_validator(mode="after")
    def coherent_records(self):
        groups = ([p.id for p in self.people], [c.id for c in self.companies], [m.id for m in self.email],
                  [m.request_id for m in self.meetings], [m.slot for m in self.meetings], self.calendar_slots, self.denied_company_ids)
        if any(len(set(group)) != len(group) for group in groups):
            raise ValueError("Record, meeting and slot identities must be unique")
        companies, people = {c.id for c in self.companies}, {p.id for p in self.people}
        addresses = {p.email.casefold() for p in self.people}
        if any(p.company_id not in companies for p in self.people) or any(m.person_id not in people for m in self.meetings):
            raise ValueError("Person/company/meeting relationships are inconsistent")
        if any(m.from_.casefold() not in addresses for m in self.email) or not set(self.denied_company_ids) <= companies:
            raise ValueError("Email or denied-company relationship is inconsistent")
        if set(self.calendar_slots) & {m.slot for m in self.meetings}:
            raise ValueError("A booked slot cannot remain available")
        return self
