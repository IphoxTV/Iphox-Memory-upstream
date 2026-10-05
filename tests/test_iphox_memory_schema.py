from datetime import datetime, timedelta, timezone
import unittest

from src.iphox_memory import (
    MemoryKind,
    MemoryRecord,
    MemoryStatus,
    VerificationLevel,
    evaluate_promotion,
    parse_memory_markdown,
    rank_for_context,
    render_memory_markdown,
    transition_memory,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)


def record(memory_id: str, *, kind=MemoryKind.FACT, status=MemoryStatus.ACTIVE, project=None,
           verification=VerificationLevel.OBSERVED, importance=0.5, confidence=0.7,
           updated_at=NOW, verified_at=None, body="Useful memory body", superseded_by=None):
    return MemoryRecord(
        memory_id=memory_id,
        title=memory_id.replace("-", " ").title(),
        kind=kind,
        status=status,
        body=body,
        project=project,
        created_at=NOW - timedelta(days=10),
        updated_at=updated_at,
        verified_at=verified_at,
        verification=verification,
        importance=importance,
        confidence=confidence,
        superseded_by=superseded_by,
        tags=("memory", "test"),
    )


class MemorySchemaTests(unittest.TestCase):
    def test_round_trip_markdown(self):
        original = MemoryRecord(
            memory_id="fiber/ui-linux-rule",
            title="Linux UI is QA, not a fork",
            kind=MemoryKind.RULE,
            status=MemoryStatus.ACTIVE,
            body="Linux and Windows compile the same shared C++/ImGui UI.",
            project="FIBER",
            created_at=NOW - timedelta(days=2),
            updated_at=NOW,
            verified_at=NOW,
            verification=VerificationLevel.VERIFIED,
            source="github",
            source_ref="abc123",
            tags=("ui", "linux", "imgui"),
            importance=0.95,
            confidence=1.0,
        )
        parsed = parse_memory_markdown(render_memory_markdown(original))
        self.assertEqual(parsed, original)

    def test_superseded_requires_target(self):
        with self.assertRaises(ValueError):
            record("project/old-state", status=MemoryStatus.SUPERSEDED)

    def test_transition_preserves_history(self):
        active = record("fiber/state", project="FIBER")
        old = transition_memory(active, MemoryStatus.SUPERSEDED, superseded_by="fiber/state-v2", now=NOW)
        self.assertEqual(old.status, MemoryStatus.SUPERSEDED)
        self.assertEqual(old.superseded_by, "fiber/state-v2")
        with self.assertRaises(ValueError):
            transition_memory(old, MemoryStatus.ACTIVE, now=NOW)

    def test_rank_excludes_historical_truth(self):
        records = [
            record("fiber/current-rule", kind=MemoryKind.RULE, project="FIBER", importance=0.9,
                   body="Use one shared ImGui UI for Linux visual QA."),
            record("fiber/old-rule", kind=MemoryKind.RULE, project="FIBER", importance=1.0,
                   body="Old duplicated UI rule", status=MemoryStatus.SUPERSEDED,
                   superseded_by="fiber/current-rule"),
            record("other/rule", kind=MemoryKind.RULE, project="ENDLESS", importance=1.0),
        ]
        ranked = rank_for_context(records, "Linux ImGui UI", project="FIBER", now=NOW)
        self.assertEqual([x.memory_id for x in ranked], ["fiber/current-rule", "other/rule"])
        self.assertNotIn("fiber/old-rule", [x.memory_id for x in ranked])

    def test_verified_requires_timestamp(self):
        with self.assertRaises(ValueError):
            record("fact/no-proof", verification=VerificationLevel.VERIFIED)

    def test_promotion_gate_rejects_chat_noise(self):
        candidate = record("session/random", kind=MemoryKind.SESSION, status=MemoryStatus.CANDIDATE)
        decision = evaluate_promotion(candidate, explicit_user_request=True)
        self.assertFalse(decision.promote)

    def test_promotion_gate_accepts_explicit_rule(self):
        candidate = record("rules/no-actions", kind=MemoryKind.RULE, status=MemoryStatus.CANDIDATE,
                           importance=0.9)
        decision = evaluate_promotion(candidate, explicit_user_request=True)
        self.assertTrue(decision.promote)


if __name__ == "__main__":
    unittest.main()
