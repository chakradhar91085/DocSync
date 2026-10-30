"""Connections to the GitHub and Notion MCP servers.

Connection config is handled by `langchain-mcp-adapters`. Tool calls go through
the underlying MCP session so we receive every content type: the GitHub server
returns file contents as embedded resources, which plain LangChain tool output drops.
"""

from __future__ import annotations

import base64
import json
import os
from contextlib import AsyncExitStack
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession

from .config import Settings


class MCPError(RuntimeError):
    pass


def server_connections(settings: Settings, servers: set[str]) -> dict[str, dict]:
    connections: dict[str, dict] = {}
    if "github" in servers:
        if not settings.github_token:
            raise MCPError("GITHUB_TOKEN is not set")
        connections["github"] = {
            "transport": "streamable_http",
            "url": settings.github_mcp_url,
            "headers": {
                "Authorization": f"Bearer {settings.github_token}",
                # Only expose the read-only toolsets we need.
                "X-MCP-Toolsets": "repos,git",
                "X-MCP-Readonly": "true",
            },
        }
    if "notion" in servers:
        if not settings.notion_token:
            raise MCPError("NOTION_TOKEN is not set")
        connections["notion"] = {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@notionhq/notion-mcp-server"],
            # npx needs the normal environment (HOME, PATH, npm config), plus the token.
            "env": {**os.environ, "NOTION_TOKEN": settings.notion_token},
        }
    if "slack" in servers:
        if not (settings.slack_bot_token and settings.slack_channel_id):
            raise MCPError("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID must both be set")
        connections["slack"] = {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "slack-mcp-server@1.3.0", "--transport", "stdio"],
            "env": {
                **os.environ,
                "SLACK_MCP_XOXB_TOKEN": settings.slack_bot_token,
                # Posting is off by default in this server; allow it for our one channel only.
                "SLACK_MCP_ADD_MESSAGE_TOOL": settings.slack_channel_id,
                "SLACK_MCP_LOG_LEVEL": "warn",
            },
        }
    return connections


def result_text(content: list[Any]) -> str:
    """Flatten MCP content blocks (text, embedded resources, blobs) into one string."""
    parts: list[str] = []
    for block in content:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(block.text)
        elif kind == "resource":
            res = block.resource
            if getattr(res, "text", None) is not None:
                parts.append(res.text)
            elif getattr(res, "blob", None):
                parts.append(base64.b64decode(res.blob).decode("utf-8", errors="replace"))
    return "\n".join(parts)


def resource_text(content: list[Any]) -> str | None:
    """Return the text of the first embedded resource, if any (used for file contents)."""
    for block in content:
        if getattr(block, "type", None) == "resource":
            res = block.resource
            if getattr(res, "text", None) is not None:
                return res.text
            if getattr(res, "blob", None):
                return base64.b64decode(res.blob).decode("utf-8", errors="replace")
    return None


class MCPToolbox:
    """Holds one open session per MCP server for the duration of a run."""

    def __init__(self, settings: Settings, servers: set[str]):
        self.client = MultiServerMCPClient(server_connections(settings, servers))
        self._stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}

    async def __aenter__(self) -> "MCPToolbox":
        for name in self.client.connections:
            self.sessions[name] = await self._stack.enter_async_context(self.client.session(name))
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def tool_names(self, server: str) -> list[str]:
        listing = await self.sessions[server].list_tools()
        return [t.name for t in listing.tools]

    async def call_raw(self, server: str, tool: str, args: dict) -> list[Any]:
        result = await self.sessions[server].call_tool(tool, args)
        if result.isError:
            raise MCPError(f"{server}.{tool} failed: {result_text(result.content)[:500]}")
        return result.content

    async def call_json(self, server: str, tool: str, args: dict) -> Any:
        text = result_text(await self.call_raw(server, tool, args))
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise MCPError(f"{server}.{tool} returned non-JSON output: {text[:300]}") from err
        if isinstance(data, dict) and data.get("status") == "error":
            raise MCPError(f"{server}.{tool} failed: {data.get('message') or data}")
        return data
