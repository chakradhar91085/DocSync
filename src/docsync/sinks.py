"""Where the docs go: Notion (via Notion's official MCP server) or local Markdown files.

Notion layout under the root page you share with the integration:

    <root page>
     ├── Architecture Overview
     ├── API Reference
     ├── Changelog
     └── Modules
          ├── <module A>
          └── <module B>
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Protocol

from .mcp_client import MCPToolbox

ARCHITECTURE = "Architecture Overview"
API = "API Reference"
CHANGELOG = "Changelog"
MODULES = "Modules"


class DocSink(Protocol):
    async def publish(self, title: str, markdown: str, parent: str | None = None) -> None: ...
    async def prepend(self, title: str, markdown: str) -> None: ...
    async def remove(self, title: str, parent: str | None = None) -> None: ...


class MarkdownSink:
    """Writes pages to a folder. Used for --dry-run, local demos and tests."""

    def __init__(self, out_dir: str | Path):
        self.out = Path(out_dir)

    def _file(self, title: str, parent: str | None) -> Path:
        folder = self.out / _slug(parent) if parent else self.out
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_slug(title)}.md"

    async def publish(self, title: str, markdown: str, parent: str | None = None) -> None:
        self._file(title, parent).write_text(f"# {title}\n\n{markdown}", encoding="utf-8")

    async def prepend(self, title: str, markdown: str) -> None:
        path = self._file(title, None)
        old = path.read_text(encoding="utf-8").split("\n", 2)[-1] if path.exists() else ""
        path.write_text(f"# {title}\n\n{markdown}\n---\n\n{old.lstrip()}", encoding="utf-8")

    async def remove(self, title: str, parent: str | None = None) -> None:
        self._file(title, parent).unlink(missing_ok=True)


class NotionMCPSink:
    """Creates and updates Notion pages through the Notion MCP server's tools."""

    def __init__(self, toolbox: MCPToolbox, root_page_id: str):
        self.toolbox = toolbox
        self.root = to_uuid(root_page_id)
        self._children: dict[str, dict[str, str]] = {}  # parent id -> {title: page id}

    async def _call(self, tool: str, args: dict):
        return await self.toolbox.call_json("notion", tool, args)

    async def _child_pages(self, parent_id: str) -> dict[str, str]:
        if parent_id in self._children:
            return self._children[parent_id]
        pages: dict[str, str] = {}
        cursor = None
        while True:
            args = {"block_id": parent_id, "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            data = await self._call("API-get-block-children", args)
            for block in data.get("results", []):
                if block.get("type") == "child_page":
                    pages[block["child_page"]["title"]] = block["id"]
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        self._children[parent_id] = pages
        return pages

    async def _page(self, title: str, parent_id: str, create: bool = True) -> str | None:
        pages = await self._child_pages(parent_id)
        if title in pages:
            return pages[title]
        if not create:
            return None
        created = await self._call("API-post-page", {
            "parent": {"page_id": parent_id},
            "properties": {"title": [{"type": "text", "text": {"content": title}}]},
        })
        pages[title] = created["id"]
        return created["id"]

    async def _parent_id(self, parent: str | None) -> str:
        return await self._page(parent, self.root) if parent else self.root

    async def _write(self, page_id: str, markdown: str) -> None:
        await self._call("API-update-page-markdown", {
            "page_id": page_id,
            "type": "replace_content",
            "replace_content": {"new_str": markdown, "allow_deleting_content": False},
        })

    async def publish(self, title: str, markdown: str, parent: str | None = None) -> None:
        page_id = await self._page(title, await self._parent_id(parent))
        await self._write(page_id, markdown)

    async def prepend(self, title: str, markdown: str) -> None:
        page_id = await self._page(title, self.root)
        current = await self._call("API-retrieve-page-markdown", {"page_id": page_id})
        old = current.get("markdown", "") if isinstance(current, dict) else ""
        await self._write(page_id, f"{markdown}\n---\n\n{old}".strip() + "\n")

    async def remove(self, title: str, parent: str | None = None) -> None:
        parent_id = await self._parent_id(parent)
        page_id = await self._page(title, parent_id, create=False)
        if page_id:
            await self._call("API-patch-page", {"page_id": page_id, "in_trash": True})
            self._children[parent_id].pop(title, None)


def to_uuid(page_id: str) -> str:
    """Accept a raw id, a dashed id or a full Notion URL and return a dashed UUID."""
    match = re.findall(r"[0-9a-fA-F]{32}|[0-9a-fA-F-]{36}", page_id)
    if not match:
        raise ValueError(f"not a Notion page id: {page_id!r}")
    return str(uuid.UUID(match[-1].replace("-", "")))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "page"
