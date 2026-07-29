import pytest
from pydantic import ValidationError

from openhands.sdk import LLM
from openhands.sdk.llm.message import Message, TextContent
from openhands.sdk.llm.options.chat_options import select_chat_options


def test_default_explicit_cache_control_preserves_existing_wire_format():
    content = TextContent(text="stable prefix", cache_prompt=True)

    assert content.to_llm_dict() == [
        {
            "type": "text",
            "text": "stable prefix",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_one_hour_ttl_is_sent_on_explicit_anthropic_cache_breakpoints():
    llm = LLM(
        model="anthropic/claude-sonnet-4-5",
        prompt_cache_ttl="1h",
    )
    messages = [
        Message(
            role="system",
            content=[TextContent(text="stable prefix", cache_prompt=True)],
        )
    ]

    formatted = llm.format_messages_for_llm(messages)

    assert formatted[0]["content"][0]["cache_control"] == {
        "type": "ephemeral",
        "ttl": "1h",
    }


def test_one_hour_ttl_applies_to_tool_message_cache_control():
    message = Message(
        role="tool",
        content=[TextContent(text="tool result", cache_prompt=True)],
        tool_call_id="call-1",
        name="lookup",
    )

    formatted = message.to_chat_dict(
        cache_enabled=True,
        vision_enabled=False,
        function_calling_enabled=True,
        force_string_serializer=False,
        send_reasoning_content=False,
        prompt_cache_ttl="1h",
    )

    assert formatted["cache_control"] == {
        "type": "ephemeral",
        "ttl": "1h",
    }


def test_openai_retention_remains_provider_native_without_cache_markers():
    llm = LLM(
        model="openai/gpt-5.2",
        prompt_cache_ttl="1h",
        prompt_cache_retention="24h",
    )
    formatted = llm.format_messages_for_llm(
        [
            Message(
                role="system",
                content=[TextContent(text="stable prefix", cache_prompt=True)],
            )
        ]
    )

    assert all(
        block.get("cache_control") in (None, {"type": "ephemeral"})
        for block in formatted[0]["content"]
    )
    assert (
        select_chat_options(llm, {}, has_tools=False)["prompt_cache_retention"] == "24h"
    )


def test_prompt_cache_ttl_rejects_unsupported_values():
    with pytest.raises(ValidationError):
        LLM.model_validate(
            {
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache_ttl": "2h",
            }
        )
