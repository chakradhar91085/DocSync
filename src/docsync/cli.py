"""Command line entry point.

    docsync run                          # GitHub MCP -> Notion MCP, incremental if possible
    docsync run --full                   # re-document everything
    docsync run --commits SHA1,SHA2      # document a specific merge (used by the GitHub Action)
    docsync run --local . --out docs_out # no tokens except the LLM: local folder -> Markdown files
    docsync run --no-slack               # skip the Slack summary
    docsync slack-test                   # post a test message to the Slack channel
    docsync tools                        # list the tools each MCP server exposes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import AsyncExitStack

from .chains import Chains
from .config import Settings
from .graph import Deps, build_graph
from .llm import build_llm
from .mcp_client import MCPToolbox
from .notify import ConsoleNotifier, SlackMCPNotifier, notion_url
from .sinks import MarkdownSink, NotionMCPSink, to_uuid
from .sources import GitHubMCPSource, LocalSource
from .state import State


async def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if not settings.llm_api_key:
        print("OPENROUTER_API_KEY (or LLM_API_KEY) is not set", file=sys.stderr)
        return 2

    servers = set()
    if not args.local:
        servers.add("github")
    if not args.out:
        servers.add("notion")
    post_to_slack = settings.slack_enabled and not args.no_slack and not args.out
    if post_to_slack:
        servers.add("slack")

    async with AsyncExitStack() as stack:
        toolbox = await stack.enter_async_context(MCPToolbox(settings, servers)) if servers else None
        source = LocalSource(args.local) if args.local else GitHubMCPSource(toolbox, settings)
        sink = MarkdownSink(args.out) if args.out else NotionMCPSink(toolbox, settings.notion_root_page_id)
        if post_to_slack:
            notifier = SlackMCPNotifier(toolbox, settings.slack_channel_id)
        else:
            notifier = None if args.no_slack else ConsoleNotifier()
        docs_url = None if args.out else notion_url(to_uuid(settings.notion_root_page_id))

        cache = State.load(settings.state_path)
        if cache.repo and cache.repo != source.name:
            cache = State()
        cache.repo = source.name

        shas = [s for s in (args.commits or "").split(",") if s]
        mode = "incremental" if shas and not args.full else "full"
        graph = build_graph(Deps(source, sink, Chains(build_llm(settings)), cache, settings, notifier, docs_url))
        result = await graph.ainvoke({"mode": mode, "shas": shas, "events": []})

        cache.last_sha = shas[-1] if shas else cache.last_sha
        cache.save(settings.state_path)

    for event in result["events"]:
        print(f"• {event}")
    return 0


async def tools(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    servers = {args.server} if args.server else {"github", "notion"} | ({"slack"} if settings.slack_enabled else set())
    async with MCPToolbox(settings, servers) as toolbox:
        for server in sorted(servers):
            print(f"[{server}]")
            for name in sorted(await toolbox.tool_names(server)):
                print(f"  {name}")
    return 0


async def slack_test(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if not settings.slack_enabled:
        print("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID must both be set", file=sys.stderr)
        return 2
    async with MCPToolbox(settings, {"slack"}) as toolbox:
        await SlackMCPNotifier(toolbox, settings.slack_channel_id).send("👋 DocSync is connected to this channel.")
    print("Test message posted.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docsync", description="Keep Notion docs in sync with your code.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="generate or update the documentation")
    p_run.add_argument("--full", action="store_true", help="re-document every file")
    p_run.add_argument("--commits", help="comma-separated SHAs of the merge to document")
    p_run.add_argument("--local", metavar="PATH", help="read code from a local folder instead of GitHub MCP")
    p_run.add_argument("--out", metavar="DIR", help="write Markdown files instead of Notion pages")
    p_run.add_argument("--no-slack", action="store_true", help="don't post a summary to Slack")

    p_tools = sub.add_parser("tools", help="list tools exposed by the MCP servers")
    p_tools.add_argument("--server", choices=["github", "notion", "slack"])

    sub.add_parser("slack-test", help="post a test message to the Slack channel")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    handler = {"run": run, "tools": tools, "slack-test": slack_test}[args.command]
    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
