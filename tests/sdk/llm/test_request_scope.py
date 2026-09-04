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


def test_request_scope_enters_once_for_nested_sync_metadata_resolution(monkeypatch):
    events: list[str] = []

    def stop_after_metadata(*_args, **_kwargs):
        raise RuntimeError("stop after metadata resolution")

    monkeypatch.setattr(
        "openhands.sdk.llm.llm.resolve_provider_metadata_sync", lambda _llm: None
    )
    monkeypatch.setattr(LLM, "_prepare_completion_params", stop_after_metadata)
    llm = LLM(model="openai/gpt-4o")
    llm.set_request_scope(lambda: recording_scope(events))

    with pytest.raises(RuntimeError, match="stop after metadata resolution"):
        llm.completion([])

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
async def test_request_scope_reentrancy_is_task_local(monkeypatch):
    events: list[str] = []
    started = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def block_metadata(_llm):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await release.wait()
        return None

    monkeypatch.setattr(
        "openhands.sdk.llm.llm.aresolve_provider_metadata", block_metadata
    )
    llm = LLM(model="openai/gpt-4o")
    llm.set_request_scope(lambda: recording_scope(events))

    tasks = [
        asyncio.create_task(llm.aresolve_runtime_metadata(force=True)) for _ in range(2)
    ]
    await asyncio.wait_for(both_started.wait(), timeout=1)

    assert events == ["enter", "enter"]

    release.set()
    await asyncio.gather(*tasks)

    assert events == ["enter", "enter", "exit", "exit"]


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
