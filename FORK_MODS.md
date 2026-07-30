# Fork modifications

This repository is a focused fork of
[`OpenHands/software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk)
used by Senpai. This file is the inventory of intentional fork behavior. Update
it in the same commit whenever the fork diverges further or an upstream sync
removes a local change.

## Comparison baseline

- Upstream repository: `https://github.com/OpenHands/software-agent-sdk.git`
- Last incorporated upstream commit:
  [`bf57d16f`](https://github.com/OpenHands/software-agent-sdk/commit/bf57d16f)
  (`v1.39.1`)
- Fork repository:
  [`morganmcg1/software-agent-sdk`](https://github.com/morganmcg1/software-agent-sdk)
- Fork commit before this documentation:
  [`2fccbe83`](https://github.com/morganmcg1/software-agent-sdk/commit/2fccbe83a19332b4ce1dba8bd18fc505dabac053)
- SDK and test divergence at that commit, excluding this documentation:
  18 files changed, 526 insertions, and 46 deletions.

All intentional runtime changes are confined to `openhands-sdk`; this fork does
not change `openhands-tools` behavior.

Reproduce the comparison locally:

```bash
git fetch upstream
git log --left-right --cherry-pick --oneline upstream/main...main
git diff --stat upstream/main...main
git diff upstream/main...main
```

## Intentional changes

### 1. Configurable Anthropic prompt-cache TTL

Commit:
[`856dd7ac`](https://github.com/morganmcg1/software-agent-sdk/commit/856dd7ac)

Purpose: allow callers to select Anthropic's one-hour cache lifetime while
preserving the upstream five-minute wire format by default.

Implementation:

- [`openhands-sdk/openhands/sdk/llm/llm.py`](openhands-sdk/openhands/sdk/llm/llm.py)
  - `LLM.prompt_cache_ttl` exposes the opt-in `"5m" | "1h"` setting.
  - `LLM.format_messages_for_llm()` passes the TTL only while prompt caching
    is active.
- [`openhands-sdk/openhands/sdk/llm/message.py`](openhands-sdk/openhands/sdk/llm/message.py)
  - `PromptCacheTTL` defines the accepted values.
  - `_prompt_cache_control()` keeps `"5m"` byte-compatible with upstream and
    adds `ttl: "1h"` only for the extended lifetime.
  - `BaseContent.to_llm_dict()`, `TextContent.to_llm_dict()`,
    `ImageContent.to_llm_dict()`, `Message.to_chat_dict()`, and
    `Message._list_serializer()` propagate the selected TTL to every explicit
    cache breakpoint, including tool-role caching.

Tests:

- [`tests/sdk/llm/test_prompt_cache_ttl.py`](tests/sdk/llm/test_prompt_cache_ttl.py)
  covers the default wire form, one-hour text/image/tool cache controls,
  disabled caching, and unsupported values.

### 2. Responses-aware LLM condenser

Commit:
[`29e8d30c`](https://github.com/morganmcg1/software-agent-sdk/commit/29e8d30c)

Purpose: make an `LLMSummarizingCondenser` configured with a Responses-mode LLM
use that same API instead of silently falling back to Chat Completions.
Condenser requests remain stateless.

Implementation:

- [`openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py`](openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py)
  - `LLMSummarizingCondenser._complete_summary()` selects
    `LLM.responses(..., store=False)` or `LLM.completion()`.
  - `LLMSummarizingCondenser._acomplete_summary()` provides the equivalent
    asynchronous behavior.
  - `_generate_condensation()` and `_agenerate_condensation()` use those
    common selection points.

Tests:

- [`tests/sdk/context/condenser/test_llm_summarizing_condenser.py`](tests/sdk/context/condenser/test_llm_summarizing_condenser.py)
  verifies synchronous and asynchronous Responses dispatch and stateless
  summary calls.

### 3. Durable stored Responses continuation

Commit:
[`91620be1`](https://github.com/morganmcg1/software-agent-sdk/commit/91620be1)

Purpose: continue an OpenAI Responses chain through `previous_response_id`,
including across OpenHands process restarts, so supported models can reuse
private reasoning and provider-managed compaction.

This feature is opt-in. Upstream-compatible defaults remain
`responses_store=False` and `responses_use_previous_response_id=False`.

#### Configuration and request construction

- [`openhands-sdk/openhands/sdk/llm/llm.py`](openhands-sdk/openhands/sdk/llm/llm.py)
  - `LLMCallContext.previous_response_id` carries conversation-scoped
    continuation state.
  - `LLM.reasoning_context` exposes OpenAI's `"current_turn" | "all_turns"`
    policy.
  - `LLM.responses_store` controls provider response storage.
  - `LLM.responses_use_previous_response_id` enables stored-chain
    continuation.
  - `LLM.responses_compact_threshold` enables provider-side compaction.
  - `LLM._coerce_inputs()` rejects continuation without response storage.
- [`openhands-sdk/openhands/sdk/llm/options/common.py`](openhands-sdk/openhands/sdk/llm/options/common.py)
  - `apply_call_context()` adds the durable `previous_response_id` to a
    Responses request when continuation is enabled.
- [`openhands-sdk/openhands/sdk/llm/options/responses_options.py`](openhands-sdk/openhands/sdk/llm/options/responses_options.py)
  - `select_responses_options()` applies `responses_store`,
    `reasoning.context`, and the `context_management` compaction threshold.

#### Durable recovery and bounded replay

- [`openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py`](openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)
  - `LocalConversation.get_llm_call_context()` scans the durable active event
    view for the latest `resp_*` ID. Reconstructing the same conversation
    therefore resumes the same provider chain after a process restart.
  - `LocalConversation.ask_agent()` explicitly resets stored continuation and
    compaction because this helper is a stateless side query.
- [`openhands-sdk/openhands/sdk/agent/utils.py`](openhands-sdk/openhands/sdk/agent/utils.py)
  - `_responses_continuation_events()` retains system instructions and only
    events created after the response-ID boundary.
  - `prepare_llm_messages()` and `aprepare_llm_messages()` use that bounded
    view and bypass local condensation for a stored provider chain.
  - `make_llm_completion()` and `amake_llm_completion()` defer the Responses
    `store` choice to the configured LLM instead of forcing `False`.

#### Condenser boundary and event fidelity

- [`openhands-sdk/openhands/sdk/agent/agent.py`](openhands-sdk/openhands/sdk/agent/agent.py)
  - Synchronous and asynchronous `Agent.step()` paths pass `LLMCallContext`
    into message preparation.
  - `Agent._can_use_local_condenser()` prevents OpenHands condensation from
    competing with provider-managed stored Responses compaction.
  - Context-window diagnostics explain the provider-compaction recovery path.
- [`openhands-sdk/openhands/sdk/event/base.py`](openhands-sdk/openhands/sdk/event/base.py)
  - `_combine_action_events()` preserves `responses_reasoning_item` when one
    OpenAI response produces multiple tool actions.

Tests:

- [`tests/sdk/agent/test_agent_context_window_condensation.py`](tests/sdk/agent/test_agent_context_window_condensation.py)
  covers provider-compaction behavior under context pressure.
- [`tests/sdk/agent/test_agent_step_responses_gating.py`](tests/sdk/agent/test_agent_step_responses_gating.py)
  covers stored-chain dispatch and local-condenser gating.
- [`tests/sdk/agent/test_agent_utils.py`](tests/sdk/agent/test_agent_utils.py)
  covers response-boundary input selection.
- [`tests/sdk/conversation/local/test_call_context_isolation.py`](tests/sdk/conversation/local/test_call_context_isolation.py)
  covers durable response-ID recovery without cross-conversation leakage.
- [`tests/sdk/llm/test_responses_parsing_and_kwargs.py`](tests/sdk/llm/test_responses_parsing_and_kwargs.py)
  covers request parameters and reasoning-item preservation.

### 4. GPT-5.6 prompt-cache compatibility

Commit:
[`2fccbe83`](https://github.com/morganmcg1/software-agent-sdk/commit/2fccbe83a19332b4ce1dba8bd18fc505dabac053)

Purpose: prevent the deprecated `prompt_cache_retention` field from being sent
to GPT-5.6. Consuming applications can pass the current
`prompt_cache_options.ttl` field through LiteLLM's existing extra-body support.

Implementation:

- [`openhands-sdk/openhands/sdk/llm/utils/model_features.py`](openhands-sdk/openhands/sdk/llm/utils/model_features.py)
  - `PROMPT_CACHE_RETENTION_MODELS` explicitly excludes `gpt-5.6` and its
    variants while retaining the broader GPT-5 match for older models.

Tests:

- [`tests/sdk/llm/test_model_features.py`](tests/sdk/llm/test_model_features.py)
  verifies that GPT-5.6 does not advertise deprecated retention support.

## Maintenance rules

1. Add or update an entry here in the same commit as every fork-only behavior.
2. Include the motivation, opt-in/default behavior, implementation symbols,
   affected paths, and tests.
3. After incorporating upstream, update the baseline commit and regenerate the
   divergence numbers.
4. Remove an entry when the equivalent upstream implementation is incorporated.
5. Prefer upstreaming generally useful changes; keep Senpai policy and defaults
   in Senpai rather than embedding them in this SDK.
6. Before publishing a fork update, run the focused tests named above plus the
   repository's formatting, lint, type, and import checks.

There are no other intentional runtime differences from the stated upstream
baseline. The merge commit that incorporated `v1.39.1` contains no additional
fork behavior.
