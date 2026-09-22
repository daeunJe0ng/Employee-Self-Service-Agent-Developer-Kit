# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Schema-lock tests for the Connect Workday result contract.

Pure-logic tests (no network) — exempt from the cassette rule in
``tests/AGENTS.md`` (kit pure-logic helpers). Where ``test_connect_contract``
pins the *mapping* values, this file locks the *envelope*: the exact keys and
the enum vocabularies the emitter is allowed to produce. It is the regression
test ``connect_contract.py`` names as the guard on
``RESULT_KEYS`` / ``CONNECT_STATUSES`` / ``CONNECT_SEVERITIES`` /
``CONNECT_OVERALLS`` — if the emitter ever grows a key or emits a value outside
those published sets, one of these tests fails.
"""

from __future__ import annotations

import itertools
import json

from flightcheck import connect_contract as cc
from flightcheck.runner import CheckResult, Priority, RunResult, Status


def _result(**kw) -> CheckResult:
    base = dict(
        checkpoint_id="WD-PKG-001",
        category="Workday",
        priority=Priority.HIGH.value,
        status=Status.PASSED.value,
        description="Workday runtime package ready",
        result="Runtime package and required flows found",
        remediation="Install or repair Workday runtime package",
    )
    base.update(kw)
    return CheckResult(**base)


# Every (internal status, priority) combination the emitter can ever see.
_ALL_STATES = list(itertools.product(list(Status), list(Priority)))


class TestPerResultEnvelope:
    """Every projected result stays inside the published vocabulary."""

    def test_keys_are_exactly_result_keys(self):
        for status, priority in _ALL_STATES:
            out = cc.to_connect_result(
                _result(status=status.value, priority=priority.value)
            )
            assert tuple(out.keys()) == cc.RESULT_KEYS, (status, priority)

    def test_status_always_in_connect_statuses(self):
        for status, priority in _ALL_STATES:
            out = cc.to_connect_result(
                _result(status=status.value, priority=priority.value)
            )
            assert out["status"] in cc.CONNECT_STATUSES, (status, out["status"])

    def test_severity_always_in_connect_severities(self):
        for status, priority in _ALL_STATES:
            out = cc.to_connect_result(
                _result(status=status.value, priority=priority.value)
            )
            assert out["severity"] in cc.CONNECT_SEVERITIES, (
                status,
                out["severity"],
            )

    def test_remediation_id_present_iff_not_pass(self):
        # A pass carries no remediation pointer; everything else points back at
        # its own checkpoint id (design-doc invariant, dereferenceable).
        for status, priority in _ALL_STATES:
            r = _result(status=status.value, priority=priority.value)
            out = cc.to_connect_result(r)
            if out["status"] == "pass":
                assert out["remediationId"] == ""
            else:
                assert out["remediationId"] == r.checkpoint_id


class TestNoSecretLeak:
    """safeEvidence carries only the check's own curated result summary."""

    def test_safe_evidence_is_verbatim_result_only(self):
        # The emitter must add no data source beyond the check's result string;
        # a token-shaped value in `result` is the check's problem to curate,
        # but the emitter must never introduce one of its own.
        marker = "curated-summary-no-raw-payload"
        out = cc.to_connect_result(_result(result=marker))
        assert out["safeEvidence"] == marker
        blob = json.dumps(out)
        assert "Authorization" not in blob
        assert "Bearer " not in blob


class TestPayloadEnvelope:
    """The whole-run payload keeps a fixed envelope and enum overall."""

    def test_payload_top_level_keys(self):
        run = RunResult(scope="s", started="now")
        run.results = [_result()]
        run.overall = "READY"
        payload = cc.to_connect_payload(run, profile="workday")
        assert set(payload.keys()) == {"profile", "overall", "results"}

    def test_overall_maps_into_connect_overalls(self):
        for internal in ("READY", "READY_WITH_WARNINGS", "NOT_READY"):
            run = RunResult(scope="s", started="now")
            run.overall = internal
            payload = cc.to_connect_payload(run)
            assert payload["overall"] in cc.CONNECT_OVERALLS, internal

    def test_payload_round_trips_through_json(self):
        run = RunResult(scope="s", started="now")
        run.results = [
            _result(),
            _result(checkpoint_id="WD-REST-001", status=Status.FAILED.value),
        ]
        run.overall = "NOT_READY"
        payload = cc.to_connect_payload(run, profile="workday-connection")
        restored = json.loads(json.dumps(payload))
        assert restored == payload

    def test_every_projected_result_in_payload_is_valid(self):
        # A mixed run: one result per internal status. Every projected row must
        # satisfy the same envelope the per-result tests lock.
        run = RunResult(scope="s", started="now")
        run.results = [
            _result(checkpoint_id=f"WD-{s.name}", status=s.value)
            for s in Status
        ]
        run.overall = "NOT_READY"
        payload = cc.to_connect_payload(run)
        for row in payload["results"]:
            assert tuple(row.keys()) == cc.RESULT_KEYS
            assert row["status"] in cc.CONNECT_STATUSES
            assert row["severity"] in cc.CONNECT_SEVERITIES
