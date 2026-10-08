> Snapshot taken 2026-10-07 from `jarvis-obiwan-research/00-obiwan-design/`, the design workspace. This copy is the
> version this repository implements.

# Command Structure: Duties, Powers, and Safeguards

> **The purpose of this document is to say who may do what, and to make the limits enforceable rather than aspirational.**

Three actors share one body of knowledge. This document names them, states each one's duties, enumerates the powers each holds, enumerates the powers each is denied, and lists the safeguards that enforce the denials.

A power that exists only as a sentence in a specification is not a limit. Every safeguard below names where it is enforced and whether it is enforced today.

Status: approved design. Governs `mvp.md` and all later phases.
Companion: `mvp.md` defines what v0.1 builds. This document defines who may operate it.

---

## 1. The chart

```text
                    COMMANDER-IN-CHIEF
                          (Conrad)
        sole source of decisions and human-origin fact
                             │
            ┌────────────────┴────────────────┐
            │                                 │
       approves, orders,                 confirms,
       amends powers                     promotes attestation
            │                                 │
            ▼                                 ▼
        ADMIRAL                           HISTORIAN
        (Jarvis)                          (Obi-Wan)
   operations and action           the record and its accuracy
            │                                 ▲
            │   submit  (source | machine)     │
            ├─────────────────────────────────▶│
            │   search  (read credential)      │
            ├─────────────────────────────────▶│
            │                                  │
      ┌─────┴─────┐                      source roots
      │           │                      (read-only)
  sub-agents   outside world
  (scoped,     (Gmail, and later
   reserved)    others)
```

The Historian is not trusted more than the Admiral. It is trusted differently. It holds more authority over the record and none at all over the world.

---

## 2. Commander-in-Chief

**Who.** Conrad.

**Duty.** Set the standing rules. Decide. Correct. Order forgetting. Grant and revoke the powers of every other actor.

**Powers.** These are exclusive and non-delegable.

| | Power |
|---|---|
| P1 | Create a human-origin record at the `direct` attestation rung |
| P2 | Promote a `relayed` record to `direct` |
| P3 | Approve an outbound action by the Admiral |
| P4 | Order a record forgotten |
| P5 | Amend any actor's powers |

No actor may exercise P1 through P5. No actor acquires one by asking, by relaying a request, or by acting in the Commander's name. An attempt is refused and journaled as a refusal, not silently downgraded.

---

## 3. Admiral

**Who.** Jarvis. The service on port 8090, backed by the single LLM on this network.

**Duty.** Operate. Observe the world, classify what it finds, draft, act within the permission stage granted to it, and command sub-agents.

**Powers.**

| | Power |
|---|---|
| A1 | Hold outside-world credentials. Today: Gmail, read-only scope |
| A2 | Capture from systems where it holds a credential |
| A3 | Submit records to the Historian with origin `source` or `machine` |
| A4 | Relay the Commander's words as a `relayed` proposal, carrying the conversation reference |
| A5 | Read the record under a read credential |
| A6 | Act outbound within its permission stage, per instance, under P3 |
| A7 | Command sub-agents and issue them read credentials no broader than its own |

**Denials.**

| | Denial |
|---|---|
| D1 | No UPDATE and no DELETE on any record, under any circumstance |
| D2 | Cannot create a human-origin record |
| D3 | Cannot promote an attestation rung |
| D4 | Cannot reach the Historian's confirm channel |
| D5 | Cannot write to any source root |
| D6 | Cannot grant itself or a sub-agent a power it does not hold |

D2 and D4 together are the point. Jarvis may tell the Historian what you said. It may not make that the same thing as you having said it.

---

## 4. Historian

**Who.** Obi-Wan. A service with no model, no outbound credential, and no published route off this host.

**Duty.** Keep the record and keep it accurate. Know what is held, where each item came from, which version is current, and what is missing.

**Powers.**

| | Power |
|---|---|
| H1 | Read source roots, read-only |
| H2 | Mint file identity and version identity |
| H3 | Assign origin and attestation from the authenticated caller and the channel used |
| H4 | Store, version, and index |
| H5 | Serve retrieval, scoped by the calling credential |
| H6 | Report contradiction, staleness, coverage, and pending work |
| H7 | Move files within its own inbox |

**Denials.**

| | Denial |
|---|---|
| E1 | No outbound capability: no mail, no internet egress, no write to any source root |
| E2 | Does not interpret. No model-scored relevance, no minted claims, no summaries recorded as fact |
| E3 | Cannot create a human-origin record except through the Commander's direct channel |
| E4 | Cannot delete a record on its own initiative |
| E5 | Cannot accept an origin or attestation value supplied in a payload |

E2 is a real constraint, not a formality. In v0.1 the Historian has no model client at all, so it is structurally incapable of judging meaning. Judgment is the Admiral's work, and whatever the Admiral concludes re-enters the record as `machine`.

---

## 5. Sub-agents

Reserved. Not built in v0.1.

When they arrive, a sub-agent receives a read credential scoped to a subset of the record, issued by the Admiral under A7, never exceeding the Admiral's own scope, revocable at any time, and journaled on issue and on use. A coding agent reading project knowledge and a photo agent reading image metadata are the intended shape.

The server-side join from credential to agent identity to permitted scope does not exist in any of the four systems the research examined. It is the main thing this structure adds, and `mvp.md` reserves its seam without building it.

---

## 6. Origin classes

Every knowledge-bearing record carries an origin the storage layer understands. There are three.

**`source`** — a deterministic derivation of an authoritative artifact. Extracted text from a document on the NAS. Re-running the extractor on the same bytes yields the same thing.

**`human`** — your assertion or your decision. Carries an attestation rung, below.

**`machine`** — anything produced by a model, an agent, an inference, or an automated extraction that is not a deterministic representation of a source.

A machine writer cannot label its output `human`. Machine knowledge does not become human knowledge by being useful, by being correct, or by being repeated.

---

## 7. The attestation ladder

Attestation applies only to the `human` class. It records how strongly the claim that you said something is backed.

| Rung | Meaning | Built |
|---|---|---|
| `relayed` | The Admiral reports that you said it. Unverified. Carries the conversation reference | v0.1 |
| `direct` | Created through the Historian's confirm channel under your own credential | v0.1 |
| `attested` | One-time password from a device you control | v2.0 |

Two rules govern it.

A rung is set by the channel the record arrived through, never claimed by the caller. Only P2 changes a rung, and promotion inserts a new version plus a promotion event; the record retains the rung it was created under. Nothing recorded at a weaker rung is retroactively relabelled when a stronger rung becomes available.

Later policy may require `attested` for a specific class of fact, such as a credential or a billing decision, without re-litigating anything already stored.

---

## 8. Safeguards

Each safeguard states the rule, why it exists, where it is enforced, and whether it is enforced in v0.1.

### S1 Origin comes from the credential, not the payload

The Historian derives `origin` from the authenticated caller and the channel. A payload field naming an origin is refused with an error rather than silently corrected.

*Why.* All four systems the research examined accepted client-asserted attribution, which reduces the label to a courtesy. Attribution is not authorization.
*Enforced.* Historian write path, ahead of validation. *v0.1.*

### S2 Attestation comes from the channel

The submit path yields `relayed`. The confirm channel yields `direct`. No caller names its own rung.

*Why.* A machine that can name its own trust grade has no trust grade.
*Enforced.* Historian, as a per-route constant. *v0.1.*

### S3 The record is append-only

Record tables accept INSERT only. No credential holds UPDATE or DELETE. A correction inserts a new version. Forgetting inserts a tombstone.

*Why.* An actor that can rewrite history can launder a mistake into a fact.
*Enforced.* Schema plus a single write module today; a database role without UPDATE or DELETE when the store supports roles. *v0.1.*

### S4 Forgetting is commander-only and leaves a mark

P4 alone. The tombstone records what was forgotten, when, under which rung, and why. Retrieval excludes the target and can surface the tombstone.

*Why.* A silent gap is indistinguishable from data loss.
*Enforced.* Historian confirm channel. *v0.1.*

### S5 The Historian holds no outbound credential

No mail, no internet egress, no write mount on any source root, no published route off the host.

*Why.* The keeper of the record should not be able to act on the world using it.
*Enforced.* Absence of credentials, read-only mounts, and no published external port. *v0.1.*

### S6 The Historian does not interpret

Retrieval returns candidates with their provenance and never ranks by model judgment.

*Why.* A historian that judged meaning would be minting inference into the record it guards.
*Enforced.* The Historian has no model client. *v0.1.*

### S7 The reviewer is not the proposer

The confirm channel refuses the Admiral's credential, including when the Admiral is relaying your instruction to confirm.

*Why.* In every system examined, the review gate was callable by the same key whose work was under review. This is open question OQ-02.
*Enforced.* Historian, credential check on the confirm route. *v0.1, strengthened by OTP in v2.0.*

### S8 Source roots are read-only at the boundary

Every source root is bind-mounted read-only, so a code defect cannot write one even if it tries.

*Why.* One reference implementation's file watcher moves the files it indexes. A rule in the mount outranks a rule in the code.
*Enforced.* Container mount options. *v0.1.*

### S9 Both sides journal, with the credential

The Admiral journals what it submitted and what it searched. The Historian journals what it accepted, from which credential, and what it refused.

*Why.* Audit tables with no writer were a recurring finding in the research, and so were audit tables with no reader. Refusals are first-class events.
*Enforced.* Both services, with a read path for each. *v0.1.*

### S10 Coverage is reported

Every retrieval response states how much of the corpus was searchable: documents indexed, chunks indexed, work pending, work failed.

*Why.* A partial index that looks complete produces confident wrong answers.
*Enforced.* Historian search response envelope. *v0.1.*

### S11 Deferred work is durable

Work postponed because a source or a dependency was unavailable becomes a row carrying attempt count, last error, and next attempt time. Nothing is dropped and nothing is retried in a tight loop. A claim carries a lease and a reclaim path.

*Why.* The Commander's standing requirement that work postpone rather than fail. Also the stale-claim gap found in one reference worker, which could strand a job forever.
*Enforced.* Historian work table and claim discipline. *v0.1.*

### S12 Powers are data

The powers table lives in the record. Amending a power is an insert under P5, journaled and versioned. Code reads the table rather than hard-coding grants.

*Why.* A power that exists only as a conditional in source cannot be audited or revoked without a deployment.
*Enforced.* Historian, read at request time. Table and read path in v0.1; the amendment interface is later.

---

## 9. Amending this structure

A power changes only under P5, and the amendment is itself a record: what changed, from what to what, when, and under which attestation rung. The structure is versioned the way knowledge is.

Until the amendment interface exists, an amendment is a change to this document plus the powers table, applied together.

---

## 10. Deferred safeguards

Named so that their absence is deliberate rather than overlooked.

| Safeguard | Waiting on |
|---|---|
| One-time-password attestation | v2.0, per the Commander's direction |
| Per-sub-agent scope enforcement | First real sub-agent |
| NAS access-control mapping into retrieval scope | NAS source roots |
| Contradiction detection and reporting | Real contradictions in a real corpus |
| Transport security and authentication on the LAN | Before any device outside the Commander's control joins |
| Cross-actor rate limits | Evidence of contention |

---

## 11. Known gaps, stated plainly

**The LAN is treated as trusted.** No TLS, no authentication between services beyond credentials. This is inherited from the Jarvis roadmap's stated posture and is scheduled for a hardening phase, not solved here.

**One host.** A single machine holds the Admiral, the Historian, the model, and the record. There is no isolation between them beyond process and container boundaries.

**The `relayed` rung is only as good as the Admiral's resistance to manipulation.** Jarvis reads untrusted input: mail bodies, fetched pages, documents. A sufficiently well-crafted instruction inside that input could cause Jarvis to relay something you never said. This is precisely why `relayed` is a separate rung from `direct`, and why nothing reaches `direct` without passing through a channel Jarvis cannot use.

**The Commander is a single point of authority with no recovery path.** If the Commander's credential is lost, no actor can promote anything. This is intentional and should be revisited alongside OTP in v2.0.
