# Obi-Wan (v0.1: the Historian)

Obi-Wan keeps the record: which documents exist, where each was last seen, which version is current, where every
piece of knowledge came from, and how much of it is searchable right now. It runs as the `obiwan` service beside
Jarvis, holds no model, no outbound credential, and no route off the host. Jarvis finds through it and judges itself.

Specification: `docs/superpowers/specs/2026-10-07-obiwan-v0.1-mvp.md` and `2026-10-07-obiwan-command-structure.md`.
Plan: `docs/superpowers/plans/2026-10-07-obiwan-v0.1.md`.

## The three actors

| Actor | Credential | May | May not |
|---|---|---|---|
| Commander (Conrad) | `OBIWAN_COMMANDER_TOKEN`, used only through `scripts/obiwan-confirm.ps1` | promote a relayed fact to direct; order a subject forgotten | |
| Admiral (Jarvis) | reader + writer | search; submit machine notes; relay Conrad's words as human/relayed; trigger scans and reindexes | reach `/confirm`; name an origin or attestation; update or delete anything |
| Historian (Obi-Wan) | none outbound | read source roots; mint identity; store, version, index; report coverage | interpret; call a model; write a source root; delete on its own initiative |

Origin is set per route: `/submit` is always `machine`, `/relay` is always `human`/`relayed`, `/confirm` is always
`human`/`direct`. A payload that names `origin` or `attestation` is refused with HTTP 400 and journaled.

## What runs where

- Container `hpz440-llm-obiwan-1`, port 8070 published on the HPZ440's loopback only. From this workstation it is
  `http://localhost:8070` through the SSH tunnel; the LAN reaches it only through Jarvis.
- `HOST_OBIWAN_DIR` (default `/srv/obiwan`) on the HPZ440:
  - `data/` → `/data`: `record.sqlite` (authoritative, append-only) and `index/fts.sqlite` (disposable projection).
  - `inbox/` → `/inbox`: drop files here. Recorded files move to `processed/<date>/`; failures to `failed/` with a
    `<name>.error.json` beside each.
  - `corpus/` → `/sources/corpus`, read-only: the first source root. More roots are added in `OBIWAN_SOURCE_ROOTS`
    as `name=/container/path;...` plus a matching `:ro` mount; no code change.

One-time host setup, on the HPZ440:

```sh
sudo mkdir -p /srv/obiwan/data /srv/obiwan/inbox /srv/obiwan/corpus
sudo chown -R 1000:1000 /srv/obiwan   # or the uid the container runs as; the corpus only needs to be readable
```

Then set the three `OBIWAN_*_TOKEN` values in `.env` (`scripts/start.ps1` refuses placeholders and identical values),
seed the corpus, start, scan:

```powershell
pwsh -NoProfile -File scripts/obiwan-seed-corpus.ps1 -SourceDir D:\Users\Conrad\Documents\programming\jarvis-obiwan-research\00-obiwan-design
pwsh -NoProfile -File scripts/start.ps1
pwsh -NoProfile -File scripts/obiwan-scan.ps1
pwsh -NoProfile -File scripts/obiwan-status.ps1
```

## Using it

- **From chat.** Ask Jarvis anything about the documents; it calls `search_knowledge`, which returns candidate passages
  with `origin`, location (`corpus:notes/plan.md`), version, and chunk, and a coverage line first. Jarvis judges;
  Obi-Wan never ranks by meaning. Tell Jarvis a fact and it calls `relay_fact`; the fact is stored as
  `human`/`relayed` with the conversation reference and Jarvis tells you the subject id.
- **Confirm a fact** (Commander only): `pwsh -NoProfile -File scripts/obiwan-confirm.ps1 -SubjectId <id>`. A new
  version at the `direct` rung is inserted; the relayed version stays visible under `/document/{id}`.
- **Forget**: `pwsh -NoProfile -File scripts/obiwan-confirm.ps1 -SubjectId <id> -Forget -Reason 'why'`. Inserts a
  tombstone, retires the subject from search, keeps the record.
- **Scan** after adding or changing files: `scripts/obiwan-scan.ps1`. Idempotent: unchanged files create nothing,
  changed files become a new version of the same `file_id`, moved files keep their `file_id`.
- **Reindex**: `scripts/obiwan-reindex.ps1` rebuilds the search projection from stored chunks without reading a
  source file.

HTTP, with `Authorization: Bearer <token>`:

```text
GET  /search?q=&k=      reader     GET /document/{doc_id}   reader     GET /status   reader   GET /journal?limit=  reader
POST /submit            writer     POST /relay              writer     POST /scan    writer   POST /reindex        writer
POST /confirm           commander  {"subject_id": ..., "action": "promote" | "forget", "reason": ...}
GET  /health            none
```

## Guarantees enforced in code

- Record tables accept INSERT only: `BEFORE UPDATE`/`BEFORE DELETE` triggers abort, and `obiwan.record.Record` is the
  only writer (S3). Corrections are new versions; forgetting is a tombstone (S4).
- Origin and attestation are per-route constants derived from the authenticated credential (S1, S2). The confirm route
  refuses the writer credential, so Jarvis cannot confirm what it relayed, even on your instruction (S7, D4).
- Powers are rows in the `powers` table, read on every request (S12).
- Every retrieval response carries coverage: documents and chunks indexed, work pending and failed, roots reachable,
  and a single `complete` flag (S10). The `search_knowledge` tool prints it first and warns when it is false.
- Source roots are mounted `:ro`; the inbox is the only writable location besides `/data` (S8, H7).
- Failed or blocked work is a row with attempts, last error and next attempt; claims carry a lease and a crash is
  reclaimed by the next scan (S11). An unreachable root is reported as a gap and nothing is marked deleted.
- Both sides journal: Obi-Wan's `events` table (`/journal`) records every acceptance and refusal with the credential
  role; Jarvis journals `obiwan_search` and `obiwan_submit` beside its `tool_call` events (S9).
- Obi-Wan has no model client and no outbound dependency of any kind (S5, S6).

## Known limits

- A file moved **and** edited between two scans is recorded as a new file; the old `file_id` keeps pointing at a path
  that no longer resolves (mvp.md section 12). Moves are resolved within one root; a copy in another root is a new
  file with `duplicate_of` noted.
- One sighting row is written per file per scan. Fine for the bounded corpus; NAS-scale compaction is deferred.
- The LAN is trusted: bearer tokens over plain HTTP between containers, no TLS. Inherited posture, hardening later.
- Only the latest version of a subject is searchable. Older versions are in the record and visible via `/document`.
- No embeddings, no vector search, no model call. Full-text ranking plus Jarvis's judgment (decision 6).

## Tests

```powershell
uv --directory obiwan run pytest     # the Historian, no network
uv --directory jarvis run pytest     # the Admiral, including the Obi-Wan client and tools
pwsh -NoProfile -File tests/assert-project-shape.ps1
pwsh -NoProfile -File tests/assert-script-contracts.ps1
```

`obiwan/tests/test_e2e_demo.py` walks the ten demonstrations of mvp.md section 17 against a temporary corpus.

## Live demonstration

(Filled in by the plan's Task 12.)
