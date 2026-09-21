# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the Connect Workday result contract emitter.

Pure-logic tests (no network) — the projection from the internal
``CheckResult`` to Connect's host-neutral contract is a deterministic
mapping, explicitly excluded from the cassette rule in ``tests/AGENTS.md``.
These pin the fixed status/severity mapping, the field projection, and the
two hard invariants from the design doc: a non-pass internal status never
becomes ``pass``, and no new data enters ``safeEvidence``.
"""

from __future__ import annotations

import pytest

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


class TestMapStatus:
    """The fixed 7 -> 6 status mapping (Dawn, 2026-09-21)."""

    @pytest.mark.parametrize(
        "internal,expected",
        [
            (Status.PASSED.value, "pass"),
            (Status.WARNING.value, "warning"),
            (Status.FAILED.value, "fail"),
            (Status.NOT_CONFIGURED.value, "fail"),
            (Status.SKIPPED.value, "skipped"),
            (Status.ERROR.value, "blocked"),
            (Status.MANUAL.value, "skipped"),
        ],
    )
    def test_each_status_maps(self, internal, expected):
        assert cc.map_status(internal) == expected

    def test_unknown_status_maps_to_blocked_never_pass(self):
        # An unrecognised internal status must be a hard stop, never a pass.
        assert cc.map_status("SomethingNew") == "blocked"

    def test_only_passed_maps_to_pass(self):
        # Invariant: no non-PASSED internal status may become "pass".
        for status in Status:
            connect = cc.map_status(status.value)
            if status is Status.PASSED:
                assert connect == "pass"
            else:
                assert connect != "pass"


class TestSeverity:
    def test_blocked_is_always_blocking(self):
        assert cc.severity_for("blocked", Priority.LOW.value) == "blocking"

    def test_fail_blocking_when_high_priority(self):
        assert cc.severity_for("fail", Priority.CRITICAL.value) == "blocking"
        assert cc.severity_for("fail", Priority.HIGH.value) == "blocking"

    def test_fail_warning_when_low_priority(self):
        assert cc.severity_for("fail", Priority.MEDIUM.value) == "warning"
        assert cc.severity_for("fail", Priority.LOW.value) == "warning"

    def test_warning_is_warning(self):
        assert cc.severity_for("warning", Priority.HIGH.value) == "warning"

    def test_not_available_is_warning(self):
        assert cc.severity_for("not_available", Priority.HIGH.value) == "warning"

    def test_pass_and_skipped_are_info(self):
        assert cc.severity_for("pass", Priority.CRITICAL.value) == "info"
        assert cc.severity_for("skipped", Priority.CRITICAL.value) == "info"


class TestToConnectResult:
    def test_field_projection(self):
        out = cc.to_connect_result(_result())
        assert out == {
            "id": "WD-PKG-001",
            "name": "Workday runtime package ready",
            "status": "pass",
            "severity": "info",
            "safeEvidence": "Runtime package and required flows found",
            "nextAction": "Install or repair Workday runtime package",
            "remediationId": "",  # a pass carries no remediation pointer
        }

    def test_failed_high_priority_is_blocking_with_remediation_id(self):
        out = cc.to_connect_result(
            _result(status=Status.FAILED.value, priority=Priority.CRITICAL.value)
        )
        assert out["status"] == "fail"
        assert out["severity"] == "blocking"
        assert out["remediationId"] == "WD-PKG-001"

    def test_not_configured_becomes_fail(self):
        out = cc.to_connect_result(_result(status=Status.NOT_CONFIGURED.value))
        assert out["status"] == "fail"

    def test_error_becomes_blocked(self):
        out = cc.to_connect_result(_result(status=Status.ERROR.value))
        assert out["status"] == "blocked"
        assert out["severity"] == "blocking"

    def test_manual_becomes_skipped(self):
        out = cc.to_connect_result(_result(status=Status.MANUAL.value))
        assert out["status"] == "skipped"

    def test_safe_evidence_is_verbatim_result_no_new_data(self):
        # safeEvidence must be exactly the check's own result summary — the
        # emitter must not synthesise or pull in any other field.
        r = _result(result="0 users/groups assigned")
        assert cc.to_connect_result(r)["safeEvidence"] == "0 users/groups assigned"


class TestToConnectPayload:
    def test_payload_shape_and_overall_mapping(self):
        run = RunResult(scope="checkpoint:WD-PKG-001", started="now")
        run.results = [
            _result(),
            _result(checkpoint_id="WD-REST-001", status=Status.FAILED.value),
        ]
        run.overall = "NOT_READY"
        payload = cc.to_connect_payload(run, profile="workday-setup")
        assert payload["profile"] == "workday-setup"
        assert payload["overall"] == "not_ready"
        assert [r["id"] for r in payload["results"]] == [
            "WD-PKG-001",
            "WD-REST-001",
        ]

    def test_overall_ready_and_warnings_map_host_neutral(self):
        run = RunResult(scope="s", started="now")
        run.overall = "READY_WITH_WARNINGS"
        assert cc.to_connect_payload(run)["overall"] == "ready_with_warnings"
        run.overall = "READY"
        assert cc.to_connect_payload(run)["overall"] == "ready"

    def test_no_skipped_result_is_reported_as_pass(self):
        # Design-doc invariant: skipped/manual never count as pass.
        run = RunResult(scope="s", started="now")
        run.results = [_result(status=Status.MANUAL.value)]
        payload = cc.to_connect_payload(run)
        assert payload["results"][0]["status"] in cc.NON_PASS_STATUSES
        assert payload["results"][0]["status"] != "pass"
