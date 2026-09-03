# Tevion

Tevion is a product-oriented visual AI Agent. It starts with a focused goal: helping users create clearly adult male portraits with fresh youthful energy, strong lighting, and a controllable visual style. The long-term product is a personal visual agent that learns from user choices, edits, ratings, and usage—not a thin wrapper around an image API.

## Product thesis

```text
user intent → visual interpretation → candidate generation → comparison → feedback
          → preference memory → better next decision
```

The first release treats GPT-image2 as a replaceable generation provider. The product boundary is the web/app experience, the task/session/version data model, the feedback loop, and the policy-controlled learning layer.

## Repository status

- `apps/api/`: backend foundation and domain contracts.
- `docs/`: product, architecture, and decision records.
- Frontend work is intentionally kept outside this repository during the early product exploration phase. Current local prototype location: `/Users/adtiger/Tevion-frontend`.

## Non-goals for the first slice

- No foundation-model training.
- No unrestricted autonomous agent loop.
- No cross-user private case retrieval.
- No public frontend code until the interaction model is validated.
- No hard dependency on ComfyUI; it can become a future provider.

## Local API foundation

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn tevion_api.main:app --reload
```

The current API only exposes health and product metadata. Generation-provider integration is deliberately a later issue after the domain contracts and UX are reviewed.

## Local database (PostgreSQL via Docker)

The product data layer targets PostgreSQL. Local development runs a real instance through docker-compose:

```bash
docker compose up -d db          # start PostgreSQL 16 (creates `tevion` + `tevion_test`)
cp .env.example .env             # optional local overrides
cd apps/api
.venv/bin/alembic upgrade head   # apply migrations to `tevion`
.venv/bin/python -m pytest       # 25+ tests, including real-PG roundtrips
```

`TEVION_DB_URL` in `.env` overrides the default local URL. Tests use the dedicated `tevion_test` database and are skipped automatically when PostgreSQL is unreachable.

## Project principles

1. Product experience before provider lock-in.
2. Explicit state transitions before free-form autonomy.
3. Every prompt, tool call, image version, decision, and feedback event is traceable.
4. Session memory, user preference, and global strategy learning remain separate.
5. Learning proposals are evaluated and versioned before release.
6. User images and private preferences are private by default.

See `docs/` for the current product and architecture definition.
