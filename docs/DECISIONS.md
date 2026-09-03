# Architecture Decision Records

## ADR-001: Start with a narrow visual goal

**Status:** Accepted

The first product goal is clearly adult male portrait generation with fresh youthful energy and strong lighting. A narrow goal makes UX, evaluation, and learning signals legible. Other themes become goal plugins after repeated-use evidence exists.

## ADR-002: Product-first, provider-replaceable

**Status:** Accepted

The product owns projects, sessions, candidate comparison, feedback, memory, and learning. GPT-image2 is the first provider behind an internal contract. This prevents a vendor API from becoming the product architecture.

## ADR-003: Explicit state machine over unrestricted autonomy

**Status:** Accepted

The agent can interpret, plan, generate, evaluate, and propose a retry, but the server controls transitions, budgets, privacy, safety gates, and retry limits.

## ADR-004: Separate memory scopes

**Status:** Accepted

Session instructions, project/persona preferences, user-wide preferences, and global strategy evidence are different data classes with different retention and consent rules.

## ADR-005: Frontend remains private during interaction discovery

**Status:** Accepted

The initial frontend prototype is stored at `/Users/adtiger/Tevion-frontend`, outside the GitHub repository. This allows rapid UX exploration without prematurely publishing an unstable product surface. Once the interaction model is validated, it can be moved into `apps/web/` or a separate private repository.

## ADR-006: Feedback is a product primitive

**Status:** Accepted

Candidate selection, comparison, rejection reason, edit request, download, and continued editing are first-class events. A “self-learning” claim is not valid until these events are captured with enough context to connect behavior to generated outputs.

## ADR-007: External identity, local authorization

**Status:** Accepted

Tevion uses an external OAuth 2.0 / OpenID Connect identity provider for login and credential management. The frontend sends an access token as `Authorization: Bearer <access_token>`. FastAPI uses HTTP Bearer extraction plus JWT/JWKS claim validation, then maps `(auth_provider, provider_subject)` to a local `users.id`. Tevion does not store the external password. Product authorization and resource ownership remain local to Tevion.
