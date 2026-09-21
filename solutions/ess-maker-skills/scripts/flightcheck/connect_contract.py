# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Connect Workday result contract.

The Connect Workday skill consumes FlightCheck through a **stable,
host-neutral result shape** it owns jointly with FlightCheck: FlightCheck
owns "the validation checks, stable result shape, safe evidence, severity,
and remediation guidance" while Connect owns orchestration and the
continue / wait / block / ready decision (Connect Workday Dev Design Doc,
"FlightCheck integration").

This module projects the internal ``CheckResult`` / ``RunResult``
(``runner.py``) into that contract. The internal model is richer and
FlightCheck-specific; the Connect contract is deliberately smaller and
transport-neutral so the same readiness signals survive if the host
experience changes.

Per-check contract (design doc "FlightCheck result contract"):

    {
      "id": "WD-PKG-001",
      "name": "Workday runtime package ready",
      "status": "pass | warning | fail | blocked | skipped | not_available",
      "severity": "blocking | warning | info",
      "safeEvidence": "...",
      "nextAction": "...",
      "remediationId": "WD-PKG-001"
    }

Hard rules from the design doc, enforced here:

* ``skipped`` and ``not_available`` must NEVER be counted as a pass. This
  module never maps an internal PASSED to anything but ``pass``, and never
  maps a non-PASSED internal status to ``pass``.
* The result must not include secrets, tokens, employee data, raw Workday
  responses, or raw connector payloads. ``safeEvidence`` carries only the
  check's already-curated ``result`` summary; the production checks are
  bound by ``AGENTS.md`` never to place raw payloads there. This module
  copies that summary verbatim and adds no new data source.

Status/severity mapping is fixed (Dawn, 2026-09-21). See ``_STATUS_MAP`` and
``severity_for``.
"""

from __future__ import annotations

from typing import Any

from flightcheck.runner import CheckResult, Priority, RunResult, Status


# Internal Status (7 values) -> Connect status enum (6 values). Fixed mapping.
#   PASSED         -> pass
#   WARNING        -> warning
#   FAILED         -> fail
#   NOT_CONFIGURED -> fail      (a required-but-absent gate is actionable, not
#                                a pass; NOT_CONFIGURED never counts as ready)
#   SKIPPED        -> skipped
#   ERROR          -> blocked   (the check could not evaluate; surface as a
#                                hard stop with diagnostic evidence)
#   MANUAL         -> skipped   (operator verifies externally; never a pass and
#                                never fails readiness)
_STATUS_MAP: dict[str, str] = {
    Status.PASSED.value: "pass",
    Status.WARNING.value: "warning",
    Status.FAILED.value: "fail",
    Status.NOT_CONFIGURED.value: "fail",
    Status.SKIPPED.value: "skipped",
    Status.ERROR.value: "blocked",
    Status.MANUAL.value: "skipped",
}

# Connect statuses the skill must never count as a successful readiness result
# (design doc: "skipped and not_available must never be counted as pass").
NON_PASS_STATUSES: frozenset = frozenset(
    {"warning", "fail", "blocked", "skipped", "not_available"}
)

# ---------------------------------------------------------------------------
# Published contract vocabulary. These are the exact keys/enums Connect can
# rely on (and import) — the single source of truth for the result shape.
# Kept in sync with the design doc "FlightCheck result contract" block; the
# schema regression test (tests/flightcheck/test_connect_contract_schema.py)
# fails if the emitter ever produces a key or value outside these sets.
# ---------------------------------------------------------------------------
RESULT_KEYS: tuple = (
    "id",
    "name",
    "status",
    "severity",
    "safeEvidence",
    "nextAction",
    "remediationId",
)
CONNECT_STATUSES: frozenset = frozenset(
    {"pass", "warning", "fail", "blocked", "skipped", "not_available"}
)
CONNECT_SEVERITIES: frozenset = frozenset({"blocking", "warning", "info"})
CONNECT_OVERALLS: frozenset = frozenset(
    {"ready", "ready_with_warnings", "not_ready"}
)

# Internal overall verdict -> host-neutral lowercase for Connect.
_OVERALL_MAP: dict[str, str] = {
    "READY": "ready",
    "READY_WITH_WARNINGS": "ready_with_warnings",
    "NOT_READY": "not_ready",
}

_BLOCKING_PRIORITIES: frozenset = frozenset(
    {Priority.CRITICAL.value, Priority.HIGH.value}
)


def map_status(internal_status: str) -> str:
    """Map an internal ``Status`` value to the Connect status enum.

    Unknown/blank internal statuses map to ``blocked`` — an unrecognised
    state is treated as a hard stop, never silently as a pass.
    """
    return _STATUS_MAP.get(internal_status, "blocked")


def severity_for(connect_status: str, priority: str) -> str:
    """Derive the Connect severity (``blocking | warning | info``).

    * ``fail`` is blocking when the check's priority is Critical/High,
      otherwise a warning (a low-priority gap should not hard-block the maker).
    * ``blocked`` is always blocking — the check could not evaluate.
    * ``warning`` maps to warning.
    * ``pass`` and ``skipped`` are informational (they carry no required
      action for the maker).
    * ``not_available`` is a warning — the signal could not be confirmed, so
      the maker should be told, but it is not a proven hard failure.
    """
    if connect_status == "blocked":
        return "blocking"
    if connect_status == "fail":
        return "blocking" if priority in _BLOCKING_PRIORITIES else "warning"
    if connect_status == "warning":
        return "warning"
    if connect_status == "not_available":
        return "warning"
    # pass, skipped
    return "info"


def to_connect_result(result: CheckResult) -> dict[str, Any]:
    """Project one internal ``CheckResult`` into the Connect contract dict.

    Field mapping (Dawn, 2026-09-21):
      id           <- checkpoint_id
      name         <- description (what the check verifies)
      status       <- map_status(status)
      severity     <- severity_for(status, priority)
      safeEvidence <- result (already-curated summary; no raw payloads)
      nextAction   <- remediation
      remediationId<- checkpoint_id (stable, dereferenceable to this check's
                      remediation text until a dedicated remediation catalog
                      exists)
    """
    connect_status = map_status(result.status)
    return {
        "id": result.checkpoint_id,
        "name": result.description,
        "status": connect_status,
        "severity": severity_for(connect_status, result.priority),
        "safeEvidence": result.result,
        "nextAction": result.remediation,
        # A passing check needs no remediation pointer; everything else points
        # back at its own stable checkpoint id.
        "remediationId": (
            "" if connect_status == "pass" else result.checkpoint_id
        ),
    }


def to_connect_payload(
    run: RunResult, profile: str | None = None
) -> dict[str, Any]:
    """Project a whole ``RunResult`` into a Connect-consumable payload.

    Shape::

        {
          "profile": "workday-setup",   # or None for a scope/checkpoint run
          "overall": "not_ready",       # host-neutral verdict
          "results": [ <per-check contract>, ... ]
        }

    ``overall`` is FlightCheck's own aggregate verdict, provided as a
    convenience; Connect still owns the final continue/block/ready decision
    per the design doc, and must not treat ``skipped`` results as passes.
    """
    return {
        "profile": profile,
        "overall": _OVERALL_MAP.get(run.overall, run.overall.lower()),
        "results": [to_connect_result(r) for r in run.results],
    }
