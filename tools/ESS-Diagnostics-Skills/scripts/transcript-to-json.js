#!/usr/bin/env node
/**
 * transcript-to-json.js — faithful transcript -> JSON helper for the ESS
 * Diagnostics skill.
 *
 * Parses a Copilot Studio / PVA transcript (JSON payload stored in a .txt) and
 * writes a LOSSLESS, pretty-printed JSON copy: every event and every field is
 * preserved exactly. The only addition is a `_turn` number annotated on each
 * event (0 for events before the first user message) so a reader can navigate
 * by conversation turn. Nothing is removed, so the output round-trips back to
 * the original once the `_turn` keys are dropped.
 *
 * This is the faithful full dump. It is NOT the compact diagnostic
 * "normalized" view the skill builds for the 5 checks — it is the whole
 * transcript, just as real JSON.
 *
 * Usage:
 *   node transcript-to-json.js <transcript.txt> [outFile.json]
 *
 * - <transcript.txt>  path to the raw transcript export (required).
 * - [outFile.json]    where to write. If omitted, writes
 *                     `<basename>-transcript.json` into the OS temp dir under
 *                     `ess-diagnostics/<basename>/` (outside any repo, because
 *                     transcripts may contain employee PII).
 *
 * Prints the absolute output path on success. Exits non-zero with an
 * `Error: ...` message on failure.
 */

"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

function fail(msg) {
  process.stderr.write("Error: " + msg + "\n");
  process.exit(1);
}

const srcArg = process.argv[2];
if (!srcArg) fail("missing transcript path. Usage: node transcript-to-json.js <transcript.txt> [outFile.json]");
if (!fs.existsSync(srcArg)) fail("transcript file not found: " + srcArg);

let raw;
try {
  raw = fs.readFileSync(srcArg, "utf8");
} catch (e) {
  fail("could not read transcript: " + e.message);
}

// Strip a leading UTF-8 BOM if present, then parse.
if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);

let events;
try {
  events = JSON.parse(raw);
} catch (e) {
  fail("transcript is not valid JSON: " + e.message);
}

if (!Array.isArray(events)) {
  fail("expected the transcript to be a JSON array of events; got " + typeof events);
}

// Annotate each event with its conversation turn number, WITHOUT mutating any
// existing field. A turn starts at each real user message
// (SynchronousIncomingActivity with activity.type === "message"). Events before
// the first user message are turn 0. `_turn` is a first key on a shallow copy;
// every original key/value is copied through untouched.
function isUserTurnStart(e) {
  return (
    e &&
    e.t === "SynchronousIncomingActivity" &&
    e.p &&
    e.p.activity &&
    e.p.activity.type === "message"
  );
}

let turn = 0;
const annotated = events.map((e, i) => {
  if (isUserTurnStart(e)) turn += 1;
  // _turn and _index first, then a faithful spread of the original event.
  return Object.assign({ _turn: turn, _index: i }, e);
});

// Resolve output path.
const base = path.basename(srcArg).replace(/\.[^.]+$/, "");
let outFile = process.argv[3];
if (!outFile) {
  const outDir = path.join(os.tmpdir(), "ess-diagnostics", base);
  try {
    fs.mkdirSync(outDir, { recursive: true });
  } catch (e) {
    fail("could not create output directory " + outDir + ": " + e.message);
  }
  outFile = path.join(outDir, base + "-transcript.json");
} else {
  const outParent = path.dirname(path.resolve(outFile));
  try {
    fs.mkdirSync(outParent, { recursive: true });
  } catch (e) {
    fail("could not create output directory " + outParent + ": " + e.message);
  }
}

try {
  fs.writeFileSync(outFile, JSON.stringify(annotated, null, 2));
} catch (e) {
  fail("could not write output: " + e.message);
}

process.stdout.write(path.resolve(outFile) + "\n");
