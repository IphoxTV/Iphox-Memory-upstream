from __future__ import annotations

from dataclasses import dataclass

from .schema import MemoryKind, MemoryRecord, MemoryStatus, VerificationLevel


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    promote: bool
    reasons: tuple[str, ...]


def evaluate_promotion(
    record: MemoryRecord,
    *,
    explicit_user_request: bool = False,
    repeated_signal: bool = False,
    source_verified: bool = False,
) -> PromotionDecision:
    """Decide whether a candidate deserves durable memory.

    The gate is intentionally conservative: session chatter does not become memory
    by default, and volatile facts/projects need either verification or repetition.
    """
    if record.status is not MemoryStatus.CANDIDATE:
        return PromotionDecision(False, ("only candidate memories enter the promotion gate",))

    reasons: list[str] = []
    if explicit_user_request:
        reasons.append("user explicitly requested durable memory")
    if repeated_signal:
        reasons.append("same signal was observed repeatedly")
    if source_verified or record.verification is VerificationLevel.VERIFIED:
        reasons.append("source is verified")
    if record.importance >= 0.8:
        reasons.append("high importance")

    if record.kind is MemoryKind.SESSION:
        return PromotionDecision(False, ("session detail belongs in handoff/session history, not durable memory",))

    if record.kind in {MemoryKind.RULE, MemoryKind.DECISION, MemoryKind.PREFERENCE}:
        promote = explicit_user_request or repeated_signal or source_verified or record.importance >= 0.8
        return PromotionDecision(promote, tuple(reasons) or ("insufficient durability signal",))

    if record.kind in {MemoryKind.FACT, MemoryKind.PROJECT, MemoryKind.HANDOFF}:
        promote = explicit_user_request or source_verified or repeated_signal
        return PromotionDecision(promote, tuple(reasons) or ("volatile memory lacks verification or repetition",))

    if record.kind in {MemoryKind.PROFILE, MemoryKind.LESSON}:
        promote = explicit_user_request or repeated_signal or source_verified
        return PromotionDecision(promote, tuple(reasons) or ("insufficient durability signal",))

    return PromotionDecision(False, ("unsupported memory type",))
