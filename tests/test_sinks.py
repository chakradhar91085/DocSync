import json
from types import SimpleNamespace

from docsync.sinks import MarkdownSink, NotionMCPSink, to_uuid


def test_to_uuid():
    raw = "1f2e3d4c5b6a79881f2e3d4c5b6a7988"
    dashed = "1f2e3d4c-5b6a-7988-1f2e-3d4c5b6a7988"
    assert to_uuid(raw) == dashed
    assert to_uuid(dashed) == dashed
    assert to_uuid(f"https://www.notion.so/My-Docs-{raw}?pvs=4") == dashed


async def test_markdown_sink_prepend(tmp_path):
    sink = MarkdownSink(tmp_path)
    await sink.prepend("Changelog", "## first\n")
    await sink.prepend("Changelog", "## second\n")
    text = (tmp_path / "changelog.md").read_text()
    assert text.startswith("# Changelog")
    assert text.index("second") < text.index("first")


class FakeToolbox:
    def __init__(self):
        self.calls = []
        self.children = {}

    async def call_json(self, server, tool, args):
        self.calls.append((tool, args))
        if tool == "API-get-block-children":
            return {"results": self.children.get(args["block_id"], []), "has_more": False}
        if tool == "API-post-page":
            new_id = f"00000000-0000-0000-0000-{len(self.calls):012d}"
            self.children.setdefault(args["parent"]["page_id"], []).append(
                {"type": "child_page", "id": new_id, "child_page": {"title": args["properties"]["title"][0]["text"]["content"]}}
            )
            return {"id": new_id}
        if tool == "API-retrieve-page-markdown":
            return {"markdown": "## old entry\n"}
        return {}


async def test_notion_sink_creates_then_reuses_pages():
    tb = FakeToolbox()
    root = "1f2e3d4c5b6a79881f2e3d4c5b6a7988"
    sink = NotionMCPSink(tb, root)
    await sink.publish("payments", "# hi", parent="Modules")
    await sink.publish("payments", "# hi again", parent="Modules")
    tools = [t for t, _ in tb.calls]
    assert tools.count("API-post-page") == 2  # "Modules" container + "payments", created once each
    writes = [a for t, a in tb.calls if t == "API-update-page-markdown"]
    assert writes[-1]["replace_content"]["new_str"] == "# hi again"

    await sink.prepend("Changelog", "## new entry\n")
    final = [a for t, a in tb.calls if t == "API-update-page-markdown"][-1]["replace_content"]["new_str"]
    assert final.index("new entry") < final.index("old entry")

    await sink.remove("payments", parent="Modules")
    assert tb.calls[-1][0] == "API-patch-page" and tb.calls[-1][1]["in_trash"] is True
