"""Tell the team what changed: a short summary posted to Slack (via a Slack MCP server)."""

from __future__ import annotations

from typing import Protocol

from .mcp_client import MCPToolbox


class Notifier(Protocol):
    async def send(self, message: str) -> None: ...


class SlackMCPNotifier:
    """Posts to one channel through the `conversations_add_message` tool of slack-mcp-server."""

    def __init__(self, toolbox: MCPToolbox, channel_id: str):
        self.toolbox = toolbox
        self.channel_id = channel_id

    async def send(self, message: str) -> None:
        await self.toolbox.call_raw("slack", "conversations_add_message", {
            "channel_id": self.channel_id,
            "payload": message,
            "content_type": "text/markdown",
        })


class ConsoleNotifier:
    """Prints the message instead of posting it (local and dry runs)."""

    async def send(self, message: str) -> None:
        print("\n--- Slack message (not sent) ---\n" + message + "\n--------------------------------")


def summary_message(state: dict, repo: str, docs_url: str | None) -> str:
    """Build the run summary from the pipeline's final state."""
    shas = state.get("shas") or []
    ref = f" (`{shas[-1][:7]}`)" if shas else ""
    lines = [f"📘 **Docs updated for {repo}**{ref}"]

    entry = state.get("changelog")
    if entry:
        lines += ["", f"**{entry.title}**: {entry.summary}"]

    lines.append("")
    updated = state.get("updated_modules") or []
    removed = state.get("removed_modules") or []
    lines.append(f"• Module pages updated: {', '.join(updated) if updated else 'none'}")
    if removed:
        lines.append(f"• Module pages removed: {', '.join(removed)}")
    lines.append(f"• API reference: {state.get('endpoint_count', 0)} endpoints")
    if state.get("architecture"):
        lines.append(f"• Architecture overview rewritten: {state.get('change_reason', 'structural change')}")
    else:
        lines.append("• Architecture overview: unchanged (minor change)")

    if docs_url:
        lines += ["", f"[Open the docs in Notion]({docs_url})"]
    return "\n".join(lines)


def notion_url(page_id: str) -> str:
    return f"https://www.notion.so/{page_id.replace('-', '')}"
