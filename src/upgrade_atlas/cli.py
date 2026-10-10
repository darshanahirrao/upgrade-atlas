import argparse
import json
import os
import sys

from .example import example_report
from .provider import ProviderError, SerpApi
from .research import markdown_report, research_upgrade


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Primary-source upgrade research, never approval")
    commands = parser.add_subparsers(dest="command", required=True)
    research = commands.add_parser("research")
    for name in ("package", "current", "target"):
        research.add_argument(name)
    research.add_argument("--format", choices=("json", "markdown"), default="markdown")
    example = commands.add_parser("example", help="Explicitly synthetic; makes no API requests")
    example.add_argument("--format", choices=("json", "markdown"), default="markdown")
    server = commands.add_parser("serve")
    server.add_argument("--port", type=int, default=8872)
    args = parser.parse_args(argv)
    if args.command == "serve":
        from .server import serve

        serve(args.port)
        return 0
    try:
        if args.command == "example":
            report = example_report()
        else:
            client = SerpApi(os.environ.get("SERPAPI_API_KEY", ""))
            report = research_upgrade(
                {"package": args.package, "current": args.current, "target": args.target},
                client.search,
            )
        print(json.dumps(report, indent=2) if args.format == "json" else markdown_report(report))
        return 2 if any(item["state"] == "error" for item in report["searches"]) else 0
    except (ProviderError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
