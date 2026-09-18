# Node→Python Transcript Helper Port — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Replace the Node.js helper `scripts/transcript-to-json.js` with a stdlib-only Python drop-in (`scripts/transcript_to_json.py`) of exact behavioral parity, update `SKILL.md` to invoke it, and delete the JS file.

**Architecture:** A single faithful procedural port (design "Approach A"). The Python script mirrors the JS flow one-for-one — BOM strip, JSON-array validation, `_turn`/`_index` annotation as first keys, temp-dir output, absolute-path print, `Error:`/exit-1 failures. No dependencies, no packaging, no CLI framework. Validated manually by diffing its output against the existing JS output for a real transcript (no automated test, per the approved design).

**Tech Stack:** Python 3.11+ stdlib only (`sys`, `json`, `pathlib`, `tempfile`). Repo lint: Ruff (E4/E7/E9/F). Git `core.autocrlf=true` — new text files must be committed with CRLF terminators.

**Design doc:** `tools/ESS-Diagnostics-Skills/docs/plans/2026-09-17-transcript-helper-node-to-python-design.md` (committed as `f2feb5a`).

**Working directory for all paths below:** repo root `Employee-Self-Service-Agent-Developer-Kit/`.

**Note on git & line endings:** `core.autocrlf=true` with no `.gitattributes` caused a "LF would be replaced by CRLF" commit failure on a LF-only file. Before every commit of a NEW text file (`.py`, `.md`), convert to CRLF first: `sed -i 's/$/\r/' <file>` (idempotent-guard: only run on files freshly written LF-only). Existing files edited in place keep their endings.

---

### Task 1: Create the Python helper

**Files:**
- Create: `tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py`

**Step 1: Write the script**

Write exactly this content to `tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py`:

```python
#!/usr/bin/env python3
"""transcript_to_json.py — faithful transcript -> JSON helper for the ESS
Diagnostics skill.

Parses a Copilot Studio / PVA transcript (JSON payload stored in a .txt) and
writes a LOSSLESS, pretty-printed JSON copy: every event and every field is
preserved exactly. The only additions are `_turn` and `_index`, annotated as
the first keys on each event (turn 0 for events before the first user message)
so a reader can navigate by conversation turn. Nothing is removed, so the
output round-trips back to the original once `_turn`/`_index` are dropped.

This is the faithful full dump. It is NOT the compact diagnostic "normalized"
view the skill builds for the 5 checks — it is the whole transcript, just as
real JSON.

Usage:
    python transcript_to_json.py <transcript.txt> [outFile.json]

- <transcript.txt>  path to the raw transcript export (required).
- [outFile.json]    where to write. If omitted, writes
                    `<basename>-transcript.json` into the OS temp dir under
                    `ess-diagnostics/<basename>/` (outside any repo, because
                    transcripts may contain employee PII).

Prints the absolute output path on success. Exits non-zero with an
`Error: ...` message on failure.
"""

import json
import sys
import tempfile
from pathlib import Path


def fail(msg):
    sys.stderr.write("Error: " + msg + "\n")
    sys.exit(1)


def is_user_turn_start(e):
    return (
        isinstance(e, dict)
        and e.get("t") == "SynchronousIncomingActivity"
        and isinstance(e.get("p"), dict)
        and isinstance(e["p"].get("activity"), dict)
        and e["p"]["activity"].get("type") == "message"
    )


def main(argv):
    if len(argv) < 2:
        fail(
            "missing transcript path. Usage: "
            "python transcript_to_json.py <transcript.txt> [outFile.json]"
        )
    src_arg = argv[1]
    src_path = Path(src_arg)
    if not src_path.exists():
        fail("transcript file not found: " + src_arg)

    try:
        raw = src_path.read_text(encoding="utf-8")
    except OSError as e:
        fail("could not read transcript: " + str(e))

    # Strip a leading UTF-8 BOM if present, then parse.
    if raw and raw[0] == "\ufeff":
        raw = raw[1:]

    try:
        events = json.loads(raw)
    except ValueError as e:
        fail("transcript is not valid JSON: " + str(e))

    if not isinstance(events, list):
        fail(
            "expected the transcript to be a JSON array of events; got "
            + type(events).__name__
        )

    # Annotate each event with its conversation turn number, WITHOUT mutating any
    # existing field. A turn starts at each real user message; events before the
    # first user message are turn 0. `_turn`/`_index` are first keys on a shallow
    # copy; every original key/value is copied through untouched.
    annotated = []
    turn = 0
    for i, e in enumerate(events):
        if is_user_turn_start(e):
            turn += 1
        if isinstance(e, dict):
            annotated.append({"_turn": turn, "_index": i, **e})
        else:
            annotated.append({"_turn": turn, "_index": i, "_value": e})

    base = src_path.name
    dot = base.rfind(".")
    if dot > 0:
        base = base[:dot]

    if len(argv) >= 3 and argv[2]:
        out_file = Path(argv[2])
        try:
            out_file.resolve().parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            fail(
                "could not create output directory "
                + str(out_file.resolve().parent)
                + ": "
                + str(e)
            )
    else:
        out_dir = Path(tempfile.gettempdir()) / "ess-diagnostics" / base
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            fail("could not create output directory " + str(out_dir) + ": " + str(e))
        out_file = out_dir / (base + "-transcript.json")

    try:
        out_file.write_text(
            json.dumps(annotated, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        fail("could not write output: " + str(e))

    sys.stdout.write(str(out_file.resolve()) + "\n")


if __name__ == "__main__":
    main(sys.argv)
```

**Step 2: Lint the new file**

Run: `cd tools/ESS-Diagnostics-Skills && python -m ruff check scripts/transcript_to_json.py`
(If Ruff is not installed, skip — it is a dev tool; note the skip.)
Expected: no errors (E4/E7/E9/F clean).

**Step 3: Run against the real transcript**

Run (from `tools/ESS-Diagnostics-Skills`):
`python scripts/transcript_to_json.py "C:\Users\rarame\Downloads\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229.txt"`
Expected: prints one absolute path ending in
`ess-diagnostics\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229-transcript.json`
and exits 0.

**Step 4: Diff Python output against the existing JS output (parity check)**

The JS dump already exists from this session at the same temp path. Regenerate
it to a side path with the JS helper, then compare:
```
node scripts/transcript-to-json.js "C:\Users\rarame\Downloads\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229.txt" /tmp/js-out.json
python scripts/transcript_to_json.py "C:\Users\rarame\Downloads\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229.txt" /tmp/py-out.json
diff /tmp/js-out.json /tmp/py-out.json && echo "IDENTICAL"
```
Expected: `IDENTICAL` (no diff). If diffs appear, they will be Unicode escaping
(check `ensure_ascii=False`) or key ordering — fix before continuing.

**Step 5: Spot-check a failure case**

Run: `python scripts/transcript_to_json.py /nonexistent/file.txt; echo "exit=$?"`
Expected: stderr line `Error: transcript file not found: /nonexistent/file.txt` and `exit=1`.

**Step 6: Commit**

```bash
cd <repo-root>
sed -i 's/$/\r/' tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py
git add tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py
git commit -m "ESS Diagnostics: add Python transcript_to_json helper (drop-in for JS)"
```
(Append the `Co-Authored-By: Claude <noreply@anthropic.com>` line per session attribution.)

---

### Task 2: Point SKILL.md at the Python helper

**Files:**
- Modify: `tools/ESS-Diagnostics-Skills/SKILL.md` (Step 1 "Faithful transcript-to-JSON" block ~line 96-98; Step 4 file #3 block ~line 378-380)

**Step 1: Replace both invocation code blocks**

Both currently read:
```
node scripts/transcript-to-json.js "<transcript-path>"
```
Change each to:
```
python scripts/transcript_to_json.py "<transcript-path>"
```

**Step 2: Add a platform note next to the Step 1 invocation**

Immediately after the Step 1 code block (which says "run from the skill
directory `tools/ESS-Diagnostics-Skills/`"), add a sentence in the existing
Windows/POSIX style:
> On Windows use `python`; on POSIX use `python3`.

**Step 3: Verify no stale JS references remain**

Run: `grep -n "node \|transcript-to-json.js\|\.js" tools/ESS-Diagnostics-Skills/SKILL.md`
Expected: no matches.

**Step 4: Commit**

```bash
git add tools/ESS-Diagnostics-Skills/SKILL.md
git commit -m "ESS Diagnostics: SKILL.md invokes Python transcript helper"
```
(SKILL.md is an existing file; no CRLF conversion needed — Edit preserves its endings. If a commit fails on CRLF, run `sed -i 's/$/\r/'` only on lines you added, or re-normalize the whole file with `unix2dos`.)

---

### Task 3: Remove the Node.js helper

**Files:**
- Delete: `tools/ESS-Diagnostics-Skills/scripts/transcript-to-json.js`

**Step 1: Confirm nothing else references it**

Run: `grep -rn "transcript-to-json" tools/ESS-Diagnostics-Skills/ --include=*.md --include=*.py --include=*.js`
Expected: no matches (SKILL.md already updated; README verified clean in design).
If any match remains, fix it before deleting.

**Step 2: Delete the file**

```bash
git rm tools/ESS-Diagnostics-Skills/scripts/transcript-to-json.js
```

**Step 3: Final sanity run**

Run the Python helper once more against the real transcript (Task 1 Step 3) to
confirm the skill's dump path still works with the JS file gone.
Expected: same absolute path printed, exit 0.

**Step 4: Commit**

```bash
git commit -m "ESS Diagnostics: remove Node transcript helper (replaced by Python)"
```

---

### Task 4: Final verification

**Step 1:** `git log --oneline -4` — confirm the four commits (design + 3 tasks) are present.
**Step 2:** `git status` — confirm clean working tree.
**Step 3:** Confirm `scripts/` now contains only `transcript_to_json.py` (no `.js`):
`ls tools/ESS-Diagnostics-Skills/scripts/`
