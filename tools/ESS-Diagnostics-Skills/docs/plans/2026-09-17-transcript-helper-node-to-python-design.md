# Convert transcript-to-json helper from Node.js to Python

**Date:** 2026-09-17
**Status:** Approved design
**Scope:** `tools/ESS-Diagnostics-Skills/`

## Problem

The ESS Diagnostics skill ships a helper, `scripts/transcript-to-json.js`, that
produces a faithful (lossless) JSON dump of a Copilot Studio / PVA transcript.
The rest of the repo is Python (3.11+, Ruff-linted, pytest suite). A lone
Node.js dependency in an otherwise Python toolkit is an avoidable footgun for
FDEs and maintainers. Convert the helper to Python and remove the Node version.

## Goals

- Replace the JS helper with a stdlib-only Python script that is an **exact
  behavioral drop-in** (same CLI contract, same output, same error/exit
  behavior).
- Update `SKILL.md` to invoke the Python helper.
- Remove the JS file. No Node dependency remains.

## Non-goals

- No automated test (matches the JS helper's current no-test status; validate
  manually).
- No CLI enhancements (`argparse`, `--help`), no packaging (`__main__.py`), no
  refactor of the diagnostic flow. Faithful port only.

## Decisions

| Question | Decision |
| --- | --- |
| Fate of the JS file | **Delete** — Python fully replaces it. |
| Invocation | `python scripts/transcript_to_json.py "<path>"` (plain script, not `-m`). |
| Interpreter in docs | Document both: `python` (Windows) / `python3` (POSIX), matching SKILL.md's existing Windows/POSIX split. |
| Fidelity | **Exact behavioral parity** — true drop-in. |
| Test | **None** — manual validation. |
| Internal structure | **Approach A** — faithful procedural port, stdlib only, no unused abstraction. |
| Filename | `transcript_to_json.py` (PEP 8 underscores). |

## Files

- **Add:** `tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py`
- **Delete:** `tools/ESS-Diagnostics-Skills/scripts/transcript-to-json.js`
- **Edit:** `tools/ESS-Diagnostics-Skills/SKILL.md` (invocation commands, ~2 spots, + platform note)
- **README.md:** no change (verified — no `node`/`.js`/`transcript-to-json` references)

No new dependencies. Stdlib only: `sys`, `json`, `pathlib`, `tempfile`.
Target: Python 3.11+.

## The Python script (behavioral parity)

CLI: `python transcript_to_json.py <transcript.txt> [outFile.json]` — arg 1
required (source), arg 2 optional (output path).

Flow, identical to the JS original:

1. `fail(msg)` → write `Error: <msg>\n` to stderr, `sys.exit(1)`.
2. Missing arg 1 → fail with the usage message. Source file not found → fail.
3. Read source as UTF-8. Strip a leading BOM (`﻿`) if present.
4. `json.loads`; on error → `fail("transcript is not valid JSON: ...")`.
5. Not a `list` → `fail("expected the transcript to be a JSON array of events; got <type>")`.
6. Annotate: walk events in array order, increment `turn` at each user-turn
   start (`t == "SynchronousIncomingActivity"` and `p.activity.type ==
   "message"`); emit each as `{"_turn": turn, "_index": i, **event}` so
   `_turn`/`_index` are the first keys and every original field is preserved
   untouched. Nested access is guarded (`isinstance` / `.get()` chains) so a
   malformed event never raises — mirrors the JS `e && e.p && e.p.activity`
   guard.
7. Resolve output path: if arg 2 is given, use it (create its parent dir);
   otherwise `tempfile.gettempdir()/ess-diagnostics/<basename>/<basename>-transcript.json`,
   creating directories. Basename = source filename minus its final extension.
8. Write with `json.dumps(annotated, indent=2, ensure_ascii=False)`.
   **`ensure_ascii=False` is required** for byte-parity with JS
   `JSON.stringify`, which emits raw (non-escaped) Unicode.
9. Print the absolute output path to stdout.

Wrapped in a `main()` called under `if __name__ == "__main__":`.

Parity guarantees preserved: identical `Error:` prefix (SKILL.md instructs the
FDE to relay it), exit codes (0 success / 1 failure), temp-path shape, printed
absolute path, and round-trippable output (drop `_turn`/`_index` → original).

## SKILL.md edits

Each `node scripts/transcript-to-json.js "<transcript-path>"` (Step 1 "Faithful
transcript-to-JSON" and Step 4, file #3) becomes:

```
python scripts/transcript_to_json.py "<transcript-path>"
```

Add a one-line platform note in the existing Windows/POSIX style: use `python`
on Windows, `python3` on POSIX. Surrounding prose (writes into the same temp
folder, prints the absolute path, relay `Error:` on failure, produce both dumps)
stays valid unchanged.

## Error handling

All failure modes route through `fail()`: missing/absent source, invalid JSON,
non-array top level, and unwritable output directory each print a single
`Error: ...` line to stderr and exit non-zero. No Python traceback leaks to the
FDE. Identical to the JS behavior.

## Validation (manual)

1. Run the new script against the real transcript
   (`Transcript_ 4b548465-...txt`); confirm it prints the same absolute path and
   writes a valid file.
2. Diff the Python output against the existing JS output for that transcript;
   expect identical content (the annotation + round-trip guarantee).
3. Spot-check a failure case (non-existent path); confirm the `Error:` line and
   non-zero exit.
