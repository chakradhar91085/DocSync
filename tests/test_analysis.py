from docsync.analysis import (
    ensure_diagram, file_route_hint, looks_like_routes, missing_symbols, module_of, verified_endpoints,
)
from docsync.config import is_source_file, SOURCE_EXTENSIONS
from docsync.schemas import ArchitectureDoc, Endpoint, FileSummary, Symbol


def test_module_of():
    assert module_of("src/docsync/llm.py") == "docsync"
    assert module_of("api/routes.py") == "api"
    assert module_of("src/main.py") == "src"
    assert module_of("main.py") == "root"


def test_source_filter():
    assert is_source_file("app/page.tsx", SOURCE_EXTENSIONS)
    assert not is_source_file("node_modules/x/index.js", SOURCE_EXTENSIONS)
    assert not is_source_file("types/global.d.ts", SOURCE_EXTENSIONS)
    assert not is_source_file("README.md", SOURCE_EXTENSIONS)


def test_next_route_hint():
    assert file_route_hint("app/api/users/[id]/route.ts") == "/api/users/{id}"
    assert file_route_hint("app/(admin)/api/stats/route.ts") == "/api/stats"
    assert file_route_hint("pages/api/index.ts") == "/api"
    assert file_route_hint("app/page.tsx") is None


def test_route_detection():
    assert looks_like_routes("x.py", '@router.post("/items")\ndef f(): ...')
    assert looks_like_routes("server.js", "app.get('/health', handler)")
    assert not looks_like_routes("util.py", "def add(a, b): return a + b")


def test_missing_symbols_flags_hallucinations():
    summary = FileSummary(path="a.py", purpose="x", key_symbols=[
        Symbol(name="real_fn", description="ok"), Symbol(name="Client.connect()", description="ok"),
        Symbol(name="fake_fn", description="made up"),
    ])
    code = "def real_fn():\n    pass\nclass Client:\n    def connect(self): ...\n"
    assert missing_symbols(summary, code) == ["fake_fn"]


def test_verified_endpoints():
    code = '@app.get("/users/{id}")\ndef u(id): ...'
    eps = [Endpoint(method="get", path="/users/{id}", summary=""), Endpoint(method="GET", path="/ghost", summary="")]
    kept = verified_endpoints(eps, code, None)
    assert [(e.method, e.path) for e in kept] == [("GET", "/users/{id}")]


def test_verified_endpoints_file_routing():
    code = "export async function GET(req) {}"
    eps = [Endpoint(method="GET", path="/whatever", summary=""), Endpoint(method="POST", path="/x", summary="")]
    kept = verified_endpoints(eps, code, "/api/users")
    assert [(e.method, e.path) for e in kept] == [("GET", "/api/users")]


def test_invalid_mermaid_falls_back_to_dependency_graph():
    modules = {
        "api": [FileSummary(path="api/r.py", purpose="", internal_dependencies=["core.db"])],
        "core": [FileSummary(path="core/db.py", purpose="")],
    }
    doc = ensure_diagram(ArchitectureDoc(summary="", mermaid="oops"), modules)
    assert doc.mermaid.startswith("flowchart TD")
    assert "m0 --> m1" in doc.mermaid
    good = ensure_diagram(ArchitectureDoc(summary="", mermaid="```mermaid\nflowchart LR\n  a --> b\n```"), modules)
    assert good.mermaid == "flowchart LR\n  a --> b"
