# Architecture Decision Records

## ADR-001: Start with a narrow visual goal

**Status:** Accepted

The first product goal is clearly adult male portrait generation with fresh youthful energy and strong lighting. A narrow goal makes UX, evaluation, and learning signals legible. Other themes become goal plugins after repeated-use evidence exists.

## ADR-002: Product-first, provider-replaceable

**Status:** Accepted

The product owns projects, sessions, candidate comparison, feedback, memory, and learning. GPT-image2 is the first provider behind an internal contract. This prevents a vendor API from becoming the product architecture.

## ADR-003: Explicit state machine over unrestricted autonomy

**Status:** Accepted

The agent can interpret, plan, generate, evaluate, and propose a bounded retry, but the server controls transitions, budgets, privacy, safety gates, and retry limits.

## ADR-004: Separate memory scopes

**Status:** Accepted

Session instructions, project/persona preferences, user-wide preferences, and global strategy evidence are different data classes with different retention and consent rules.

## ADR-005: Frontend remains private during interaction discovery

**Status:** Superseded by ADR-008

The initial frontend prototype was stored at `/Users/adtiger/Tevion-frontend`, outside the GitHub repository, while the interaction model was being validated.

## ADR-006: Feedback is a product primitive

**Status:** Accepted

Candidate selection, comparison, rejection reason, edit request, download, and continued editing are first-class events. A “self-learning” claim is not valid until these events are captured with enough context to connect behavior to generated outputs.

## ADR-007: External identity, local authorization

**Status:** Accepted

Tevion uses an external OAuth 2.0 / OpenID Connect identity provider for login and credential management. The frontend sends an access token as `Authorization: Bearer ***`. FastAPI uses HTTP Bearer extraction plus JWT/JWKS claim validation, then maps `(auth_provider, provider_subject)` to a local `users.id`. Tevion does not store the external password. Product authorization and resource ownership remain local to Tevion.

## ADR-008: Move the validated frontend prototype into the monorepo

**Status:** Accepted

The validated, dependency-free frontend prototype is maintained at `apps/web/` in the Tevion repository. This creates one versioned product workspace while preserving the current static prototype shape until UX validation justifies a Vite/React migration.

Frontend and backend remain separate ownership areas:

- Frontend Issues modify `apps/web/**`.
- Backend Issues modify `apps/api/**` and relevant backend migrations.
- Only explicitly labeled `area:integration` Issues may modify both areas.

The original `/Users/adtiger/Tevion-frontend` directory is retained as a migration backup and is not part of the runtime source of truth.
