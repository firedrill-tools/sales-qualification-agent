"""Owned native Composio session, with explicit account scope and no local fallback."""
from contextlib import contextmanager
import os

import httpx
from composio import Composio
from composio_langchain import LangchainProvider

TOOLKITS = ("attio", "gmail", "googlecalendar")


def validate_accounts(accounts):
    if not isinstance(accounts, dict) or set(accounts) != set(TOOLKITS):
        raise ValueError("Composio needs exactly one connected test account ID for each of attio, gmail and googlecalendar")
    if any(not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value) for value in accounts.values()):
        raise ValueError("Connected test account IDs must be nonblank strings without whitespace")
    return dict(accounts)


@contextmanager
def composio_tools(user_id, accounts, *, allow_write, observation, transport=None):
    accounts = validate_accounts(accounts)
    if not os.getenv("COMPOSIO_API_KEY"):
        raise ValueError("COMPOSIO_API_KEY required for Composio mode")
    session = None
    details = observation["connector"]
    details.update({"transport": "composio-native-http", "toolkits": list(TOOLKITS), "connected_accounts": accounts,
                    "session_id": None, "cleanup": "not_created"})
    # Both SDKs use ordinary synchronous HTTP here. Supplying a MockTransport
    # exercises these actual SDKs in tests, without replacing the provider tools.
    details["http_calls"] = []

    def observe_http(response):
        response.read()
        details["http_calls"].append({"endpoint": {"scheme": response.request.url.scheme, "host": response.request.url.host, "port": response.request.url.port},
                                     "method": response.request.method, "path": response.request.url.path,
                                     "status": response.status_code})
        if response.request.method == "POST" and response.request.url.path.endswith("/tool_router/session") and response.status_code == 200:
            try:
                identifier = response.json().get("session_id")
                if isinstance(identifier, str) and identifier.strip():
                    details.update({"session_id": identifier, "cleanup": "pending"})
            except (ValueError, AttributeError):
                pass
    with httpx.Client(transport=transport, timeout=30, event_hooks={"response": [observe_http]}) as http:
        sdk = Composio(api_key=os.environ["COMPOSIO_API_KEY"], provider=LangchainProvider(), http_client=http,
                       max_retries=0, timeout=30, allow_tracking=False, file_upload_dirs=False,
                       dangerously_allow_auto_upload_download_files=False)
        try:
            details["cleanup"] = "creation_outcome_unknown"
            session = sdk.sessions.create(user_id=user_id, toolkits=list(TOOLKITS), connected_accounts=accounts,
                tags=["readOnlyHint"], tools={
                    "attio": {"tags": ["readOnlyHint", "updateHint"] if allow_write else ["readOnlyHint"]},
                    "gmail": {"tags": ["readOnlyHint"]},
                    "googlecalendar": {"tags": ["readOnlyHint", "createHint"] if allow_write else ["readOnlyHint"]},
                }, manage_connections=False, sandbox={"enable": False}, proxy_execute=False)
            details.update({"session_id": session.session_id, "cleanup": "pending"})
            config = session.config.model_dump(mode="json", exclude_none=True) if hasattr(session.config, "model_dump") else dict(session.config)
            toolkits = config.get("toolkits") or {}
            if (config.get("user_id") != user_id or config.get("connected_accounts") != {key: [value] for key, value in accounts.items()} or
                set(toolkits.get("enabled", [])) != set(TOOLKITS) or "disabled" in toolkits):
                raise RuntimeError("Created Composio session did not confirm the requested user/account/toolkit scope")
            details["session_scope_echo_validated"] = True
            yield session.tools()
        finally:
            identifier = session.session_id if session is not None else details.get("session_id")
            if identifier is not None:
                try:
                    deleted = session.delete() if session is not None else sdk.sessions.delete(identifier)
                    if deleted["session_id"] != identifier:
                        raise RuntimeError("Connector deletion acknowledged a different session")
                    details["cleanup"] = "deleted"
                except Exception as error:
                    details["cleanup"] = "failed"
                    details["cleanup_error_type"] = type(error).__name__
                    # Preserve an in-flight model/provider failure; the runner
                    # separately turns an otherwise successful cleanup failure
                    # into a failed invocation with its original evidence.
