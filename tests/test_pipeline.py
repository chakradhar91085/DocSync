from docsync.chains import Chains
from docsync.config import Settings
from docsync.graph import Deps, build_graph
from docsync.sinks import MarkdownSink
from docsync.sources import LocalSource
from docsync.state import State

from .conftest import git


async def run(repo, out, llm, cache, mode="full", shas=()):
    deps = Deps(LocalSource(repo), MarkdownSink(out), Chains(llm.runnable), cache, Settings(max_concurrency=2))
    return await build_graph(deps).ainvoke({"mode": mode, "shas": list(shas), "events": []})


async def test_full_then_incremental(sample_repo, tmp_path, fake_llm):
    out = tmp_path / "docs"
    cache = State()
    await run(sample_repo, out, fake_llm, cache)

    assert fake_llm.calls["file_summary"] >= 2 and fake_llm.calls["architecture"] == 1
    assert (out / "modules" / "api.md").exists() and (out / "modules" / "core.md").exists()
    api_md = (out / "api-reference.md").read_text()
    assert "`/users/{user_id}`" in api_md and "/ghost" not in api_md  # hallucinated route dropped
    api_module = (out / "modules" / "api.md").read_text()
    assert "read_user" in api_module and "imaginary_helper" not in api_module  # hallucinated symbol dropped
    assert "flowchart TD" in (out / "architecture-overview.md").read_text()  # fallback diagram

    # A second full run on unchanged code costs zero file-summary calls.
    before = fake_llm.calls["file_summary"]
    await run(sample_repo, out, fake_llm, cache)
    assert fake_llm.calls["file_summary"] == before

    # Merge a small change: only that file is re-summarised, architecture is left alone.
    (sample_repo / "core" / "db.py").write_text(
        "def get_user(user_id):\n    return {'id': user_id}\n\ndef health():\n    return 'ok'\n"
    )
    git(sample_repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "add health check")
    sha = git(sample_repo, "rev-parse", "HEAD")
    summaries, archs = fake_llm.calls["file_summary"], fake_llm.calls["architecture"]
    result = await run(sample_repo, out, fake_llm, cache, mode="incremental", shas=[sha])

    assert result["change_kind"] == "minor"
    assert fake_llm.calls["file_summary"] - summaries <= 2  # one file (+1 retry for the fake hallucination)
    assert fake_llm.calls["architecture"] == archs
    assert "Added health check" in (out / "changelog.md").read_text()


async def test_new_module_is_structural(sample_repo, tmp_path, fake_llm):
    out = tmp_path / "docs"
    cache = State()
    await run(sample_repo, out, fake_llm, cache)
    (sample_repo / "billing").mkdir()
    (sample_repo / "billing" / "invoice.py").write_text("def create_invoice():\n    return 1\n")
    git(sample_repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(sample_repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "billing")
    sha = git(sample_repo, "rev-parse", "HEAD")
    result = await run(sample_repo, out, fake_llm, cache, mode="incremental", shas=[sha])
    assert result["change_kind"] == "structural"
    assert (out / "modules" / "billing.md").exists()


async def test_deleted_module_page_is_removed(sample_repo, tmp_path, fake_llm):
    out = tmp_path / "docs"
    cache = State()
    await run(sample_repo, out, fake_llm, cache)
    git(sample_repo, "rm", "-q", "core/db.py")
    git(sample_repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "drop core")
    sha = git(sample_repo, "rev-parse", "HEAD")
    await run(sample_repo, out, fake_llm, cache, mode="incremental", shas=[sha])
    assert not (out / "modules" / "core.md").exists()
    assert "core/db.py" not in cache.files
