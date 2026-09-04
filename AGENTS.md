# Tevion Agent Instructions

## Project

Tevion is a product-oriented visual AI Agent.

The current product loop is:

user intent
→ visual interpretation
→ candidate generation
→ comparison
→ feedback
→ preference memory
→ better future decisions

The first product direction focuses on clearly adult male portraits with fresh youthful energy, strong lighting, and controllable visual style.

## Repository boundaries

- Backend code lives under `apps/api/`.
- Product and architecture documentation lives under `docs/`.
- The maintained frontend prototype lives under `apps/web/`.
- `/Users/adtiger/Tevion-frontend` is a migration backup only; do not modify it
  unless an Issue explicitly requests backup synchronization.
- Do not modify files outside the repository unless the issue explicitly requires it.

## Agent ownership boundaries

- Frontend Issues may modify `apps/web/**` and frontend-specific docs only.
- Backend Issues may modify `apps/api/**`, backend migrations, and backend docs.
- Only Issues explicitly labeled `area:integration` may modify both
  `apps/web/**` and `apps/api/**`.
- A backend Agent must not modify frontend code to hide a missing API contract.
- A frontend Agent must not modify backend code, migrations, Docker, or
  database configuration.
- Reviewers must reject changes outside the Issue's declared area.

## Development flow

Follow the six-category workflow:

1. Getting Started
2. The Main Flow
3. Shaping
4. Upkeep
5. Productivity Skills
6. Reference Skills

When the issue is ambiguous, product-oriented, architectural, or affects the learning boundary, do shaping first instead of immediately writing implementation code.

When the issue is a clear vertical slice, implement it with focused tests.

## Required behavior for Issue work

Before changing code:

1. Read the full GitHub Issue.
2. Read `README.md`.
3. Read the relevant files under `docs/`.
4. Identify the user outcome.
5. Identify non-goals.
6. Identify affected domain objects and events.
7. Identify the memory scope:
   - session memory
   - project memory
   - user preference
   - global evidence
8. Define the verification command.

Do not silently expand the scope of the Issue.

## Git rules

- Always create a dedicated branch for an Issue.
- Branch format:
  `agent/issue-<number>-<short-slug>`
- Do not work directly on `main`.
- Use conventional commits:
  - `feat: ...`
  - `fix: ...`
  - `docs: ...`
  - `test: ...`
  - `refactor: ...`
- Do not force-push.
- Do not merge pull requests automatically.
- Do not delete branches automatically.

## Verification

For API changes:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest

Prefer focused tests first, then run the complete relevant test suite.

If the project has no test suite yet, perform at least:

import checks
application startup check
targeted Python checks
API health check where appropriate
GitHub reporting
When work is complete:

Report what changed.
Report which verification commands were run.
Report failures honestly.
Include the branch name.
Open a pull request only if the Issue explicitly allows it or the automation prompt requests it.
Comment on the original Issue with a concise status update.
Never claim a PR or test succeeded unless the command actually succeeded.
Safety and privacy
Do not expose API keys or secrets.
Do not put private user images into logs, commits, or Issue comments.
User images and private preferences are private by default.
Do not introduce unrestricted autonomous loops.
Keep state transitions explicit and bounded.
Do not perform global learning based on one user's feedback.
