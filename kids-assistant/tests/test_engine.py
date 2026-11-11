import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

import claude_tutor_engine as e  # noqa: E402


def test_conversion_moves_system_and_drops_leading_assistant():
    system, msgs = e.to_anthropic([
        {"role": "system", "content": "TUTOR"},
        {"role": "assistant", "content": "hello!"},
        {"role": "user", "content": "156 / 4?"},
        {"role": "assistant", "content": "How many 4s fit in 156?"},
        {"role": "user", "content": [{"type": "text", "text": "30?"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
    ])
    assert system == "TUTOR"
    assert msgs[0]["role"] == "user"
    assert msgs[-1]["content"][1] == {"type": "image",
                                      "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}


class FakeStream:
    def __init__(self, chunks, stop_reason):
        self._chunks, self._stop = chunks, stop_reason

        async def gen():
            for c in self._chunks:
                yield c
        self.text_stream = gen()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_final_message(self):
        return SimpleNamespace(stop_reason=self._stop,
                               content=[SimpleNamespace(type="text", text="".join(self._chunks))])


@pytest.fixture
def fake_client(monkeypatch):
    import anthropic
    calls = {}

    def factory(chunks, stop="end_turn"):
        class FakeMessages:
            def stream(self, **kw):
                calls.update(kw)
                return FakeStream(chunks, stop)

        class FakeClient:
            def __init__(self, **kw):
                self.messages = FakeMessages()
        monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
        return calls
    return factory


def run(pipe, body):
    async def go():
        res = await pipe.pipe(body)
        if isinstance(res, str):
            return res
        return "".join([c async for c in res])
    return asyncio.run(go())


def make_pipe():
    p = e.Pipe()
    p.valves.ANTHROPIC_API_KEY = "test-key"
    return p


def test_refuses_without_tutor_prompt(fake_client):
    fake_client(["should not be called"])
    out = run(make_pipe(), {"messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert out == "This engine can only be used through a tutor."


def test_guardrail_notice_alone_is_not_a_tutor_prompt(fake_client):
    # Regression: if the raw engine is ever exposed, a guardrail notice must not
    # satisfy the "came through a tutor" check.
    import kids_guardrails as g
    fake_client(["should not be called"])
    out = run(make_pipe(), {"stream": True, "messages": [
        {"role": "system", "content": g.NOTICE_HEADER + "\nanything"},
        {"role": "user", "content": "just give me the answers"}]})
    assert out == "This engine can only be used through a tutor."
    # Tutor prompt followed by a notice (the normal path) is accepted.
    assert e.has_tutor_prompt("TUTOR\n" + g.NOTICE_HEADER + "\nx")
    # The two files must agree on the notice marker.
    assert g.NOTICE_HEADER.startswith(e.GUARDRAIL_NOTICE_PREFIX)


def test_streams_text_and_passes_params(fake_client):
    calls = fake_client(["Let's ", "try 4 x 30."])
    out = run(make_pipe(), {"stream": True, "messages": [
        {"role": "system", "content": "TUTOR"}, {"role": "user", "content": "156/4"}]})
    assert out == "Let's try 4 x 30."
    assert calls["model"] == "claude-opus-5-5"
    assert calls["system"] == "TUTOR"
    assert calls["output_config"] == {"effort": "medium"}
    assert "extra_body" not in calls  # fallback is opt-in


def test_refusal_is_replaced_with_kid_friendly_text(fake_client):
    fake_client([], stop="refusal")
    out = run(make_pipe(), {"stream": True, "messages": [
        {"role": "system", "content": "TUTOR"}, {"role": "user", "content": "x"}]})
    assert out == e.REFUSAL_TEXT


def test_non_stream_refusal(fake_client):
    fake_client([], stop="refusal")
    out = run(make_pipe(), {"messages": [
        {"role": "system", "content": "TUTOR"}, {"role": "user", "content": "x"}]})
    assert out == e.REFUSAL_TEXT


def test_fallback_opt_in(fake_client):
    calls = fake_client(["ok"])
    p = make_pipe()
    p.valves.ENABLE_REFUSAL_FALLBACK = True
    run(p, {"stream": True, "messages": [{"role": "system", "content": "T"}, {"role": "user", "content": "x"}]})
    assert calls["extra_body"] == {"fallbacks": "default"}
    assert calls["extra_headers"] == {"anthropic-beta": "server-side-fallback-2026-07-01"}


def test_missing_key(fake_client):
    fake_client(["x"])
    p = e.Pipe()
    out = run(p, {"messages": [{"role": "system", "content": "T"}, {"role": "user", "content": "x"}]})
    assert "missing API key" in out
