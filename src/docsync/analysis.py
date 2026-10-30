"""Code-side helpers: module grouping, route detection and hallucination checks."""

from __future__ import annotations

import re

from .schemas import ArchitectureDoc, Endpoint, FileSummary

CONTAINER_DIRS = {"src", "lib", "packages", "apps", "internal", "pkg"}

ROUTE_PATTERNS = [
    re.compile(r"@(?:app|router|api|bp|blueprint)\.(?:get|post|put|patch|delete|route|api_route)\s*\("),  # FastAPI/Flask
    re.compile(r"\b(?:app|router|server)\.(?:get|post|put|patch|delete|all)\s*\(\s*['\"`]/"),  # Express/Fastify
    re.compile(r"export\s+(?:async\s+)?function\s+(?:GET|POST|PUT|PATCH|DELETE)\b"),  # Next.js route handlers
    re.compile(r"@(?:Get|Post|Put|Patch|Delete|Request)Mapping\b"),  # Spring
    re.compile(r"@(?:Get|Post|Put|Patch|Delete)\s*\("),  # NestJS
    re.compile(r"\bpath\s*\(\s*['\"]"),  # Django urls.py
    re.compile(r"\.(?:HandleFunc|GET|POST|PUT|DELETE)\s*\(\s*\""),  # Go
]


def module_of(path: str) -> str:
    """Group files by their top-level folder, skipping container folders like `src/`."""
    dirs = path.split("/")[:-1]
    if len(dirs) > 1 and dirs[0] in CONTAINER_DIRS:
        dirs = dirs[1:]
    return dirs[0] if dirs else "root"


def looks_like_routes(path: str, content: str) -> bool:
    return file_route_hint(path) is not None or any(p.search(content) for p in ROUTE_PATTERNS)


def file_route_hint(path: str) -> str | None:
    """Routes implied by the file path (Next.js app router and pages/api)."""
    m = re.search(r"(?:^|/)app/(.*)/route\.(?:ts|js|tsx|jsx)$", path)
    if m:
        segs = [s for s in m.group(1).split("/") if not (s.startswith("(") and s.endswith(")"))]
        return "/" + "/".join(_param(s) for s in segs)
    m = re.search(r"(?:^|/)pages/(api/.*)\.(?:ts|js)$", path)
    if m:
        route = re.sub(r"/index$", "", m.group(1))
        return "/" + "/".join(_param(s) for s in route.split("/"))
    return None


def _param(segment: str) -> str:
    m = re.fullmatch(r"\[\.{0,3}(.+)\]", segment)
    return "{" + m.group(1) + "}" if m else segment


# ---------------------------------------------------------------- verification

def _identifier(name: str) -> str:
    name = name.strip().rstrip("()").strip("`")
    return re.split(r"[.:#]", name)[-1].strip()


def missing_symbols(summary: FileSummary, content: str) -> list[str]:
    """Names the LLM claims are in the file but are not (hallucinations)."""
    missing = []
    for sym in summary.key_symbols:
        ident = _identifier(sym.name)
        if not ident or not re.search(rf"(?<![\w$]){re.escape(ident)}(?![\w$])", content):
            missing.append(sym.name)
    return missing


def drop_symbols(summary: FileSummary, names: list[str]) -> FileSummary:
    keep = [s for s in summary.key_symbols if s.name not in set(names)]
    return summary.model_copy(update={"key_symbols": keep})


def verified_endpoints(endpoints: list[Endpoint], content: str, route_hint: str | None) -> list[Endpoint]:
    """Keep only endpoints whose route (or handler) can be found in the source."""
    kept = []
    for e in endpoints:
        e = e.model_copy(update={"method": e.method.upper().strip()})
        if route_hint is not None:
            if re.search(rf"\b{re.escape(e.method)}\b", content):
                kept.append(e.model_copy(update={"path": route_hint}))
            continue
        static = [s for s in e.path.split("/") if s and not re.match(r"^[:{<\[]", s)]
        anchor = static[-1] if static else None
        if anchor is None:
            if re.search(r"""['"`]/['"`]""", content):
                kept.append(e)
        elif anchor in content:
            kept.append(e)
    return kept


def valid_mermaid(diagram: str) -> bool:
    lines = [ln.strip() for ln in diagram.strip().splitlines() if ln.strip()]
    return bool(lines) and re.match(r"^(flowchart|graph)\s+(TD|TB|LR|RL|BT)\b", lines[0]) is not None and len(lines) > 1


def fallback_mermaid(modules: dict[str, list[FileSummary]]) -> str:
    """Module dependency graph built from the import lists: used if the LLM's diagram is invalid."""
    ids = {name: f"m{i}" for i, name in enumerate(sorted(modules))}
    lines = ["flowchart TD"] + [f'    {ids[n]}["{n}"]' for n in sorted(modules)]
    edges = set()
    for name, summaries in modules.items():
        for s in summaries:
            for dep in s.internal_dependencies:
                target = _module_for_import(dep, set(modules))
                if target and target != name:
                    edges.add((ids[name], ids[target]))
    lines += [f"    {a} --> {b}" for a, b in sorted(edges)]
    return "\n".join(lines)


def _module_for_import(dep: str, modules: set[str]) -> str | None:
    for token in re.split(r"[./\\@~]+", dep):
        if token in modules:
            return token
    return None


def ensure_diagram(doc: ArchitectureDoc, modules: dict[str, list[FileSummary]]) -> ArchitectureDoc:
    mermaid = re.sub(r"^```(?:mermaid)?|```$", "", doc.mermaid.strip(), flags=re.MULTILINE).strip()
    if not valid_mermaid(mermaid):
        mermaid = fallback_mermaid(modules)
    return doc.model_copy(update={"mermaid": mermaid})
