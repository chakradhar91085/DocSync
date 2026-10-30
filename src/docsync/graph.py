"""The DocSync pipeline as a LangGraph state machine.

    collect -> summarize -> modules -> api -> classify --structural--> architecture -> changelog -> END
                                                       \\--minor-------------------->/
"""

from __future__ import annotations

import asyncio
import logging
import operator
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from . import render
from .analysis import looks_like_routes, module_of
from .chains import Chains
from .config import Settings, is_manifest_file
from .schemas import ArchitectureDoc, ChangelogEntry
from .sinks import API, ARCHITECTURE, CHANGELOG, MODULES, DocSink
from .sources import ChangeSet, CodeSource, select_manifests, select_source_files
from .state import FileRecord, State, content_hash

log = logging.getLogger("docsync")


class RunState(TypedDict, total=False):
    mode: Literal["full", "incremental"]
    shas: list[str]
    changes: ChangeSet
    source_files: list[str]
    manifests: list[str]
    to_process: list[str]
    removed: list[str]
    affected_modules: list[str]
    new_or_gone_modules: list[str]
    change_kind: Literal["minor", "structural"]
    change_reason: str
    architecture: ArchitectureDoc
    changelog: ChangelogEntry
    events: Annotated[list[str], operator.add]


@dataclass
class Deps:
    source: CodeSource
    sink: DocSink
    chains: Chains
    cache: State
    settings: Settings


def build_graph(deps: Deps):
    sem = asyncio.Semaphore(deps.settings.max_concurrency)
    cache = deps.cache

    async def collect(state: RunState) -> RunState:
        all_paths = await deps.source.list_files()
        source_files = select_source_files(all_paths, deps.settings)
        mode = state.get("mode", "full")
        if mode == "incremental" and not cache.files:
            mode = "full"  # first run in this environment: nothing to diff against
        current = set(source_files)
        removed = [p for p in cache.files if p not in current]

        if mode == "full":
            to_process = source_files
            changes = ChangeSet()
            affected = sorted({module_of(p) for p in source_files} | {module_of(p) for p in removed})
        else:
            changes = await deps.source.get_changes(state.get("shas", []))
            to_process = [f.path for f in changes.files if f.status != "removed" and f.path in current]
            affected = sorted({module_of(p) for p in to_process} | {module_of(p) for p in removed})

        known = {module_of(p) for p in cache.files}
        now = {module_of(p) for p in source_files}
        return {
            "mode": mode, "changes": changes, "source_files": source_files,
            "manifests": select_manifests(all_paths), "to_process": to_process, "removed": removed,
            "affected_modules": affected, "new_or_gone_modules": sorted(known ^ now) if known else [],
            "events": [f"{mode} run: {len(to_process)} files to check, {len(removed)} removed"],
        }

    async def summarize(state: RunState) -> RunState:
        """Chain 1 (+ chain 3 for route files), mapped over files, skipping unchanged ones."""
        done: list[str] = []

        async def one(path: str) -> None:
            async with sem:
                try:
                    content = (await deps.source.read_file(path))[: deps.settings.max_file_chars]
                    digest = content_hash(content)
                    if path in cache.files and cache.files[path].hash == digest:
                        return
                    summary = await deps.chains.summarize_file(path, content)
                    endpoints = await deps.chains.extract_api(path, content) if looks_like_routes(path, content) else []
                    cache.files[path] = FileRecord(hash=digest, summary=summary, endpoints=endpoints)
                    done.append(path)
                except Exception as err:  # one bad file must not sink the run
                    log.warning("skipping %s: %s", path, err)

        await asyncio.gather(*(one(p) for p in state["to_process"]))
        for path in state["removed"]:
            cache.files.pop(path, None)
        return {"events": [f"summarised {len(done)} files ({len(state['to_process']) - len(done)} unchanged/skipped)"]}

    async def modules(state: RunState) -> RunState:
        """Chain 2: reduce file summaries into one page per affected module."""
        by_module = _group(cache)
        written: list[str] = []

        async def one(name: str) -> None:
            async with sem:
                if name not in by_module:
                    cache.modules.pop(name, None)
                    await deps.sink.remove(name, parent=MODULES)
                    return
                doc = await deps.chains.write_module(name, by_module[name])
                cache.modules[name] = doc
                await deps.sink.publish(name, render.module_page(doc, by_module[name]), parent=MODULES)
                written.append(name)

        await asyncio.gather(*(one(m) for m in state["affected_modules"]))
        return {"events": [f"module pages updated: {', '.join(sorted(written)) or 'none'}"]}

    async def api(state: RunState) -> RunState:
        endpoints = [e for rec in cache.files.values() for e in rec.endpoints]
        endpoints.sort(key=lambda e: (e.path, e.method))
        await deps.sink.publish(API, render.api_page(endpoints))
        return {"events": [f"API reference: {len(endpoints)} endpoints"]}

    async def classify(state: RunState) -> RunState:
        """Chain 4: route the run. Cheap rules first, the LLM only when rules can't decide."""
        if state["mode"] == "full":
            return {"change_kind": "structural", "change_reason": "full documentation run"}
        changes = state["changes"]
        if state["new_or_gone_modules"]:
            return {"change_kind": "structural", "change_reason": f"modules added/removed: {state['new_or_gone_modules']}"}
        if any(is_manifest_file(f.path) for f in changes.files):
            return {"change_kind": "structural", "change_reason": "dependency manifest changed"}
        if not state["to_process"] and not state["removed"]:
            return {"change_kind": "minor", "change_reason": "no source files changed"}
        result = await deps.chains.classify_change(changes)
        return {"change_kind": result.kind, "change_reason": result.reason}

    async def architecture(state: RunState) -> RunState:
        """Chain 5: only runs for structural changes."""
        manifests = []
        for path in state["manifests"]:
            try:
                manifests.append(f"--- {path}\n{(await deps.source.read_file(path))[:2000]}")
            except Exception as err:
                log.warning("could not read %s: %s", path, err)
        doc = await deps.chains.write_architecture(
            deps.source.name, dict(sorted(cache.modules.items())), _group(cache), "\n".join(manifests),
        )
        await deps.sink.publish(ARCHITECTURE, render.architecture_page(doc))
        return {"architecture": doc, "events": [f"architecture rewritten ({state['change_reason']})"]}

    async def changelog(state: RunState) -> RunState:
        """Chain 6: one plain-English entry per merge (incremental runs only)."""
        changes = state.get("changes")
        if state["mode"] != "incremental" or not changes or not changes.messages:
            return {"events": ["changelog: skipped (full run)"]}
        entry = await deps.chains.write_changelog(changes)
        await deps.sink.prepend(CHANGELOG, render.changelog_entry(entry, state.get("shas", [])))
        return {"changelog": entry, "events": [f"changelog: {entry.title}"]}

    def route(state: RunState) -> str:
        return "architecture" if state["change_kind"] == "structural" else "changelog"

    graph = StateGraph(RunState)
    for name, fn in [
        ("collect", collect), ("summarize", summarize), ("modules", modules), ("api", api),
        ("classify", classify), ("architecture", architecture), ("changelog", changelog),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "collect")
    graph.add_edge("collect", "summarize")
    graph.add_edge("summarize", "modules")
    graph.add_edge("modules", "api")
    graph.add_edge("api", "classify")
    graph.add_conditional_edges("classify", route, {"architecture": "architecture", "changelog": "changelog"})
    graph.add_edge("architecture", "changelog")
    graph.add_edge("changelog", END)
    return graph.compile()


def _group(cache: State) -> dict[str, list]:
    groups: dict[str, list] = {}
    for path, rec in sorted(cache.files.items()):
        groups.setdefault(module_of(path), []).append(rec.summary)
    return groups
