# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Helpers for reading agent connection references from minimalBots PPAPI."""

from __future__ import annotations

import json
from typing import Any


WORKDAY_SOAP_CONNECTOR_ID = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"


def agent_bot_ids(config: dict[str, Any]) -> list[str]:
    """Return configured bot IDs from single-agent and multi-agent config shapes."""
    bot_ids: list[str] = []
    for agent in config.get("agents", []) or []:
        bid = (agent or {}).get("botId")
        if isinstance(bid, str) and bid.strip():
            bot_ids.append(bid.strip())
    if not bot_ids:
        single = (config.get("agent") or {}).get("botId")
        if isinstance(single, str) and single.strip():
            bot_ids.append(single.strip())

    seen: set[str] = set()
    ordered: list[str] = []
    for bid in bot_ids:
        if bid not in seen:
            seen.add(bid)
            ordered.append(bid)
    return ordered


def connection_reference(change: dict[str, Any]) -> dict[str, Any]:
    """Unwrap a minimalBots connectionReferenceChange into its reference payload."""
    nested = change.get("connectionReference")
    if isinstance(nested, dict):
        return nested
    return change


def is_workday_reference(change: dict[str, Any]) -> bool:
    ref = connection_reference(change)
    connector_id = str(ref.get("connectorId") or ref.get("connectorid") or "").lower()
    logical_name = str(
        ref.get("connectionReferenceLogicalName")
        or ref.get("connectionreferencelogicalname")
        or ref.get("logicalName")
        or ""
    ).lower()
    display_name = str(ref.get("displayName") or ref.get("displayname") or "").lower()

    return (
        connector_id.endswith("/apis/shared_workdaysoap")
        or "shared_workdaysoap" in logical_name
        or "workday" in display_name
    )


def shared_connection_parameter_values(change: dict[str, Any]) -> dict[str, str]:
    """Return sharedConnectionParameters.values as a simple key/value map."""
    ref = connection_reference(change)
    raw_params = ref.get("sharedConnectionParameters") or ref.get(
        "sharedconnectionparameters"
    )
    if isinstance(raw_params, str):
        try:
            raw_params = json.loads(raw_params)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw_params, dict):
        return {}

    raw_values = raw_params.get("values")
    if not isinstance(raw_values, dict):
        return {}

    values: dict[str, str] = {}
    for key, raw_value in raw_values.items():
        if not isinstance(key, str):
            continue
        value = raw_value.get("value") if isinstance(raw_value, dict) else raw_value
        if value is None:
            continue
        values[key] = str(value)
    return values


def workday_shared_connection_parameters(runner) -> tuple[dict[str, str] | None, str]:
    """Read Workday shared connection parameters via runner.minimalbots."""
    minimalbots = getattr(runner, "minimalbots", None)
    if minimalbots is None:
        return None, "minimalBots client is not available"

    config = getattr(runner, "config", None) or {}
    bot_ids = agent_bot_ids(config)
    if not bot_ids:
        return None, "agent botId is not configured"

    for bot_id in bot_ids:
        refs = minimalbots.get_connection_references(bot_id)
        if not isinstance(refs, list):
            continue
        for change in refs:
            if isinstance(change, dict) and is_workday_reference(change):
                values = shared_connection_parameter_values(change)
                if values:
                    return values, ""
                return None, (
                    "Workday connection reference is missing "
                    "sharedConnectionParameters.values"
                )

    return None, "Workday connection reference was not found"
