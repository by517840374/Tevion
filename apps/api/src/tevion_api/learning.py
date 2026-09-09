from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeedbackEvidence:
    """One captured user decision about a visual attribute.

    `scope` separates session / project / user / global memory so a temporary
    instruction never silently promotes into a permanent user preference.
    `consented` gates global evidence; `deleted` is an explicit tombstone.
    """

    scope: str
    key: str
    value: str
    source: str
    scope_id: str | None = None
    consented: bool = False
    deleted: bool = False
    preference_id: str | None = None
    status: str = "active"
    evidence_id: str | None = None


@dataclass(frozen=True)
class ProjectedPreference:
    scope: str
    scope_id: str | None
    key: str
    value: str
    weight: float
    source: str
    evidence_count: int
    id: str = ""
    status: str = "active"
    evidence_ids: tuple[str, ...] = ()


_SOURCE_WEIGHTS: dict[str, float] = {
    "explicit_feedback": 1.0,
    "tagged_feedback": 0.8,
    "selection": 0.7,
    "usage": 0.5,
    "inference": 0.2,
}


class PreferenceProjector:
    """Deterministically aggregate feedback evidence into preferences.

    Replaying the same events in the same order always yields the same
    projection, which makes the memory layer inspectable and resettable.
    """

    def project(self, events: list[FeedbackEvidence]) -> list[ProjectedPreference]:
        buckets: dict[tuple[str, str | None, str, str], dict[str, Any]] = {}
        for event in events:
            if event.scope == "global" and not event.consented:
                continue
            identity = event.preference_id or f"legacy:{event.scope}:{event.scope_id or ''}:{event.key}:{event.value}"
            bucket_key = (event.scope, event.scope_id, identity, event.key)
            if event.deleted or event.status == "deleted":
                buckets.pop(bucket_key, None)
                continue
            bucket = buckets.setdefault(
                bucket_key,
                {
                    "id": event.preference_id or identity,
                    "value": event.value,
                    "status": event.status,
                    "weight": 0.0,
                    "count": 0,
                    "best_source": "",
                    "best_weight": -1.0,
                    "evidence_ids": [],
                },
            )
            bucket["value"] = event.value
            bucket["status"] = event.status
            weight = _SOURCE_WEIGHTS.get(event.source, 0.5)
            bucket["weight"] += weight
            bucket["count"] += 1
            if event.evidence_id:
                bucket["evidence_ids"].append(event.evidence_id)
            if weight > bucket["best_weight"]:
                bucket["best_weight"] = weight
                bucket["best_source"] = event.source

        projected = [
            ProjectedPreference(
                id=value["id"],
                scope=bucket_key[0],
                scope_id=bucket_key[1],
                key=bucket_key[3],
                value=value["value"],
                weight=value["weight"],
                source=value["best_source"],
                evidence_count=value["count"],
                status=value["status"],
                evidence_ids=tuple(value["evidence_ids"]),
            )
            for bucket_key, value in buckets.items()
        ]
        return sorted(
            projected,
            key=lambda item: (
                -item.weight,
                item.scope,
                item.scope_id or "",
                item.key,
                item.value,
            ),
        )


__all__ = [
    "FeedbackEvidence",
    "PreferenceProjector",
    "ProjectedPreference",
    "_SOURCE_WEIGHTS",
]
