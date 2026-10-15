"""One-request CLI, model-free dataset initialization and structured failure evidence."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from .agent import SalesRunError, run
from .datasets import DEFAULT_MANIFEST, initialize_case, list_cases
from .workspace import Workspace


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qualify one lead through LangChain")
    parser.add_argument("request", nargs="?")
    parser.add_argument("--list-cases", action="store_true", help="Validate/list all inputs without a model")
    parser.add_argument("--init-case", help="Copy one verified case to a fresh workspace without a model")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--mode", choices=["synthetic", "composio"], default="synthetic")
    parser.add_argument("--workspace", type=Path, default=Path("workspace.json"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-sol"))
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-live-actions", action="store_true")
    parser.add_argument("--composio-accounts", type=Path, help="JSON mapping toolkit to one connected test account ID")
    args = parser.parse_args(argv)
    try:
        if args.list_cases or args.init_case:
            if args.list_cases and args.init_case or args.request or args.mode != "synthetic":
                raise ValueError("Choose exactly one of listing, initialization, or a model request")
            manifest = args.manifest or DEFAULT_MANIFEST
            result = list_cases(manifest) if args.list_cases else initialize_case(args.init_case, args.workspace, manifest)
            print(json.dumps(result))
            return 0
        if args.manifest:
            raise ValueError("--manifest requires --list-cases or --init-case")
        if not args.request:
            raise ValueError("A request is required for a model run")
        accounts = None
        if args.mode == "composio":
            if not args.allow_live_actions:
                raise ValueError("Composio mode requires --allow-live-actions and connected test accounts")
            if args.composio_accounts is None:
                raise ValueError("--composio-accounts must select the connected test account IDs")
            with args.composio_accounts.open("rb") as source:
                snapshot = source.read(16 * 1024 + 1)
            if len(snapshot) > 16 * 1024:
                raise ValueError("Account configuration exceeds 16 KiB")
            accounts = json.loads(snapshot)
        elif args.composio_accounts:
            raise ValueError("--composio-accounts requires Composio mode")
        workspace = Workspace(args.workspace, args.allow_write) if args.mode == "synthetic" else None
        result = run(args.request, mode=args.mode, model=args.model, workspace=workspace,
                     request_id=str(uuid4()) if args.request_id is None else args.request_id, user_id=os.getenv("COMPOSIO_USER_ID"),
                     connected_accounts=accounts, allow_live_actions=args.allow_live_actions, allow_write=args.allow_write)
    except SalesRunError as error:
        print(json.dumps({"error": {"code": "agent_failed", "message": str(error),
              "type": error.provider_error_type, "http_status": error.http_status}, "observation": error.observation}), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"error": {"code": "invalid_input_or_configuration", "message": str(error)}}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
