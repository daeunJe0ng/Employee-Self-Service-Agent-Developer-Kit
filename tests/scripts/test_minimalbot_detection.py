# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic tests for the MinimalBot (Dataverse-free) transport.

Covers detection (``is_minimalbot`` / ``_is_native_da``), ring derivation
(``ring_for_config`` and the per-ring helpers), the ring-aware environment host,
``environmentId`` precedence, the ring-derived client wiring, the ring-aware
Copilot Studio origin/deep-link helpers in ``evaluation_runs``, and the
flag-safety rejections in ``push._minimalbot_push``.

None of these touch the network — they exercise the kit's pure-logic helpers,
which ``tests/AGENTS.md`` exempts from the cassette rule.
"""

from __future__ import annotations

from typing import Any

import pytest

import minimalbot_evaluation as mbe
import evaluation_runs
import push


ENV_ID = "214d162d-0479-e7b3-b118-3ba749943035"
BOT_ID = "fc27c063-49bb-4241-9546-8239e385a267"

TEST_ENDPOINT = "https://abc123.environment.api.test.powerplatform.com"
PREPROD_ENDPOINT = "https://abc123.environment.api.preprod.powerplatform.com"
PROD_ENDPOINT = "https://abc123.environment.api.powerplatform.com"


# -- is_minimalbot / _is_native_da ------------------------------------------


def test_is_minimalbot_true_for_top_level_releaseline_da():
    config = {
        "releaseLine": "da",
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is True


def test_is_minimalbot_true_for_agent_releaseline_da():
    config = {
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID, "releaseLine": "DA"},
    }
    assert mbe.is_minimalbot(config) is True


def test_is_minimalbot_true_for_power_platform_endpoint_marker():
    config = {
        "powerPlatformApiEndpoint": TEST_ENDPOINT,
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is True


def test_is_minimalbot_false_when_dataverse_endpoint_present():
    # A classic agent that also happens to carry a DA marker must NOT be
    # misrouted to the Dataverse-free plane while it has a Dataverse endpoint.
    config = {
        "releaseLine": "da",
        "dataverseEndpoint": "https://contoso.crm.dynamics.com",
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is False


def test_is_minimalbot_false_without_environment_id():
    config = {
        "releaseLine": "da",
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is False


def test_is_minimalbot_false_without_explicit_marker():
    # No dataverseEndpoint AND no DA marker: a half-configured classic agent is
    # not silently treated as a MinimalBot (the core regression this fixes).
    config = {
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID},
    }
    assert mbe.is_minimalbot(config) is False


def test_is_minimalbot_false_for_non_dict():
    assert mbe.is_minimalbot(None) is False  # type: ignore[arg-type]


# -- ring_for_config and per-ring helpers -----------------------------------


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        (TEST_ENDPOINT, "test"),
        (PREPROD_ENDPOINT, "preprod"),
        (PROD_ENDPOINT, "prod"),
    ],
)
def test_ring_for_config_derives_ring_from_endpoint(endpoint, expected):
    assert mbe.ring_for_config({"powerPlatformApiEndpoint": endpoint}) == expected


def test_ring_for_config_defaults_to_prod_when_absent():
    assert mbe.ring_for_config({"environmentId": ENV_ID}) == "prod"


def test_ring_for_config_defaults_to_prod_on_unrecognised_endpoint():
    assert mbe.ring_for_config({"powerPlatformApiEndpoint": "https://x.example"}) == "prod"


def test_api_base_and_scope_per_ring():
    assert mbe._api_base_for_ring("prod") == "https://api.powerplatform.com"
    assert mbe._api_base_for_ring("test") == "https://api.test.powerplatform.com"
    assert mbe._scope_for_ring("test") == "https://api.test.powerplatform.com/.default"


def test_agent_backend_is_cosmos_only_on_test_ring():
    assert mbe._agent_backend_for_ring("test") == "cosmos"
    assert mbe._agent_backend_for_ring("prod") is None
    assert mbe._agent_backend_for_ring("preprod") is None


# -- _environment_host (ring-aware) -----------------------------------------


def test_environment_host_is_ring_specific():
    prod_host = mbe._environment_host(ENV_ID, "prod")
    test_host = mbe._environment_host(ENV_ID, "test")
    assert prod_host.startswith("https://")
    assert prod_host.endswith(".environment.api.powerplatform.com")
    assert test_host.endswith(".environment.api.test.powerplatform.com")
    # The split index differs between rings, so the hosts must not collide.
    assert prod_host != test_host


def test_environment_host_round_trips_through_ring_detection():
    # The host we build for a ring must itself resolve back to that ring.
    from agentbuilder import ring_from_environment_host

    for ring in ("prod", "preprod", "test"):
        host = mbe._environment_host(ENV_ID, ring)
        assert ring_from_environment_host(host) == ring


# -- environmentId precedence -----------------------------------------------


def test_environment_id_prefers_agent_over_top_level():
    config = {
        "environmentId": "top-level-stale",
        "agent": {"environmentId": "agent-specific"},
    }
    assert mbe._environment_id(config) == "agent-specific"


def test_environment_id_falls_back_to_top_level():
    config = {"environmentId": "top-level", "agent": {"botId": BOT_ID}}
    assert mbe._environment_id(config) == "top-level"


# -- client wiring derives from ring ----------------------------------------


def test_client_defaults_to_test_ring():
    client = mbe.MinimalBotEvaluationClient(ENV_ID, BOT_ID, "tenant-1")
    assert client.ring == "test"
    assert client.api_base == "https://api.test.powerplatform.com"
    assert client.scope == "https://api.test.powerplatform.com/.default"
    assert client.agent_backend == "cosmos"
    assert client.host.endswith(".environment.api.test.powerplatform.com")


def test_from_config_derives_prod_ring_and_no_cosmos_backend():
    config = {
        "powerPlatformApiEndpoint": PROD_ENDPOINT,
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID, "releaseLine": "da"},
    }
    client = mbe.MinimalBotEvaluationClient.from_config(config)
    assert client.ring == "prod"
    assert client.api_base == "https://api.powerplatform.com"
    assert client.scope == "https://api.powerplatform.com/.default"
    assert client.agent_backend is None
    assert client.host.endswith(".environment.api.powerplatform.com")


# -- evaluation_runs ring-aware Studio helpers ------------------------------


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        (PROD_ENDPOINT, "https://copilotstudio.microsoft.com"),
        (PREPROD_ENDPOINT, "https://copilotstudio.preprod.microsoft.com"),
        (TEST_ENDPOINT, "https://copilotstudio.test.microsoft.com"),
    ],
)
def test_studio_origin_for_config_is_ring_aware(endpoint, expected):
    assert evaluation_runs._studio_origin_for_config(
        {"powerPlatformApiEndpoint": endpoint}) == expected


def test_studio_origin_falls_back_to_prod_when_endpoint_absent():
    assert (
        evaluation_runs._studio_origin_for_config({})
        == "https://copilotstudio.microsoft.com"
    )


def test_agent_studio_url_deep_link_appends_agent_backend():
    url = evaluation_runs._agent_studio_url(
        "https://copilotstudio.test.microsoft.com",
        ENV_ID,
        BOT_ID,
        test_set_id="set-1",
        run_id="run-1",
        agent_backend="cosmos",
    )
    assert url == (
        "https://copilotstudio.test.microsoft.com"
        f"/environments/{ENV_ID}/copilots/{BOT_ID}"
        "/evaluation/runsDetails/set-1/run-1?agentBackend=cosmos"
    )


def test_agent_studio_url_deep_link_without_backend_has_no_query():
    url = evaluation_runs._agent_studio_url(
        "https://copilotstudio.microsoft.com",
        ENV_ID,
        BOT_ID,
        test_set_id="set-1",
        run_id="run-1",
    )
    assert url is not None
    assert "?agentBackend=" not in url


def test_agent_studio_url_falls_back_to_overview_without_run_ids():
    url = evaluation_runs._agent_studio_url(
        "https://copilotstudio.microsoft.com", ENV_ID, BOT_ID)
    assert url == (
        f"https://copilotstudio.microsoft.com/environments/{ENV_ID}"
        f"/bots/{BOT_ID}/overview"
    )


def test_agent_studio_url_returns_none_when_ids_missing():
    assert evaluation_runs._agent_studio_url("origin", "", BOT_ID) is None
    assert evaluation_runs._agent_studio_url("", ENV_ID, BOT_ID) is None


# -- push._minimalbot_push flag safety (#3) ---------------------------------


def _minimalbot_config(folder: str) -> dict[str, Any]:
    return {
        "powerPlatformApiEndpoint": TEST_ENDPOINT,
        "environmentId": ENV_ID,
        "agent": {"botId": BOT_ID, "folder": folder, "releaseLine": "da"},
    }


def test_minimalbot_push_rejects_force_delete(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        push._minimalbot_push(
            _minimalbot_config(str(tmp_path)),
            dry_run=False,
            force_delete=True,
            repair_mode=False,
            only_globs=None,
        )
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--force-delete is not supported" in out
    assert "No request was made" in out


def test_minimalbot_push_rejects_repair(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        push._minimalbot_push(
            _minimalbot_config(str(tmp_path)),
            dry_run=False,
            force_delete=False,
            repair_mode=True,
            only_globs=None,
        )
    assert exc.value.code == 1
    assert "--repair" in capsys.readouterr().out


def test_warn_minimalbot_non_eval_changes_flags_topic_edits(tmp_path, capsys):
    agent_dir = tmp_path / "agent"
    baseline_dir = agent_dir / ".baseline"
    (baseline_dir / "topics").mkdir(parents=True)
    # A new topic (botcomponent) not under evaluations/ must be surfaced.
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "greet.mcs.yml").write_text("kind: Topic\n", encoding="utf-8")

    push._warn_minimalbot_non_eval_changes(str(agent_dir))
    out = capsys.readouterr().out
    assert "will NOT be pushed" in out
    assert "topics/greet.mcs.yml" in out


def test_warn_minimalbot_non_eval_changes_silent_for_eval_only(tmp_path, capsys):
    agent_dir = tmp_path / "agent"
    baseline_dir = agent_dir / ".baseline"
    baseline_dir.mkdir(parents=True)
    eval_dir = agent_dir / "evaluations" / "set-a"
    eval_dir.mkdir(parents=True)
    (eval_dir / "set.mcs.yml").write_text("kind: EvaluationSet\n", encoding="utf-8")

    push._warn_minimalbot_non_eval_changes(str(agent_dir))
    assert "will NOT be pushed" not in capsys.readouterr().out
