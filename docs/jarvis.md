# Jarvis (Phase 1: Observe)

Jarvis reads new Gmail with a read-only credential, archives every message as an immutable knowledge object, classifies it with the local model, searches earlier mail for evidence, prepares a reply draft and a proposed inbox action, and shows a grouped briefing. It takes no outbound action: nothing is sent, labelled, archived, or deleted in Gmail. The permission stage is 1 (Observe) as defined in `JARVIS_Home_Assistant_Reference.md`; drafts and proposed actions are shown so their quality can be judged, never executed.

## What runs where

- `jarvis` container on the HPZ440 (`compose.yaml`), built from `jarvis/`. Talks to `llm-api` over the compose network. Publishes `JARVIS_HOST_PORT` (default 8090). LAN only, no auth, no TLS.
- Data under `HOST_JARVIS_DATA_DIR` on the host (default `/srv/llm/jarvis-data`), mounted at `/data`:

```
/data/archive/<key>/nko-v0.json ...   one directory per message; v0 is the fact of record, never rewritten
/data/archive/<key>/raw.eml           the original RFC 822 message
/data/archive/<key>/attachments/      one file per attachment, named `<sha256 prefix>-<filename>`
/data/journal/YYYY-MM-DD.jsonl        append-only event log: run, capture, classify, draft, correction, policy_reject, error
/data/index/mail.sqlite               full-text index; disposable, rebuilt from the archive
/data/secrets/token.json              Gmail refresh token, read-only scope
```

## One-time Gmail setup

1. In Google Cloud Console create a project (or reuse one), enable the **Gmail API**, and create an **OAuth client ID** of type **Desktop app**. Download it as `credentials.json` and save it at `C:\Users\<you>\.jarvis\credentials.json`, outside every repository. It is never copied to the host and never pasted into a chat.
2. Copy `.env.example` to `.env` if not done; set `JARVIS_GMAIL_ACCOUNT`.
3. In a terminal of your own (not through an AI session), run `pwsh -NoProfile -File scripts/jarvis-auth.ps1` (add `-CredentialsPath` if the file is elsewhere). A browser window asks for consent to the single scope `gmail.readonly`. The script writes `token.json`, copies it to `/data/secrets/` on the host through the Docker context, and deletes the local copy.
4. `pwsh -NoProfile -File scripts/start.ps1` builds and starts the stack, including `jarvis`.

To revoke: remove the app at https://myaccount.google.com/permissions and delete `/data/secrets/token.json` on the host.

## Using it

- `pwsh -NoProfile -File scripts/jarvis-run.ps1` triggers one pass and prints the archive count. The first pass looks back 7 days (`initial_lookback_days`); later passes start one hour before the previous run.
- One run captures at most `JARVIS_MAX_MESSAGES_PER_RUN` (default 50) new messages and persists each one as it arrives, so an interrupted run keeps everything it had already archived; it backs off and retries when Google answers a rate-limit error, and running again continues from where it stopped.
- Open `http://localhost:8090/` (or the HPZ440's LAN address). Four groups: Needs your decision, Reply suggested, For your information, Likely noise. Each card separates facts (from the message), evidence (links to earlier mail), inference (the model's classification and its reasoning), and the draft. An Unprocessed section at the bottom lists messages whose last stage failed, with the error; the next run retries them. After five `error` events a message is no longer retried and simply stays in Unprocessed. Clearing that counter is not supported: fix the cause, re-run, and if the message still needs processing delete its archive directory so the next poll re-captures it.
- To correct a classification, pick a group in the card's form and submit. That writes a new version of the message with a `decisions` entry and a `correction` journal event; nothing else changes. Later classifications from the same sender or domain see your corrections as examples.
- `/message/<key>` shows every version and journal event for one message.
- `pwsh -NoProfile -File scripts/jarvis-reindex.ps1` drops and rebuilds the search index from the archive. Safe at any time.
- `pwsh -NoProfile -File scripts/health.ps1` now also checks `/health` on the Jarvis port.

## Guarantees enforced in code

- The OAuth token is requested with `gmail.readonly` only, and the client refuses to start if the stored token carries any other scope.
- `jarvis/policy` allows exactly `read, archive_copy, classify, search, suggest, draft`. Model output is filtered: any `tool_calls`, `function_call`, `send`, `forward`, `delete`, `label`, `modify`, or `action` key is dropped and journaled as `policy_reject`.
- Message bodies are passed to the model as untrusted data; the system prompt says so, and the policy filter applies regardless.
- Versions are written atomically and never overwritten.

## Known limits

- The briefing's forms carry no CSRF token. Accepted: the service is LAN-only, unauthenticated by design, and never takes an outbound action.
- Message text is fenced as untrusted data in the prompt, but the fence itself is not escaped. A hostile message can at worst mis-group itself or produce a draft that is displayed and never sent.
- A large backlog is drained 50 messages per run, not all at once; trigger repeated runs, or raise `JARVIS_MAX_MESSAGES_PER_RUN`, to catch up. Gmail's per-user quota is the real ceiling.

## Tests

```powershell
cd jarvis
uv run pytest
```

No network, no GPU, no Gmail. The Gmail source is tested against recorded API payloads in `jarvis/tests/fixtures/`.

## First live run

Date: 2026-09-30. Inbox: `conradstorz@gmail.com`, query `in:inbox newer_than:1d`, cap 20 messages per run, six runs.

| Measure | Value |
| --- | --- |
| Messages captured, classified, drafted | 120 / 120 / 120 |
| Groups (latest classification) | needs_decision 22, reply_suggested 3, fyi 62, likely_noise 33 |
| Drafts with reply text / proposed actions | 17 / none 97, label 15, archive 8 |
| Capture to draft, first attempt | median 2.6 s, p90 4.0 s, max 5.5 s (target: under 10 s) |
| `policy_reject` events | 0 |
| `LLM_CONTEXT_SIZE` | 8192 (raised from 4096 after two prompts returned HTTP 400) |

Problems found and fixed during the run, in order: Google's per-minute quota cut the first pass off before any message was persisted (now each message is saved as it arrives, runs are capped, and rate-limit responses back off); `start.ps1` did not rebuild the image (now `up -d --build`); the model wrote free text into `deadline` (schema now constrains it to an ISO date and the validator coerces anything else to null); the `reasoning` string could run to the token limit and truncate the JSON (all schema strings now carry `maxLength`); llama.cpp's 400 body was not journaled (it is now). After those fixes the final pass processed 20 messages with zero errors.

Classification quality has not yet been judged: no corrections have been submitted. Review the briefing and correct a few cards; the correction rate over the coming weeks is the Phase 2 quality gate.

## Not in this phase

Sending or modifying mail, cloud models, scheduled polling, calendar or document sources, the GTE workspace agent, auth on the briefing, NAS storage. See `roadmap.md`.
