# Datum Engine — FastAPI Service

FastAPI is a stateless execution engine. Odoo is the only database, reached over
HTTP through `integrations/`. Reviewer skill is `rev-strs` (stakeholder requirements
review), not scope of work.

---

## 0. Schemas vs. models — why schemas still exist with no DB

- **Model** (SQLAlchemy): a Python class mapped to a database table. Not used here —
  there's no database for FastAPI to own.
- **Schema** (Pydantic): defines the shape of data moving through the API — what a
  request must contain, what a response will contain. FastAPI uses schemas to
  validate incoming JSON, auto-generate `/docs`, and serialize outgoing JSON. This
  has nothing to do with storage, so it stays even with no DB. It's now the _only_
  place data shape is defined, since there's no `models/` folder duplicating it.

## 0.1 What a YAML file is

Plain-text structured data, like JSON but easier to hand-write (indentation instead
of braces/quotes). Used for `registry/*.yaml` because a skill's shape (identifier,
version, kind, inputs, outputs) needs to be _data your program reads_, not code baked
into the program — that's what lets a real prompt replace the placeholder later
without touching Python (§2.2, §10). Example:

```yaml
identifier: gen-discovery-questions
version: 1
kind: generator
accepted_inputs:
  - type: prospect_context
    required: true
outputs:
  - document_type: discovery_questionnaire
    distribution_class: client_permitted
instruction: "Summarize the provided context in one paragraph." # placeholder for now
```

`registry_service.py` reads these with `PyYAML` and turns them into Python objects.

---

## 1. Architecture

```
datum-engine/
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
│
├── registry/
│   ├── discovery_questionnaire.yaml
│   ├── stakeholder_requirements.yaml
│   ├── stakeholder_requirements_review.yaml
│   └── scope_of_work.yaml
│
├── app/
│   │   main.py
│   │
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── router.py
│   │       └── endpoints/
│   │           ├── discovery_questionnaire.py
│   │           ├── stakeholder_requirements.py
│   │           ├── stakeholder_requirements_review.py
│   │           ├── scope_of_work.py
│   │           └── skills.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   │
│   ├── schemas/
│   │   ├── discovery_questionnaire.py
│   │   ├── stakeholder_requirements.py
│   │   ├── stakeholder_requirements_review.py
│   │   ├── scope_of_work.py
│   │   └── skill.py
│   │
│   ├── services/
│   │   ├── discovery_questionnaire_service.py
│   │   ├── stakeholder_requirements_service.py
│   │   ├── stakeholder_requirements_review_service.py
│   │   ├── scope_of_work_service.py
│   │   ├── orchestrator.py
│   │   ├── review_loop_service.py
│   │   ├── clarification_service.py
│   │   └── registry_service.py
│   │
│   ├── integrations/
│   │   ├── odoo_client.py
│   │   ├── task_state.py
│   │   ├── issues.py
│   │   └── uploaded_files.py
│   │
│   ├── providers/
│   │   ├── base.py
│   │   ├── gemini_provider.py
│   │   ├── groq_provider.py
│   │   ├── cohere_provider.py
│   │   ├── fallback_chain.py
│   │   └── search_provider.py
│   │
│   ├── workers/
│   │   ├── queue.py
│   │   └── task_worker.py
│   │
│   ├── rendering/
│   │   ├── template_renderer.py
│   │   └── validation_gate.py
│   │
│   └── utils/
│       ├── documents.py
│       └── files.py
│
└── tests/
    ├── unit/
    └── integration/
```

---

## 2. What Goes In Each File

**`.env` / `.env.example`**

```
ODOO_BASE_URL=
ODOO_API_KEY=
API_AUTH_TOKEN=
GEMINI_API_KEY=
GROQ_API_KEY=
COHERE_API_KEY=
TAVILY_API_KEY=
LLM_PROVIDER_ORDER=gemini,groq,cohere
REGISTRY_PATH=./registry
QUEUE_BACKEND=memory
WORKER_CONCURRENCY=3
CYCLE_CEILING_DEFAULT=5
TEMPLATE_DIR=./templates
```

**`requirements.txt`** — fastapi[standard], pydantic, pydantic-settings, httpx,
pyyaml, python-multipart, pypdf, python-docx, google-generativeai, groq, cohere,
structlog, python-dotenv, pytest, pytest-asyncio, pytest-mock, respx, ruff.

**`registry/*.yaml`** — one file per skill: identifier, version, kind, accepted
inputs, outputs, and a placeholder `instruction` string (§10).

**`app/main.py`** — creates the `FastAPI()` app, includes the v1 router, loads the
registry into memory on startup (`registry_service.load_all()`), starts the worker.

**`app/api/deps.py`** — `verify_api_token()` dependency (checks the Authorization
header against `API_AUTH_TOKEN`); `get_odoo_client()` dependency that hands endpoints
a configured `odoo_client.py` instance.

**`app/api/v1/router.py`** — `include_router()` for each endpoint module, mounted
under `/api/v1`.

**`app/api/v1/endpoints/discovery_questionnaire.py`**

- `POST /discovery-questionnaire/generate` — validates the request against
  `DiscoveryQuestionnaireRequest`, calls
  `discovery_questionnaire_service.start()`, returns `{task_id}` immediately.
- `GET /discovery-questionnaire/{task_id}` — calls
  `discovery_questionnaire_service.get_status()`, returns current state + outputs.

**`app/api/v1/endpoints/skills.py`** — `GET /skills` — calls
`registry_service.list_summaries()` and returns `SkillSummary` objects. Never
includes the `instruction` field.

**`app/core/config.py`** — a `Settings(BaseSettings)` class typing every `.env` var.

**`app/core/security.py`** — one function that raises `401` if the incoming
`Authorization` header doesn't match `API_AUTH_TOKEN`.

**`app/core/logging.py`** — `structlog` setup, plus a processor that scrubs anything
resembling prompt/instruction text before it's logged (§2.2).

**`app/core/exceptions.py`** — custom exceptions (`RegistryNotFoundError`,
`OdooUnavailableError`, `ProviderFailureError`) and the handlers that turn them into
clean JSON error responses for Odoo.

**`app/schemas/discovery_questionnaire.py`**

- `DiscoveryQuestionnaireRequest` — `project_id`, `file_ids: list[str]`,
  `instructions: str | None`
- `DiscoveryQuestionnaireTaskResponse` — `task_id: str`
- `DiscoveryQuestionnaireResultResponse` — `state: str`, `outputs: list[OutputRef]`

**`app/schemas/skill.py`** — `SkillSummary`: `identifier`, `version`, `kind`,
`accepted_inputs` — deliberately excludes `instruction`.

**`app/services/discovery_questionnaire_service.py`**

- `start(request)` — resolves the registry entry via `registry_service`, calls
  `integrations/task_state.create_task()` (idempotency check happens here, against
  Odoo), enqueues the job via `workers/queue.py`, returns the `task_id`.
- `get_status(task_id)` — calls `integrations/task_state.get_task()`.

**`app/services/orchestrator.py`** — `execute(task_id)`: pulls the task + registry
entry + files via `integrations/`, builds the prompt (registry instruction + pulled
file text), calls `providers/fallback_chain.generate()`, runs
`rendering/validation_gate.py`, pushes the output back via
`integrations/task_state.py`, retries on transient failure (bounded, per §4.2).

**`app/services/registry_service.py`** — `load_all()` reads every YAML in
`registry/` into memory at startup; `resolve(skill_id)` returns one entry;
`list_summaries()` strips `instruction` for the `/skills` endpoint.

**`app/services/review_loop_service.py`, `clarification_service.py`** — stubs for
now. Not touched by the questionnaire path; they matter once StRS + its reviewer are
built.

**`app/integrations/odoo_client.py`** — a thin `httpx.AsyncClient` wrapper: base URL

- auth header, generic `get()`/`post()` methods.

**`app/integrations/task_state.py`** — `create_task()`, `update_task_state()`,
`get_task()` — each calls a specific endpoint on your Odoo `datum_engine` module's
controller.

**`app/integrations/uploaded_files.py`** — `fetch_file(file_id) -> bytes`, via
Odoo's attachment download endpoint.

**`app/integrations/issues.py`** — stub for now; used once the review loop exists.

**`app/providers/base.py`** — abstract `LLMProvider` with a `generate(prompt,
files=None, tools=None)` method every provider implements.

**`app/providers/gemini_provider.py` / `groq_provider.py` / `cohere_provider.py`**
— concrete implementations of `LLMProvider` for each service.

**`app/providers/fallback_chain.py`** — tries providers in the order set by
`LLM_PROVIDER_ORDER`, catching rate-limit/failure errors and falling to the next.

**`app/providers/search_provider.py`** — Tavily wrapper, used as a tool on the Groq
fallback path (Gemini has search built in).

**`app/workers/queue.py`** — a simple `asyncio.Queue` wrapper (swap for Redis later
if needed).

**`app/workers/task_worker.py`** — loop that pulls a `task_id` off the queue, calls
`orchestrator.execute(task_id)`, bounded by `asyncio.Semaphore(WORKER_CONCURRENCY)`.

**`app/rendering/template_renderer.py`** — takes structured content, fills an
OdooTec Word template via `python-docx`, handles RTL/Arabic layout.

**`app/rendering/validation_gate.py`** — checks a rendered document has every
required section before it's accepted as a finished output.

**`app/utils/documents.py`** — `extract_text(file_bytes, mime_type)` using `pypdf`
/ `python-docx`.

**`app/utils/files.py`** — file size/type validation, temp file cleanup.

**`tests/unit/`** — services tested with mocked providers and a mocked
`odoo_client`.

**`tests/integration/`** — FastAPI test client hitting `/discovery-questionnaire/
generate` end to end, with providers and Odoo both mocked.

---

## 3. Three-Day Plan — Discovery Questionnaire Only

| Day   | Build                                                                                                                                                                                                                                                                                            | Proof it works                                                                                                                             |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **1** | `config.py`, `security.py`, `logging.py`, `main.py`; `registry/discovery_questionnaire.yaml` + `registry_service.py`; `schemas/discovery_questionnaire.py` + `schemas/skill.py`; `endpoints/skills.py`                                                                                           | `GET /skills` returns the questionnaire skill's summary, no prompt text visible                                                            |
| **2** | `integrations/odoo_client.py`, `task_state.py`, `uploaded_files.py` (against a mock or test Odoo endpoint); `providers/base.py` + `gemini_provider.py` + a single-provider `fallback_chain.py`; `orchestrator.py` with one step (pull files → call provider → return raw text, no rendering yet) | `POST /discovery-questionnaire/generate` returns a `task_id`; the worker calls Gemini, gets text back, and pushes the result state to Odoo |
| **3** | `rendering/template_renderer.py` + `validation_gate.py`; `workers/queue.py` + `task_worker.py` fully wired; test Arabic/RTL output specifically (§9, §11 — don't defer this)                                                                                                                     | `GET /discovery-questionnaire/{task_id}` shows `queued → running → succeeded` and a downloadable, correctly-rendered Arabic `.docx`        |

---

## 4. Build Prompt

```
You are a senior Python/FastAPI backend engineer. Build a FastAPI microservice
called "datum-engine" that generates a discovery questionnaire document, called by
an Odoo module as the sole data store — this service has NO DATABASE OF ITS OWN.

ARCHITECTURE (follow exactly):

datum-engine/
├── .env.example
├── requirements.txt
├── README.md
├── registry/
│   └── discovery_questionnaire.yaml
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── router.py
│   │       └── endpoints/
│   │           ├── discovery_questionnaire.py
│   │           └── skills.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   ├── schemas/
│   │   ├── discovery_questionnaire.py
│   │   └── skill.py
│   ├── services/
│   │   ├── discovery_questionnaire_service.py
│   │   ├── orchestrator.py
│   │   └── registry_service.py
│   ├── integrations/
│   │   ├── odoo_client.py
│   │   ├── task_state.py
│   │   └── uploaded_files.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── gemini_provider.py
│   │   └── fallback_chain.py
│   ├── workers/
│   │   ├── queue.py
│   │   └── task_worker.py
│   ├── rendering/
│   │   ├── template_renderer.py
│   │   └── validation_gate.py
│   └── utils/
│       ├── documents.py
│       └── files.py
└── tests/
    ├── unit/
    └── integration/

RULES:
1. NO database, NO SQLAlchemy, NO ORM of any kind. Every piece of state (task
   creation, task status, idempotency checks) is read from or written to Odoo over
   HTTP via app/integrations/. Odoo is the only system of record.
2. The skill definition (identifier, version, kind, accepted inputs, outputs,
   instruction placeholder) lives in registry/discovery_questionnaire.yaml as DATA,
   never hardcoded in Python. Load it with PyYAML.
3. GET /skills must never return the "instruction" field — strip it before
   responding.
4. A run is asynchronous: POST /discovery-questionnaire/generate returns a task_id
   immediately, without waiting for the LLM call to finish. Actual execution happens
   in a background worker pulling from an in-memory asyncio.Queue.
5. Resubmitting the same idempotency key must not create a duplicate task — check
   with Odoo before creating a new one.
6. The LLM provider sits behind an abstract interface (app/providers/base.py) so
   adding a second provider later is a new adapter file, not a rewrite. Implement
   Gemini as the only concrete provider for now, using the google-generativeai SDK.
7. No prompt/instruction text may ever appear in a log line, exception message, or
   API response — build core/logging.py to scrub it.
8. Arabic (RTL) output is a functional requirement for this document type — the
   rendering step must be tested with Arabic content, not just English.
9. Auth: every request from Odoo must include a header matching API_AUTH_TOKEN from
   .env, checked in core/security.py.
10. Write unit tests for services/ with mocked providers and a mocked Odoo client,
    and one integration test that exercises the full POST -> worker -> GET flow.

Build it file by file, in this order: core/config.py -> core/security.py ->
core/logging.py -> core/exceptions.py -> registry/discovery_questionnaire.yaml ->
services/registry_service.py -> schemas/skill.py -> api/v1/endpoints/skills.py ->
schemas/discovery_questionnaire.py -> integrations/odoo_client.py ->
integrations/task_state.py -> integrations/uploaded_files.py ->
providers/base.py -> providers/gemini_provider.py -> providers/fallback_chain.py ->
services/orchestrator.py -> services/discovery_questionnaire_service.py ->
workers/queue.py -> workers/task_worker.py ->
api/v1/endpoints/discovery_questionnaire.py -> api/v1/router.py -> app/main.py ->
rendering/validation_gate.py -> rendering/template_renderer.py -> utils/documents.py
-> utils/files.py -> tests/.

After each file, briefly state what it does and how it connects to the previous one
before moving to the next, so I can follow along and stop you if something needs to
change.
```
