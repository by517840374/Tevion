# Tevion Architecture

## Core decision

Tevion is a product system with an agent runtime inside it. The web/app and its data contracts are first-class; GPT-image2 is only one implementation of an `ImageGenerationProvider`.

Authentication is separate from business authorization. An external OAuth 2.0 / OpenID Connect provider handles login and credentials. FastAPI acts as a resource server: it extracts `Authorization: Bearer <access_token>`, validates token signature and claims, maps the provider subject to a local `users.id`, and enforces ownership on every private resource.

```text
Web/App
  ↓ OAuth/OIDC login (Authorization Code + PKCE)
Identity Provider
  ↓ access token
Web/App: Authorization: Bearer <access_token>
  ↓
Product API
  ├── token validation, local user mapping, projects, sessions, permissions
  └── generation task commands and event stream
       ↓
Agent Runtime (explicit state machine)
  ├── request interpreter
  ├── visual director / prompt planner
  ├── provider executor
  ├── critic and policy gate
  └── feedback learner
       ↓
Provider boundary
  ├── GPT-image2 (first)
  ├── ComfyUI (future)
  └── other hosted/local providers (future)
       ↓
Data and learning platform
  ├── task/event/version store
  ├── asset store
  ├── preference memory
  ├── case retrieval
  ├── strategy experiments
  └── offline evaluation and release gate
```

## Bounded workflow

```text
CREATED
 → UNDERSTANDING
 → AWAITING_CONFIRMATION (when confidence is low or cost is high)
 → PLANNING
 → EXPLORING or REFINING
 → GENERATING
 → EVALUATING
 ├─ ACCEPTABLE → AWAITING_SELECTION
 ├─ RETRYABLE → RETRYING (bounded)
 └─ BLOCKED → NEEDS_USER_REVIEW
 → COMPLETED
```

The runtime may propose actions, but the server owns allowed transitions, retry limits, privacy checks, and provider selection. This makes the system inspectable and recoverable.

## Domain boundaries

### Product domain

Users, projects, personas, sessions, image versions, selections, feedback, and exports.

### Agent domain

Interpretations, plans, prompt drafts, tool decisions, critic reports, retry reasons, and strategy versions.

### Learning domain

Preference events, feature extraction, case eligibility, experiment assignments, aggregate metrics, candidate strategies, evaluation runs, approvals, and rollbacks.

These domains communicate through IDs and immutable events rather than sharing mutable internal objects.

## Event-first traceability

Every generation should be reconstructable from:

```text
request
→ interpretation version
→ preference snapshot
→ recalled case IDs (if authorized)
→ strategy version
→ prompt draft/final
→ provider request metadata
→ output asset/version
→ critic report
→ user decision and later use
```

Do not store secrets, raw authorization headers, or private assets in logs.

## Memory isolation

- Session memory may be used immediately in the current session.
- Project memory is scoped to a project/persona and can be edited or deleted.
- User memory is explicit or high-confidence repeated behavior.
- Global strategy data is consented, minimized, anonymized, and evaluated offline.
- Private cases never enter another user's retrieval results.

## Authentication and authorization

```text
external provider: login, password, MFA, token issuance
FastAPI: bearer extraction, JWT/JWKS validation, claims checks
Tevion database: local user identity mapping and product ownership
```

The `users` table includes `auth_provider` and `provider_subject`, with a unique constraint on `(auth_provider, provider_subject)`. Business tables reference internal `users.id`, never a raw email address. A valid token alone is insufficient: every project, session, image version, feedback event, and preference query must verify ownership or explicit project membership.

## Provider contract

The provider interface must normalize differences in API request/response formats. It returns an internal generation result containing provider request ID, model, effective parameters, assets, latency, cost when available, and raw metadata subject to redaction. Business logic must not depend on a provider SDK type.

## First implementation boundary

The first code slice establishes:

- backend package and domain contracts;
- health/product metadata endpoint;
- frontend prototype outside the public repository;
- GitHub issue backlog describing product slices;
- a stable path for adding the real provider without coupling the UI to it.
- an authentication seam that can accept a real OIDC provider without embedding password logic in the product.

It intentionally does not pretend that the learning loop exists before event capture and feedback UX are implemented.
