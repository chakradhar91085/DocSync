"""Deterministic Markdown rendering of chain outputs (the LLM never writes raw page layout)."""

from __future__ import annotations

from datetime import datetime, timezone

from .schemas import ArchitectureDoc, ChangelogEntry, Endpoint, FileSummary, ModuleDoc


def module_page(doc: ModuleDoc, summaries: list[FileSummary]) -> str:
    lines = [f"## Overview", doc.overview, ""]
    if doc.responsibilities:
        lines += ["## Responsibilities", *[f"- {r}" for r in doc.responsibilities], ""]
    if doc.key_files:
        lines += ["## Key files", *[f"- `{f.path}`: {f.role}" for f in doc.key_files], ""]
    lines += ["## How it fits", doc.how_it_fits, ""]
    lines += ["## File reference"]
    for s in sorted(summaries, key=lambda s: s.path):
        lines += [f"### `{s.path}`", s.purpose]
        lines += [f"- `{sym.name}` ({sym.kind}): {sym.description}" for sym in s.key_symbols]
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def api_page(endpoints: list[Endpoint]) -> str:
    if not endpoints:
        return "No HTTP endpoints were detected in this repository.\n"
    rows = ["| Method | Path | Summary | Source |", "| --- | --- | --- | --- |"]
    for e in endpoints:
        rows.append(f"| {e.method} | `{e.path}` | {_cell(e.summary)} | `{e.source_file}` |")
    lines = ["## Endpoints", *rows, ""]
    for e in endpoints:
        lines += [f"### {e.method} `{e.path}`", e.summary, ""]
        if e.params:
            lines += ["| Name | In | Type | Required | Description |", "| --- | --- | --- | --- | --- |"]
            lines += [
                f"| `{p.name}` | {p.location} | {p.type} | {'yes' if p.required else 'no'} | {_cell(p.description)} |"
                for p in e.params
            ]
            lines.append("")
        if e.response:
            lines += [f"**Response:** {e.response}", ""]
        lines += [f"Source: `{e.source_file}`", ""]
    return "\n".join(lines).strip() + "\n"


def architecture_page(doc: ArchitectureDoc) -> str:
    lines = ["## Summary", doc.summary, ""]
    if doc.mermaid:
        lines += ["## Diagram", "```mermaid", doc.mermaid.strip(), "```", ""]
    if doc.components:
        lines += ["## Components", *[f"- **{c.name}**: {c.responsibility}" for c in doc.components], ""]
    if doc.data_flow:
        lines += ["## Data flow", *[f"{i}. {step}" for i, step in enumerate(doc.data_flow, 1)], ""]
    if doc.tech_stack:
        lines += ["## Tech stack", *[f"- {t}" for t in doc.tech_stack], ""]
    return "\n".join(lines).strip() + "\n"


def changelog_entry(entry: ChangelogEntry, shas: list[str], when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    commits = ", ".join(f"`{s[:7]}`" for s in shas)
    lines = [f"## {when:%Y-%m-%d} · {entry.title}", entry.summary, ""]
    lines += [f"- {c}" for c in entry.changes]
    if entry.impact:
        lines += ["", f"**Impact:** {entry.impact}"]
    lines += ["", f"Commits: {commits}", ""]
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
