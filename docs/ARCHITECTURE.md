# Tevion Architecture

## Core decision

Tevion is a product system with an agent runtime inside it. The web/app and its data contracts are first-class; GPT-image2 is only one implementation of an `ImageGenerationProvider`.

```text
Web/App
  ↓
Product API
  ├── identity, projects, sessions, feedback, permissions
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

## Provider contract

The provider interface must normalize differences in API request/response formats. It returns an internal generation result containing provider request ID, model, effective parameters, assets, latency, cost when available, and raw metadata subject to redaction. Business logic must not depend on a provider SDK type.

## First implementation boundary

The first code slice establishes:

- backend package and domain contracts;
- health/product metadata endpoint;
- frontend prototype outside the public repository;
- GitHub issue backlog describing product slices;
- a stable path for adding the real provider without coupling the UI to it.

It intentionally does not pretend that the learning loop exists before event capture and feedback UX are implemented.
