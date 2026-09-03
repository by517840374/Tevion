# Tevion Product Development Flow

Tevion adopts a six-part skill/workflow taxonomy inspired by AI Hero's skill organization. The categories are not a collection of isolated agent prompts. They are the operating system for moving Tevion from product intent to a reliable, learning product.

```text
Getting Started → The Main Flow → Shaping → Upkeep
                         ↑             ↓
                Productivity     Reference
```

## Why this exists

Tevion is a product, not a single generation script. The project needs a repeatable way to answer six questions:

1. How does a new contributor or agent understand the product?
2. What is the path from an idea to a shipped slice?
3. How do we turn ambiguity into a decision before coding?
4. How do we keep the system and backlog healthy after shipping?
5. How do we make recurring work faster without weakening standards?
6. Where do stable domain facts and implementation recipes live?

Each category has a different job and produces a different kind of artifact. They should not be collapsed into one giant “agent skill”.

---

## 1. Getting Started — 入门准备

**Purpose:** establish enough shared context that a person or coding agent can work safely.

### Tevion scope

- product brief and target user;
- architecture map and domain glossary;
- local development setup;
- provider and secret boundaries;
- repository conventions;
- privacy and adult-subject safety boundary;
- how to run the API, tests, and private frontend exploration.

### Outputs

```text
docs/PRODUCT_BRIEF.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
apps/api/README.md
.env.example
```

### Entry gate

Before making a product or code change, the agent should be able to explain:

- what Tevion is and is not;
- which user behavior is the learning signal;
- which memory scope is affected;
- which repository or private prototype is allowed to change;
- how the change will be verified.
- how the change handles authenticated identity, ownership, and private data.

---

## 2. The Main Flow — 主流程

**Purpose:** move one product slice from intent to verified delivery.

### Tevion flow

```text
product opportunity
→ product slice
→ domain/event contract
→ UX decision
→ implementation issue
→ vertical code slice
→ verification
→ commit / PR
→ learning signal
```

### Required stages

1. **Frame the slice** — define the user outcome and non-goals.
2. **Shape the decision** — resolve ambiguity with a short product/architecture decision.
3. **Define the contract** — entities, events, API behavior, and state transitions.
4. **Build vertically** — connect UI/API/domain behavior rather than building disconnected layers.
5. **Verify** — run focused tests and an end-to-end or ad-hoc check appropriate to the slice.
6. **Ship deliberately** — commit with a clear message and link the GitHub issue.
7. **Observe the learning signal** — define what user event will tell us whether the slice works.

### Tevion first vertical slices

```text
Slice 1: project/session/persona/event contracts
Slice 2: authentication seam and local user mapping
Slice 3: bounded agent state machine
Slice 4: GPT-image2 provider contract and mocked execution
Slice 5: create-session API + private workbench integration
Slice 6: candidate selection and feedback persistence
Slice 7: project preference projection and visible memory
```

A slice is not complete when code compiles. It is complete when the user can perform the intended action and the system records the evidence needed for the next product decision.

---

## 3. Shaping — 打磨 / 塑形

**Purpose:** turn unclear product or technical ideas into decisions before implementation.

### Use shaping when

- the desired user experience is ambiguous;
- several data models are plausible;
- a provider capability is uncertain;
- a feature could pollute memory or global learning;
- a proposed change expands the first product goal;
- the team is about to build a platform instead of validating a narrow slice.

### Shaping tools

- product brief update;
- domain glossary;
- event-storming table;
- user-flow sketch;
- thin prototype;
- architecture decision record;
- acceptance examples;
- risk and privacy review.

### Shaping questions for Tevion

```text
What user decision are we trying to improve?
What is the smallest interaction that produces evidence?
Is this session memory, project memory, user memory, or global evidence?
What must remain deterministic instead of delegated to the model?
What happens when the agent is uncertain or repeatedly fails?
How will we know this change improved personalization rather than merely output volume?
```

### Exit gate

A shaped item has:

- one clear user outcome;
- explicit non-goals;
- named domain objects/events;
- a privacy and safety boundary;
- measurable acceptance criteria;
- a GitHub issue small enough to implement vertically.

---

## 4. Upkeep — 维护

**Purpose:** keep the product, codebase, data, and backlog trustworthy after the first release.

### Tevion upkeep areas

#### Product upkeep

- review whether users complete the explore → refine loop;
- remove unused controls and stale style templates;
- review rejected-output reasons;
- check whether “Agent memory” remains understandable and editable.

#### Runtime upkeep

- inspect failed transitions and provider errors;
- enforce retry and cost budgets;
- remove secrets and sensitive images from logs;
- maintain idempotency and resumability.

#### Data upkeep

- validate event payloads;
- detect duplicate or orphaned image versions;
- expire temporary assets;
- keep private project data out of global retrieval;
- maintain a small fixed regression set.

#### Learning upkeep

- compare strategy versions offline;
- inspect preference drift;
- require consent for global learning;
- keep rollback paths for prompt/strategy changes;
- never promote a strategy based on one user's feedback.

### Upkeep cadence

```text
per change: focused verification and event-schema check
weekly: backlog / failure / feedback review
monthly: regression, cost, privacy, and strategy review
before release: migration, rollback, and product acceptance review
```

---

## 5. Productivity Skills — 效率技能

**Purpose:** accelerate repeatable human-facing work without changing product truth.

These are workflow helpers, not business logic. Examples for Tevion:

- create a well-formed GitHub issue from a product decision;
- summarize a session trace into a failure report;
- generate a migration checklist;
- prepare a release note from merged slices;
- compare two strategy experiment reports;
- turn a user feedback cluster into candidate backlog items;
- produce a local demo dataset from approved fixtures.

Productivity automation must not:

- silently alter user preferences;
- publish a learning strategy;
- change production schemas without review;
- expose private image assets;
- substitute a generated summary for source evidence.

---

## 6. Reference Skills — 参考类技能

**Purpose:** store stable, reusable facts and recipes that other workflow steps can invoke.

### Tevion reference areas

```text
docs/reference/
├── domain-glossary.md
├── event-catalog.md
├── provider-contract.md
├── state-machine.md
├── preference-evidence.md
├── privacy-and-consent.md
└── verification-commands.md
```

Reference material should be concise, versioned, and source-oriented. It explains “what is true” or “how this boundary works”; it does not decide whether a new feature should exist.

---

## How the categories map to GitHub work

| Category | Typical issue label | Primary artifact | Completion signal |
|---|---|---|---|
| Getting Started | `docs`, `foundation` | setup/context docs | a new contributor can orient safely |
| The Main Flow | `feature`, `vertical-slice` | code + tests + event path | user outcome works end to end |
| Shaping | `product`, `architecture` | decision/spec/prototype | ambiguity is reduced before build |
| Upkeep | `maintenance`, `reliability` | fixes, audits, regression updates | system remains trustworthy |
| Productivity Skills | `tooling`, `automation` | repeatable helper/workflow | recurring work gets faster safely |
| Reference Skills | `reference` | stable domain recipe | agents can reuse verified knowledge |

Labels are signals for triage, not a replacement for the issue body. Each issue should still state the user outcome, scope, non-goals, acceptance criteria, and evidence required.

## Operating rule

When unsure which category applies:

```text
unclear idea        → Shaping
known product slice → The Main Flow
new contributor     → Getting Started
already shipped     → Upkeep
repeated manual task→ Productivity Skills
stable fact/recipe  → Reference Skills
```

The purpose of this taxonomy is to keep Tevion's core loop visible:

```text
shape the right product decision
→ build a narrow vertical slice
→ observe real user feedback
→ maintain trustworthy data
→ improve the next decision
```
