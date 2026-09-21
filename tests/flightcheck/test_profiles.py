# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the FlightCheck Connect-facing validation profiles.

Pure-logic tests (no network, no clients) — the cardinal cassette rule in
``tests/AGENTS.md`` explicitly excludes "tests of the kit's pure-logic
helpers (no network)". A profile introduces no new endpoint; it only groups
already-registered checkpoint IDs. These pin the profile registry's
validity, resolution, union-plan, and matcher invariants the Connect
gating feature relies on.
"""

from __future__ import annotations

import pytest

from flightcheck import profiles, registry
from flightcheck.profiles import Profile, ProfileError


class TestValidateProfiles:
    """The shipped profiles must be internally consistent."""

    def test_shipped_profiles_are_valid(self):
        # Import already ran validate_profiles() once; calling it again must
        # not raise for the real profile set.
        profiles.validate_profiles()

    def test_every_member_resolves_to_a_registered_checkpoint(self):
        for profile in profiles.PROFILES.values():
            for member in profile.members:
                assert registry.resolve(member) is not None, (
                    f"profile {profile.name!r} references unresolvable "
                    f"member {member!r}"
                )

    def test_empty_member_list_is_rejected(self, monkeypatch):
        bad = Profile(name="empty", title="t", description="d", members=())
        monkeypatch.setattr(profiles, "_PROFILES", [bad])
        with pytest.raises(ProfileError, match="no members"):
            profiles.validate_profiles()

    def test_unresolvable_member_is_rejected(self, monkeypatch):
        bad = Profile(
            name="bad", title="t", description="d",
            members=("DOES-NOT-EXIST",),
        )
        monkeypatch.setattr(profiles, "_PROFILES", [bad])
        with pytest.raises(ProfileError, match="does not resolve"):
            profiles.validate_profiles()

    def test_duplicate_name_is_rejected(self, monkeypatch):
        a = Profile(name="dup", title="t", description="d", members=("ENV-001",))
        b = Profile(name="dup", title="t", description="d", members=("ENV-002",))
        monkeypatch.setattr(profiles, "_PROFILES", [a, b])
        with pytest.raises(ProfileError, match="Duplicate profile name"):
            profiles.validate_profiles()


class TestResolveProfile:
    """Name -> Profile lookup."""

    def test_known_profile_resolves(self):
        p = profiles.resolve_profile("workday-setup")
        assert p is not None
        assert p.name == "workday-setup"
        assert "WD-PKG-001" in p.members

    def test_unknown_profile_returns_none(self):
        assert profiles.resolve_profile("does-not-exist") is None

    def test_empty_name_returns_none(self):
        assert profiles.resolve_profile("") is None

    def test_list_profiles_is_sorted_and_complete(self):
        listed = profiles.list_profiles()
        assert [p.name for p in listed] == sorted(profiles.PROFILES)
        assert len(listed) == len(profiles.PROFILES)


class TestUmbrellaProfile:
    """The 'workday' umbrella profile unions every staged profile."""

    def test_umbrella_exists(self):
        assert "workday" in profiles.PROFILES

    def test_umbrella_is_union_of_staged_profiles(self):
        umbrella = set(profiles.PROFILES["workday"].members)
        staged = {
            m
            for name, p in profiles.PROFILES.items()
            if name != "workday"
            for m in p.members
        }
        assert umbrella == staged

    def test_umbrella_members_are_deduped(self):
        members = profiles.PROFILES["workday"].members
        assert len(members) == len(set(members))


class TestProfileMatcher:
    """The matcher keeps rows owned by ANY member, family-aware."""

    def test_exact_member_matches_only_itself(self):
        match = profiles.profile_matcher(("WD-PKG-001",))
        assert match("WD-PKG-001") is True
        assert match("WD-REST-001") is False

    def test_family_member_matches_family_namespace(self):
        # WD-CONN is a family; its dynamic children must match.
        match = profiles.profile_matcher(("WD-CONN",))
        assert match("WD-CONN-003") is True
        assert match("WD-CONN-012") is True  # fixed child still in namespace
        assert match("WD-PKG-001") is False

    def test_any_member_matches(self):
        match = profiles.profile_matcher(("ENV-001", "ESS-SOLN-001"))
        assert match("ENV-001") is True
        assert match("ESS-SOLN-001") is True
        assert match("WD-RUN-001") is False


class TestCombinedRequirements:
    """The union plan spans every member's transitive closure."""

    def test_clients_are_the_union_of_members(self):
        # Union of two members must be a superset of each member alone.
        one = registry.transitive_requirements("ENV-001").clients
        two = registry.transitive_requirements("WD-RUN-001").clients
        clients, _cfg, _dv, _fns = profiles.combined_requirements(
            ("ENV-001", "WD-RUN-001")
        )
        assert one <= clients
        assert two <= clients

    def test_requires_config_is_or_of_members(self):
        _clients, requires_config, _dv, _fns = profiles.combined_requirements(
            ("ENV-001",)
        )
        assert requires_config == (
            registry.transitive_requirements("ENV-001").requires_config
        )

    def test_ordered_fns_are_deduped_by_function(self):
        # Two Workday-family members share run_workday_checks; it must appear
        # exactly once in the merged plan.
        _clients, _cfg, _dv, fns = profiles.combined_requirements(
            ("WD-RUN-001", "WD-PKG-001")
        )
        seen = [fn for _label, fn in fns]
        assert len(seen) == len(set(seen)), "category fns must be de-duped"

    def test_ordered_fns_follow_category_order(self):
        _clients, _cfg, _dv, fns = profiles.combined_requirements(
            ("WD-RUN-001", "ENV-001")
        )
        labels = [label for label, _fn in fns]
        indices = [
            registry.CATEGORY_ORDER.index(label)
            for label in labels
            if label in registry.CATEGORY_ORDER
        ]
        assert indices == sorted(indices), (
            "category fns must be ordered by CATEGORY_ORDER"
        )


class TestResolvePlan:
    """End-to-end: name -> ProfilePlan."""

    def test_resolve_plan_populates_every_field(self):
        plan = profiles.resolve_plan("workday-setup")
        assert plan.profile.name == "workday-setup"
        assert plan.ordered_fns, "a profile plan must register at least one fn"
        assert callable(plan.matcher)
        # The matcher must accept at least one of the profile's own members.
        assert plan.matcher("WD-PKG-001") is True

    def test_unknown_profile_raises(self):
        with pytest.raises(ProfileError, match="not registered"):
            profiles.resolve_plan("nope")
