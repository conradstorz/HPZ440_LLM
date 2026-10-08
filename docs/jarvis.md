# Jarvis (Phase 1: Observe, Phase 1.5: Converse)

Jarvis reads new Gmail with a read-only credential, archives every message as an immutable knowledge object, classifies it with the local model, searches earlier mail for evidence, prepares a reply draft and a proposed inbox action, and shows a grouped briefing. It takes no outbound action: nothing is sent, labelled, archived, or deleted in Gmail. The permission stage is 1 (Observe) as defined in `JARVIS_Home_Assistant_Reference.md`; drafts and proposed actions are shown so their quality can be judged, never executed.

## What runs where

- `jarvis` container on the HPZ440 (`compose.yaml`), built from `jarvis/`. Talks to `llm-api` over the compose network. Publishes `JARVIS_HOST_PORT` (default 8090). LAN only, no auth, no TLS.
- Data under `HOST_JARVIS_DATA_DIR` on the host (default `/srv/llm/jarvis-data`), mounted at `/data`:

```
/data/archive/<key>/nko-v0.json ...   one directory per message; v0 is the fact of record, never rewritten
/data/archive/<key>/raw.eml           the original RFC 822 message
/data/archive/<key>/attachments/      one file per attachment, named `<sha256 prefix>-<filename>`
/data/journal/YYYY-MM-DD.jsonl        append-only event log: run, capture, classify, draft, correction, note, tool_call, chat, policy_reject, error
/data/index/mail.sqlite               full-text index; disposable, rebuilt from the archive
/data/notes/notes.jsonl               append-only teaching notes; the latest version of each id wins
/data/secrets/token.json              Gmail refresh token, read-only scope
/data/secrets/agent_token             bearer token for GTE's workspace agent on the workstation
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

## Chat (Phase 1.5)

Jarvis is also a chat model. In Open WebUI (`http://localhost:3000`) pick **jarvis** from the model list beside the raw
llama.cpp model; Open WebUI reaches it at `http://jarvis:8090/v1` over the compose network. The raw model answers from
nothing but its weights; Jarvis answers from your archive, and cites the message keys it used.

What it can do: search and read your archived mail, show the briefing for any group, record a correction, read a
document on your workstation through GTE's agent, and keep notes you teach it. Every one of those is a tool call that
passes `jarvis/policy` first and is written to the journal as a `tool_call` event with its arguments, whether it
succeeded, and the first 200 characters of its result. A whole turn is journaled as one `chat` event (steps taken,
tools used, characters in and out, plus `tool_calls_skipped`, `overflow_retries` and `task_mode`). Open WebUI's chat
id reaches the journal as `conversation_id` because
`compose.yaml` sets `ENABLE_FORWARD_USER_INFO_HEADERS=true`; without it Open WebUI strips the header and every turn
journals `None`.

The loop executes at most three tool calls per step, dropping duplicates and anything past the cap with a `skipped`
tool reply, because a 7B model asked one question can emit thirty calls in a single turn and their combined results
overflow the context. Jarvis also detects Open WebUI's own generation prompts — chat titles, tags, follow-up
questions, which begin `### Task:` — and answers them with one plain model call, no tools and no notes, so they
neither run a Jarvis loop nor leave pending notes behind.

What it cannot do: send, forward, label, archive, or delete mail; reach the internet; call a cloud model. The policy
gate refuses those actions in code, not by prompt, and the reply says so plainly if you ask.

`JARVIS_CONTEXT_TOKENS` is the context the agent budgets for (system prompt, transcript, tool results and tool
schemas, leaving room for the reply); `compose.yaml` feeds it and llama.cpp's `--ctx-size` from the same
`LLM_CONTEXT_SIZE`, so raising one raises both. A turn also stops after 90 seconds or six tool steps and answers
with what it has.

Two operator settings in Open WebUI matter:

- Set the **Task Model** (Admin → Settings → Interface) to the raw llama.cpp model. Left on `jarvis`, every chat
  title and tag generation costs a second model call on the same GPU; Jarvis recognises those prompts and answers
  them without tools, but the raw model does the job faster and keeps them out of the chat journal entirely.
- On an existing Open WebUI volume the persisted connection list wins over `OPENAI_API_BASE_URLS`. If `jarvis` is
  missing from the model list, add the connection `http://jarvis:8090/v1` (any key) in Admin → Settings →
  Connections.

### Teaching it

Say "remember: invoices from Acme are always mine" and the note is saved active at once. State a preference any other
way and Jarvis proposes the note, asks "Save this note? (yes/no)", and saves it only after you say yes. Until then the
note is **pending** and reaches no prompt: pending notes are never injected into chat, classification, or drafts, and
a pending note nobody confirms is retired automatically after a day.

Active notes are injected into the system prompt for chat and into the classify and draft prompts for every message in
the next run, so teaching Jarvis a triage rule changes the next briefing.

`http://localhost:8090/notes` lists every note by status (active, pending, retired) with its id, version, what it
applies to, and where it came from. Each active or pending note has a Retire form; a reason is required and is stored
with the note. The Pending section also has a **Retire all pending** form, for when a stray turn has left a pile of
proposals behind; there the reason is optional. Retiring writes a new version, it does not delete: the note's history
stays in `notes.jsonl`.

### Workstation documents

Document tools read files on this Windows workstation through GTE's passive agent. Jarvis always initiates; the agent
never calls into the HPZ440.

1. Set `JARVIS_WORKSPACE_AGENT_URL` in `.env` to the workstation's tailnet address and the agent's port, for example
   `http://100.x.y.z:8765`. Left empty, the document tools stay registered but every call answers that no workspace
   agent is configured.
2. Put the agent's bearer token in `C:\Users\<you>\.jarvis\agent_token` (one line, no quotes). It stays on the
   workstation; only the copy under `/data/secrets/` reaches the host.
3. Run `pwsh -NoProfile -File scripts/jarvis-agent-token.ps1`. It copies the token to `/data/secrets/agent_token` on
   the host at mode 600 and never prints it.
4. Run `pwsh -NoProfile -File scripts/start.ps1` to restart with the new URL.

The token is read from disk on each request, not at startup, so the service starts fine before the token exists;
`list_documents` and `read_document` simply report that the agent is unavailable. Nothing read this way is archived.

### Live check

Date: 2026-09-30, first deploy of the Converse branch. Through the `jarvis` model endpoint (`POST /v1/chat/completions`, non-stream, from the workstation):

- "How many archived messages need my decision?" produced one `briefing` tool call and a correct count with message keys in 8 s. Journal: one `tool_call` (ok), one `chat` event with `steps: 1`.
- "remember: this is a live-check note ..." produced one `propose_note` call; the note landed active on `/notes` with `source: explicit` and was retired from the page afterwards.
- Zero `policy_reject` events across both turns.
- Open WebUI on the existing volume had the single llama.cpp URL persisted in its database, so the two connection rows (`openai.api_base_urls`, `openai.api_keys`) were updated in place before the restart; `jarvis` then appeared in its model list without touching the Admin UI.
- Not yet exercised: a proposed-then-confirmed note from inside Open WebUI, and workstation documents (no `JARVIS_WORKSPACE_AGENT_URL` set yet).
- First Open WebUI session found two defects, both fixed the same day: the persona let the model deny having Gmail access (it now names the mail tools and forbids that denial; "show me my recent messages" answers in 7 s), and the model could emit 30 to 40 tool calls in one response and overflow the context (now at most 3 per step, deduplicated, with a tighter token estimate and one overflow retry). Open WebUI's title and tag prompts had also been reaching Jarvis and creating junk pending notes; Jarvis now answers those `### Task:` prompts without tools, the Task Model was pointed at the raw llama.cpp model, and the junk notes were retired in bulk from `/notes`.

## Guarantees enforced in code

- The OAuth token is requested with `gmail.readonly` only, and the client refuses to start if the stored token carries any other scope.
- `jarvis/policy` allows exactly ten actions: `read`, `archive_copy`, `classify`, `search`, `suggest`, `draft`, `correct`, `notes_read`, `notes_write`, `documents_read`. Chat can reach `correct`, `notes_write`, and `documents_read` as well as the read-only ones, so a conversation can reclassify a message, save or retire a note, and read a workstation file — and nothing else. Every tool call is gated before it runs: an unknown tool name, non-JSON arguments, or an action outside that list is journaled as `policy_reject` and never executed. Allowed calls are journaled as `tool_call` with the arguments the model sent, whether the call succeeded, and the first 200 characters of the result.
- Model output is filtered too: any `tool_calls`, `function_call`, `send`, `forward`, `delete`, `label`, `modify`, or `action` key in a classification or draft is dropped and journaled as `policy_reject`.
- A note is saved active only when your own message in that turn contains remember, rule, from now on, always, or never. A model that asks for an explicit note without those words — including one talked into it by text inside a message or a document — gets a pending note that reaches no prompt until you say yes.
- Message bodies are passed to the model as untrusted data; the system prompt says so, and the policy filter applies regardless.
- Versions are written atomically and never overwritten.

## Known limits

- The briefing's forms carry no CSRF token. Accepted: the service is LAN-only, unauthenticated by design, and never takes an outbound action.
- Message text is fenced as untrusted data in the prompt, but the fence itself is not escaped. A hostile message can at worst mis-group itself or produce a draft that is displayed and never sent.
- The chat endpoint (`/v1/chat/completions`) carries no auth, like the rest of the service. Anything on the LAN that
  can reach port 8090 can read your mail through it. LAN only; the hardening phase in `roadmap.md` owns this.
- A pending note expires after a day. If you meant to say yes and did not, state the rule again.
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

## Production batch, 2026-10-05

Three consecutive runs against unpolled mail (last prior run 2026-09-30), cap 20 per run, production
config: one llama.cpp slot, `LLM_CONTEXT_SIZE` 8192. GPU sampled at 1 Hz throughout. 60 messages, no
synthetic load and no replay — this is the real pipeline on the current build.

| Measure | Value |
| --- | --- |
| Messages captured, classified, drafted | 60 / 60 / 60 |
| First-pass errors | **0** (0 `error` events, 0 `skipped`, 0 `policy_reject`) |
| Capture to draft, first attempt | p50 3.03 s, p90 4.18 s, p95 4.87 s, p99 5.35 s, max 5.74 s (target: under 10 s) |
| Classify stage alone | p50 2.63 s, p90 3.48 s, max 4.13 s |
| Draft stage alone | 0 s for 46 of 60; p90 1.57 s, max 2.32 s for the 14 that drafted |
| Groups | fyi 26, likely_noise 22, needs_decision 10, reply_suggested 2 |
| Drafts with reply text / proposed actions | 11 / none 53, label 5, archive 2 |
| GPU power | 13.7 W idle with the model resident, 142.2 W mean under load, 170.9 W peak |
| GPU utilisation under load | 84% mean |
| VRAM | 4,909 MB peak of 12,288 MB |
| Wall clock per run | 66-73 s for 20 messages, about 3.5 s each including the Gmail fetch |

Two things this settles. **Latency is not a constraint**: the worst message in 60 finished at 5.74 s
against a 10 s target, and the distribution is tight — p50 to max spans 2.7 s. **The 6.1 % first-pass
classification failure rate recorded on 2026-09-30 was an artefact of that day's bring-up**, not a
property of the build: the three fixes it provoked (`d358027`, `16fe9be`, `a2e3a41`) landed 16:47-17:09 UTC,
the two runs after them had zero errors, and this batch adds 60 more consecutive clean messages. 60 of 60
bounds the current rate below roughly 5 % at 95 % confidence; it does not prove zero.

Per message the pipeline makes one classify call and, for 14 of 60, one draft call. `likely_noise` never
drafts and `needs_decision` always does. So the LLM cost of triage is close to one structured completion
per message, which is why a 20-message run takes about a minute and why concurrency has little to offer
at this volume — the box was idle between runs, not saturated.

### The cap was silently losing mail

All three runs returned `capped: true`. Investigating that on 2026-10-06 found a real defect, not a
queue that would drain on its own.

`JARVIS_GMAIL_QUERY` was `in:inbox newer_than:1d` and the cap was 20. The inbox takes **~171
messages/day** (1,160 over 7 days), so no run could ever finish its window: `capped` latched, and
`_next_since` held the watermark to preserve a backlog it had no power to preserve. The query's
`newer_than:1d` is tighter than the `after:` the poller derives from `since`, so Gmail returned the
same 171 ids either way — the watermark was inert. Mail a capped run left behind simply aged past
`newer_than:1d` and became unreachable. 969 of the last 7 days' messages were unseen against 124 of
the last 1 day, so roughly **845 messages were never triaged and cannot now be found by this query**.

Two changes:

- `JARVIS_GMAIL_QUERY` is now `in:inbox newer_than:1d category:primary` and the cap is back to its 50
  default. One day of `category:primary` is ~12 messages against a cap of 50, so a run completes
  uncapped and the window actually advances. One day by category, measured 2026-10-06: promotions 51,
  updates 92, forums 13, primary 12, social 1. **The cap and the query are one lever** — widening the
  query without raising the cap reintroduces the loss, which is why `.env.example` now says so beside
  both.

  The headroom is real rather than assumed: `category:primary` runs 12.4/day over the last 7 days and
  9.7/day over 30, and the busiest single day in the last 14 was **15**, against a cap of 50. A
  weekday spike would have to more than triple to re-enter the failure.
- `GmailSource.poll` builds `after:` from one day *before* `since`. Gmail filters by date in the
  account's timezone while `since` is a UTC instant, so flooring it to a UTC date could land a day late
  and cut inside the requested window — just after midnight, `after:<today>` dropped all of yesterday
  evening. The clause is now only ever a lower bound; `query` is where a tighter window belongs, and
  `Store.exists()` absorbs the overlap. Covered by
  `test_poll_window_is_never_narrower_than_the_caller_asked_for`.

The ~845 skipped messages are not recoverable through this query. Most were `promotions` or `updates`
and out of scope under the new one; nothing was deleted, and they remain in Gmail.

**Every classification figure recorded above this line is drawn from the whole inbox, and is not
comparable to anything measured after 2026-10-06.** `category:primary` is a different population:
the 2026-10-05 batch was 22 of 60 `likely_noise`, which is largely what Gmail already files under
promotions and updates. Expect the group mix to shift hard toward `needs_decision` and `fyi`, and do
not read that as a model change. The Phase 2 quality gate — the correction rate — needs a fresh
baseline taken under the new query; the pre-2026-10-06 numbers cannot serve as one.

## Not in this phase

Sending or modifying mail, cloud models, scheduled polling, calendar sources, auth on the briefing or the chat endpoint, NAS storage. See `roadmap.md`. Phase 1.5 added chat, teaching notes, and read-only workstation documents; the rest of this list is unchanged.
