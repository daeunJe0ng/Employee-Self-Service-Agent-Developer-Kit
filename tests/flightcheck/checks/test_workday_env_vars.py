# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the Workday environment variable
FlightCheck checks (WD-ENV-001, WD-ENV-002, WD-ENV-003).

Mocks the Dataverse environmentvariabledefinitions and
environmentvariablevalues queries with `responses`, then runs the
ACTUAL production check function from
solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py
against the mocked state. Asserts that:

* When the Dataverse mock returns a "good" config (all three env vars
  present, ISU account set), FlightCheck reports PASSED.

* When the Dataverse mock returns a "bad" config (critical ISU
  account missing), FlightCheck reports FAILED with the expected
  remediation pointing the operator at /connect workday.

* When the Dataverse mock returns a partial config (ISU account set
  but the optional report-name vars missing), FlightCheck reports
  PASSED with the documented defaults.

This is the test pattern the rest of the FlightCheck suite should
follow: assemble a runner with whatever inputs the check needs,
register Dataverse / Graph / PP Admin / Workday SOAP / ServiceNow
mocks for the desired tenant state, invoke the real production
check, and assert on the CheckResult list it produces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv
from tests.mocks import minimalbots as mb

require_validated_mock(dv)
require_validated_mock(mb)


# ───────────────────────────────────────────────────────────────────────
# Test runner — minimal stand-in for FlightCheckRunner that the workday
# check needs. We don't import the real FlightCheckRunner because it
# does too much (registers checks, manages output formatters, etc.) for
# what these tests need; we just need an object with .env_url and
# .dv_token fields.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    env_url: str
    dv_token: str
    config: dict[str, Any] = field(default_factory=dict)
    minimalbots: Any = None


@pytest.fixture
def runner(fake_dataverse_url: str, fake_token: str) -> _MinimalRunner:
    return _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token)


# ───────────────────────────────────────────────────────────────────────
# Helpers to register Dataverse mock responses for various tenant states
# ───────────────────────────────────────────────────────────────────────


def _ess_env_var_def(schema_name: str, definition_id: str) -> dict[str, Any]:
    """Build an environmentvariabledefinitions record matching the
    select fields the check requests."""
    return {
        "@odata.etag": 'W/"1"',
        "displayname": schema_name.replace("EmployeeContext", ""),
        "schemaname": f"new_{schema_name}",
        "environmentvariabledefinitionid": definition_id,
    }


def _ess_env_var_value(definition_id: str, schema_name: str, value: str) -> dict[str, Any]:
    """Build an environmentvariablevalues record matching the
    select fields the check requests."""
    return {
        "@odata.etag": 'W/"1"',
        "value": value,
        "schemaname": f"new_{schema_name}_value",
        "_environmentvariabledefinitionid_value": definition_id,
    }


# Stable definition IDs so values can refer to them by FK.
_DEF_ISU = "00000000-0000-0000-0000-000000006001"
_DEF_REPORT_NAME = "00000000-0000-0000-0000-000000006002"
_DEF_REPORT_INSTANCE = "00000000-0000-0000-0000-000000006003"

_ALL_THREE_DEFINITIONS = [
    _ess_env_var_def("EmployeeContextRequestAccountName", _DEF_ISU),
    _ess_env_var_def("EmployeeContextRequestReportName", _DEF_REPORT_NAME),
    _ess_env_var_def("EmployeeContextRequestReportInstanceName", _DEF_REPORT_INSTANCE),
]


def _register_dataverse_state(
    *,
    base_url: str,
    definitions: list[dict[str, Any]],
    values: list[dict[str, Any]],
) -> None:
    """Register the two paginated Dataverse queries the check makes."""
    # The check calls query_all with a $filter for definitions and no
    # filter for values. We don't use match_querystring so the responses
    # match regardless of the exact query string the production code builds.
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariabledefinitions",
        json=dv.collection(definitions),
        status=200,
    )
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariablevalues",
        json=dv.collection(values),
        status=200,
    )


def _result_by_id(results: list, checkpoint_id: str):
    """Lookup helper: find the CheckResult with a given checkpoint_id."""
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


def _minimalbots_client(fake_token: str):
    from flightcheck.minimalbots_client import MinimalBotsClient

    client = MinimalBotsClient(
        tenant_id="00000000-0000-0000-0000-000000001111",
        environment_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0,
        ring="test",
    )
    client._token = fake_token
    return client


def _register_minimalbots_components(payload: dict) -> None:
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}/components",
        json=payload,
        status=200,
        match=[
            responses.matchers.query_param_matcher(
                {"api-version": "2024-10-01"}
            )
        ],
    )


# ───────────────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────────────


class TestMinimalBotsSharedConnectionParameters:
    """WD-ENV-001 reads DA Workday tenant config from minimalBots."""

    @responses.activate
    def test_workday_shared_parameters_present_passes(
        self, fake_dataverse_url: str, fake_token: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        _register_minimalbots_components(mb.component_change_set())
        runner = _MinimalRunner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            config={"agent": {"botId": mb.MOCK_BOT_ID}},
            minimalbots=_minimalbots_client(fake_token),
        )

        results = _check_env_vars(runner)

        assert {r.checkpoint_id for r in results} == {"WD-ENV-001"}
        wd_001 = _result_by_id(results, "WD-ENV-001")
        assert wd_001.status == "Passed"
        assert "sharedConnectionParameters.values" in wd_001.result
        assert mb.MOCK_WORKDAY_TENANT in wd_001.result

    @responses.activate
    def test_workday_reference_missing_fails(
        self, fake_dataverse_url: str, fake_token: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        _register_minimalbots_components(mb.component_change_set_without_workday())
        runner = _MinimalRunner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            config={"agent": {"botId": mb.MOCK_BOT_ID}},
            minimalbots=_minimalbots_client(fake_token),
        )

        wd_001 = _result_by_id(_check_env_vars(runner), "WD-ENV-001")

        assert wd_001.status == "Failed"
        assert "Workday connection reference was not found" in wd_001.result
        assert "reconnect or repair" in wd_001.remediation

    @responses.activate
    def test_required_shared_parameter_missing_fails(
        self, fake_dataverse_url: str, fake_token: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        shared = mb.workday_shared_connection_parameters(tenant_name="")
        payload = mb.component_change_set()
        payload["connectionReferenceChanges"] = [
            {
                "connectionReference": {
                    "connectionReferenceLogicalName": (
                        "cr123_shared_workdaysoap.shared_workdaysoap.workday"
                    ),
                    "connectorId": "/providers/Microsoft.PowerApps/apis/shared_workdaysoap",
                    "displayName": "Workday SOAP",
                    "sharedConnectionParameters": json.dumps(shared),
                }
            }
        ]
        _register_minimalbots_components(payload)
        runner = _MinimalRunner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            config={"agent": {"botId": mb.MOCK_BOT_ID}},
            minimalbots=_minimalbots_client(fake_token),
        )

        wd_001 = _result_by_id(_check_env_vars(runner), "WD-ENV-001")

        assert wd_001.status == "Failed"
        assert "tenantName" in wd_001.result
        assert "Reconnect the Workday connector" in wd_001.remediation


class TestGoodConfig:
    """All three env vars set — every checkpoint should PASS."""

    @responses.activate
    def test_all_three_env_vars_set_returns_three_passes(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
                _ess_env_var_value(_DEF_REPORT_NAME, "EmployeeContextRequestReportName", "WD User Context"),
                _ess_env_var_value(_DEF_REPORT_INSTANCE, "EmployeeContextRequestReportInstanceName", "Report2"),
            ],
        )

        results = _check_env_vars(runner)

        wd_001 = _result_by_id(results, "WD-ENV-001")
        wd_002 = _result_by_id(results, "WD-ENV-002")
        wd_003 = _result_by_id(results, "WD-ENV-003")

        assert wd_001.status == "Passed"
        assert wd_001.priority == "Critical"
        assert "ISU_MOCK" in wd_001.result

        assert wd_002.status == "Passed"
        assert "WD User Context" in wd_002.result

        assert wd_003.status == "Passed"
        assert "Report2" in wd_003.result

    @responses.activate
    def test_critical_var_set_optional_vars_missing_passes_with_defaults(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Customer set the critical ISU account but didn't override the
        report name defaults. The optional checkpoints should PASS with
        the documented defaults rather than warn."""
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
                # Report name and instance NOT in val_map (no value records).
            ],
        )

        results = _check_env_vars(runner)

        wd_001 = _result_by_id(results, "WD-ENV-001")
        wd_002 = _result_by_id(results, "WD-ENV-002")
        wd_003 = _result_by_id(results, "WD-ENV-003")

        assert wd_001.status == "Passed"
        assert "ISU_MOCK" in wd_001.result

        assert wd_002.status == "Passed"
        assert "Using default" in wd_002.result
        assert "WD User Context" in wd_002.result  # documented default

        assert wd_003.status == "Passed"
        assert "Using default" in wd_003.result
        assert "Report2" in wd_003.result


class TestBadConfig:
    """Critical ISU account missing — WD-ENV-001 must FAIL with remediation."""

    @responses.activate
    def test_isu_account_missing_returns_critical_failure(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_env_vars

        # Definitions exist (extension pack is installed) but the
        # customer hasn't set any values yet.
        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[],
        )

        results = _check_env_vars(runner)
        wd_001 = _result_by_id(results, "WD-ENV-001")

        assert wd_001.status == "Failed", (
            f"Expected WD-ENV-001 to FAIL when ISU account is unset, got "
            f"status={wd_001.status} result={wd_001.result!r}"
        )
        assert wd_001.priority == "Critical"
        assert "must be set manually" in wd_001.result
        assert "/connect workday" in wd_001.remediation
        assert wd_001.doc_link.startswith(
            "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
        )

    @responses.activate
    def test_isu_account_missing_does_not_block_optional_checkpoint_passes(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Even when the critical checkpoint fails, the two optional
        checkpoints should still PASS with their defaults — the failure
        is per-checkpoint, not all-or-nothing."""
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[],
        )

        results = _check_env_vars(runner)

        assert _result_by_id(results, "WD-ENV-001").status == "Failed"
        assert _result_by_id(results, "WD-ENV-002").status == "Passed"
        assert _result_by_id(results, "WD-ENV-003").status == "Passed"


class TestEdgeCases:
    @responses.activate
    def test_definitions_table_empty_treats_critical_as_failed(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Extension pack not installed → no definitions → critical FAILS,
        optional checkpoints still PASS with defaults.

        This pins current behavior. Whether that's the right outcome is
        a product question (a missing extension pack is different from
        a configured-but-unset env var); update this test if the check
        is ever reworked to differentiate.
        """
        from flightcheck.checks.workday import _check_env_vars

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=[],
            values=[],
        )

        results = _check_env_vars(runner)

        assert _result_by_id(results, "WD-ENV-001").status == "Failed"
        assert _result_by_id(results, "WD-ENV-002").status == "Passed"
        assert _result_by_id(results, "WD-ENV-003").status == "Passed"

    def test_skips_when_no_dataverse_token(self) -> None:
        """No token (e.g. user opted out of auth) — check returns a single
        SKIPPED result, doesn't crash, doesn't try to make an HTTP call."""
        from flightcheck.checks.workday import _check_env_vars

        runner_no_token = _MinimalRunner(env_url="", dv_token="")

        results = _check_env_vars(runner_no_token)
        assert len(results) == 1
        assert results[0].checkpoint_id == "WD-ENV-001"
        assert results[0].status == "Skipped"
        assert "token not available" in results[0].result.lower()

    @responses.activate
    def test_partial_match_on_schema_name_works(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """The check's schema-name match is case-insensitive substring,
        so 'new_EmployeeContextRequestAccountName_value' matches
        'EmployeeContextRequestAccountName' from ENV_VARS. Pin this
        behavior — if anyone tightens the match to exact-equality,
        this test catches the regression.
        """
        from flightcheck.checks.workday import _check_env_vars

        # The publisher prefixes Dataverse adds usually look like
        # "new_" or "msdyn_"; the check's `var_name.lower() in k.lower()`
        # match is what survives that.
        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
            ],
        )

        results = _check_env_vars(runner)
        assert _result_by_id(results, "WD-ENV-001").status == "Passed"
        assert "ISU_MOCK" in _result_by_id(results, "WD-ENV-001").result


class TestSimplifiedInstallGate:
    """Pins the simplified install contract for `_check_env_vars`.

    WD-ENV-001 is re-pointed to the DA Workday connection reference's
    sharedConnectionParameters. WD-ENV-002/003 remain ISU/RaaS-only
    legacy Dataverse environment variables and still skip on simplified.

      * Any other verdict (None / "full" / "partial" / "unknown" /
        "none" / "skipped") → run the existing logic. The "skip only
        on a positive INCOMPATIBLE match" rule is the safety
        valve — operators debugging a broken install need every
        signal, not silence.
    """

    def test_simplified_without_minimalbots_skips_all_three_with_correct_priorities(self) -> None:
        """`flavor == "simplified"` without minimalBots keeps all checks non-networked."""
        from flightcheck.checks.workday import _check_env_vars

        runner = _MinimalRunner(env_url="https://dv.example", dv_token="dv-token")
        runner._workday_package_flavor = "simplified"

        results = _check_env_vars(runner)

        assert {r.checkpoint_id for r in results} == {"WD-ENV-001", "WD-ENV-002", "WD-ENV-003"}
        wd_001 = _result_by_id(results, "WD-ENV-001")
        assert wd_001.status == "Skipped"
        assert "minimalBots client is not available" in wd_001.result

        for checkpoint_id in ("WD-ENV-002", "WD-ENV-003"):
            r = _result_by_id(results, checkpoint_id)
            assert r.status == "Skipped"
            assert "WD-PKG-001" in r.result
            assert "simplified" in r.result.lower()
            assert "Generic User" in r.remediation
            assert "Context Generic User" in r.remediation
            assert "workday-simplified-setup" in r.doc_link

        # WD-ENV-001 is critical; the other two are high.
        assert _result_by_id(results, "WD-ENV-001").priority == "Critical"
        assert _result_by_id(results, "WD-ENV-002").priority == "High"
        assert _result_by_id(results, "WD-ENV-003").priority == "High"

    @responses.activate
    def test_full_verdict_runs_existing_logic_unchanged(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """`flavor == "full"` → check runs as today. Pinned with a
        happy-path mock; the WD-ENV-001 row reflects the real
        underlying state instead of the gate's SKIP message."""
        from flightcheck.checks.workday import _check_env_vars

        runner._workday_package_flavor = "full"
        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[
                _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", "ISU_MOCK"),
            ],
        )

        results = _check_env_vars(runner)
        assert _result_by_id(results, "WD-ENV-001").status == "Passed"
        assert "ISU_MOCK" in _result_by_id(results, "WD-ENV-001").result

    @responses.activate
    @pytest.mark.parametrize("flavor", ["partial", "unknown", "none", "skipped"])
    def test_ambiguous_verdicts_still_run_existing_logic(
        self, runner: _MinimalRunner, fake_dataverse_url: str, flavor: str,
    ) -> None:
        """Per AGENTS.md principle #11.b: skip ONLY on a positive
        match for the INCOMPATIBLE flavor. Any other verdict — partial
        install, unknown shape, no Workday refs at all, or
        Dataverse-skipped — must run the existing logic so operators
        debugging a broken install see every available signal.

        Protects against a future careless rewrite like
        `if flavor != "full": skip` that would pass the simplified/
        full tests above but silently break these intermediate states.
        """
        from flightcheck.checks.workday import _check_env_vars

        runner._workday_package_flavor = flavor
        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[],
        )

        results = _check_env_vars(runner)
        # ISU env var unset → critical FAIL (existing behavior); the
        # gate must NOT suppress this on ambiguous flavors.
        wd_001 = _result_by_id(results, "WD-ENV-001")
        assert wd_001.status == "Failed", (
            f"flavor={flavor!r} must run existing logic and FAIL when ISU "
            f"env var is unset, got status={wd_001.status}"
        )
        assert "must be set manually" in wd_001.result

    @responses.activate
    def test_attribute_absent_runs_existing_logic_for_backwards_compat(
        self, runner: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Backwards-compat: minimal test runners that don't set
        `_workday_package_flavor` (the default state of the
        `_MinimalRunner` dataclass) must continue producing the
        pre-gating behavior. The `getattr(..., None)` default is what
        enables this."""
        from flightcheck.checks.workday import _check_env_vars

        # Verify the precondition — `_MinimalRunner` doesn't set the
        # gate attribute by default.
        assert not hasattr(runner, "_workday_package_flavor")

        _register_dataverse_state(
            base_url=fake_dataverse_url,
            definitions=_ALL_THREE_DEFINITIONS,
            values=[],
        )

        results = _check_env_vars(runner)
        assert _result_by_id(results, "WD-ENV-001").status == "Failed"
