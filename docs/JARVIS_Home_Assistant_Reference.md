# Jarvis: Home AI Assistant Reference

Status: Planning reference  
Updated: 2026-09-23

## Purpose

Jarvis is a personal assistant that runs primarily on the local home network. Conrad interacts with Jarvis, which handles routine work with a local language model and consults stronger cloud models when useful. Jarvis retains records and research locally for later retrieval. The first and most common job is triage of new email.

This document records agreed behavior and an initial architecture. It is not a claim that any components have been installed or that a particular GPU or model has been selected.

## Available infrastructure

- HP Z440 Docker server, currently with 32 GiB RAM, planned GPU upgrade for local LLM inference.
- Synology NAS with terabytes of available storage. The DS220+ with Btrfs is a candidate primary archive; the older DS216j may serve as a separate backup destination, subject to capacity and configuration checks.
- Home network linking the server and NAS. External LLMs are reached through an explicitly controlled gateway.

## Core design

1. Jarvis is the user-facing assistant and orchestrator. A local model handles triage, retrieval, and routine reasoning when capable.
2. Application code, rather than a model's instructions alone, enforces access, disclosures, approvals, and tool permissions.
3. Cloud models may receive redacted personal information when that improves the task. Jarvis sends the minimum useful context and records the exact disclosure. If identifiable details are necessary and cannot be safely redacted, Jarvis requests approval before disclosing them.
4. Original source material and an event journal are retained on the NAS. A searchable index is derived from those originals and may be rebuilt.
5. Permissions grow in explicit, narrow stages. One approved action does not automatically create standing authorization.

### Logical components

| Component | Role |
| --- | --- |
| Jarvis application on Z440 | Conversation, task state, permission checks, tool execution, and journal entries. |
| Local inference service | Local LLM for triage, summarization, drafting suggestions, and tool planning. |
| Mail connector | Reads incoming mail and, only when authorized, creates drafts or sends messages. |
| Retrieval service | Searches archived mail, documents, research, and prior decisions with source links. |
| Cloud gateway | Redaction, provider selection, disclosure policy, cost limits, and request logging. |
| NAS archive | Originals, attachments, research captures, event journal, and protected backups. |
| User interface | Inbox briefing, evidence, proposed actions, approvals, and rule management. |

Potential starting tools include Ollama for local inference, Open WebUI for a prototype interface, and LiteLLM for cloud routing. These were candidates when this document was written; `roadmap.md` records the committed choices, including `llama.cpp` rather than Ollama for local inference. Jarvis-specific permission and journal logic still needs an application layer.

## First milestone: read-only daily inbox briefing

Jarvis processes new messages and presents a concise briefing. For each message it should:

1. Capture the original message and attachments, retaining source identifiers, receipt time, and content hashes.
2. Determine the sender, conversation, topic, requested action, deadlines, and likely priority.
3. Search relevant earlier mail and documents, showing evidence separately from its inferences.
4. Place the message in a useful group: **Needs your decision**, **Reply suggested**, **For your information**, or **Likely noise**. Explain why and propose a next step.
5. Suggest reply text where appropriate, but take no outbound action in the first milestone.

The briefing should highlight changes in attached documents and related prior decisions when relevant. It should make it easy to correct a classification so Jarvis can improve its rules without treating every correction as permission to act.

### First milestone permission boundary

Jarvis may read and archive incoming messages, classify them, search local records, and suggest replies. It may not send email, delete messages, unsubscribe, or move messages out of the inbox under this milestone. Email bodies, attachments, and web pages are untrusted input; instructions contained in them do not grant permissions.

## Permission growth

| Stage | Authorized behavior |
| --- | --- |
| 1. Observe | Read, archive, classify, and brief. |
| 2. Propose | Prepare drafts and proposed actions for review. |
| 3. Individual approval | Execute a specific send or other action after Conrad approves that instance. |
| 4. Standing rule | Execute only within a separately approved rule with an explicit trigger, recipients, permitted content, and limits. |

Rules are negotiated one at a time. Each rule has a version, approval record, effective status, and revocation path. Every action records the rule or individual approval authorizing it. A global pause control stops outbound actions immediately while allowing reading and drafting.

Example of a possible future rule: acknowledge receipt of a recurring monthly statement from one verified sender to that same sender using approved wording. This example is not an approved rule.

## Cloud model disclosure

- A standing authorization permits Jarvis to send useful **redacted** excerpts to external LLMs when a task benefits from their capabilities.
- Before a request leaves the home network, the gateway determines which excerpt is needed, removes unnecessary personal identifiers, and applies disclosure and spending limits.
- Record the reason for escalation, provider and model, exact outbound payload, time, response, and resulting action or recommendation.
- If necessary details cannot be redacted without defeating the task, ask for a specific approval before sending them.
- Cloud providers receive no direct access to the mailbox or NAS through this design.

## Archive, retrieval, and integrity

Keep original mail, attachments, retrieved documents, and research captures with provenance (source, URL when applicable, retrieval time, and content hash). Record requests, tool calls, model versions, classifications, corrections, approvals, rule changes, disclosures, and outcomes in an append-oriented event journal. Keep the search index separate from this source-of-truth archive.

An append-only application log alone does not guarantee immutability against an administrator or a compromised account. Before claiming immutable storage, verify DSM version and model support for Synology WriteOnce or immutable snapshots, configure retention and separate credentials, and test restoration. Maintain a separate backup, potentially on the DS216j. Define retention rules for mail and third-party research captures.

## Implementation sequence

1. Confirm GPU, local model, mailbox access method, NAS storage layout, and backup capabilities.
2. Build capture, local classification, source-linked search, journal, and read-only briefing.
3. Review real briefings and corrections until classification quality is dependable.
4. Add draft creation and per-message approval for sending.
5. Add the cloud gateway and disclosure audit, then approve narrow recurring email rules individually.

## Decisions still open

Several of these are now resolved in `roadmap.md` (mailbox: Gmail; GPU: RTX 3060 12GB, pending install; inference: `llama.cpp`; application stack: Python; archive: HPZ440 disk first, then NAS). The list below is kept as originally written.

- Which mailbox or mailboxes Jarvis will triage, and whether the briefing runs on a schedule, on demand, or both.
- GPU and local model choice; acceptable latency and power budget.
- Exact archive retention, encryption, recovery, and NAS immutability options.
- How redaction is reviewed for unusually sensitive topics and how cloud usage budgets are set.
- Interface for approvals, rule changes, and the outbound pause control.

