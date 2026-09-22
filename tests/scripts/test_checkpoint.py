# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json

import pytest

import checkpoint


def _write_agent_file(agent_dir, value: str) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "topic.yml").write_text(value, encoding="utf-8")


def test_revert_reason_restores_named_checkpoint(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")

    _write_agent_file(agent_dir, "edited")
    checkpoint.create_checkpoint(str(agent_dir), "auto-save before push")
    _write_agent_file(agent_dir, "pushed")

    checkpoint.cmd_revert_reason(str(agent_dir), "before Workday redirect")

    assert (agent_dir / "topic.yml").read_text(encoding="utf-8") == "before"
    checkpoints_dir = agent_dir / ".checkpoints"
    reasons = []
    for meta_path in checkpoints_dir.glob("*/_meta.json"):
        reasons.append(json.loads(meta_path.read_text(encoding="utf-8"))["reason"])
    assert "auto-save before named revert" in reasons


def test_revert_reason_fails_when_checkpoint_is_missing(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "current")

    with pytest.raises(SystemExit) as exc:
        checkpoint.cmd_revert_reason(str(agent_dir), "missing")

    assert exc.value.code == 1
