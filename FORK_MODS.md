# Fork modifications

This repository is a focused fork of
[`OpenHands/software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk)
used by Senpai. This is the authoritative ledger of intentional divergence.
Entries are newest first. Update the relevant entry whenever a fork behavior
changes, and remove it when upstream incorporates the equivalent behavior.

## Comparison baseline

- Upstream repository: `https://github.com/OpenHands/software-agent-sdk.git`
- Last incorporated upstream commit:
  [`bf57d16f`](https://github.com/OpenHands/software-agent-sdk/commit/bf57d16f)
  (`v1.39.1`)
- Fork repository:
  [`morganmcg1/software-agent-sdk`](https://github.com/morganmcg1/software-agent-sdk)
- Runtime commit described below:
  [`d093d0cc`](https://github.com/morganmcg1/software-agent-sdk/commit/d093d0cc7dc710c3f45624a677d6112abb899814)
- Repository divergence at that commit: 38 files changed, 1,846 insertions,
  and 80 deletions.

All runtime changes are confined to `openhands-sdk`; this fork does not change
`openhands-tools` behavior.

Reproduce the comparison locally:

```bash
git fetch upstream
git log --left-right --cherry-pick --oneline upstream/main...main
git diff --stat upstream/main...main
git diff upstream/main...main
```

## Intentional changes

### Provider-compatible discriminated tool schemas — 2026-07-31 11:29:52 +01:00 — [`d093d0cc`](https://github.com/morganmcg1/software-agent-sdk/commit/d093d0cc7dc710c3f45624a677d6112abb899814), [`479e4cf0`](https://github.com/morganmcg1/software-agent-sdk/commit/479e4cf0d4055a0713c43842acb99c4541826e60)

Purpose: expose every field and discriminator value from a Pydantic object
union in a form that both Anthropic and OpenAI models can populate. Upstream's
MCP simplifier discarded `oneOf`, reducing a field such as Senpai's
`github_transition.transition` to an untyped object. The first fork revision
retained `oneOf`, but a direct Anthropic tool-use smoke test showed that Claude
serialized the nested object as a JSON string whenever `oneOf` remained.

Implementation:

- [`openhands-sdk/openhands/sdk/tool/schema.py`](openhands-sdk/openhands/sdk/tool/schema.py)
  - `_process_schema_node()` recursively resolves every object-union branch,
    then presents the LLM with one ordinary object containing the union of its
    properties.
  - Pydantic `const` values become single-value enums; discriminator enums are
    combined deterministically.
  - A field is marked required only when every branch requires it. Compatible
    types and constraints are retained; incompatible types are left
    unconstrained instead of publishing a false contract.
  - The original Pydantic action remains authoritative after generation, so
    branch-specific required fields and extra-field rejection are unchanged.

Tests:

- [`tests/sdk/tool/test_mcp_schema.py`](tests/sdk/tool/test_mcp_schema.py)
  proves that fields, merged discriminator values, shared required fields,
  descriptions, and resolved references survive `Action.to_mcp_schema()`, and
  that runtime union validation remains strict.
- Live direct-provider smoke tests used Senpai's complete eight-operation
  `github_transition` schema. Anthropic Claude Haiku 4.5 and OpenAI Responses
  GPT-5.4 both returned the requested nested `push_branch` object with the
  correct types. These calls bypassed LiteLLM for provider isolation.

### File-agent reasoning effort — 2026-07-30 17:03:40 +01:00 — [`afe77a78`](https://github.com/morganmcg1/software-agent-sdk/commit/afe77a787ffb6d14e8db60d1c6b72b5dcebbe90e)

Purpose: let a Markdown agent definition select its own reasoning effort
without requiring a programmatic factory or a complete stored LLM profile.

Implementation:

- [`openhands-sdk/openhands/sdk/subagent/schema.py`](openhands-sdk/openhands/sdk/subagent/schema.py)
  - `AgentDefinition.reasoning_effort` is a typed optional field.
  - `reasoning_effort: inherit` and an omitted value preserve the parent LLM
    setting.
  - Any other provider-supported string is retained as the agent override.
- [`openhands-sdk/openhands/sdk/subagent/registry.py`](openhands-sdk/openhands/sdk/subagent/registry.py)
  - `agent_definition_to_factory()` applies the override after resolving the
    agent's inherited LLM or stored model profile.

Tests:

- [`tests/sdk/subagent/test_subagent_schema.py`](tests/sdk/subagent/test_subagent_schema.py)
  covers explicit and inherited frontmatter values.
- [`tests/sdk/subagent/test_subagent_registry.py`](tests/sdk/subagent/test_subagent_registry.py)
  proves that the factory copies the parent LLM and applies the child effort.

### Durable Anthropic server-side compaction — 2026-07-30 14:01:19 +01:00 — [`afb3639c`](https://github.com/morganmcg1/software-agent-sdk/commit/afb3639c0e7846f25e33b10302b02611fcd72a3f)

Purpose: use Anthropic's model-native compaction without losing its opaque
continuation block during tool calls, process restarts, or OpenHands event
reconstruction.

Anthropic does not expose an OpenAI-style `previous_response_id`. Its Messages
API remains stateless: after compaction, the caller must replay the returned
`compaction` content block in later requests. This fork therefore enables
compaction only after making that block first-class durable OpenHands state.

Configuration and request construction:

- [`openhands-sdk/openhands/sdk/llm/llm.py`](openhands-sdk/openhands/sdk/llm/llm.py)
  - `LLM.anthropic_compact_threshold` enables native compaction with Anthropic's
    documented 50,000-token minimum.
  - `LLM.anthropic_compaction_instructions` defaults to a compact continuation
    charter that preserves decisions and explicitly forbids tool calls while
    summarizing. Anthropic documents that a tool call during compaction can
    return an unusable block with no content.
  - `LLM.uses_anthropic_compaction()` is the single provider gate used by the
    request and agent paths.
- [`openhands-sdk/openhands/sdk/llm/options/chat_options.py`](openhands-sdk/openhands/sdk/llm/options/chat_options.py)
  - `select_chat_options()` sends
    `context_management.edits[].type="compact_20260112"` with an input-token
    trigger and optional instructions.
  - An explicit caller-supplied `context_management` value wins.
  - LiteLLM adds the required `compact-2026-01-12` beta header.

Typed capture, persistence, and exact replay:

- [`openhands-sdk/openhands/sdk/llm/message.py`](openhands-sdk/openhands/sdk/llm/message.py)
  - `AnthropicCompactionBlock` models the provider's opaque `type` and
    `content`.
  - `Message.from_llm_chat_message()` captures LiteLLM's
    `provider_specific_fields.compaction_blocks`.
  - `Message.to_chat_dict()` restores those provider fields. LiteLLM then puts
    the compaction block first in the Anthropic assistant content array, as the
    API requires.
  - An empty block fails loudly instead of silently discarding continuation
    state.
- [`openhands-sdk/openhands/sdk/event/llm_convertible/action.py`](openhands-sdk/openhands/sdk/event/llm_convertible/action.py),
  [`openhands-sdk/openhands/sdk/event/base.py`](openhands-sdk/openhands/sdk/event/base.py),
  [`openhands-sdk/openhands/sdk/agent/response_dispatch.py`](openhands-sdk/openhands/sdk/agent/response_dispatch.py),
  and
  [`openhands-sdk/openhands/sdk/agent/agent.py`](openhands-sdk/openhands/sdk/agent/agent.py)
  - Preserve the block through message events, tool actions, tool validation
    errors, parallel tool-call reconstruction, and JSON event serialization.
  - A compaction-only response is retained as provider reasoning state rather
    than classified as empty.

Context ownership and data retention:

- [`openhands-sdk/openhands/sdk/agent/utils.py`](openhands-sdk/openhands/sdk/agent/utils.py)
  - Before the first provider block, Anthropic receives the normal complete
    OpenHands view.
  - After compaction, only system instructions, the assistant event containing
    the latest block, and subsequent events are sent. Anthropic documents that
    content before the block is ignored.
  - This is an outbound view reduction only. The complete file-backed
    OpenHands event log remains untouched for restart recovery, observability,
    debugging, and user-directed search.
- [`openhands-sdk/openhands/sdk/agent/agent.py`](openhands-sdk/openhands/sdk/agent/agent.py)
  - Disables the local OpenHands condenser while native Anthropic compaction is
    active, preventing two independent summaries from competing.

Tests:

- [`tests/sdk/llm/test_anthropic_compaction.py`](tests/sdk/llm/test_anthropic_compaction.py)
  covers request options, caller precedence, the actual LiteLLM Anthropic wire
  transformation and beta header, response parsing, empty-block failure,
  JSON and full-conversation restart recovery, parallel tool calls, outbound
  tail selection, synchronous and asynchronous condenser gating, and
  compaction-only response classification.
- [`tests/sdk/agent/test_response_dispatch.py`](tests/sdk/agent/test_response_dispatch.py)
  proves that a real agent tool-action dispatch preserves the block.

Reference:
[Anthropic context compaction](https://platform.claude.com/docs/en/build-with-claude/compaction).

### Optional Laminar observability dependency — 2026-07-30 13:29:29 +01:00 — [`527771ce`](https://github.com/morganmcg1/software-agent-sdk/commit/527771ce74d68e2e031649cbb4eb9ebde6b5cf69)

Purpose: keep the base SDK install provider-neutral and avoid installing a
second telemetry stack in applications, such as Senpai, that use another
observability integration.

Implementation:

- [`openhands-sdk/pyproject.toml`](openhands-sdk/pyproject.toml)
  - `lmnr` moved from required dependencies to the `laminar` optional extra.
  - Existing Laminar behavior remains available with
    `openhands-sdk[laminar]`.
  - No runtime fallback was added. The existing lazy imports mean an
    application that does not enable Laminar does not import it; an
    application that enables Laminar must install the extra.
- [`uv.lock`](uv.lock)
  - Records Laminar as an optional SDK dependency instead of a base
    requirement.

Tests:

- The existing 36 Laminar observability tests pass with the optional extra
  present.
- Package metadata was checked to ensure `lmnr` is absent from base
  dependencies and present under the `laminar` extra.

### Explicit Responses stable-prefix cache breakpoint — updated 2026-07-30 13:18:15 +01:00 — [`aac9673f`](https://github.com/morganmcg1/software-agent-sdk/commit/aac9673f49a5a9e21e494b127df5bca923e7d8d7), [`da7d76fe`](https://github.com/morganmcg1/software-agent-sdk/commit/da7d76fe3d0b0f5b169ff47c5617a8ecf38a004c)

Purpose: expose OpenAI's explicit Responses cache boundary without rewriting a
serialized request outside the SDK. This is opt-in; upstream-compatible
serialization remains the default.

Implementation:

- [`openhands-sdk/openhands/sdk/llm/llm.py`](openhands-sdk/openhands/sdk/llm/llm.py)
  - `LLM.responses_prompt_cache_breakpoint` enables the feature.
  - `LLM._build_responses_payload()` serializes system content as Responses
    input items and marks only the first non-empty text block with
    `prompt_cache_breakpoint={"mode": "explicit"}`.
  - Later system blocks, including dynamic project context, remain unmarked.
  - Subscription transport is unchanged.
- [`openhands-sdk/openhands/sdk/llm/utils/responses_serialization.py`](openhands-sdk/openhands/sdk/llm/utils/responses_serialization.py)
  - `system_message_to_responses_item()` owns the typed wire representation.

The consuming application must also send
`prompt_cache_options.mode="explicit"` and a supported TTL. Senpai uses a
30-minute TTL and a stable `prompt_cache_key` per role and agent kind. OpenAI
still requires an exact prefix match; the key is a routing hint, not a way to
reuse incompatible prompts.

Tests:

- [`tests/sdk/llm/test_responses_serialization.py`](tests/sdk/llm/test_responses_serialization.py)
  proves that the stable block is marked, dynamic content is not marked, only
  one breakpoint is emitted, and the default and subscription paths are
  unchanged.

### GPT-5.6 prompt-cache compatibility — 2026-07-30 10:34:37 +01:00 — [`2fccbe83`](https://github.com/morganmcg1/software-agent-sdk/commit/2fccbe83a19332b4ce1dba8bd18fc505dabac053)

Purpose: prevent the deprecated `prompt_cache_retention` field from being sent
to GPT-5.6. Applications can pass the current `prompt_cache_options` object
through LiteLLM's existing extra-body support.

Implementation:

- [`openhands-sdk/openhands/sdk/llm/utils/model_features.py`](openhands-sdk/openhands/sdk/llm/utils/model_features.py)
  - `PROMPT_CACHE_RETENTION_MODELS` explicitly excludes `gpt-5.6` and its
    variants while retaining the broader GPT-5 match for older models.

Tests:

- [`tests/sdk/llm/test_model_features.py`](tests/sdk/llm/test_model_features.py)
  verifies that GPT-5.6 does not advertise deprecated retention support.

### Durable stored OpenAI Responses continuation — 2026-07-30 10:23:48 +01:00 — [`91620be1`](https://github.com/morganmcg1/software-agent-sdk/commit/91620be1)

Purpose: continue an OpenAI Responses chain through `previous_response_id`,
including after an OpenHands process restart, so supported models can reuse
private reasoning and provider-managed compaction.

This is opt-in. Defaults remain `responses_store=False` and
`responses_use_previous_response_id=False`.

Configuration and request construction:

- [`openhands-sdk/openhands/sdk/llm/llm.py`](openhands-sdk/openhands/sdk/llm/llm.py)
  - `LLMCallContext.previous_response_id` carries conversation-scoped state.
  - `LLM.reasoning_context` exposes `"current_turn" | "all_turns"`.
  - `LLM.responses_store` controls provider storage.
  - `LLM.responses_use_previous_response_id` enables continuation.
  - `LLM.responses_compact_threshold` enables provider-side compaction.
  - `LLM._coerce_inputs()` rejects continuation without response storage.
- [`openhands-sdk/openhands/sdk/llm/options/common.py`](openhands-sdk/openhands/sdk/llm/options/common.py)
  - `apply_call_context()` adds `previous_response_id` to the next request.
- [`openhands-sdk/openhands/sdk/llm/options/responses_options.py`](openhands-sdk/openhands/sdk/llm/options/responses_options.py)
  - `select_responses_options()` applies `store`, reasoning context, and the
    provider compaction threshold.

Durable recovery and bounded client input:

- [`openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py`](openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)
  - `LocalConversation.get_llm_call_context()` recovers the latest `resp_*`
    ID from the durable active event view. Reconstructing the same conversation
    resumes the same provider chain.
  - `LocalConversation.ask_agent()` disables storage, continuation, and
    compaction because it is an independent one-shot side query.
- [`openhands-sdk/openhands/sdk/agent/utils.py`](openhands-sdk/openhands/sdk/agent/utils.py)
  - `_responses_continuation_events()` retains system instructions and sends
    only events created after the response-ID boundary.
  - `prepare_llm_messages()` and `aprepare_llm_messages()` bypass local
    condensation for a stored provider chain.
  - `make_llm_completion()` and `amake_llm_completion()` defer `store` to the
    configured LLM instead of forcing `False`.
- [`openhands-sdk/openhands/sdk/agent/agent.py`](openhands-sdk/openhands/sdk/agent/agent.py)
  - Synchronous and asynchronous steps pass `LLMCallContext` into message
    preparation.
  - `Agent._can_use_local_condenser()` prevents local condensation from
    competing with the stored provider chain.
- [`openhands-sdk/openhands/sdk/event/base.py`](openhands-sdk/openhands/sdk/event/base.py)
  - `_combine_action_events()` preserves the Responses reasoning item when one
    response produces multiple tool actions.

#### Storage, compaction, and data-retention contract

Senpai's main OpenAI agent path uses `store=True`. OpenAI retains each response
object so the next call can name it with `previous_response_id`; OpenHands
persists that ID in its own event log and restores it after a process restart.
OpenAI documents a default 30-day retention period for stored response objects.
All earlier input tokens in the chain remain billable even though OpenHands
sends only the new delta.

`store=False` means OpenAI does not retain the response object. Stateless
callers must request encrypted reasoning content and replay the necessary input
and output items themselves. This fork uses that mode only for independent
condenser and `ask_agent()` calls; they must not mutate the main response chain.

When `previous_response_id` continuation and provider compaction are active,
OpenHands does **not** feed its locally condensed history to the main model.
OpenAI explicitly recommends against manually pruning a chained Responses
history. The provider's opaque compaction item carries forward relevant state
and reasoning in the representation the model expects. See
[OpenAI Responses compaction](https://developers.openai.com/api/docs/guides/compaction).

This does not delete local data. OpenHands retains the complete file-backed
event log for restart recovery, UI, observability, and debugging. The
`_responses_continuation_events()` reduction only controls the client delta
sent beside `previous_response_id`; it is not manual pruning of the provider's
active chain.

Tests:

- [`tests/sdk/agent/test_agent_context_window_condensation.py`](tests/sdk/agent/test_agent_context_window_condensation.py)
  covers provider compaction under context pressure.
- [`tests/sdk/agent/test_agent_step_responses_gating.py`](tests/sdk/agent/test_agent_step_responses_gating.py)
  proves that the second step receives the first `resp_*` ID and that local
  condensation is gated.
- [`tests/sdk/agent/test_agent_utils.py`](tests/sdk/agent/test_agent_utils.py)
  covers response-boundary input selection.
- [`tests/sdk/conversation/local/test_call_context_isolation.py`](tests/sdk/conversation/local/test_call_context_isolation.py)
  covers durable response-ID recovery without cross-conversation leakage.
- [`tests/sdk/llm/test_responses_parsing_and_kwargs.py`](tests/sdk/llm/test_responses_parsing_and_kwargs.py)
  covers request parameters and reasoning-item preservation.

### Responses-aware LLM condenser — 2026-07-30 09:52:00 +01:00 — [`29e8d30c`](https://github.com/morganmcg1/software-agent-sdk/commit/29e8d30c)

Purpose: make an `LLMSummarizingCondenser` configured with a Responses-mode LLM
use Responses rather than silently falling back to Chat Completions. Condenser
calls remain independent and stateless.

Implementation:

- [`openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py`](openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py)
  - `_complete_summary()` selects `LLM.responses(..., store=False)` or
    `LLM.completion()`.
  - `_acomplete_summary()` provides equivalent asynchronous behavior.
  - `_generate_condensation()` and `_agenerate_condensation()` share those
    selection points.

Tests:

- [`tests/sdk/context/condenser/test_llm_summarizing_condenser.py`](tests/sdk/context/condenser/test_llm_summarizing_condenser.py)
  verifies synchronous and asynchronous dispatch and `store=False`.

### Configurable Anthropic prompt-cache TTL — 2026-07-29 19:07:57 +01:00 — [`856dd7ac`](https://github.com/morganmcg1/software-agent-sdk/commit/856dd7ac)

Purpose: allow callers to select Anthropic's one-hour cache lifetime while
preserving the upstream five-minute wire representation by default.

Implementation:

- [`openhands-sdk/openhands/sdk/llm/llm.py`](openhands-sdk/openhands/sdk/llm/llm.py)
  - `LLM.prompt_cache_ttl` exposes `"5m" | "1h"`.
  - `LLM.format_messages_for_llm()` passes it only while caching is active.
- [`openhands-sdk/openhands/sdk/llm/message.py`](openhands-sdk/openhands/sdk/llm/message.py)
  - `PromptCacheTTL` defines accepted values.
  - `_prompt_cache_control()` preserves the upstream five-minute form and adds
    `ttl: "1h"` only for the extended lifetime.
  - Content and message serializers propagate the TTL to text, image, tool,
    and tool-role cache boundaries.

Tests:

- [`tests/sdk/llm/test_prompt_cache_ttl.py`](tests/sdk/llm/test_prompt_cache_ttl.py)
  covers default and one-hour text/image/tool controls, disabled caching, and
  unsupported values.


Primary provider references:

- [Anthropic adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking)
- [Anthropic extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
- [Anthropic server-side compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)

## Maintenance rules

1. Put each change under a header containing its name, timestamp, and commit
   ID; keep entries newest first.
2. Include motivation, opt-in/default behavior, implementation symbols,
   affected paths, provider contracts, and tests.
3. After incorporating upstream, update the baseline commit and regenerate the
   divergence numbers.
4. Remove an entry when the equivalent upstream implementation is incorporated.
5. Prefer upstreaming generally useful changes; keep Senpai policy in Senpai.
6. Before publishing, run the named focused tests plus formatting, lint, type,
   and import checks.

There are no other intentional runtime differences from the stated upstream
baseline. The merge commit that incorporated `v1.39.1` contains no additional
fork behavior.
