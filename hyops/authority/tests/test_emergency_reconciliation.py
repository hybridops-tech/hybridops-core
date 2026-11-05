"""Tests for authority-transition semantics in emergency reconciliation."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from hyops.authority.emergency_reconciliation import (
    create_transition_record,
    decide_provisional_use,
    detect_observation_disagreement,
    distinguish_observation_sources,
    is_observation_fresh,
    record_return_to_declared,
)
from hyops.authority.models import (
    AuthorityObservation,
    AuthorityTransitionPolicy,
)


class TestEmergencyReconciliation(unittest.TestCase):
    """Test authority transition semantics for emergency reconciliation."""

    def setUp(self) -> None:
        """Set up test observations."""
        now = datetime.now(timezone.utc).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        stale = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()

        self.declared = AuthorityObservation(
            token="declared-state-v1",
            observed_at=now,
            scope="production/primary",
            strength="authoritative",
        )

        self.controller_cache_recent = AuthorityObservation(
            token="declared-state-v1",
            observed_at=recent,
            scope="controller/cache",
            strength="inferred",
        )

        self.controller_cache_stale = AuthorityObservation(
            token="declared-state-v1",
            observed_at=stale,
            scope="controller/cache",
            strength="inferred",
        )

        self.live_device_fresh_same = AuthorityObservation(
            token="declared-state-v1",
            observed_at=recent,
            scope="device/live",
            strength="observed",
        )

        self.live_device_fresh_diff = AuthorityObservation(
            token="drift-state-v2",
            observed_at=recent,
            scope="device/live",
            strength="observed",
        )

    def test_detect_no_disagreement(self) -> None:
        """All observations agree - no disagreement."""
        result = detect_observation_disagreement(
            self.declared, self.controller_cache_recent, self.live_device_fresh_same
        )
        self.assertFalse(result)

    def test_detect_disagreement_with_live_device(self) -> None:
        """Live device disagrees with declared intent."""
        result = detect_observation_disagreement(
            self.declared, self.controller_cache_recent, self.live_device_fresh_diff
        )
        self.assertTrue(result)

    def test_detect_disagreement_only_cache(self) -> None:
        """Only declared and cache present - no disagreement."""
        result = detect_observation_disagreement(self.declared, self.controller_cache_recent, None)
        self.assertFalse(result)

    def test_is_observation_fresh_recent(self) -> None:
        """Recent observation is considered fresh."""
        now = datetime.now(timezone.utc).isoformat()
        recent_obs = AuthorityObservation(
            token="test",
            observed_at=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
            scope="test",
            strength="test",
        )
        is_fresh, reason = is_observation_fresh(recent_obs, now, max_age_s=60)
        self.assertTrue(is_fresh)
        self.assertIn("fresh", reason.lower())

    def test_is_observation_stale(self) -> None:
        """Old observation is considered stale."""
        now = datetime.now(timezone.utc).isoformat()
        stale_obs = AuthorityObservation(
            token="test",
            observed_at=(datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
            scope="test",
            strength="test",
        )
        is_fresh, reason = is_observation_fresh(stale_obs, now, max_age_s=60)
        self.assertFalse(is_fresh)
        self.assertIn("exceeds threshold", reason)

    def test_is_observation_no_timestamp(self) -> None:
        """Observation with no timestamp is not fresh."""
        obs = AuthorityObservation(
            token="test", observed_at="", scope="test", strength="test"
        )
        is_fresh, reason = is_observation_fresh(obs)
        self.assertFalse(is_fresh)
        self.assertIn("no timestamp", reason)

    def test_distinguish_observation_sources_all_present(self) -> None:
        """Distinguish sources when all observations are present."""
        sources = distinguish_observation_sources(
            self.declared, self.controller_cache_recent, self.live_device_fresh_same
        )

        self.assertIn("declared", sources)
        self.assertIn("controller_cache", sources)
        self.assertIn("live_device", sources)

        self.assertEqual(sources["declared"].source_type, "declared")
        self.assertEqual(sources["declared"].freshness_basis, "verified")
        self.assertEqual(sources["controller_cache"].source_type, "controller_cache")
        self.assertEqual(sources["live_device"].source_type, "live_device")

    def test_distinguish_stale_controller_cache(self) -> None:
        """Stale controller cache is marked unverifiable."""
        sources = distinguish_observation_sources(
            self.declared, self.controller_cache_stale, self.live_device_fresh_same
        )

        cache_source = sources.get("controller_cache")
        self.assertIsNotNone(cache_source)
        self.assertIn("exceeds threshold", cache_source.metadata.get("freshness_reason", ""))

    def test_decide_provisional_use_allowed(self) -> None:
        """Provisional use is allowed when policy permits."""
        policy = AuthorityTransitionPolicy(
            allow_provisional_use=True,
            require_explicit_decision=False,
            max_provisional_duration_s=300,
            failure_mode="provisional_ok",
            record_unverifiable=True,
        )

        decision = decide_provisional_use(
            self.declared, self.live_device_fresh_diff, policy, operator_decision=True
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.decision_type, "provisional_use")
        self.assertIn("recover", decision.rationale.lower())

    def test_decide_provisional_use_requires_decision(self) -> None:
        """Provisional use denied when explicit decision required but not given."""
        policy = AuthorityTransitionPolicy(
            allow_provisional_use=True,
            require_explicit_decision=True,
            max_provisional_duration_s=300,
            failure_mode="fail_closed",
            record_unverifiable=True,
        )

        decision = decide_provisional_use(
            self.declared, self.live_device_fresh_diff, policy, operator_decision=False
        )

        self.assertIsNone(decision)

    def test_decide_provisional_use_policy_denied(self) -> None:
        """Provisional use denied when policy doesn't allow it."""
        policy = AuthorityTransitionPolicy(
            allow_provisional_use=False,
            require_explicit_decision=False,
            max_provisional_duration_s=0,
            failure_mode="fail_closed",
            record_unverifiable=False,
        )

        decision = decide_provisional_use(
            self.declared, self.live_device_fresh_diff, policy, operator_decision=True
        )

        self.assertIsNone(decision)

    def test_create_transition_record_no_transition(self) -> None:
        """Transition record with no transition when all agree."""
        record = create_transition_record(
            "primary_ipam",
            "inventory_ipam",
            "netbox",
            self.declared,
            self.controller_cache_recent,
            self.live_device_fresh_same,
            None,
        )

        self.assertEqual(record.transition_type, "no_transition")
        self.assertFalse(record.detected_disagreement)

    def test_create_transition_record_with_disagreement(self) -> None:
        """Transition record detects disagreement."""
        record = create_transition_record(
            "primary_ipam",
            "inventory_ipam",
            "netbox",
            self.declared,
            self.controller_cache_recent,
            self.live_device_fresh_diff,
            None,
        )

        self.assertEqual(record.transition_type, "keep_declared")
        self.assertTrue(record.detected_disagreement)

    def test_record_return_to_declared(self) -> None:
        """Record return transition back to declared authority."""
        initial_record = create_transition_record(
            "primary_ipam",
            "inventory_ipam",
            "netbox",
            self.declared,
            None,
            self.live_device_fresh_diff,
            None,
        )

        return_record = record_return_to_declared(
            initial_record, return_condition_met=True, result="declared state re-verified"
        )

        self.assertTrue(return_record.return_condition_met)
        self.assertEqual(return_record.return_result, "declared state re-verified")
        self.assertNotEqual(return_record.return_to_declared_at, "")

    def test_transition_record_to_evidence(self) -> None:
        """Transition record serializes to evidence without credentials."""
        policy = AuthorityTransitionPolicy(
            allow_provisional_use=True,
            require_explicit_decision=False,
            max_provisional_duration_s=300,
            failure_mode="provisional_ok",
            record_unverifiable=True,
        )

        decision = decide_provisional_use(
            self.declared, self.live_device_fresh_diff, policy, operator_decision=True
        )

        record = create_transition_record(
            "primary_ipam",
            "inventory_ipam",
            "netbox",
            self.declared,
            self.controller_cache_recent,
            self.live_device_fresh_diff,
            decision,
        )

        evidence = record.to_evidence()

        # Verify structure and content
        self.assertEqual(evidence["logical_authority"], "primary_ipam")
        self.assertEqual(evidence["capability"], "inventory_ipam")
        self.assertTrue(evidence["detected_disagreement"])
        self.assertEqual(evidence["transition_type"], "provisional_use")
        self.assertIn("declared_authority", evidence)
        self.assertIn("live_device_state", evidence)
        self.assertIn("transition_decision", evidence)

        # Verify no credentials/secrets in evidence
        # (note: "token" is the authority state value, not a credential)
        evidence_str = str(evidence).lower()
        self.assertNotIn("secret", evidence_str)
        self.assertNotIn("password", evidence_str)
        self.assertNotIn("credential", evidence_str)
        self.assertNotIn("api_key", evidence_str)


if __name__ == "__main__":
    unittest.main()
