from typing import Any, cast
from unittest.mock import Mock

import pytest
from litellm.llms.anthropic.chat.transformation import AnthropicConfig
from litellm.types.utils import Message as LiteLLMMessage

from openhands.sdk.agent import Agent
from openhands.sdk.agent.response_dispatch import LLMResponseType, classify_response
from openhands.sdk.agent.utils import aprepare_llm_messages, prepare_llm_messages
from openhands.sdk.context.condenser import CondenserBase
from openhands.sdk.context.view import View
from openhands.sdk.conversation import Conversation
from openhands.sdk.event import (
    ActionEvent,
    LLMConvertibleEvent,
    MessageEvent,
    SystemPromptEvent,
)
from openhands.sdk.llm import (
    LLM,
    AnthropicCompactionBlock,
    Message,
    MessageToolCall,
    TextContent,
)
from openhands.sdk.llm.options.chat_options import select_chat_options
from openhands.sdk.tool import Action


class _CompactionAction(Action):
    value: str


def _message_texts(messages: list[Message]) -> list[str]:
    return [
        "".join(part.text for part in message.content if isinstance(part, TextContent))
        for message in messages
    ]


def test_anthropic_compaction_request_uses_native_context_management() -> None:
    instructions = "Preserve decisions and pending work. Do not call tools."
    llm = LLM(
        model="anthropic/claude-opus-4-6",
        anthropic_compact_threshold=150_000,
        anthropic_compaction_instructions=instructions,
    )

    options = select_chat_options(llm, {}, has_tools=True)

    assert options["context_management"] == {
        "edits": [
            {
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": 150_000},
                "instructions": instructions,
            }
        ]
    }


def test_explicit_context_management_takes_precedence() -> None:
    llm = LLM(
        model="anthropic/claude-opus-4-6",
        anthropic_compact_threshold=150_000,
    )
    explicit = {"edits": [{"type": "clear_tool_uses_20250919"}]}

    options = select_chat_options(
        llm,
        {"context_management": explicit},
        has_tools=True,
    )

    assert options["context_management"] is explicit


def test_compaction_block_is_captured_and_replayed_through_litellm_fields() -> None:
    response = LiteLLMMessage(
        role="assistant",
        content="Continue from the compacted state.",
        provider_specific_fields={
            "compaction_blocks": [
                {"type": "compaction", "content": "Durable provider summary"}
            ]
        },
    )

    message = Message.from_llm_chat_message(response)
    wire_message = message.to_chat_dict(
        cache_enabled=True,
        vision_enabled=False,
        function_calling_enabled=True,
        force_string_serializer=False,
        send_reasoning_content=False,
    )

    assert message.anthropic_compaction_blocks == [
        AnthropicCompactionBlock(content="Durable provider summary")
    ]
    assert wire_message["provider_specific_fields"] == {
        "compaction_blocks": [
            {"type": "compaction", "content": "Durable provider summary"}
        ]
    }


def test_litellm_places_compaction_first_and_enables_anthropic_beta() -> None:
    message = Message(
        role="assistant",
        content=[TextContent(text="Continue from compacted state.")],
        anthropic_compaction_blocks=[
            AnthropicCompactionBlock(content="Durable provider summary")
        ],
    ).to_chat_dict(
        cache_enabled=True,
        vision_enabled=False,
        function_calling_enabled=True,
        force_string_serializer=False,
        send_reasoning_content=False,
    )
    context_management = {
        "edits": [
            {
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": 150_000},
            }
        ]
    }
    config = AnthropicConfig()
    options = config.map_openai_params(
        {"context_management": context_management},
        {},
        "claude-opus-4-6",
        True,
    )
    headers: dict[str, str] = {}

    request = config.transform_request(
        "claude-opus-4-6",
        cast(Any, [{"role": "user", "content": "continue"}, message]),
        options,
        {"drop_params": True},
        headers,
    )

    assert request["context_management"] == context_management
    assert request["messages"][1]["content"] == [
        {"type": "compaction", "content": "Durable provider summary"},
        {"type": "text", "text": "Continue from compacted state."},
    ]
    assert headers["anthropic-beta"] == "compact-2026-01-12"


def test_empty_compaction_block_fails_instead_of_losing_provider_state() -> None:
    response = LiteLLMMessage(
        role="assistant",
        content=None,
        provider_specific_fields={
            "compaction_blocks": [{"type": "compaction", "content": None}]
        },
    )

    with pytest.raises(ValueError, match="empty Anthropic compaction block"):
        Message.from_llm_chat_message(response)


def test_action_event_persists_compaction_block_across_json_restart() -> None:
    event = ActionEvent(
        thought=[TextContent(text="Run the next check")],
        action=_CompactionAction(value="check"),
        tool_name="check",
        tool_call_id="call-1",
        tool_call=MessageToolCall(
            id="call-1",
            name="check",
            arguments='{"value":"check"}',
            origin="completion",
        ),
        llm_response_id="response-1",
        anthropic_compaction_blocks=[
            AnthropicCompactionBlock(content="Durable provider summary")
        ],
    )

    restored = ActionEvent.model_validate_json(event.model_dump_json())

    assert restored.to_llm_message().anthropic_compaction_blocks == [
        AnthropicCompactionBlock(content="Durable provider summary")
    ]


def test_parallel_tool_actions_reconstruct_one_compacted_assistant_turn() -> None:
    block = AnthropicCompactionBlock(content="Durable provider summary")
    actions: list[LLMConvertibleEvent] = [
        ActionEvent(
            thought=[TextContent(text="Run both checks")],
            action=_CompactionAction(value="first"),
            tool_name="check",
            tool_call_id="call-1",
            tool_call=MessageToolCall(
                id="call-1",
                name="check",
                arguments='{"value":"first"}',
                origin="completion",
            ),
            llm_response_id="response-1",
            anthropic_compaction_blocks=[block],
        ),
        ActionEvent(
            thought=[],
            action=_CompactionAction(value="second"),
            tool_name="check",
            tool_call_id="call-2",
            tool_call=MessageToolCall(
                id="call-2",
                name="check",
                arguments='{"value":"second"}',
                origin="completion",
            ),
            llm_response_id="response-1",
        ),
    ]

    [message] = LLMConvertibleEvent.events_to_messages(actions)

    assert message.anthropic_compaction_blocks == [block]
    assert [call.id for call in message.tool_calls or []] == ["call-1", "call-2"]


def test_conversation_restart_recovers_compaction_block(tmp_path) -> None:
    llm = LLM(
        model="anthropic/claude-opus-4-6",
        anthropic_compact_threshold=150_000,
    )
    conversation = Conversation(
        agent=Agent(llm=llm, tools=[]),
        persistence_dir=tmp_path,
        workspace=tmp_path,
        delete_on_close=False,
    )
    conversation.state.append_event(
        MessageEvent(
            source="agent",
            llm_message=Message(
                role="assistant",
                content=[TextContent(text="compacted turn")],
                anthropic_compaction_blocks=[
                    AnthropicCompactionBlock(content="Durable provider summary")
                ],
            ),
            llm_response_id="response-1",
        )
    )
    conversation_id = conversation.id

    resumed = Conversation(
        agent=Agent(llm=llm.model_copy(), tools=[]),
        persistence_dir=tmp_path,
        workspace=tmp_path,
        conversation_id=conversation_id,
        delete_on_close=False,
    )

    restored_event = resumed.state.active_branch()[-1]
    assert isinstance(restored_event, MessageEvent)
    assert restored_event.llm_message.anthropic_compaction_blocks == [
        AnthropicCompactionBlock(content="Durable provider summary")
    ]


def test_provider_compaction_sends_system_prompt_and_latest_compacted_tail() -> None:
    events = [
        SystemPromptEvent(
            system_prompt=TextContent(text="stable system"),
            tools=[],
        ),
        MessageEvent(
            source="user",
            llm_message=Message(
                role="user",
                content=[TextContent(text="old user input")],
            ),
        ),
        MessageEvent(
            source="agent",
            llm_message=Message(
                role="assistant",
                content=[TextContent(text="compacted turn")],
                anthropic_compaction_blocks=[
                    AnthropicCompactionBlock(content="Durable provider summary")
                ],
            ),
        ),
        MessageEvent(
            source="user",
            llm_message=Message(
                role="user",
                content=[TextContent(text="new user input")],
            ),
        ),
    ]
    llm = LLM(
        model="anthropic/claude-opus-4-6",
        anthropic_compact_threshold=150_000,
    )

    messages = prepare_llm_messages(View(events=events), llm=llm)

    assert isinstance(messages, list)
    assert _message_texts(messages) == [
        "stable system",
        "compacted turn",
        "new user input",
    ]
    assert messages[1].anthropic_compaction_blocks == [
        AnthropicCompactionBlock(content="Durable provider summary")
    ]


def test_provider_compaction_bypasses_openhands_condenser() -> None:
    events: list[LLMConvertibleEvent] = [
        MessageEvent(
            source="user",
            llm_message=Message(
                role="user",
                content=[TextContent(text="keep me")],
            ),
        )
    ]
    llm = LLM(
        model="anthropic/claude-opus-4-6",
        anthropic_compact_threshold=150_000,
    )
    condenser = Mock(spec=CondenserBase)

    messages = prepare_llm_messages(
        View(events=events),
        condenser=condenser,
        llm=llm,
    )

    assert isinstance(messages, list)
    assert _message_texts(messages) == ["keep me"]
    condenser.condense.assert_not_called()


async def test_provider_compaction_bypasses_async_openhands_condenser() -> None:
    events: list[LLMConvertibleEvent] = [
        MessageEvent(
            source="user",
            llm_message=Message(
                role="user",
                content=[TextContent(text="keep me")],
            ),
        )
    ]
    llm = LLM(
        model="anthropic/claude-opus-4-6",
        anthropic_compact_threshold=150_000,
    )
    condenser = Mock(spec=CondenserBase)

    messages = await aprepare_llm_messages(
        View(events=events),
        condenser=condenser,
        llm=llm,
    )

    assert isinstance(messages, list)
    assert _message_texts(messages) == ["keep me"]
    condenser.acondense.assert_not_called()


def test_compaction_only_response_is_preserved_as_reasoning_state() -> None:
    message = Message(
        role="assistant",
        anthropic_compaction_blocks=[
            AnthropicCompactionBlock(content="Durable provider summary")
        ],
    )

    assert classify_response(message) == LLMResponseType.REASONING_ONLY
