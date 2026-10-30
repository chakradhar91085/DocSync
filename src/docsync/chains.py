"""The six LLM chains. Each one is: prompt template -> LLM -> validated Pydantic object."""

from __future__ import annotations

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from . import prompts
from .analysis import drop_symbols, ensure_diagram, file_route_hint, missing_symbols, verified_endpoints
from .llm import invoke_structured
from .schemas import (
    ArchitectureDoc, ChangeClass, ChangelogEntry, Endpoint, EndpointList, FileSummary, ModuleDoc,
)
from .sources import ChangeSet


class Chains:
    def __init__(self, llm: Runnable):
        self.llm = llm

    async def _run(self, prompt: ChatPromptTemplate, schema: type[BaseModel], **values):
        messages = prompt.format_messages(**values)
        return await invoke_structured(self.llm, messages, schema)

    # 1 ------------------------------------------------------------------ map
    async def summarize_file(self, path: str, content: str) -> FileSummary:
        """Summarise one file, then verify every symbol it mentions exists in the code.

        If the model invented names, it gets one retry with the bad names listed;
        anything still unverifiable is dropped rather than published.
        """
        summary = await self._run(prompts.FILE_SUMMARY, FileSummary, path=path, content=content, feedback="")
        missing = missing_symbols(summary, content)
        if missing:
            feedback = (
                f"A previous attempt listed symbols that do not exist in this file: {', '.join(missing)}. "
                "Only list identifiers that literally appear in the code."
            )
            summary = await self._run(prompts.FILE_SUMMARY, FileSummary, path=path, content=content, feedback=feedback)
            summary = drop_symbols(summary, missing_symbols(summary, content))
        return summary.model_copy(update={"path": path})

    # 2 --------------------------------------------------------------- reduce
    async def write_module(self, module: str, summaries: list[FileSummary]) -> ModuleDoc:
        compact = json.dumps([s.model_dump() for s in summaries], indent=1)[:30_000]
        doc = await self._run(prompts.MODULE_DOC, ModuleDoc, module=module, summaries=compact)
        return doc.model_copy(update={"name": module})

    # 3 ------------------------------------------------------------------ api
    async def extract_api(self, path: str, content: str) -> list[Endpoint]:
        hint = file_route_hint(path)
        result = await self._run(
            prompts.API_EXTRACT, EndpointList, path=path, content=content,
            route_hint=hint or "(declared in code)",
        )
        endpoints = [e.model_copy(update={"source_file": path}) for e in result.endpoints]
        return verified_endpoints(endpoints, content, hint)

    # 4 --------------------------------------------------------------- router
    async def classify_change(self, changes: ChangeSet) -> ChangeClass:
        return await self._run(
            prompts.CHANGE_CLASSIFY, ChangeClass, messages="\n".join(changes.messages),
            files=_file_list(changes), diff=changes.diff_excerpt(),
        )

    # 5 ------------------------------------------------------------ architecture
    async def write_architecture(
        self, repo: str, modules: dict[str, ModuleDoc], summaries: dict[str, list[FileSummary]], manifests: str,
    ) -> ArchitectureDoc:
        compact = json.dumps({n: m.model_dump(exclude={"key_files"}) for n, m in modules.items()}, indent=1)[:30_000]
        doc = await self._run(prompts.ARCHITECTURE, ArchitectureDoc, repo=repo, modules=compact, manifests=manifests[:6_000])
        return ensure_diagram(doc, summaries)

    # 6 ------------------------------------------------------------- changelog
    async def write_changelog(self, changes: ChangeSet) -> ChangelogEntry:
        return await self._run(
            prompts.CHANGELOG, ChangelogEntry, messages="\n".join(changes.messages),
            files=_file_list(changes), diff=changes.diff_excerpt(),
        )


def _file_list(changes: ChangeSet) -> str:
    return "\n".join(f"- {f.path} ({f.status})" for f in changes.files)
