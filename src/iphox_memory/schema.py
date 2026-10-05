from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Iterable

import yaml


class MemoryKind(StrEnum):
    PROFILE = "profile"
    PROJECT = "project"
    DECISION = "decision"
    FACT = "fact"
    PREFERENCE = "preference"
    HANDOFF = "handoff"
    LESSON = "lesson"
    RULE = "rule"
    SESSION = "session"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class VerificationLevel(StrEnum):
    INFERRED = "inferred"
    OBSERVED = "observed"
    VERIFIED = "verified"


_ALLOWED_TRANSITIONS: dict[MemoryStatus, frozenset[MemoryStatus]] = {
    MemoryStatus.CANDIDATE: frozenset({MemoryStatus.ACTIVE, MemoryStatus.ARCHIVED}),
    MemoryStatus.ACTIVE: frozenset({MemoryStatus.STALE, MemoryStatus.SUPERSEDED, MemoryStatus.ARCHIVED}),
    MemoryStatus.STALE: frozenset({MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED, MemoryStatus.ARCHIVED}),
    MemoryStatus.SUPERSEDED: frozenset({MemoryStatus.ARCHIVED}),
    MemoryStatus.ARCHIVED: frozenset(),
}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{2,159}$")
_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_./+-]{1,}", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _aware_utc(value)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    return _aware_utc(parsed)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    title: str
    kind: MemoryKind
    status: MemoryStatus
    body: str
    project: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    verified_at: datetime | None = None
    verification: VerificationLevel = VerificationLevel.INFERRED
    source: str | None = None
    source_ref: str | None = None
    supersedes: tuple[str, ...] = ()
    superseded_by: str | None = None
    tags: tuple[str, ...] = ()
    importance: float = 0.5
    confidence: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _aware_utc(self.created_at) or _utcnow())
        object.__setattr__(self, "updated_at", _aware_utc(self.updated_at) or self.created_at)
        object.__setattr__(self, "verified_at", _aware_utc(self.verified_at))
        object.__setattr__(self, "supersedes", tuple(dict.fromkeys(self.supersedes)))
        object.__setattr__(self, "tags", tuple(dict.fromkeys(tag.strip() for tag in self.tags if tag.strip())))
        self.validate()

    def validate(self) -> None:
        if not _ID_RE.fullmatch(self.memory_id):
            raise ValueError("memory_id must be a stable lowercase id/path-like key")
        if not self.title.strip():
            raise ValueError("title is required")
        if not self.body.strip():
            raise ValueError("body is required")
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError("importance must be between 0 and 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.verified_at and self.verified_at < self.created_at:
            raise ValueError("verified_at cannot precede created_at")
        if self.memory_id in self.supersedes:
            raise ValueError("a memory cannot supersede itself")
        if self.superseded_by == self.memory_id:
            raise ValueError("a memory cannot be superseded by itself")
        if self.status is MemoryStatus.SUPERSEDED and not self.superseded_by:
            raise ValueError("superseded memories require superseded_by")
        if self.status is not MemoryStatus.SUPERSEDED and self.superseded_by:
            raise ValueError("superseded_by is only valid when status=superseded")
        if self.verification is VerificationLevel.VERIFIED and self.verified_at is None:
            raise ValueError("verified memories require verified_at")

    @property
    def is_context_eligible(self) -> bool:
        return self.status in {MemoryStatus.ACTIVE, MemoryStatus.STALE}


def transition_memory(
    record: MemoryRecord,
    new_status: MemoryStatus,
    *,
    superseded_by: str | None = None,
    verified_at: datetime | None = None,
    verification: VerificationLevel | None = None,
    now: datetime | None = None,
) -> MemoryRecord:
    """Apply a fail-closed lifecycle transition.

    History is preserved: superseding marks the old record instead of deleting it.
    """
    if new_status is record.status:
        raise ValueError("transition must change status")
    if new_status not in _ALLOWED_TRANSITIONS[record.status]:
        raise ValueError(f"invalid transition: {record.status} -> {new_status}")
    if new_status is MemoryStatus.SUPERSEDED and not superseded_by:
        raise ValueError("superseded transition requires superseded_by")
    if new_status is not MemoryStatus.SUPERSEDED and superseded_by:
        raise ValueError("superseded_by only applies to superseded transition")
    stamp = _aware_utc(now) or _utcnow()
    return replace(
        record,
        status=new_status,
        updated_at=stamp,
        superseded_by=superseded_by if new_status is MemoryStatus.SUPERSEDED else None,
        verified_at=_aware_utc(verified_at) if verified_at is not None else record.verified_at,
        verification=verification or record.verification,
    )


def _frontmatter(record: MemoryRecord) -> dict[str, object]:
    data: dict[str, object] = {
        "memory_id": record.memory_id,
        "type": record.kind.value,
        "status": record.status.value,
        "verification": record.verification.value,
        "importance": round(record.importance, 4),
        "confidence": round(record.confidence, 4),
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }
    optional: tuple[tuple[str, object], ...] = (
        ("project", record.project),
        ("verified_at", _iso(record.verified_at)),
        ("source", record.source),
        ("source_ref", record.source_ref),
        ("supersedes", list(record.supersedes) or None),
        ("superseded_by", record.superseded_by),
        ("tags", list(record.tags) or None),
    )
    for key, value in optional:
        if value not in (None, "", [], ()):
            data[key] = value
    return data


def render_memory_markdown(record: MemoryRecord) -> str:
    """Render canonical human-readable Markdown; Markdown remains the source of truth."""
    front = yaml.safe_dump(_frontmatter(record), sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n# {record.title.strip()}\n\n{record.body.rstrip()}\n"


def parse_memory_markdown(text: str) -> MemoryRecord:
    if not text.startswith("---\n"):
        raise ValueError("memory note must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("memory note has unterminated YAML frontmatter")
    raw_front = text[4:end]
    payload = yaml.safe_load(raw_front) or {}
    if not isinstance(payload, dict):
        raise ValueError("frontmatter must be a mapping")
    content = text[end + 5 :].lstrip("\n")
    lines = content.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("memory note must start with an H1 title after frontmatter")
    title = lines[0][2:].strip()
    body = "\n".join(lines[1:]).strip()
    return MemoryRecord(
        memory_id=str(payload.get("memory_id", "")),
        title=title,
        kind=MemoryKind(str(payload.get("type", ""))),
        status=MemoryStatus(str(payload.get("status", ""))),
        body=body,
        project=str(payload["project"]) if payload.get("project") is not None else None,
        created_at=_parse_datetime(payload.get("created_at"), "created_at"),
        updated_at=_parse_datetime(payload.get("updated_at"), "updated_at"),
        verified_at=_parse_datetime(payload.get("verified_at"), "verified_at"),
        verification=VerificationLevel(str(payload.get("verification", VerificationLevel.INFERRED.value))),
        source=str(payload["source"]) if payload.get("source") is not None else None,
        source_ref=str(payload["source_ref"]) if payload.get("source_ref") is not None else None,
        supersedes=tuple(str(x) for x in payload.get("supersedes", []) or []),
        superseded_by=str(payload["superseded_by"]) if payload.get("superseded_by") is not None else None,
        tags=tuple(str(x) for x in payload.get("tags", []) or []),
        importance=float(payload.get("importance", 0.5)),
        confidence=float(payload.get("confidence", 0.5)),
    )


def _terms(value: str) -> set[str]:
    return {m.group(0).casefold() for m in _TERM_RE.finditer(value)}


def rank_for_context(
    records: Iterable[MemoryRecord],
    task: str,
    *,
    project: str | None = None,
    limit: int = 12,
    include_stale: bool = False,
    now: datetime | None = None,
) -> list[MemoryRecord]:
    """Deterministic pre-ranking before semantic/vector re-ranking.

    This intentionally excludes candidate/superseded/archived notes. It keeps the
    context pack small and prevents historical truth from masquerading as current truth.
    """
    if limit < 1:
        return []
    current = _aware_utc(now) or _utcnow()
    query_terms = _terms(task)
    kind_weight = {
        MemoryKind.RULE: 5.0,
        MemoryKind.DECISION: 4.5,
        MemoryKind.HANDOFF: 4.0,
        MemoryKind.PREFERENCE: 4.0,
        MemoryKind.FACT: 3.5,
        MemoryKind.PROJECT: 3.25,
        MemoryKind.PROFILE: 2.75,
        MemoryKind.LESSON: 2.5,
        MemoryKind.SESSION: 1.0,
    }
    verification_weight = {
        VerificationLevel.INFERRED: 0.0,
        VerificationLevel.OBSERVED: 1.0,
        VerificationLevel.VERIFIED: 2.0,
    }
    scored: list[tuple[float, str, MemoryRecord]] = []
    for record in records:
        if record.status is MemoryStatus.STALE and not include_stale:
            continue
        if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.STALE}:
            continue
        score = kind_weight[record.kind]
        score += verification_weight[record.verification]
        score += record.importance * 2.0 + record.confidence
        if project:
            if record.project == project:
                score += 6.0
            elif record.project is None:
                score += 1.0
            else:
                score -= 4.0
        haystack = " ".join((record.title, record.body, " ".join(record.tags)))
        overlap = len(query_terms & _terms(haystack))
        score += min(overlap, 6) * 0.8
        age_days = max(0.0, (current - record.updated_at).total_seconds() / 86400.0)
        if record.kind in {MemoryKind.HANDOFF, MemoryKind.SESSION, MemoryKind.PROJECT}:
            score += max(0.0, 2.0 - age_days / 14.0)
        if record.status is MemoryStatus.STALE:
            score -= 5.0
        scored.append((score, record.memory_id, record))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [record for _, _, record in scored[:limit]]
