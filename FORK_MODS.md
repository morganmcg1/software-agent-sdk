# Fork modifications

This repository is a focused fork of
[OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk)
used by Senpai. This file lists only the major intentional differences from
upstream. Tests, documentation, CI changes, and mechanical follow-up commits
are not separate fork features.

Remove an entry when upstream provides the same behavioral contract.

## Baseline

- Upstream baseline:
  [v1.40.0](https://github.com/OpenHands/software-agent-sdk/tree/v1.40.0)
  ([2f276539](https://github.com/OpenHands/software-agent-sdk/commit/2f27653959f7596769427ee4657247b32c94504e))
- Fork branch:
  [morganmcg1/software-agent-sdk:main](https://github.com/morganmcg1/software-agent-sdk/tree/main)

Compare the fork against its incorporated upstream baseline:

~~~bash
git fetch https://github.com/OpenHands/software-agent-sdk.git tag v1.40.0
git log --oneline v1.40.0..main
git diff --stat v1.40.0..main
git diff v1.40.0..main -- openhands-sdk openhands-tools
~~~

## Major feature changes

### Provider-managed conversation continuity and compaction

The fork supports durable, opt-in provider-native context chains while keeping
the complete local OpenHands event log.

- **OpenAI Responses:** <code>responses_store</code>,
  <code>responses_use_previous_response_id</code>,
  <code>reasoning_context</code>, and
  <code>responses_compact_threshold</code> enable stored response continuation
  and provider compaction. The latest response ID is recovered after process
  restart. Continued calls send current system instructions and only input
  created after the stored response boundary.
- **Anthropic Messages:** <code>anthropic_compact_threshold</code> enables
  native compaction. The provider's opaque compaction block survives tool
  actions, parallel calls, serialization, and process restarts, then is
  replayed exactly on later requests.
- The local OpenHands condenser is disabled while either provider-managed
  chain is active, preventing competing summaries. An independently configured
  Responses-mode summarizing condenser still uses Responses with
  <code>store=False</code>.

Source commits:
[29e8d30c](https://github.com/morganmcg1/software-agent-sdk/commit/29e8d30c),
[91620be1](https://github.com/morganmcg1/software-agent-sdk/commit/91620be1),
[afb3639c](https://github.com/morganmcg1/software-agent-sdk/commit/afb3639c).

### Token-aware local condensation

The local LLM summarizing condenser can combine its existing token trigger
with an explicit post-condensation event budget.

- **Bounded post-condensation history:** <code>target_size</code> caps the number
  of retained events after any condensation trigger. Leaving it unset
  preserves the existing trigger-specific targets.
- **Tokenizer readiness:** <code>LLM.has_chat_template_tokenizer()</code> lets
  callers verify that exact chat-template token counting is available before
  relying on a token threshold.
- **Matching template inputs:** Token counting applies configured
  <code>chat_template_kwargs</code>, so it renders the same template variant as
  the model request.

Source commit:
[33608f0b](https://github.com/morganmcg1/software-agent-sdk/commit/33608f0b8242ca0e1f6251efc8f535e249cd6101).

### Provider prompt-cache controls

- Anthropic prompt caching retains the upstream five-minute default and adds
  an optional one-hour lifetime through <code>prompt_cache_ttl</code>.
- OpenAI Responses can mark the first non-empty system-text block as an
  explicit cache boundary through
  <code>responses_prompt_cache_breakpoint</code>. Callers place stable context
  first and dynamic system context afterward. They must also provide
  <code>prompt_cache_options.mode="explicit"</code> and a supported TTL.
- GPT-5.6 is excluded from the deprecated
  <code>prompt_cache_retention</code> field so callers can supply
  <code>prompt_cache_options</code> through the existing extra-body path.

Source commits:
[856dd7ac](https://github.com/morganmcg1/software-agent-sdk/commit/856dd7ac),
[2fccbe83](https://github.com/morganmcg1/software-agent-sdk/commit/2fccbe83),
[aac9673f](https://github.com/morganmcg1/software-agent-sdk/commit/aac9673f),
[da7d76fe](https://github.com/morganmcg1/software-agent-sdk/commit/da7d76fe).

### Provider-compatible discriminated tool schemas

Pydantic object unions are presented to models as one flattened object
containing every branch property and discriminator value. Only fields required
by every branch are marked required in the model-facing schema. The original
Pydantic union remains authoritative, preserving branch-specific validation
and extra-field rejection.

Source commits:
[479e4cf0](https://github.com/morganmcg1/software-agent-sdk/commit/479e4cf0),
[d093d0cc](https://github.com/morganmcg1/software-agent-sdk/commit/d093d0cc).

### Markdown-agent reasoning effort

Agent frontmatter accepts an optional <code>reasoning_effort</code>. An omitted
value or <code>inherit</code> preserves the parent LLM setting; an explicit
value is applied after the inherited model or stored profile is resolved.

Source commit:
[afe77a78](https://github.com/morganmcg1/software-agent-sdk/commit/afe77a78).

### UTF-8-safe file editing

The file editor accepts a valid UTF-8 detection sample of up to 1 MiB before
consulting statistical charset detection, preventing untouched Unicode content
from being silently transcoded. Samples that are not valid UTF-8 still use
legacy-encoding detection.

Source commit:
[06e229d2](https://github.com/morganmcg1/software-agent-sdk/commit/06e229d2).

## Packaging difference

### Optional Laminar observability

Laminar is not installed with the base SDK. Existing Laminar observability
remains available through <code>openhands-sdk[laminar]</code>.

Source commit:
[527771ce](https://github.com/morganmcg1/software-agent-sdk/commit/527771ce).

## Maintenance

1. Record only major behavioral or packaging differences, not tests, docs, CI,
   refactors, or mechanical fixes.
2. Update the upstream baseline whenever a new upstream release is
   incorporated.
3. Remove a difference when upstream provides an equivalent contract.
4. Keep Senpai-specific policy in Senpai rather than in this SDK fork.

There are no other intentional runtime differences from the stated upstream
baseline.
