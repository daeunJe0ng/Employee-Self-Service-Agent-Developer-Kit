# ESS Diagnostics Skill (v4) — Interactive Walkthrough + Real-Schema Parse Map — Design

## Purpose

Fix two problems found when dry-running the v3 skill against a real transcript
(`Transcript_a9b8b841-...txt`):

1. **The skill was not interactive.** It ran the whole diagnosis in one shot:
   it never stopped to ask the FDE for the specific problem, and it never paused
   turn-by-turn for FDE input. The v3 rules *said* to do both, but they were soft
   guidance ("ask if missing", "pause") with no hard stop, so the model flowed
   straight through.
2. **The parse map did not match real data.** Real Copilot Studio / PVA exports
   carry diagnostic events as `Trace` events discriminated by `p.data.kind`, use
   `SynchronousIncomingActivity` for user turns, and expose grounding/rewrite via
   `AnalyticsAiMetricsSignalTraceData` / `KnowledgeTraceData`. The v3 map's
   `IncomingActivity` / `search_results[]`-with-`Name`/`Text` shape does not exist
   in the observed transcript.

This is a v4 revision of `tools/ESS-Diagnostics-Skills/SKILL.md`. Scope: both the
interaction model AND the parse-map reconciliation.

## 1. Problem-statement hard gate (new Step 0)

Add **Step 0: Establish the Problem**, run before any parsing:

- On invocation the skill STOPS, confirms the transcript **file path**, and
  explicitly asks: **"What specific problem are you investigating in this
  transcript?"**
- It may NOT read/parse the transcript until the FDE answers.
- If a problem statement was supplied in the invocation args, the skill echoes it
  back and asks the FDE to confirm or refine it — never silently accepts it.
- Rules bullet changes from "ask if missing" to a firm hard stop: "Do not proceed
  past Step 0 until the FDE has stated the problem and you have confirmed the file
  path — even if a problem was supplied in the invocation."

## 2. Interactive per-turn walkthrough with structured pause

Step 2 becomes a real interactive loop with a hard stop after each turn.

At each turn's pause, the skill presents a **structured summary** (explicit, not
just verdicts):

- **Intent** — recognized intent (id/message) or the failure signal.
- **Search query** — original user prompt + issued/rewritten query & keywords.
- **Search response** — result count / cited sources, and what the bot answered.
- A one-line **verdict strip**: `001 Pass · 002 Pass · 003 Pass · 004 Pass · 005 Pass`.

Then a **section menu**:

```
Drill into a section, or advance:
  1. Intent          2. Search query     3. Search results
  4. Grounding       5. Final answer
  [continue] next turn   [run all] finish without pausing   [override] a verdict
```

- **Hard stop:** the skill WAITS here; it may not look at the next turn until the
  FDE responds. Default is per-turn stops.
- **Escape hatch:** at the first pause the FDE may type `run all` to switch to a
  batch pass (auto-advance through remaining turns, still producing the full
  report).
- **Drill-down (sections 1–5):** show the full raw transcript evidence for that
  section (complete query/keywords, full result list, full intent object, full
  answer text) PLUS the check's reasoning (why Pass/Fail/N/A), and explicitly
  invite the FDE to **override** the verdict with their domain knowledge.
- **Override:** recorded (check, original verdict → override, FDE reason) and
  carried into the final report.

## 3. Parse-map reconciliation (real schema)

Rewrite Step 1's parse map to the observed real export. Ordering by array
position is unchanged (that rule was correct). Structural change: most diagnostic
events are `Trace` events keyed by `p.data.kind`.

| Concept | Where it lives | Fields |
|---|---|---|
| User utterance | `t = SynchronousIncomingActivity`, `p.activity.type = "message"` | `p.activity.text` |
| Bot message | `t = OutgoingActivity`, `p.activity.type = "message"` | `p.activity.text` |
| Intent recognized | `t = Trace`, `p.data.kind = LlmIntentRecognized` | `intentId`, `intentMessage`, `userUtterance` |
| Search issued | `t = Trace`, `p.data.kind = PluginStart` | `input.search_query`, `input.search_keywords`, `pluginName` |
| Search results | `t = Trace`, `p.data.kind = PluginResponse` | `citableContent[]` (`source`, `chunks`), `output` |
| Grounding/answer signal | `t = Trace`, `p.data.kind = AnalyticsAiMetricsSignalTraceData` | `completionState`, `triggeredGptFallback`, `rewrittenMessage`, `rewrittenMessageKeywords`, `verifiedSearchResults[]` (`url`, `rankScore`, `snippet`, `searchType`), `citedKnowledgeSources`, `textCitations` |
| Knowledge search state | `t = Trace`, `p.data.kind = KnowledgeTraceData` | `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `failedKnowledgeSourcesTypes` |

Only `p.activity.type = "message"` activities are real user/bot turns;
`type = "event"` activities are system/plumbing and are skipped for turn
segmentation.

Check reconciliation:

- **CHECK-001 Intent Recognition** — recognized via `LlmIntentRecognized`. The
  failure signal is `triggeredGptFallback = true` on
  `AnalyticsAiMetricsSignalTraceData` (there is no `UnknownIntentTriggered` in
  real data). Fail if intent is absent or GPT fallback was triggered.
- **CHECK-002 Search Query Issued** — original prompt from
  `SynchronousIncomingActivity.p.activity.text` (the intent's `userUtterance` is
  often empty). Issued query/keywords from `PluginStart.input`. **Rewrite is read
  directly** from `rewrittenMessage` / `rewrittenMessageKeywords`, not inferred.
- **CHECK-003 Search Result Topical Relevance** — use
  `verifiedSearchResults[].rankScore` and `snippet` where present (rankScore does
  exist in this schema); fall back to keyword overlap on `snippet` / `source` /
  `citableContent.chunks`.
- **CHECK-004 Knowledge Grounding Consistency** — from `isKnowledgeSearched`,
  `completionState`, `citedKnowledgeSources`, and `verifiedSearchResults` count
  vs. what the answer does with them.
- **CHECK-005 Final Answer vs. Retrieved Content / Guardrails** — answer text vs.
  `verifiedSearchResults` / `citedKnowledgeSources` / `textCitations`.

**Graceful missing-field handling:** if a mapped field/event is absent in a given
transcript, mark the affected check **N/A** with "field not present in this
transcript" rather than failing or guessing. Note that the map derives from
observed exports and field names may vary by bot configuration.

## 4. Outputs, PII handling, testing

**Outputs written OUTSIDE the repo (PII safety):** the markdown Debug Report and
normalized JSON are written to a per-run subfolder in the OS temp directory
(`%TEMP%/ess-diagnostics/<transcript-name>/` on Windows; `$TMPDIR` or `/tmp` on
POSIX), NOT under `tools/ESS-Diagnostics-Skills/`. Nothing is written into the
repo, so commits can never capture employee PII. The skill tells the FDE the
absolute temp paths when done and warns once that outputs may contain PII and
should not be shared outside approved channels.

**Report additions:** the confirmed problem statement (from Step 0) and any FDE
verdict overrides (check, original → override, reason). Per-turn results surface
intent / search query + rewrite / search response explicitly.

**Normalized JSON updates:** `search.rewritten` / `rewrite_note` sourced from
`rewrittenMessage` / `rewrittenMessageKeywords`; `search_results` becomes the real
`verifiedSearchResults[]` shape (`url`, `rankScore`, `snippet`, …) and/or
`citableContent[]`; add a `grounding` object (`completionState`,
`isKnowledgeSearched`, `citedKnowledgeSources`, `triggeredGptFallback`). Still NO
verdicts in the JSON.

**Testing:** re-run the dry run against the same real transcript and confirm:
Step 0 gate fires; the structured per-turn pause + section menu + drill-down +
override work; the new parse map extracts intent/search/grounding correctly; and
outputs land in the OS temp dir, not the repo. No automated suite (prose skill).

## Note on prior v3 decisions this revisits

- v3's final review removed reliance on a "completion state" field because it was
  unmapped. Real data DOES carry `completionState` / `isKnowledgeSearched`, so v4
  re-introduces it as a mapped field for CHECK-004.
- v3 asserted there is "no rank/score field" on results. Real
  `verifiedSearchResults[]` objects DO have `rankScore`, so CHECK-003 may use it.
- These are corrections grounded in one real export; the graceful-missing-field
  rule guards against over-fitting to a single transcript.
