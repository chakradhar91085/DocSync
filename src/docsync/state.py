"""Run-to-run cache: content hash -> summary/endpoints per file.

This is what makes incremental sync cheap: an unchanged file is never sent to the
LLM again, which matters on free-tier rate limits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from .schemas import Endpoint, FileSummary, ModuleDoc

STATE_VERSION = 1


class FileRecord(BaseModel):
    hash: str
    summary: FileSummary
    endpoints: list[Endpoint] = Field(default_factory=list)


class State(BaseModel):
    version: int = STATE_VERSION
    repo: str = ""
    last_sha: str = ""
    files: dict[str, FileRecord] = Field(default_factory=dict)
    modules: dict[str, ModuleDoc] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "State":
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") != STATE_VERSION:
            return cls()
        return cls.model_validate(data)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2), encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
