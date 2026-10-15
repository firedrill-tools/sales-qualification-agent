"""LangChain agent and deliberate Composio transport switch."""
import json
import os
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from .workspace import Workspace

SYSTEM = """You are a sales qualification assistant. Resolve people by exact email, not name alone.
Read company and message evidence before changing qualification. Mark qualified only with
a concrete need, budget and timeline. If identity, account or budget is ambiguous, explain
the uncertainty and do not write. Schedule only when explicitly requested, using an available
slot. Never claim a CRM change or meeting unless the tool confirms it. Summarize evidence."""


def synthetic_tools(workspace: Workspace):
    @tool
    def search_people(query: str) -> str:
        """Find CRM people by name or email; similar names can belong to different accounts."""
        return json.dumps(workspace.people(query))

    @tool
    def get_company(company_id: str) -> str:
        """Read CRM company need, size and budget by exact company ID."""
        return json.dumps(workspace.company(company_id))

    @tool
    def get_messages(email: str) -> str:
        """Read inbound messages for one exact email address."""
        return json.dumps(workspace.messages(email))

    @tool
    def available_slots() -> str:
        """List currently available UTC calendar slots."""
        return json.dumps(workspace.slots())

    @tool
    def update_qualification(person_id: str, status: str, reason: str) -> str:
        """Set a CRM person's qualification and add evidence note. Requires write permission."""
        try:
            return json.dumps(workspace.qualify(person_id, status, reason))
        except PermissionError as exc:
            return json.dumps({"error": str(exc)})

    @tool
    def schedule_meeting(person_id: str, slot: str, request_id: str) -> str:
        """Book a UTC meeting once per request ID. Requires write permission."""
        try:
            return json.dumps(workspace.schedule(person_id, slot, request_id))
        except PermissionError as exc:
            return json.dumps({"error": str(exc)})

    return [search_people, get_company, get_messages, available_slots,
            update_qualification, schedule_meeting]


def composio_tools(user_id: str):
    """Real hosted connector path; never silently falls back to local tools."""
    from composio import Composio
    from composio_langchain import LangchainProvider

    if not os.getenv("COMPOSIO_API_KEY"):
        raise RuntimeError("COMPOSIO_API_KEY required for Composio mode")
    composio = Composio(provider=LangchainProvider())
    session = composio.sessions.create(user_id=user_id, toolkits=["attio", "gmail", "googlecalendar"])
    return session.tools()


def run(prompt: str, *, mode: str, model: str, workspace: Workspace | None = None,
        user_id: str | None = None):
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY required; no local model fallback")
    if mode == "synthetic":
        if workspace is None:
            raise ValueError("synthetic mode requires workspace")
        tools = synthetic_tools(workspace)
    elif mode == "composio":
        if not user_id:
            raise RuntimeError("COMPOSIO_USER_ID required for Composio mode")
        tools = composio_tools(user_id)
    else:
        raise ValueError("unknown mode")
    agent = create_agent(model=ChatOpenAI(model=model), tools=tools, system_prompt=SYSTEM)
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content
