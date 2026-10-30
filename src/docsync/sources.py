"""Where the code comes from: a GitHub repo (via GitHub MCP) or a local folder."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import IGNORED_DIRS, Settings, is_manifest_file, is_source_file
from .mcp_client import MCPToolbox, resource_text


@dataclass
class ChangedFile:
    path: str
    status: str  # added | modified | removed | renamed
    patch: str = ""


@dataclass
class ChangeSet:
    messages: list[str] = field(default_factory=list)
    files: list[ChangedFile] = field(default_factory=list)

    def diff_excerpt(self, limit: int = 8_000) -> str:
        text = "\n".join(f"--- {f.path} ({f.status})\n{f.patch}" for f in self.files)
        return text[:limit]


class CodeSource(Protocol):
    name: str

    async def list_files(self) -> list[str]: ...
    async def read_file(self, path: str) -> str: ...
    async def get_changes(self, shas: list[str]) -> ChangeSet: ...


class GitHubMCPSource:
    """Reads a repository through GitHub's official MCP server."""

    def __init__(self, toolbox: MCPToolbox, settings: Settings):
        self.toolbox = toolbox
        self.owner, self.repo = settings.owner_and_name
        self.ref = settings.ref
        self.name = settings.repo
        self._settings = settings

    async def list_files(self) -> list[str]:
        tree = await self.toolbox.call_json("github", "get_repository_tree", {
            "owner": self.owner, "repo": self.repo, "tree_sha": self.ref, "recursive": True,
        })
        return [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"]

    async def read_file(self, path: str) -> str:
        content = await self.toolbox.call_raw("github", "get_file_contents", {
            "owner": self.owner, "repo": self.repo, "path": path, "ref": self.ref,
        })
        text = resource_text(content)
        if text is None:
            raise FileNotFoundError(path)
        return text

    async def get_changes(self, shas: list[str]) -> ChangeSet:
        changes = ChangeSet()
        seen: dict[str, ChangedFile] = {}
        for sha in shas:
            commit = await self.toolbox.call_json("github", "get_commit", {
                "owner": self.owner, "repo": self.repo, "sha": sha, "detail": "full_patch",
            })
            message = (commit.get("commit") or {}).get("message", "")
            changes.messages.append(f"{sha[:7]}: {message.strip()}")
            for f in commit.get("files") or []:
                seen[f["filename"]] = ChangedFile(f["filename"], f.get("status", "modified"), f.get("patch", ""))
        changes.files = list(seen.values())
        return changes


class LocalSource:
    """Reads a folder on disk. Used for local runs, demos and tests (no GitHub token needed)."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.name = self.root.name

    async def list_files(self) -> list[str]:
        files = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and not any(part in IGNORED_DIRS for part in rel.parts[:-1]):
                files.append(rel.as_posix())
        return files

    async def read_file(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8", errors="replace")

    async def get_changes(self, shas: list[str]) -> ChangeSet:
        """Use local git for the diff of each commit."""
        changes = ChangeSet()
        seen: dict[str, ChangedFile] = {}
        status_map = {"A": "added", "M": "modified", "D": "removed", "R": "renamed"}
        for sha in shas:
            msg = _git(self.root, "log", "-1", "--format=%s%n%b", sha)
            changes.messages.append(f"{sha[:7]}: {msg.strip()}")
            for line in _git(self.root, "show", "--name-status", "--format=", sha).splitlines():
                if not line.strip():
                    continue
                code, *paths = line.split("\t")
                path = paths[-1]
                patch = _git(self.root, "show", "--format=", sha, "--", path)
                seen[path] = ChangedFile(path, status_map.get(code[0], "modified"), patch)
        changes.files = list(seen.values())
        return changes


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def select_source_files(paths: list[str], settings: Settings) -> list[str]:
    files = [p for p in paths if is_source_file(p, settings.extensions)]
    return files[: settings.max_files]


def select_manifests(paths: list[str]) -> list[str]:
    return [p for p in paths if is_manifest_file(p) and p.count("/") <= 1]
