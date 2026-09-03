# Event Catalog

Source: `apps/api/src/tevion_api/models.py`, `apps/api/src/tevion_api/domain.py`, `apps/api/src/tevion_api/runtime.py`, and the initial migration.

## Task state transition events

Task runtime events are stored as `TaskEvent` entries in `runtime.py` and carry:

- `event_type: str`
- `payload: dict[str, Any] | None`

Observed task state flow in tests and runtime code:

- `understanding_started` → `UNDERSTANDING`
- `interpretation_confirmed` → `PLANNING`
- `plan_created` → `EXPLORING`
- `generation_started` → `GENERATING`
- `generation_completed` → `EVALUATING`
- `quality_failed` → `RETRYING`
- `retry_started` → `GENERATING`
- `quality_failed_again` → `RETRYING`

## Feedback events

ORM model: `FeedbackEvent`

Fields:

- `id: str`
- `user_id: str`
- `session_id: str`
- `image_version_id: str`
- `event_type: str`
- `payload_json: dict`
- `created_at: datetime`

Domain model constrains `event_type` to:

- `selected`
- `rejected`
- `rated`
- `edited`
- `downloaded`

Observed payload shape in tests:

- `payload_json={"rating": 5}`

## Preference events

ORM model: `PreferenceEvent`

Fields:

- `id: str`
- `user_id: str`
- `scope: str`
- `scope_id: str | None`
- `key: str`
- `value: str`
- `source: str`
- `confidence: float`
- `deleted: bool`
- `created_at: datetime`

Domain model constrains:

- `scope`: `session | project | user | global`
- `source`: `explicit_feedback | tagged_feedback | selection | usage | inference`
- `confidence`: `0..1`

Notes:

- `deleted=True` is the explicit tombstone flag.
- `scope_id` is optional and may be unset for scopes that do not need an entity id.
- `global` evidence is subject to consent checks in the learning layer.
