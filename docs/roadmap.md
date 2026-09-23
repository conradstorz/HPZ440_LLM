# Roadmap: From HPZ440 Local LLM to Jarvis

Status: Approved roadmap
Updated: 2026-09-23

This repository started as an operations stack for serving a 7B GGUF model on the HPZ440 (`compose.yaml`, `scripts/*.ps1`). It will grow into the Jarvis home assistant described in `JARVIS_Home_Assistant_Reference.md`. This document reconciles the two: what exists today, what Jarvis needs, and the order in which the gap closes.

Each phase is one spec, plan, implement cycle (`docs/superpowers/specs/`, `docs/superpowers/plans/`). A phase is not done until its exit criteria are met and its tests pass.

## Decisions already made

| Decision | Choice | Consequence |
| --- | --- | --- |
| Repo scope | This repo grows into Jarvis. | Jarvis services are added to `compose.yaml`; application code lives here. |
| Inference server | Keep `llama.cpp` (`llm-api`). | Jarvis talks to `http://llm-api:8080/v1` inside the compose network. Ollama is not adopted. |
| GPU | RTX 3060 12GB, not yet installed. | Phase 0 blocks on hardware. Model class stays 7B Q4_K_M/Q5_K_M. |
| First mailbox | Gmail, `conradstorz@gmail.com`. | Gmail API with OAuth. Read-only scope until Phase 3. |
| Application stack | Python managed with `uv`. | One `jarvis` container (FastAPI or similar) beside `llm-api` and `open-webui`. |
| Archive location | HPZ440 local disk first, Synology later. | New `HOST_JARVIS_DATA_DIR` in `.env`, bind-mounted like `HOST_MODEL_DIR`. NAS migration is a cross-cutting track. |

## Current state (what exists)

- `llm-api`: `ghcr.io/ggml-org/llama.cpp:server-cuda`, one GPU reserved, models mounted read-only at `/models`, published on `LLM_HOST_PORT` (8080).
- `open-webui`: browser chat against `llm-api`, published on `WEBUI_HOST_PORT` (3000), data in the `open-webui-data` volume.
- Workstation scripts: `check-context`, `start`, `stop`, `health`, `switch-model`, `benchmark`, `list-models`.
- Tests: two standalone PowerShell scripts that regex-match literal file content.
- Nothing has run on real GPU hardware yet.

Mapping to the Jarvis logical components:

| Jarvis component | Status in this repo |
| --- | --- |
| Local inference service | Exists (`llm-api`). Unvalidated on hardware. |
| User interface | Open WebUI exists as a raw chat surface only. No briefing, approvals, or rule UI. |
| Jarvis application | Absent. |
| Mail connector | Absent. |
| Retrieval service | Absent. |
| Cloud gateway | Absent. |
| NAS archive | Absent. |

## Phase 0: Foundation

Goal: a working, measured inference layer on real hardware, plus the configuration surface later phases need.

In scope:

- Install the RTX 3060 in the HPZ440 and confirm the NVIDIA container runtime works from the `hpz440` Docker context.
- Place one 7B instruct GGUF (Q4_K_M) under `/srv/llm/models` and run the stack.
- Set a real `WEBUI_SECRET_KEY` in `.env`.
- Add `HOST_JARVIS_DATA_DIR` to `.env.example` and `compose.yaml` (unused until Phase 1) and ignore its local counterpart in `.gitignore`.
- Extend `benchmark.ps1` output to record tokens per second from the response `usage` and `timings` fields so later model choices are comparable.

Out of scope: any Jarvis application code, mail access, cloud calls.

Exit criteria:

- `health.ps1` passes against the running stack.
- `benchmark.ps1` writes a JSON file with a measured tokens/sec for the chosen model, and that number is recorded in `docs/models.md`.
- Both test scripts pass after the `.env.example` and `compose.yaml` changes.

Decisions this phase resolves: model file and quantization; acceptable latency for triage (target: one email classified in under 10 seconds); whether 4096 context is enough for a message plus retrieved evidence, or `LLM_CONTEXT_SIZE` must rise.

## Phase 1: Observe (read-only inbox briefing)

Goal: Jarvis reads new Gmail, stores a local archive copy under `/data/archive/` (the Gmail mailbox itself is never modified; messages stay in the inbox), classifies it, searches prior records, and presents a briefing. It takes no outbound action. This is the Jarvis document's first milestone and permission stage 1.

Architecture added to `compose.yaml`:

- `jarvis`: Python service (uv-managed, `pyproject.toml` under `jarvis/`) exposing a small HTTP UI and an internal API. Talks to `llm-api` over the compose network. Bind-mounts `HOST_JARVIS_DATA_DIR` at `/data`.
- One new published port, `JARVIS_HOST_PORT`, for the briefing UI. LAN only, no auth; that constraint is unchanged until a hardening phase.

Internal units, each independently testable:

| Unit | Responsibility | Depends on |
| --- | --- | --- |
| `capture` | Poll Gmail (read-only OAuth scope), store raw message and attachments with source id, receipt time, SHA-256, under `/data/archive/`. Idempotent on message id. | Gmail API |
| `journal` | Append-only event log (`/data/journal/`, one JSONL file per day): captures, classifications, corrections, approvals, rule changes, disclosures. Every later unit writes here. | filesystem |
| `classify` | Given a captured message plus retrieved evidence, ask `llm-api` for sender, topic, requested action, deadline, priority, and one of four groups: Needs your decision, Reply suggested, For your information, Likely noise. Output is structured JSON validated in code. | `llm-api`, `retrieval` |
| `retrieval` | SQLite full-text index over archived mail and documents, rebuildable from `/data/archive/`. Returns source-linked evidence. | filesystem |
| `briefing` | Renders the grouped briefing with evidence separated from inference, a suggested reply where relevant, and a one-click correction control that writes to `journal`. | `classify`, `retrieval`, `journal` |
| `policy` | The permission gate. In Phase 1 it allows only read, copy to the local archive, classify, search, suggest. Any outbound tool call is rejected in code, not by prompt. | none |

Rules enforced in code, not in prompts:

- Email bodies, attachments, and fetched pages are untrusted input. Model output that requests a tool call outside the current permission stage is logged and dropped.
- The Gmail credential is granted read-only scope. Send scope is not requested until Phase 3.
- The archive is source of truth; the index can be deleted and rebuilt at any time.

Operator surface additions: `scripts/jarvis-briefing.ps1` (trigger a run, print summary) and `scripts/jarvis-reindex.ps1`. Both follow the existing `.env` parsing convention.

Testing: unit tests under `jarvis/tests/` (`uv run pytest`) for `journal` append and replay, `retrieval` rebuild, `classify` JSON validation with a stubbed LLM, and `policy` rejecting outbound calls. The existing PowerShell literal-content tests gain assertions for the new compose service, env keys, and scripts.

Exit criteria:

- A scheduled or on-demand run produces a briefing for real new mail with all four groups populated correctly at least once.
- Corrections are recorded in the journal and change nothing else.
- The index can be deleted and rebuilt with identical search results.
- No outbound Gmail action is possible: the OAuth scope is read-only and the `policy` tests prove rejection.

Decisions this phase resolves: schedule vs on-demand (start on-demand, add a periodic poll once quality is trusted); how corrections feed back (Phase 1 stores them; Phase 2 uses them); briefing UI framework (server-rendered HTML is enough).

## Phase 2: Propose (drafts and proposed actions)

Goal: permission stage 2. Jarvis prepares reply drafts and proposed actions (Gmail archive, label, unsubscribe) for review. Still nothing leaves the network or the inbox.

In scope:

- `draft` unit: produces reply text and a proposed action per message, stored with the message and shown in the briefing.
- Correction loop: past corrections from the journal are retrieved as few-shot evidence for `classify` and `draft`.
- Quality gate: a `docs/quality.md` log of weekly review sessions recording classification accuracy against Conrad's corrections. Phase 3 does not start until accuracy is judged dependable in that log.

Exit criteria: drafts appear in the briefing; proposed actions are recorded but never executed; the quality log shows a stable, acceptable correction rate over several weeks of real use.

## Phase 3: Individual approval (first outbound actions)

Goal: permission stage 3. A specific send or inbox action executes only after Conrad approves that instance.

In scope:

- Gmail credential upgraded to include send and modify scopes. This is the first credential change since Phase 1 and is itself a journaled event.
- `policy` gains per-instance approvals: an approval record (message id, action, approved content hash, timestamp) must exist before a new `act` unit performs anything. Content edited after approval invalidates it.
- Global outbound pause: a single flag under `/data/` that `act` checks on every call; reading and drafting continue while paused.
- Briefing UI gains approve, reject, and edit-then-approve controls.

Exit criteria: one real reply sent through Jarvis with its approval record and journal entry; a paused system provably refuses the same action; tests cover approval-hash mismatch and pause.

## Phase 4: Cloud gateway and standing rules

Goal: escalate to stronger cloud models with redaction and audit, then permission stage 4 (narrow standing rules).

In scope:

- `gateway` service in `compose.yaml` (LiteLLM or a small in-house proxy). Only `jarvis` may call it; `llm-api` and Open WebUI remain local-only.
- Redaction step before egress: minimum useful excerpt, identifiers removed, disclosure record (reason, provider, model, exact payload, response, resulting action) written to the journal.
- Spend limits per day and per request; an approval prompt when redaction would defeat the task.
- Standing rules: versioned rule records with trigger, recipients, permitted content, limits, approval record, and revocation. `act` executes under a rule only when every field matches. Rules are approved one at a time.

Exit criteria: a cloud escalation is visible end to end in the journal with its redacted payload; one narrow rule (the Jarvis document's monthly-statement example or similar) is approved, exercised, and revoked as a test.

## Cross-cutting tracks

These run alongside phases rather than gating one.

**NAS migration.** Phase 1 writes to HPZ440 local disk. Before Phase 3 goes live, move `/data/archive/` and `/data/journal/` to a Synology DS220+ share mounted on the HPZ440 and bind-mounted into `jarvis`; `HOST_JARVIS_DATA_DIR` simply changes value. Then, as a separate step, verify DSM support for WriteOnce or immutable snapshots, configure retention with separate credentials, set up the DS216j as a second backup target, and test a restore. Do not describe the archive as immutable in any doc until that restore test is recorded.

**Repository conventions.** Every phase must keep the existing rules: literal-content tests updated in the same change as any renamed script, port, or doc heading; `.env` parsing consistent across all PowerShell scripts; archive, journal, OAuth tokens, and index data gitignored. Python code uses `uv` exclusively.

**Security posture.** LAN-only, no auth, no TLS remains the stated scope through Phase 4. Once the briefing UI holds mail content, that is a real exposure on the LAN even without internet access. A hardening phase (auth on `jarvis` and Open WebUI, TLS, network segmentation) should be scheduled before any device outside Conrad's control joins the network. Public internet exposure stays out of scope.

## Open decisions

| Decision | Resolved in | Notes |
| --- | --- | --- |
| Model file and quantization | Phase 0 | Measured, not guessed. |
| Triage latency and power budget | Phase 0 | Benchmark numbers in `docs/models.md`. |
| Context size for message plus evidence | Phase 0 | May raise `LLM_CONTEXT_SIZE`. |
| Briefing schedule vs on-demand | Phase 1 | Start on-demand. |
| Retention rules for mail and research captures | NAS track | Define before NAS migration. |
| Encryption and recovery for the archive | NAS track | Tied to the restore test. |
| Redaction review for sensitive topics | Phase 4 | Approval prompt is the fallback. |
| Cloud usage budgets | Phase 4 | Per day and per request. |
| Approval and rule-management interface | Phase 3 | Extends the briefing UI. |
| Hardening timing | Security track | Before non-Conrad devices join the LAN. |

## Non-goals (unchanged from the original design)

Kubernetes or multi-node orchestration, training or fine-tuning, automated downloads from gated model providers, and public internet exposure.
