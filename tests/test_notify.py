from docsync.chains import Chains
from docsync.config import Settings
from docsync.graph import Deps, build_graph
from docsync.notify import SlackMCPNotifier, notion_url, summary_message
from docsync.schemas import ChangelogEntry
from docsync.sinks import MarkdownSink
from docsync.sources import LocalSource
from docsync.state import State

from .conftest import git


class RecordingNotifier:
    def __init__(self, fail=False):
        self.messages, self.fail = [], fail

    async def send(self, message):
        if self.fail:
            raise RuntimeError("slack is down")
        self.messages.append(message)


def test_summary_message():
    state = {
        "shas": ["abcdef1234567"], "updated_modules": ["api", "core"], "removed_modules": ["old"],
        "endpoint_count": 3, "changelog": ChangelogEntry(title="Added health check", summary="New endpoint."),
    }
    msg = summary_message(state, "me/shop", "https://www.notion.so/abc")
    assert "me/shop" in msg and "`abcdef1`" in msg
    assert "Added health check" in msg
    assert "api, core" in msg and "removed: old" in msg
    assert "3 endpoints" in msg and "unchanged" in msg
    assert "(https://www.notion.so/abc)" in msg


def test_notion_url():
    assert notion_url("1f2e3d4c-5b6a-7988-1f2e-3d4c5b6a7988") == "https://www.notion.so/1f2e3d4c5b6a79881f2e3d4c5b6a7988"


async def test_slack_notifier_calls_mcp_tool():
    calls = []

    class Toolbox:
        async def call_raw(self, server, tool, args):
            calls.append((server, tool, args))
            return []

    await SlackMCPNotifier(Toolbox(), "C123").send("hello")
    assert calls == [("slack", "conversations_add_message",
                      {"channel_id": "C123", "payload": "hello", "content_type": "text/markdown"})]


async def run(repo, out, llm, notifier, mode="full", shas=()):
    deps = Deps(LocalSource(repo), MarkdownSink(out), Chains(llm.runnable), State(), Settings(), notifier)
    return await build_graph(deps).ainvoke({"mode": mode, "shas": list(shas), "events": []})


async def test_pipeline_posts_summary(sample_repo, tmp_path, fake_llm):
    notifier = RecordingNotifier()
    await run(sample_repo, tmp_path / "docs", fake_llm, notifier)
    assert len(notifier.messages) == 1
    assert "Architecture overview rewritten" in notifier.messages[0]


async def test_slack_failure_does_not_fail_run(sample_repo, tmp_path, fake_llm):
    result = await run(sample_repo, tmp_path / "docs", fake_llm, RecordingNotifier(fail=True))
    assert any("Slack: post failed" in e for e in result["events"])
    assert (tmp_path / "docs" / "api-reference.md").exists()
