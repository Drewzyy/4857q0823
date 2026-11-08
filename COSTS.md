# Costs

## Today

Milestone 1 makes no paid API calls. All platform APIs used (YouTube Data API, TikTok Login Kit/Display/Content Posting, Meta Graph) are free within their quotas. Developer accounts are free.

## Plan for AI spend (Milestone 4+)

- **Local first.** Transcription via faster-whisper on the Mac (free). Audio fingerprints, scene detection and most matching are deterministic code, not AI.
- **Cheapest model that works**, per task, configurable in Settings: classification and metadata on the economy tier, titles/captions on economy or balanced, only multi-step reasoning on the best tier.
- **Never twice.** Every AI result is cached by content hash (transcripts, embeddings, analyses, titles). Same audio is never transcribed again.
- **Batching and structured output** to cut tokens.
- **Budget enforcement.** The monthly budget, warning threshold and hard stop in Settings are already stored. Every AI call will go through one metered client that writes an `ai_calls` ledger row (provider, model, tokens, cost, task, clip) and refuses calls past a hard stop. The cost dashboard (per clip, per published video, per month) reads that ledger.
- **Privacy default.** Footage is not sent to cloud AI unless you turn that on.

## Development cost notes

Decisions are recorded in ARCHITECTURE.md and ROADMAP.md so future sessions don't re-research them.
