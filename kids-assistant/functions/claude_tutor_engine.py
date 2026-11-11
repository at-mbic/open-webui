"""
title: Claude Tutor Engine
author: kids-assistant
description: Model provider for the kids' tutors. Calls Claude through the official Anthropic SDK. Refuses requests that arrive without a tutor system prompt, so the raw model can't be used directly.
requirements: anthropic
version: 0.1.0
"""

# Install as a Pipe function. It appears as one model with id
# "claude_tutor_engine". The tutor models (Estelle / Dorian) use it as their
# base model, and Open WebUI adds each tutor's system prompt before calling
# pipe(). Children are never given access to this base model directly.

from __future__ import annotations

import re
from typing import AsyncGenerator, Optional, Union

from pydantic import BaseModel, Field

REFUSAL_TEXT = (
    "I can't help with that one. If it's something important, please ask your "
    "parent or another trusted adult."
)
ERROR_TEXT = "Sorry, the study buddy is having trouble right now. Please try again in a minute."

# Must match NOTICE_HEADER's prefix in kids_guardrails.py. Guardrail notices
# are system text too, but they are not a tutor prompt.
GUARDRAIL_NOTICE_PREFIX = "[Guardrail notice"


def has_tutor_prompt(system: str) -> bool:
    idx = system.find(GUARDRAIL_NOTICE_PREFIX)
    core = system[:idx] if idx >= 0 else system
    return bool(core.strip())


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert OpenAI-style messages to (system, messages) for the Messages API."""
    system_parts: list[str] = []
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            text = content if isinstance(content, str) else " ".join(
                p.get("text", "") for p in content or [] if isinstance(p, dict)
            )
            if text.strip():
                system_parts.append(text)
            continue
        if role not in ("user", "assistant"):
            continue
        blocks: list[dict] = []
        if isinstance(content, str):
            if content.strip():
                blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for p in content:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "text" and p.get("text", "").strip():
                    blocks.append({"type": "text", "text": p["text"]})
                elif p.get("type") == "image_url" and role == "user":
                    url = (p.get("image_url") or {}).get("url", "")
                    match = re.match(r"data:(image/[\w.+-]+);base64,(.+)", url, re.S)
                    if match:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": match.group(1), "data": match.group(2)},
                        })
        if blocks:
            out.append({"role": role, "content": blocks})
    # The Messages API requires the conversation to start with a user turn.
    while out and out[0]["role"] != "user":
        out.pop(0)
    return "\n\n".join(system_parts), out


class Pipe:
    class Valves(BaseModel):
        ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key.")
        MODEL: str = Field(default="claude-opus-5-5")
        EFFORT: str = Field(default="medium", description="low | medium | high | xhigh | max")
        MAX_TOKENS: int = Field(default=8000)
        REQUIRE_SYSTEM_PROMPT: bool = Field(
            default=True,
            description="Refuse requests without a system prompt (i.e. not via a tutor model).",
        )
        ENABLE_REFUSAL_FALLBACK: bool = Field(
            default=False,
            description="Re-run safety-declined requests on a fallback model "
            "(server-side-fallback beta). Off by default for a children's app: "
            "a refusal here is usually the guardrail doing its job.",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __user__: Optional[dict] = None) -> Union[str, AsyncGenerator[str, None]]:
        import anthropic

        system, messages = to_anthropic(body.get("messages", []))
        if self.valves.REQUIRE_SYSTEM_PROMPT and not has_tutor_prompt(system):
            return "This engine can only be used through a tutor."
        if not messages:
            return "What would you like to work on?"
        if not self.valves.ANTHROPIC_API_KEY:
            return "The tutor isn't set up yet (missing API key). Ask your parent."

        client = anthropic.AsyncAnthropic(api_key=self.valves.ANTHROPIC_API_KEY)
        kwargs = dict(
            model=self.valves.MODEL,
            max_tokens=self.valves.MAX_TOKENS,
            system=system,
            messages=messages,
            output_config={"effort": self.valves.EFFORT},
        )
        if self.valves.ENABLE_REFUSAL_FALLBACK:
            kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
            kwargs["extra_body"] = {"fallbacks": "default"}

        if body.get("stream", False):
            return self._stream(client, kwargs)

        try:
            async with client.messages.stream(**kwargs) as stream:
                final = await stream.get_final_message()
        except anthropic.APIError:
            return ERROR_TEXT
        if final.stop_reason == "refusal":
            return REFUSAL_TEXT
        return "".join(b.text for b in final.content if b.type == "text")

    async def _stream(self, client, kwargs) -> AsyncGenerator[str, None]:
        import anthropic

        emitted = False
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    emitted = True
                    yield text
                final = await stream.get_final_message()
            if final.stop_reason == "refusal":
                yield ("\n\n" if emitted else "") + REFUSAL_TEXT
            elif final.stop_reason == "max_tokens":
                yield "\n\n(That answer got cut off. Ask me to keep going.)"
        except anthropic.RateLimitError:
            yield ERROR_TEXT
        except anthropic.APIStatusError:
            yield ERROR_TEXT
        except anthropic.APIConnectionError:
            yield ERROR_TEXT
