import argparse
import os
from pathlib import Path
from .agent import run
from .workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description="Qualify a lead through LangChain")
    parser.add_argument("request")
    parser.add_argument("--mode", choices=["synthetic", "composio"], default="synthetic")
    parser.add_argument("--workspace", type=Path, default=Path("workspace.json"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-sol"))
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-live-actions", action="store_true")
    args = parser.parse_args()
    if args.mode == "composio" and not args.allow_live_actions:
        parser.error("Composio mode requires --allow-live-actions and connected test accounts")
    if args.mode == "synthetic" and not args.workspace.exists():
        parser.error(f"workspace missing: {args.workspace}; copy fixtures/starter.json first")
    try:
        result = run(args.request, mode=args.mode, model=args.model,
                     workspace=Workspace(args.workspace, args.allow_write) if args.mode == "synthetic" else None,
                     user_id=os.getenv("COMPOSIO_USER_ID"))
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(result)


if __name__ == "__main__":
    main()
