# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the FlightCheck runner's single-checkpoint filtering.

Pure-logic tests (no network, no clients) — the cardinal cassette rule in
``tests/AGENTS.md`` explicitly excludes "tests of the kit's pure-logic
helpers (no network)". These pin the ``FlightCheckRunner`` hydrate-then-
filter contract that ``cli._run_single_checkpoint`` relies on:

  * a ``target_matcher`` keeps only the rows it accepts (exact target or a
    whole family) and drops the rest of the hydration rows,
  * a synthetic ``{CAT}-ERR`` sentinel (appended when a category function
    raises) is ALWAYS retained — even when it doesn't match the target — so
    a hydration/owner failure surfaces as an error instead of an empty,
    falsely-green run,
  * ``target_matcher=None`` (full/scope runs) applies no filter,
  * the sentinel's id/status/priority shape is stable, and a raised check
    counts as an ERROR (``RunResult.errors``) not a FAILED
    (``RunResult.failed``) — the distinction the CLI exit code depends on.
"""

from __future__ import annotations

from flightcheck.runner import (
    CheckResult,
    FlightCheckRunner,
    Priority,
    Role,
    Status,
)


def _row(
    checkpoint_id: str,
    category: str,
    status: str = Status.PASSED.value,
) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=category,
        priority=Priority.MEDIUM.value,
        status=status,
        description=f"{checkpoint_id} check",
        result="ok",
    )


def _fn_returning(*rows: CheckResult):
    def _fn(runner):  # noqa: ARG001 — runner arg is the check-fn contract
        return list(rows)

    return _fn


def _fn_raising(message: str = "boom"):
    def _fn(runner):  # noqa: ARG001
        raise RuntimeError(message)

    return _fn


class TestTargetMatcherFiltering:
    def test_family_matcher_keeps_only_family_rows(self) -> None:
        runner = FlightCheckRunner(
            scope="checkpoint:WD-FLOW",
            target_matcher=lambda cid: cid == "WD-FLOW" or cid.startswith("WD-FLOW-"),
        )
        runner.register(
            "Workday",
            _fn_returning(
                _row("WD-FLOW-001", "Workday"),
                _row("WD-FLOW-002", "Workday"),
            ),
        )
        runner.register("Environment", _fn_returning(_row("ENV-001", "Environment")))

        result = runner.run()

        ids = [r.checkpoint_id for r in result.results]
        assert ids == ["WD-FLOW-001", "WD-FLOW-002"]
        assert "ENV-001" not in ids

    def test_exact_matcher_keeps_single_row(self) -> None:
        runner = FlightCheckRunner(
            scope="checkpoint:WD-FLOW-002",
            target_matcher=lambda cid: cid == "WD-FLOW-002",
        )
        runner.register(
            "Workday",
            _fn_returning(
                _row("WD-FLOW-001", "Workday"),
                _row("WD-FLOW-002", "Workday"),
            ),
        )

        result = runner.run()

        assert [r.checkpoint_id for r in result.results] == ["WD-FLOW-002"]


class TestDuplicateRowCollapse:
    def test_identical_rows_from_two_functions_collapse_to_one(self) -> None:
        # A profile/target run can register both a broad category function and
        # a single-purpose wrapper that re-runs the same underlying check,
        # yielding byte-identical rows. The matcher-filtered run must collapse
        # them to one (the ENV-009 / ENV-CAPACITY-001 double-emit seen live).
        dup = _row("ENV-009", "Environment", Status.FAILED.value)
        runner = FlightCheckRunner(
            scope="profile:workday-setup",
            target_matcher=lambda cid: cid in {"ENV-001", "ENV-009"},
        )
        # Broad sweep emits ENV-001 and ENV-009; the dedicated wrapper emits
        # an identical ENV-009 row.
        runner.register(
            "Environment",
            _fn_returning(_row("ENV-001", "Environment"), dup),
        )
        runner.register("Environment", _fn_returning(_row("ENV-009", "Environment",
                                                          Status.FAILED.value)))

        result = runner.run()

        ids = [r.checkpoint_id for r in result.results]
        assert ids == ["ENV-001", "ENV-009"]
        assert ids.count("ENV-009") == 1

    def test_distinct_same_id_rows_are_kept(self) -> None:
        # Rows sharing a checkpoint_id but differing in status/evidence are
        # genuinely distinct and must NOT be collapsed.
        runner = FlightCheckRunner(
            scope="profile:p",
            target_matcher=lambda cid: cid == "WD-FLOW-001",
        )
        row_pass = _row("WD-FLOW-001", "Workday", Status.PASSED.value)
        row_fail = CheckResult(
            checkpoint_id="WD-FLOW-001",
            category="Workday",
            priority=Priority.MEDIUM.value,
            status=Status.FAILED.value,
            description="WD-FLOW-001 check",
            result="different evidence",
        )
        runner.register("Workday", _fn_returning(row_pass, row_fail))

        result = runner.run()

        assert len(result.results) == 2


class TestErrSentinelRetention:
    def test_err_sentinel_retained_even_when_unmatched(self) -> None:
        runner = FlightCheckRunner(
            scope="checkpoint:WD-FLOW-001",
            target_matcher=lambda cid: cid == "WD-FLOW-001",
        )
        # A prerequisite/owner category that raises → "PRE-ERR" sentinel.
        runner.register("Prerequisites", _fn_raising())
        runner.register(
            "Workday",
            _fn_returning(
                _row("WD-FLOW-001", "Workday"),
                _row("WD-FLOW-002", "Workday"),
            ),
        )

        result = runner.run()

        ids = [r.checkpoint_id for r in result.results]
        # Target row kept, sibling dropped, sentinel retained though it does
        # not match the target matcher.
        assert "WD-FLOW-001" in ids
        assert "WD-FLOW-002" not in ids
        assert "PRE-ERR" in ids

    def test_err_sentinel_shape_is_stable(self) -> None:
        runner = FlightCheckRunner(
            scope="checkpoint:X",
            target_matcher=lambda cid: cid == "NOPE",
        )
        runner.register("Prerequisites", _fn_raising("kaboom"))

        result = runner.run()

        sentinels = [r for r in result.results if r.checkpoint_id.endswith("-ERR")]
        assert len(sentinels) == 1
        sentinel = sentinels[0]
        assert sentinel.checkpoint_id == "PRE-ERR"  # category[:3].upper() + "-ERR"
        assert sentinel.status == Status.ERROR.value
        assert sentinel.priority == Priority.HIGH.value
        assert sentinel.category == "Prerequisites"
        assert Role.ESS_MAKER.value in sentinel.roles
        assert "kaboom" in sentinel.result

    def test_err_only_run_is_not_ready_but_not_failed(self) -> None:
        """A raised category function is an ERROR, not a FAILED result.

        Both CLI modes treat either count as a nonzero exit.
        """
        runner = FlightCheckRunner(
            scope="checkpoint:WD-FLOW-001",
            target_matcher=lambda cid: cid == "WD-FLOW-001",
        )
        runner.register("Prerequisites", _fn_raising())

        result = runner.run()

        assert result.failed == 0
        assert result.errors == 1
        assert result.overall == "NOT_READY"


class TestNoMatcherNoFilter:
    def test_matcher_none_keeps_all_rows(self) -> None:
        runner = FlightCheckRunner(scope="full")  # target_matcher defaults to None
        runner.register(
            "Workday",
            _fn_returning(
                _row("WD-FLOW-001", "Workday"),
                _row("WD-FLOW-002", "Workday"),
            ),
        )
        runner.register("Environment", _fn_returning(_row("ENV-001", "Environment")))

        result = runner.run()

        ids = sorted(r.checkpoint_id for r in result.results)
        assert ids == ["ENV-001", "WD-FLOW-001", "WD-FLOW-002"]

    def test_matcher_none_keeps_err_sentinel_and_rows(self) -> None:
        runner = FlightCheckRunner(scope="full")
        runner.register("Prerequisites", _fn_raising())
        runner.register("Workday", _fn_returning(_row("WD-FLOW-001", "Workday")))

        result = runner.run()

        ids = sorted(r.checkpoint_id for r in result.results)
        assert ids == ["PRE-ERR", "WD-FLOW-001"]
