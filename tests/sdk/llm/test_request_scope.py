import asyncio
from contextlib import contextmanager

import pytest

from openhands.sdk import LLM


@contextmanager
def recording_scope(events: list[str]):
    events.append("enter")
    try:
        yield
    finally:
        events.append("exit")


@pytest.mark.parametrize("method_name", ["completion", "responses"])
def test_request_scope_wraps_sync_request_methods(method_name):
    events: list[str] = []
    llm = LLM.model_construct()
    llm.set_request_scope(lambda: recording_scope(events))

    with pytest.raises(TypeError):
        getattr(llm, method_name)()

    assert events == ["enter", "exit"]


@pytest.mark.parametrize("method_name", ["acompletion", "aresponses"])
@pytest.mark.asyncio
async def test_request_scope_wraps_async_request_methods(method_name):
    events: list[str] = []
    llm = LLM.model_construct()
    llm.set_request_scope(lambda: recording_scope(events))

    with pytest.raises(TypeError):
        await getattr(llm, method_name)()

    assert events == ["enter", "exit"]


@pytest.mark.asyncio
async def test_request_scope_exits_when_async_request_is_cancelled(monkeypatch):
    events: list[str] = []
    request_started = asyncio.Event()

    async def block_request(*_args, **_kwargs):
        request_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(LLM, "_aprepare_completion_params", block_request)
    llm = LLM(model="openai/gpt-4o")
    llm.set_request_scope(lambda: recording_scope(events))
    task = asyncio.create_task(llm.acompletion([]))
    await request_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == ["enter", "exit"]


@pytest.mark.parametrize("deep", [False, True])
def test_request_scope_is_runtime_only_and_shared_by_model_copies(deep):
    def factory():
        return recording_scope([])

    llm = LLM.model_construct()
    llm.set_request_scope(factory)

    copied = llm.model_copy(deep=deep)

    assert copied._request_scope is llm._request_scope
    assert "_request_scope" not in llm.model_dump()
