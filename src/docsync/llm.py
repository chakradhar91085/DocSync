"""LLM client: any OpenAI-compatible endpoint (OpenRouter by default), with
rate limiting, retries, a fallback model and robust JSON parsing.

Free open-source models don't all support strict JSON-schema mode, so instead of
relying on it we ask for JSON in the prompt, parse it ourselves and, if it fails
validation, send the error back to the model once so it can correct itself.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

from .config import Settings

T = TypeVar("T", bound=BaseModel)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def build_llm(settings: Settings) -> Runnable:
    from langchain_openai import ChatOpenAI

    limiter = InMemoryRateLimiter(
        requests_per_second=settings.requests_per_second,
        check_every_n_seconds=0.1,
        max_bucket_size=max(1, settings.max_concurrency),
    )

    def make(model: str) -> BaseChatModel:
        return ChatOpenAI(
            model=model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.temperature,
            max_retries=3,
            timeout=120,
            rate_limiter=limiter,
            default_headers={"HTTP-Referer": "https://github.com/docsync", "X-Title": "DocSync"},
        )

    primary = make(settings.model).with_retry(stop_after_attempt=2)
    if settings.fallback_model and settings.fallback_model != settings.model:
        return primary.with_fallbacks([make(settings.fallback_model)])
    return primary


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles <think> tags and ``` fences)."""
    text = _THINK_RE.sub("", text).strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError("model output JSON is not an object")
    return obj


def _content_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)


async def invoke_structured(llm: Runnable, messages: list[BaseMessage], schema: type[T]) -> T:
    """Call the LLM and return a validated `schema` instance (one self-correction retry)."""
    reply = await llm.ainvoke(messages)
    text = _content_text(reply)
    try:
        return schema.model_validate(extract_json(text))
    except (ValueError, ValidationError) as err:
        repair = messages + [
            AIMessage(content=text),
            HumanMessage(
                content=f"Your reply was not valid JSON for the required schema. Error: {err}\n"
                "Reply again with ONLY the corrected JSON object."
            ),
        ]
        reply = await llm.ainvoke(repair)
        return schema.model_validate(extract_json(_content_text(reply)))
