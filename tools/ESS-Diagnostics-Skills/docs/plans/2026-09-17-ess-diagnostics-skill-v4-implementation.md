# ESS Diagnostics Skill v4 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Revise `tools/ESS-Diagnostics-Skills/SKILL.md` to (a) make the diagnosis interactive — a hard problem-statement gate and a structured per-turn pause with section drill-down and verdict override — and (b) reconcile the parse map with the real Copilot Studio / PVA export schema, writing PII-bearing outputs to an OS temp dir outside the repo.

**Architecture:** Prose edits to a single `SKILL.md` (read-only Claude skill, no code). Sourced from the v4 design doc `docs/plans/2026-09-17-ess-diagnostics-skill-v4-design.md` and from field paths observed in a real transcript. Validation is a manual dry run.

**Tech Stack:** Markdown. No test framework.

**Line endings:** repo is `core.autocrlf=true` + `core.safecrlf=true`, files are CRLF. After each edit, normalize to exactly one CRLF per line: `sed -i 's/\r$//' <file> && sed -i 's/$/\r/' <file>`; verify `file <file>` says "CRLF line terminators" and `grep -aoP '\r\r' <file> | wc -l` prints 0. Only touch `tools/ESS-Diagnostics-Skills/SKILL.md` unless a task says otherwise.

**Real schema reference (from the observed transcript):**
- User turn: `t = SynchronousIncomingActivity`, `p.activity.type = "message"`, text at `p.activity.text`.
- Bot turn: `t = OutgoingActivity`, `p.activity.type = "message"`, text at `p.activity.text`. (`type = "event"` activities are system plumbing — skip.)
- Diagnostic events: `t = Trace`, discriminated by `p.data.kind` ∈ {`LlmIntentRecognized`, `PluginStart`, `PluginResponse`, `KnowledgeTraceData`, `AnalyticsAiMetricsSignalTraceData`, …}.
- `PluginStart.input`: `search_query`, `search_keywords`, `enable_summarization`.
- `PluginResponse`: `citableContent[]` (`source`, `chunks`), `output`.
- `AnalyticsAiMetricsSignalTraceData`: `completionState`, `triggeredGptFallback`, `rewrittenMessage`, `rewrittenMessageKeywords`, `verifiedSearchResults[]` (`url`, `rankScore`, `snippet`, `searchType`), `citedKnowledgeSources`, `textCitations`.
- `KnowledgeTraceData`: `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `failedKnowledgeSourcesTypes`.

---

### Task 1: Add Step 0 (problem-statement hard gate) and strengthen the Rule

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** In `## Rules`, replace the bullet "Require two inputs up front… If either is missing, ask for it before proceeding." with a hard-stop bullet: the skill must not proceed past Step 0 until the FDE has stated the problem and the file path is confirmed — even if a problem was supplied in the invocation.

**Step 2:** Insert a new `## Step 0: Establish the Problem` section BEFORE `## Step 1`. It must instruct: on invocation, STOP; confirm the transcript file path; explicitly ask "What specific problem are you investigating in this transcript?"; do not read/parse until answered; if a problem statement was supplied in the args, echo it back and ask the FDE to confirm or refine rather than silently accepting.

**Step 3:** CRLF-normalize, verify, `git add`, commit: `feat: add Step 0 problem-statement hard gate to diagnostics skill`.

---

### Task 2: Rewrite the Step 1 parse map to the real schema

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Replace the Step 1 parse-map table with the concept→location→fields table from the v4 design (SynchronousIncomingActivity; OutgoingActivity; Trace/`p.data.kind` for LlmIntentRecognized, PluginStart, PluginResponse, AnalyticsAiMetricsSignalTraceData, KnowledgeTraceData). Keep the array-position ordering rule. Add: only `p.activity.type = "message"` activities are real turns; `type = "event"` are skipped for segmentation. Replace the old "search_results[] with keys FileType/Name/Text/…, no score field" note with the real result shapes (`citableContent[]` source/chunks; `verifiedSearchResults[]` url/rankScore/snippet).

**Step 2:** Add the graceful-missing-field rule: if a mapped field/event is absent, mark the affected check N/A with "field not present in this transcript" rather than failing/guessing; note the map derives from observed exports and may vary by bot config.

**Step 3:** CRLF-normalize, verify, `git add`, commit: `feat: reconcile Step 1 parse map with real transcript schema`.

---

### Task 3: Reconcile the 5 checks with the real fields

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Update each check bullet in Step 2:
- CHECK-001: recognized via `LlmIntentRecognized`; failure = intent absent OR `triggeredGptFallback = true`. Remove `UnknownIntentTriggered` as the failure path (note it's not present in real data; keep a mention that some exports may use it).
- CHECK-002: original prompt from `SynchronousIncomingActivity.p.activity.text`; issued query/keywords from `PluginStart.input`; rewrite read DIRECTLY from `rewrittenMessage` / `rewrittenMessageKeywords` (not inferred).
- CHECK-003: use `verifiedSearchResults[].rankScore` + `snippet` where present; fall back to keyword overlap on `snippet`/`source`/`citableContent.chunks`. (rankScore DOES exist — drop the "no score field" claim.)
- CHECK-004: from `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `verifiedSearchResults` count vs. the answer.
- CHECK-005: answer vs. `verifiedSearchResults` / `citedKnowledgeSources` / `textCitations`.

**Step 2:** Keep the existing "earlier failed check removes a later precondition ⇒ N/A" rule.

**Step 3:** CRLF-normalize, verify, `git add`, commit: `feat: reconcile the 5 checks with real transcript fields`.

---

### Task 4: Make Step 2 an interactive loop with structured pause + drill-down + override

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Rewrite the Step 2 walkthrough framing so that per turn the skill presents a STRUCTURED SUMMARY: Intent (id/message or failure signal); Search query (original prompt + issued/rewritten query & keywords); Search response (result count / cited sources + bot answer); and a one-line verdict strip `001 … · 005 …`.

**Step 2:** Add the section menu + hard stop:
- Menu options 1–5 (Intent, Search query, Search results, Grounding, Final answer) plus `[continue]`, `[run all]`, `[override]`.
- Hard stop: the skill WAITS and may not look at the next turn until the FDE responds.
- `run all` (available from the first pause) switches to a batch pass that auto-advances remaining turns but still produces the full report.

**Step 3:** Add drill-down + override behavior:
- Drill-down (section 1–5): show full raw transcript evidence for that section PLUS the check's reasoning (why Pass/Fail/N/A), and explicitly invite the FDE to override the verdict.
- Override: record (check, original verdict → override, FDE reason); it flows into the final report.

**Step 4:** CRLF-normalize, verify, `git add`, commit: `feat: make per-turn walkthrough interactive with drill-down and override`.

---

### Task 5: Update Step 4 outputs — OS temp dir, overrides, real-schema JSON

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Change output location: write the two files to a per-run subfolder in the OS temp dir (`%TEMP%/ess-diagnostics/<transcript-name>/` on Windows; `$TMPDIR` or `/tmp` on POSIX), NOT under the repo. Remove the `reports/`-under-repo path. Add a one-time PII warning and instruct the skill to report the absolute temp paths.

**Step 2:** Markdown report additions: include the confirmed problem statement (from Step 0) and any FDE verdict overrides (check, original → override, reason).

**Step 3:** Normalized JSON updates: `search.rewritten`/`rewrite_note` from `rewrittenMessage`/`rewrittenMessageKeywords`; `search_results` → real `verifiedSearchResults[]` shape (`url`, `rankScore`, `snippet`, …) and/or `citableContent[]`; add a `grounding` object (`completionState`, `isKnowledgeSearched`, `citedKnowledgeSources`, `triggeredGptFallback`). Update the fenced JSON example to this shape. Keep "NO verdicts in JSON".

**Step 4:** CRLF-normalize, verify, `git add`, commit: `feat: write outputs to OS temp dir and update JSON to real schema`.

---

### Task 6: Update README for v4 behavior

**Files:** Modify `tools/ESS-Diagnostics-Skills/README.md`.

**Step 1:** Update the README to describe: the Step 0 problem gate; the interactive per-turn pause with section drill-down and override; outputs written to an OS temp dir (not the repo) with a PII note; and the CHECK-004 (grounding) / CHECK-003 (rankScore) reconciliations. Keep it concise.

**Step 2:** CRLF-normalize, verify, `git add`, commit: `docs: update README for v4 interactive + real-schema behavior`.

---

### Task 7: Dry-run validation against the real transcript

**Files:** none (validation only).

**Step 1:** Follow the revised SKILL.md against `C:\Users\rarame\Downloads\Transcript_a9b8b841-6a4f-4675-9e79-92fc6df74be9.txt`. Confirm:
- Step 0 hard gate fires (skill asks for the problem before parsing).
- Parse map extracts the real events: 3 turns; intents `LlmIntentRecognized`; PluginStart queries + `rewrittenMessage`; `verifiedSearchResults` (count 10), `completionState = Answered`.
- The per-turn structured pause shows intent/search/response + verdict strip + section menu; drill-down shows raw evidence + reasoning; an override is accepted and recorded; `run all` works.
- Outputs land in the OS temp dir (NOT the repo); `git status` under the repo stays clean.

**Step 2:** Do NOT commit any generated report/JSON. Confirm nothing was written under `tools/ESS-Diagnostics-Skills/`. Record any gaps found; if SKILL.md needs a fix, apply it and commit `fix: address gaps found during v4 dry run`.

---

## Execution Handoff

Two options:
1. **Subagent-Driven (this session)** — fresh subagent per task, spec review between tasks.
2. **Parallel Session** — new session using `development/reference/executing-plans-guide.md`.
