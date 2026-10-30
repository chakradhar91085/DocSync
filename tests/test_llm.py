import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from docsync.llm import extract_json, invoke_structured
from docsync.schemas import ChangeClass


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('<think>{"no": 1}</think> Sure! ```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Here you go: {"a": {"b": 3}} trailing') == {"a": {"b": 3}}
    with pytest.raises(ValueError):
        extract_json("no json here")


async def test_invoke_structured_self_corrects():
    replies = iter(["I think it's minor", '{"kind": "minor", "reason": "typo fix"}'])
    seen = []

    def respond(messages):
        seen.append(messages)
        return AIMessage(content=next(replies))

    result = await invoke_structured(RunnableLambda(respond), [HumanMessage(content="classify")], ChangeClass)
    assert result == ChangeClass(kind="minor", reason="typo fix")
    assert "not valid JSON" in seen[1][-1].content
