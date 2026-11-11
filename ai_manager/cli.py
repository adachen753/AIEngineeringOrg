import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ai_manager.submission_file import load_submission_file


def api_request(base_url: str, path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(base_url.rstrip("/") + path, data=data,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"API unavailable: {exc}") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AI Manager API client")
    parser.add_argument("--api-url", default=os.environ.get("AIM_API_URL", "http://127.0.0.1:8765"))
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("submit", help="Submit a JSON or Markdown Submission file")
    submit.add_argument("file", type=Path)
    submit.add_argument("--approved", action="store_true",
                        help="Explicitly authorize the submitted paths and fixed test command")
    for name in ("status", "events", "artifacts", "cancel", "retry", "input", "approve"):
        command = commands.add_parser(name)
        if name == "status":
            command.add_argument("id", nargs="?")
        else:
            command.add_argument("id")
        if name == "input":
            command.add_argument("text")
        if name == "approve":
            command.add_argument("--approved", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            payload = load_submission_file(args.file).payload(approved=args.approved)
            result = api_request(args.api_url, "/workflows", payload)
        else:
            path = "/workflows"
            if args.id:
                path += "/" + quote(args.id, safe="")
            payload = None
            if args.command != "status":
                path += "/" + args.command
            if args.command in {"cancel", "retry", "input", "approve"}:
                payload = {}
            if args.command == "input":
                payload = {"text": args.text}
            if args.command == "approve":
                payload = {"approved": args.approved}
            result = api_request(args.api_url, path, payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
