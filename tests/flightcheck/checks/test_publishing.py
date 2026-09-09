# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the Publishing & QA checklist (PUB-*, QA-*).

The user surfaced that the publishing rows were emitted as
``NotConfigured`` with a generic "Verify: <desc>" remediation and a
single homepage link — operators had no way to act on them. The
module was rewritten so:

  * process-only rows are ``Status.MANUAL`` (nothing is genuinely "not
    configured" — the kit just can't witness the action remotely);
  * PUB-001 and PUB-002 use minimalBots ALM probes where possible;
  * every ``result`` describes WHAT the kit can't see, not the
    boilerplate "Manual verification required";
  * every ``remediation`` carries concrete steps and the best
    available deep link (Copilot Studio agent for QA-*; Power Apps
    Solutions for PUB-001/002; the Microsoft 365 admin center
    Integrated apps page for PUB-006/011).

These tests pin those contracts so the rows can't drift back to
"vague + NotConfigured" without breaking CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlparse

import pytest
import responses
import yaml
from responses import matchers


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


from tests.conftest import require_validated_mock
from tests.mocks import minimalbots as mb

require_validated_mock(mb)


def _runner(
    env_id: str | None = "env-abc",
    bot_id: str | None = "bot-xyz",
    *,
    minimalbots=None,
    alm_import_probe: bool = False,
):
    """Minimal runner stub exposing the attributes publishing.py reads."""
    config: dict = {}
    if bot_id:
        config["agents"] = [{"slug": "esshr", "botId": bot_id}]
    return SimpleNamespace(
        env_id=env_id,
        config=config,
        minimalbots=minimalbots,
        alm_import_probe=alm_import_probe,
    )


@pytest.fixture
def minimalbots_client(fake_token: str):
    from flightcheck.minimalbots_client import MinimalBotsClient

    client = MinimalBotsClient(
        tenant_id="00000000-0000-0000-0000-000000001111",
        environment_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0,
        ring="test",
    )
    client._token = fake_token
    return client


def _results_by_id(runner) -> dict:
    from flightcheck.checks.publishing import run_publishing_checks
    return {r.checkpoint_id: r for r in run_publishing_checks(runner)}


def _delete_calls():
    return [c for c in responses.calls if c.request.method == "DELETE"]


def _pub_002_row(runner) -> dict:
    from flightcheck.checks.publishing import _build_checks

    return next(row for row in _build_checks(runner) if row["id"] == "PUB-002")


def _add_validated_publishing_cassette(*, base_url: str) -> str:
    """Replay the redacted export-200/import-409 cassette via responses."""
    cassette_path = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "cassettes"
        / "flightcheck_minimalbots_publishing.yaml"
    )
    data = yaml.safe_load(cassette_path.read_text(encoding="utf-8"))
    bot_id = ""
    for interaction in data["interactions"]:
        request = interaction["request"]
        response = interaction["response"]
        parsed = urlparse(request["uri"])
        url = f"{base_url.rstrip('/')}{parsed.path}"
        if "/alm/" in parsed.path and "/export" in parsed.path:
            bot_id = parsed.path.split("/alm/", 1)[1].split("/export", 1)[0]
        headers = {
            key: values[0] if isinstance(values, list) else values
            for key, values in (response.get("headers") or {}).items()
            if key.lower() not in {"content-length", "transfer-encoding"}
        }
        body = (response.get("body") or {}).get("string") or b""
        responses.add(
            request["method"],
            url,
            body=body,
            status=response["status"]["code"],
            headers=headers,
            match=[matchers.query_param_matcher(dict(parse_qsl(parsed.query)))],
        )
    assert bot_id, "publishing cassette did not include an export bot id"
    return bot_id


# --------------------------------------------------------------- shape


def test_all_eight_checks_emitted():
    """Regression guard: the published checklist must keep its 8 IDs."""
    by_id = _results_by_id(_runner())
    assert set(by_id) == {
        "QA-001", "QA-002", "QA-012",
        "PUB-001", "PUB-002", "PUB-003", "PUB-006", "PUB-011",
    }


def test_process_only_checks_are_manual_not_notconfigured():
    """The user's principle: nothing here is misconfigured. Don't
    label it ``NotConfigured`` — that wrongly implies setup is missing."""
    from flightcheck.runner import Status
    by_id = _results_by_id(_runner())
    for checkpoint_id in ("QA-001", "QA-002", "QA-012", "PUB-003", "PUB-006", "PUB-011"):
        r = by_id[checkpoint_id]
        assert r.status == Status.MANUAL.value, (
            f"{r.checkpoint_id} regressed to status={r.status!r}; "
            "process-only publishing/QA gates are manual, not NotConfigured."
        )


def test_pub_001_and_pub_002_are_skipped_when_minimalbots_unavailable():
    from flightcheck.runner import Status

    by_id = _results_by_id(_runner(minimalbots=None, alm_import_probe=True))

    assert by_id["PUB-001"].status == Status.SKIPPED.value
    assert "minimalBots ALM client is unavailable" in by_id["PUB-001"].result
    assert by_id["PUB-002"].status == Status.SKIPPED.value
    assert "minimalBots ALM client is unavailable" in by_id["PUB-002"].result


def test_every_check_has_concrete_result_text():
    """No row may carry the old "Manual verification required" stub."""
    for r in _results_by_id(_runner()).values():
        assert r.result.strip(), f"{r.checkpoint_id} has empty result"
        assert r.result != "Manual verification required", (
            f"{r.checkpoint_id} regressed to the generic result stub."
        )


def test_every_check_has_remediation_and_doc_link():
    for r in _results_by_id(_runner()).values():
        assert r.remediation.strip(), f"{r.checkpoint_id} has empty remediation"
        # Remediation must say more than "Verify: <desc>".
        assert not r.remediation.startswith("Verify:"), (
            f"{r.checkpoint_id} regressed to the boilerplate remediation."
        )
        assert r.doc_link.startswith("https://"), (
            f"{r.checkpoint_id} has missing/invalid doc_link {r.doc_link!r}"
        )


def test_category_is_publishing():
    for r in _results_by_id(_runner()).values():
        assert r.category == "Publishing"


# ----------------------------------------------------------- QA deep links


def test_qa_checks_link_to_studio_when_env_and_bot_resolved():
    by_id = _results_by_id(_runner(env_id="env-abc", bot_id="bot-xyz"))
    expected = (
        "https://copilotstudio.microsoft.com/environments/env-abc/"
        "bots/bot-xyz/overview"
    )
    for qa_id in ("QA-001", "QA-002", "QA-012"):
        assert expected in by_id[qa_id].remediation, (
            f"{qa_id} remediation missing the Studio deep link {expected!r}; "
            f"got: {by_id[qa_id].remediation!r}"
        )


def test_qa_checks_remain_actionable_without_studio_link():
    """If env_id or botId is missing, the remediation must still tell
    the operator where to go — just without a clickable shortcut."""
    by_id = _results_by_id(_runner(env_id=None, bot_id=None))
    for qa_id in ("QA-001", "QA-002", "QA-012"):
        text = by_id[qa_id].remediation
        # No copilotstudio.microsoft.com link when we can't build one.
        assert "copilotstudio.microsoft.com/environments/" not in text
        # But the operator is still told where to perform the action.
        assert "Analytics" in text and "Evaluations" in text


def test_qa_checks_point_at_evaluations_doc():
    by_id = _results_by_id(_runner())
    for qa_id in ("QA-001", "QA-002", "QA-012"):
        assert by_id[qa_id].doc_link.endswith("/evaluations"), (
            f"{qa_id} doc_link should land on the evaluations guide; "
            f"got {by_id[qa_id].doc_link!r}"
        )


# ----------------------------------------------------------- PUB deep links


def test_pub_001_links_to_maker_solutions_for_export():
    by_id = _results_by_id(_runner(env_id="env-abc"))
    text = by_id["PUB-001"].remediation
    assert "https://make.powerapps.com/environments/env-abc/solutions" in text, (
        f"PUB-001 must deep-link to the maker Solutions list so the "
        f"operator can find Export → Managed; got: {text!r}"
    )
    # And the operator is told what to actually click.
    assert "Export solution" in text and "Managed" in text


@responses.activate
def test_pub_001_export_present_passes(minimalbots_client):
    from flightcheck.runner import Status

    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/export",
        body=mb.export_package(),
        status=200,
        content_type="application/zip",
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )

    result = _results_by_id(
        _runner(bot_id=mb.MOCK_BOT_ID, minimalbots=minimalbots_client)
    )["PUB-001"]

    assert result.status == Status.PASSED.value
    assert "valid zip package" in result.result


@responses.activate
def test_pub_001_export_empty_fails(minimalbots_client):
    from flightcheck.runner import Status

    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/export",
        body=b"",
        status=200,
        content_type="application/zip",
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )

    result = _results_by_id(
        _runner(bot_id=mb.MOCK_BOT_ID, minimalbots=minimalbots_client)
    )["PUB-001"]

    assert result.status == Status.FAILED.value, result.result
    assert "empty package" in result.result


def test_pub_002_describes_target_environment_import():
    text = _results_by_id(_runner())["PUB-002"].remediation
    # The action happens in a *different* environment than the kit
    # was pointed at, so we can't deep-link — but we must say where.
    assert "test environment" in text.lower()
    assert "Import solution" in text


def test_pub_002_requires_explicit_opt_in(minimalbots_client):
    from flightcheck.runner import Status

    result = _results_by_id(
        _runner(bot_id=mb.MOCK_BOT_ID, minimalbots=minimalbots_client)
    )["PUB-002"]

    assert result.status == Status.SKIPPED.value
    assert "not explicitly enabled" in result.result
    assert "--alm-import-probe" in result.remediation


@responses.activate
def test_pub_002_import_success_and_cleanup_passes(minimalbots_client):
    from flightcheck.runner import Status

    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/export",
        body=mb.export_package(),
        status=200,
        content_type="application/zip",
    )
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/import",
        json=mb.import_result(),
        status=200,
    )
    responses.add(
        responses.DELETE,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}",
        status=204,
    )

    result = _results_by_id(
        _runner(
            bot_id=mb.MOCK_BOT_ID,
            minimalbots=minimalbots_client,
            alm_import_probe=True,
        )
    )["PUB-002"]

    assert result.status == Status.PASSED.value
    assert "cleanup deleted it" in result.result
    deletes = _delete_calls()
    assert len(deletes) == 1
    assert deletes[0].request.url.startswith(
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}"
    )


@responses.activate
def test_pub_002_schema_collision_fails(minimalbots_client):
    from flightcheck.runner import Status

    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/export",
        body=mb.export_package(),
        status=200,
        content_type="application/zip",
    )
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/import",
        status=409,
    )

    result = _results_by_id(
        _runner(
            bot_id=mb.MOCK_BOT_ID,
            minimalbots=minimalbots_client,
            alm_import_probe=True,
        )
    )["PUB-002"]

    assert result.status == Status.FAILED.value, result.result
    assert "schema_collision" in result.result
    assert not _delete_calls()


@responses.activate
def test_pub_002_replays_validated_export_import_schema_collision_cassette(minimalbots_client):
    from flightcheck.checks.publishing import _check_pub_002_import_probe
    from flightcheck.runner import Status

    bot_id = _add_validated_publishing_cassette(base_url=minimalbots_client.base_url)
    runner = _runner(
        bot_id=bot_id,
        minimalbots=minimalbots_client,
        alm_import_probe=True,
    )

    result = _check_pub_002_import_probe(runner, _pub_002_row(runner))

    assert result.status == Status.FAILED.value, result.result
    assert "schema_collision" in result.result
    assert "could not mint a new transient agent" in result.result
    assert not _delete_calls()


@responses.activate
def test_pub_002_delete_called_when_import_result_is_invalid(minimalbots_client):
    from flightcheck.runner import Status

    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/export",
        body=mb.export_package(),
        status=200,
        content_type="application/zip",
    )
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/import",
        json={"cdsBotId": mb.MOCK_BOT_ID},
        status=200,
    )
    responses.add(
        responses.DELETE,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}",
        status=204,
    )

    result = _results_by_id(
        _runner(
            bot_id=mb.MOCK_BOT_ID,
            minimalbots=minimalbots_client,
            alm_import_probe=True,
        )
    )["PUB-002"]

    assert result.status == Status.FAILED.value
    assert "did not return both cdsBotId and schemaName" in result.result
    deletes = _delete_calls()
    assert len(deletes) == 1
    assert deletes[0].request.url.startswith(
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}"
    )


def test_pub_003_is_explicitly_organizational():
    """No portal link applies. The remediation must own that fact so
    the operator doesn't search for a non-existent maker page."""
    text = _results_by_id(_runner())["PUB-003"].remediation
    assert "organizational gate" in text.lower()
    assert "sign-off" in text.lower() or "sign off" in text.lower()


def test_pub_006_links_to_m365_admin_integrated_apps():
    text = _results_by_id(_runner())["PUB-006"].remediation
    expected = (
        "https://admin.microsoft.com/Adminportal/Home#/Settings/IntegratedApps"
    )
    assert expected in text, (
        f"PUB-006 must deep-link to M365 admin → Integrated apps so a "
        f"tenant admin can approve the publish request; got: {text!r}"
    )


def test_pub_011_is_informational_with_no_action_at_publish_time():
    text = _results_by_id(_runner())["PUB-011"].remediation
    # Operators should see explicitly that this row needs no action.
    assert "no action" in text.lower(), (
        f"PUB-011 is a heads-up; the remediation must say no action is "
        f"required at publish time; got: {text!r}"
    )
    # And still link to where to check status if rollout drags.
    assert "Integrated apps" in text
