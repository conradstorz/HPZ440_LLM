# Jarvis Phase 1: Observe (plus Draft) Design

Status: Approved
Updated: 2026-09-30
Amended 2026-09-30: only token.json is copied to the host; implementation signatures for policy.filter_model_output and briefing.render recorded.
Roadmap phase: `docs/roadmap.md`, Phase 1, plus the `draft` unit pulled forward from Phase 2

## Purpose

Add the first Jarvis application to this repo: a `jarvis` container that reads new Gmail with a read-only credential, archives each message as an immutable knowledge object, classifies it with the local `llm-api`, searches prior mail for evidence, prepares a reply draft and a proposed action, and presents a grouped briefing with a correction control. It takes no outbound action. Nothing leaves the LAN and the Gmail mailbox is never modified.

`draft` is included now because it is local, read-only, and cheap once `classify` exists. The permission stage stays at 1 (Observe): drafts and proposed actions are stored and shown, never executed.

The build is structured so that seven units can be implemented in parallel by independent sub-agents against contracts fixed up front.

## Facts and decisions carried in

- Inference: `llm-api` (llama.cpp, Qwen2.5-7B-Instruct Q4_K_M, 56 tok/s measured 2026-09-29) at `http://llm-api:8080/v1` inside the compose network.
- Mailbox: `conradstorz@gmail.com`. A new Google Cloud OAuth client (Desktop app type) will be created for Jarvis; nothing from `my_ai_agent-DEPRICATED/` is reused except the library choice (`google-api-python-client`, `google-auth-oauthlib`).
- Data lives on HPZ440 local disk under `HOST_JARVIS_DATA_DIR` (`/srv/llm/jarvis-data`, already in `.env.example`), bind-mounted at `/data`. NAS migration is a later cross-cutting track.
- Application stack: Python 3.12 managed with `uv`, one container, FastAPI with server-rendered Jinja2 templates. No JavaScript framework.
- LAN only, no auth, no TLS, per `docs/operations.md`. The briefing will hold mail content; the hardening phase in the roadmap is unchanged.

### Relationship to GTE

`D:\Users\Conrad\Documents\programming\GTE` (General Triage Engine) already solves adjacent problems. Jarvis adopts, by copy rather than by dependency:

- **The Normalized Knowledge Object (NKO)** from `GTE/src/gte/models/nko.py` and `preliminary design docs/035_Normalized_Knowledge_Object.md`: one immutable, source-independent object with a facts / observations / classifications / recommendations / decisions hierarchy and a version chain where interpretation derives new versions and v0 is the fact of record.
- **The thin `Source` protocol** (`poll() -> list[NKO]`) as the only extensibility point for new inputs. Calendar, Drive, and the workspace agent later become new `Source` implementations; nothing above `sources/` changes.
- **The one-time Gmail OAuth bootstrap pattern** from `GTE/scripts/bootstrap_gmail_oauth.py` and `docs/PHASE1_RUNBOOK.md` section 1.

Jarvis does not adopt GTE's capability framework (`Capability`, `CapabilityResult`, `display/send/search/manage`, `Direction`, connector registry and console), Postgres, the Fernet secrets service, or its Windows workspace agent code. Jarvis has one inbox and no outbound capability in this phase. When Jarvis needs documents from this workstation or printing, it will call GTE's existing passive agent (`/scan`, `/file`, `/print`) the same way GTE does, honouring GTE's invariant 9 (the engine initiates, the agent never calls up). Neither is in this phase.

Copying rather than depending is deliberate: the two projects have different lifecycles, and GTE's status enum and invariants do not all apply here.

## Layout

```
jarvis/
  pyproject.toml            # uv; python 3.12; fastapi, uvicorn, jinja2, pydantic>=2, httpx,
                            # google-api-python-client, google-auth, google-auth-oauthlib,
                            # google-auth-httplib2; dev: pytest, pytest-asyncio
  Dockerfile                # python:3.12-slim, uv sync --frozen --no-dev, CMD uvicorn jarvis.web:app
  jarvis/
    __init__.py
    core/
      nko.py                # NKO, KnowledgeType, NKOStatus (copied from GTE, trimmed)
      store.py              # versioned archive under /data/archive
      llm.py                # LLMClient protocol, LlamaCppClient, FakeLLM
      config.py             # Settings from env: DATA_DIR, LLM_BASE_URL, LLM_MODEL, GMAIL_QUERY, ...
      paths.py              # /data layout constants
    sources/
      base.py               # Source protocol, FakeSource
      gmail.py              # GmailSource (read-only scope)
    journal/__init__.py
    policy/__init__.py
    retrieval/__init__.py
    classify/__init__.py
    draft/__init__.py
    briefing/
      __init__.py
      templates/            # briefing.html, message.html, base.html
    pipeline.py             # run_once()
    web.py                  # FastAPI app
    cli.py                  # `jarvis run`, `jarvis reindex`, `jarvis auth`
  tests/
    conftest.py             # tmp_path DATA_DIR, FakeLLM, FakeSource, fixture loader
    fixtures/               # gmail_message_*.json (recorded API payloads), *.eml
    test_nko_store.py  test_journal.py  test_policy.py  test_retrieval.py
    test_gmail_source.py  test_classify.py  test_draft.py  test_briefing.py
    test_pipeline.py  test_web.py
```

`/data` layout on the host (`HOST_JARVIS_DATA_DIR`):

```
/data/
  archive/<dedup_key>/nko-v0.json, nko-v1.json, ..., raw.eml, attachments/<sha256>-<filename>
  journal/YYYY-MM-DD.jsonl
  index/mail.sqlite
  secrets/credentials.json, token.json
```

`dedup_key` for Gmail is `gmail:<account>:<message_id>`, filesystem-safe after replacing `:` with `_` in directory names.

## Shared contracts (`core/`)

These are written first, by one agent, before any parallel work starts. Every other unit imports only from `core/` and `sources/base.py`.

### `core/nko.py`

Copied from GTE with these changes:

- `KnowledgeType`: `email`, `document`, `calendar_event`.
- `NKOStatus`: `captured`, `classified`, `drafted`, `corrected`. Errors are journal events, not versions.
- Everything else as in GTE: `id: UUID`, `knowledge_type`, `source_system`, `source_account`, `source_identifier`, `source_url`, `dedup_key`, `occurred_at`, `received_at`, `participants`, `subject`, `content`, `attachments`, `references`, `facts`, `observations`, `classifications`, `recommendations`, `decisions`, `confidence`, `status`, `labels`, `policy_matches`, `raw_metadata`, `version`; `frozen=True`; tuples for sequence fields; a read-only mapping for `raw_metadata`; `NKO.new(**fields)`; `NKO.derive(**changes)` returning `version + 1`.

### Version chain

| Version | Produced by | Adds |
| --- | --- | --- |
| v0 | `sources/gmail.py` | Facts only. `participants` (from/to/cc with name and address), `subject`, `content` (plain text, HTML stripped), `attachments` (`filename`, `mime`, `size`, `sha256`, `path`), `references` (`thread_id`, `in_reply_to`, `message_id_header`), `raw_metadata` (full Gmail `users.messages.get` payload minus body data). `status=captured`. Written once, never rewritten. |
| v1 | `classify` | `observations`: retrieved evidence, each `{nko_id, dedup_key, subject, received_at, snippet, score}`. `classifications`: exactly one entry `{group, topic, requested_action, deadline, priority, reasoning, model, at}`. `status=classified`. |
| v2 | `draft` | `recommendations`: exactly one entry `{reply_text, proposed_action, rationale, model, at}`. `status=drafted`. |
| v3+ | `briefing.apply_correction` | `decisions`: appended `{from_group, to_group, note, at}`. `status=corrected`. Every correction is a new version. |

Enumerations, enforced in code:

- `group`: `needs_decision`, `reply_suggested`, `fyi`, `likely_noise`.
- `priority`: `high`, `normal`, `low`.
- `proposed_action`: `none`, `archive`, `label`, `unsubscribe`.
- `deadline`: ISO date or null. `requested_action`: string or null.

The effective group of a message is the `to_group` of its last `decisions` entry if any, else `classifications[0].group`.

### `core/store.py`

```python
def save_version(nko: NKO) -> Path       # writes archive/<key>/nko-v<N>.json atomically (temp + rename); refuses to overwrite
def get_latest(dedup_key: str) -> NKO | None
def get_version(dedup_key: str, version: int) -> NKO
def get_versions(dedup_key: str) -> list[NKO]
def exists(dedup_key: str) -> bool
def iter_latest() -> Iterator[NKO]         # every message, latest version
def save_raw(dedup_key: str, name: str, data: bytes) -> Path   # raw.eml and attachments
```

### `core/llm.py`

```python
class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int = 1024) -> dict: ...

class LlamaCppClient(LLMClient):   # POST {LLM_BASE_URL}/v1/chat/completions with
                                   # response_format={"type": "json_schema", "json_schema": {...}},
                                   # temperature 0, timeout from settings, returns parsed dict,
                                   # raises LLMError on HTTP error, timeout, or unparseable JSON
class FakeLLM(LLMClient):          # constructed with a list of responses (dicts or exceptions) returned in order
```

### `sources/base.py`

```python
class Source(Protocol):
    name: str
    def poll(self, since: datetime) -> Iterator[NKO]: ...   # yields v0 NKOs; must not yield a dedup_key already in store

class FakeSource(Source):          # yields NKOs built from tests/fixtures
```

### `journal` event shape

```python
class JournalEvent(BaseModel):
    ts: datetime
    kind: Literal["run", "capture", "classify", "draft", "correction", "policy_reject", "error"]
    nko_id: UUID | None
    dedup_key: str | None
    version: int | None
    payload: dict
```

## Units

Each unit is one package with one public surface, its own tests, and no imports from sibling units except through `core/`.

| Unit | Public functions | Depends on |
| --- | --- | --- |
| `journal` | `append(event)`; `read(day: date) -> list[JournalEvent]`; `events_for(dedup_key) -> list[JournalEvent]`; `last_run() -> JournalEvent \| None`. One JSONL file per UTC day under `/data/journal/`, append-only, one `open(..., "a")` per event. Malformed lines are skipped and counted, never fatal. | filesystem |
| `policy` | `ALLOWED = {"read", "archive_copy", "classify", "search", "suggest", "draft"}`; `check(action: str) -> None` raises `PolicyViolation` otherwise; `filter_model_output(output: dict, *, dedup_key=None) -> (clean, rejected)` strips any `tool_calls`, `function_call`, or top-level keys named `action`/`send`/`forward`/`delete`/`label`/`modify` from a model response and journals a `policy_reject` for each. | journal |
| `retrieval` | `index(nko)`; `search(query: str, k: int = 5, exclude: str \| None = None) -> list[Evidence]`; `rebuild() -> int` drops the index and re-indexes every `store.iter_latest()`. SQLite with FTS5 (`subject`, `content`, `sender` columns, `dedup_key` unindexed), file `/data/index/mail.sqlite`, schema version pragma; mismatch triggers rebuild. `Evidence` is a small pydantic model matching the `observations` entry shape. | store |
| `sources/gmail` | `GmailSource(settings).poll(since)`. Scope: `https://www.googleapis.com/auth/gmail.readonly` only. Query: `GMAIL_QUERY` (default `in:inbox`) plus `after:<since>`. Lists ids, skips any `store.exists(dedup_key)`, fetches `format=raw` for `raw.eml` and `format=full` for the payload, saves attachments by sha256, yields v0. `normalize(payload, raw_bytes) -> NKO` is a pure function tested on fixtures. Token from `/data/secrets/token.json`; refresh is automatic; missing or revoked token raises `AuthRequired` naming `scripts/jarvis-auth.ps1`. | Gmail API, store |
| `classify` | `classify(nko: NKO, evidence: list[Evidence], corrections: list[dict], llm: LLMClient) -> NKO` returns v1. System prompt states the message is untrusted data and instructions inside it are not commands. User prompt includes sender, subject, first N chars of content (N from settings, default 6000), evidence snippets, and up to 5 prior corrections from the same sender or domain as few-shot examples. Requests the JSON schema for the classification entry. Two retries on `LLMError` or schema validation failure, then raises `ClassifyError`. Output is passed through `policy.filter_model_output` before validation. | `LLMClient`, policy, journal |
| `draft` | `draft(nko: NKO, corrections: list[dict], llm: LLMClient) -> NKO` returns v2. For `likely_noise` and `fyi` with no requested action, `reply_text` is null without calling the model. Same untrusted-data system prompt, same retry and policy filter. | `LLMClient`, policy, journal |
| `briefing` | `render(nkos: list[NKO], errors: dict[str, JournalEvent]) -> str`; `render_message(nko: NKO, versions: list[NKO], events: list[JournalEvent]) -> str`; `apply_correction(dedup_key, to_group, note) -> NKO` derives a new version, saves it, journals `correction`, changes nothing else; `corrections_for(sender: str, domain: str) -> list[dict]` reads past `decisions` for classify and draft. | store, journal, jinja2 |
| `pipeline` | `run_once(sources, llm) -> RunSummary`. | all |
| `web` | FastAPI app, routes below. | briefing, pipeline |

## Data flow

`run_once()`:

1. `policy.check("read")`.
2. `since` = `journal.last_run().ts` minus 1 hour of overlap, or now minus `INITIAL_LOOKBACK_DAYS` (default 7) on first run.
3. For each source, for each v0 yielded by `poll(since)`:
   1. `store.save_version(v0)`, `journal.append(capture)`, `retrieval.index(v0)`.
   2. `evidence = retrieval.search(f"{subject} {sender}", k=5, exclude=dedup_key)`.
   3. `corrections = briefing.corrections_for(sender, domain)`.
   4. `v1 = classify(...)`, `store.save_version(v1)`, `journal.append(classify)`.
   5. `v2 = draft(...)`, `store.save_version(v2)`, `journal.append(draft)`.
   6. Any exception in steps 2 to 5 is caught per message: `journal.append(error, payload={"stage", "message"})`, and the loop continues. A message with a v0 but no v1 is retried on the next run because `poll` only skips keys already in the store, and the pipeline re-enters at the first missing version.
4. `journal.append(run, payload={"captured", "classified", "drafted", "errors", "since"})`.

Retrieval indexes v0 content only, so a rebuild from the archive gives identical search results.

## Error handling

- One message failing (LLM timeout, invalid JSON after retries, oversized attachment) never stops the run.
- `AuthRequired` from the Gmail source aborts the run before any message is processed, with the message naming `scripts/jarvis-auth.ps1`.
- `store.save_version` writes to `nko-v<N>.json.tmp` then renames; a crash leaves no partial version. An attempt to save an existing version raises.
- The FTS index is disposable. Any schema mismatch or corruption triggers `rebuild()`.
- Attachments larger than `MAX_ATTACHMENT_BYTES` (default 25 MB) are recorded in `attachments` with `path=null` and `skipped_reason`.
- `LlamaCppClient` timeout defaults to 120 s per call; on the measured 56 tok/s a 1024-token answer fits.

## Web surface

| Route | Behaviour |
| --- | --- |
| `GET /` | Briefing. Four sections in the order Needs your decision, Reply suggested, For your information, Likely noise, each listing messages by effective group, newest first. Each card separates **facts** (sender, subject, received, attachments), **evidence** (observation snippets linked to `/message/<key>`), **inference** (topic, requested action, deadline, priority, reasoning), and **draft** (reply text, proposed action, rationale). A correction form (group select, optional note) posts to `/correct`. An "Unprocessed" section at the bottom lists messages whose latest journal event is `error`, with the error text. A "Run now" button posts to `/run`. |
| `POST /correct` | Form fields `dedup_key`, `to_group`, `note`. Calls `apply_correction`, redirects to `/`. |
| `POST /run` | Runs `run_once()` synchronously, redirects to `/`. A second concurrent request returns 409 while a run is in progress (process-level lock). |
| `GET /message/{dedup_key}` | Every version of the NKO and every journal event for it, in order. |
| `GET /health` | `{"ok": true, "llm": bool, "messages": int, "last_run": iso \| null}`. `llm` is a `GET {LLM_BASE_URL}/v1/models` probe. |

No auth. LAN only.

## Compose and configuration

`compose.yaml` gains:

```yaml
  jarvis:
    build: ./jarvis
    restart: unless-stopped
    depends_on:
      - llm-api
    ports:
      - "${JARVIS_HOST_PORT:-8090}:8090"
    environment:
      - JARVIS_DATA_DIR=/data
      - JARVIS_LLM_BASE_URL=http://llm-api:8080
      - JARVIS_LLM_MODEL=${LLM_MODEL_PATH:-/models/model.gguf}
      - JARVIS_GMAIL_ACCOUNT=${JARVIS_GMAIL_ACCOUNT:-}
      - JARVIS_GMAIL_QUERY=${JARVIS_GMAIL_QUERY:-in:inbox}
    volumes:
      - "${HOST_JARVIS_DATA_DIR:-/srv/llm/jarvis-data}:/data"
```

`.env.example` gains `JARVIS_HOST_PORT=8090`, `JARVIS_GMAIL_ACCOUNT=conradstorz@gmail.com`, `JARVIS_GMAIL_QUERY=in:inbox`, and the existing `HOST_JARVIS_DATA_DIR` comment changes from "reserved" to "mounted at /data in jarvis".

`.gitignore` gains `jarvis/secrets/`, `credentials.json`, `token.json`, `jarvis/.venv/`, `*.sqlite`.

Settings are read with pydantic-settings from `JARVIS_*` environment variables, with defaults suitable for tests (`DATA_DIR` overridden by `conftest.py`).

## Operator scripts

All follow the `Select-String` single-key `.env` convention of `start.ps1` and require `.env` to exist.

| Script | Does |
| --- | --- |
| `scripts/jarvis-auth.ps1 -CredentialsPath <credentials.json>` | Runs `uv run jarvis auth <credentials.json>` in `jarvis/` on the workstation (console OAuth flow, read-only scope, browser opens locally), producing `token.json`. Then copies `token.json` (which embeds the client id and secret needed for refresh) into `HOST_JARVIS_DATA_DIR/secrets/` on the host via a one-shot `alpine` container reading stdin. `credentials.json` stays on the workstation. |
| `scripts/jarvis-run.ps1` | `POST http://localhost:<JARVIS_HOST_PORT>/run`, then `GET /health`, prints message count and last run time. |
| `scripts/jarvis-reindex.ps1` | `docker --context <ctx> compose exec -T jarvis uv run --no-dev jarvis reindex`, prints indexed count. |
| `scripts/health.ps1` | Gains a `GET /health` against `JARVIS_HOST_PORT`, reported alongside the existing two checks. |

## Documentation

- `docs/jarvis.md` (new): what Phase 1 does and does not do, the `/data` layout, the OAuth bootstrap steps (Google Cloud project, enable Gmail API, Desktop-app OAuth client, download `credentials.json`, run `jarvis-auth.ps1`), how to read a briefing, how corrections work, and the reindex procedure.
- `docs/roadmap.md`: Phase 1 section gains a status line and notes that `draft` was pulled forward; the "Mapping to the Jarvis logical components" table updates.
- `README.md`: one paragraph and the three new script lines.
- `CLAUDE.md`: commands table gains the three scripts; a line noting `.env` parsing now spans ten scripts.

## Testing

Python, `uv run pytest` in `jarvis/`, no network, no GPU, `DATA_DIR` pointed at `tmp_path`:

| Test file | Proves |
| --- | --- |
| `test_nko_store.py` | `derive` increments `version` and preserves v0 fields; frozen fields and tuples reject mutation; save/get/iter round-trip; overwrite refused; a simulated crash mid-write (patch `os.replace` to raise) leaves no `nko-v<N>.json`. |
| `test_journal.py` | append then `read(day)`; `events_for` in order; a malformed line is skipped, others returned; `last_run` returns the newest `run`. |
| `test_policy.py` | every `ALLOWED` action passes; `send`, `delete`, `modify`, `label`, `unsubscribe`, `http_fetch` raise `PolicyViolation`; `filter_model_output` removes `tool_calls` and a top-level `send` key, journals one `policy_reject` each, and returns the remaining dict intact. |
| `test_retrieval.py` | index 3 fixtures; search by a distinctive subject word returns that one first; `exclude` works; delete the sqlite file, `rebuild()` returns 3 and the same query gives the same ranking. |
| `test_gmail_source.py` | `normalize()` on `fixtures/gmail_message_plain.json` and `_html_with_attachment.json` yields expected participants, subject, stripped text, attachment sha256; `poll` with a fake API client skips a `dedup_key` already in store; missing token raises `AuthRequired`. The real API is never called. |
| `test_classify.py` | `FakeLLM` valid response yields v1 with the right `group` and one `classifications` entry; invalid JSON twice then valid succeeds on the third; three failures raise `ClassifyError`; corrections text appears in the user prompt; a response with `tool_calls` yields a v1 plus one `policy_reject` event. |
| `test_draft.py` | v1 yields v2 with one `recommendations` entry; `likely_noise` skips the LLM (`FakeLLM` never called); `proposed_action` outside the enum fails validation. |
| `test_briefing.py` | `render` places each fixture under its group heading; `apply_correction` creates v(N+1) with one `decisions` entry, a `correction` journal event, and leaves `classifications` unchanged; the corrected message renders under its new group. |
| `test_pipeline.py` | `FakeSource` with 3 messages and `FakeLLM`: 3 v2s in store, journal has 3 capture, 3 classify, 3 draft, 1 run; when the second message's LLM call raises, that message has v0 only, an `error` event, and the other two complete; a second run skips the two done messages and completes the third. |
| `test_web.py` | `TestClient`: `GET /` 200 with the four headings; `POST /correct` 303 and the message moves group; `GET /message/<key>` lists versions; `GET /health` shape; `POST /run` during a run returns 409. |

PowerShell (`tests/assert-project-shape.ps1`, `tests/assert-script-contracts.ps1`) gain assertions for: the `jarvis` service block and `JARVIS_HOST_PORT` in `compose.yaml`; the three new keys in `.env.example`; `jarvis-auth.ps1`, `jarvis-run.ps1`, `jarvis-reindex.ps1` existing and containing the `.env` guard and `Select-String` pattern; `health.ps1` referencing `JARVIS_HOST_PORT`; `token.json` and `*.sqlite` in `.gitignore`; `docs/jarvis.md` existing with its top heading.

## Build order

Execution is sub-agent-driven, per the global development workflow rule.

1. **Serial, one agent: contracts.** `jarvis/pyproject.toml`, `Dockerfile`, `core/` (nko, store, llm, config, paths), `sources/base.py`, `tests/conftest.py`, `tests/fixtures/`, `test_nko_store.py`. Must pass before step 2 starts.
2. **Parallel, seven agents, one unit each with its tests:** `journal`, `policy`, `retrieval`, `sources/gmail`, `classify`, `draft`, `briefing` + `web`. Each agent touches only its own package, its template directory if any, and its own test file. `classify`, `draft`, and `briefing` are told the exact `journal`, `policy`, and `store` function signatures from this spec and may import them; if the sibling is not merged yet they stub it locally in tests only.
3. **Serial, one agent: integration.** `pipeline.py`, `cli.py`, `test_pipeline.py`, `compose.yaml`, `.env.example`, `.gitignore`, the three scripts, `health.ps1`, both PowerShell test scripts, docs.
4. **Serial, with the operator: first live run.** Build on hpz440, create the OAuth client, `jarvis-auth.ps1`, `jarvis-run.ps1`, review the first briefing, record the outcome and the measured per-message latency in `docs/roadmap.md` and `docs/models.md`.

## Exit criteria (from the roadmap, unchanged)

- A run produces a briefing for real new mail with all four groups populated correctly at least once.
- Corrections are recorded in the journal and change nothing else.
- The index can be deleted and rebuilt with identical search results.
- No outbound Gmail action is possible: the OAuth scope is read-only and the `policy` tests prove rejection.
- Both PowerShell test scripts and `uv run pytest` pass.

## Open decisions recorded, not resolved here

| Decision | When |
| --- | --- |
| Whether GTE's workspace agent supports two paired callers (GTE and Jarvis) with separate tokens, or expects exactly one engine. | Before any document source is added. |
| Whether `LLM_CONTEXT_SIZE` must rise to 8192 for message plus evidence plus corrections. | Measured in build step 4; raise in `.env` and record in `docs/models.md` if needed. |
| Scheduled polling. | Stay on-demand until briefing quality is trusted, as the roadmap says. |
| Calendar and Drive sources. | Later phase; the `Source` protocol is the hook. |

## Non-goals

Sending, labelling, archiving, or deleting mail; any cloud model call; auth or TLS on the briefing; NAS storage; scheduled runs; a JavaScript front end; reuse of GTE as a package dependency.
