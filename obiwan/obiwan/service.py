"""The Historian's operations. Origin and attestation are fixed per method, from the channel (S1, S2); nothing here
reads them from a caller. Every response that returns knowledge also returns coverage (S10)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from obiwan.auth import Gate
from obiwan.chunking import chunk_text
from obiwan.core.config import RESERVED_ROOT, Settings
from obiwan.core.ids import new_id, sha256_text, utcnow
from obiwan.inbox import Inbox, process_inbox
from obiwan.projection import FtsProjection
from obiwan.record import Chunk, Document, Record
from obiwan.scanner import scan_roots
from obiwan.work import WorkQueue
from obiwan.worker import drain


class Service:
    def __init__(self, settings: Settings, *, record: Record, work: WorkQueue, projection: FtsProjection, inbox: Inbox, gate: Gate,
                 now: Callable[[], datetime] = utcnow) -> None:
        self.settings, self.record, self.work, self.projection, self.inbox, self.gate = settings, record, work, projection, inbox, gate
        self._now = now

    @property
    def roots(self) -> dict[str, Path]:
        return {**self.settings.roots, RESERVED_ROOT: self.settings.inbox_dir}

    # ----- writes -----

    def _store_text(self, *, subject_id: str, origin: str, attestation: str | None, content: str, title: str | None, role: str,
                    now: datetime, conversation_ref: str | None = None, promotion_of: str | None = None) -> tuple[Document, list[Chunk]]:
        if not content.strip():
            raise ValueError("content is empty")
        if len(content) > self.settings.max_submit_chars:
            raise ValueError(f"content is {len(content)} chars, above the {self.settings.max_submit_chars} limit")
        doc = self.record.add_document(subject_id=subject_id, origin=origin, attestation=attestation, content_hash=sha256_text(content),
                                       media_type="text/plain", size=len(content.encode("utf-8")), title=title, submitted_by=role,
                                       conversation_ref=conversation_ref, promotion_of=promotion_of, created_at=now)
        self.record.add_text(doc.doc_id, content)
        chunks = self.record.add_chunks(doc.doc_id, chunk_text(content, chunk_chars=self.settings.chunk_chars))
        return doc, chunks

    def submit(self, *, content: str, title: str | None, role: str) -> dict:
        now = self._now()
        with self.record.transaction():
            doc, chunks = self._store_text(subject_id=new_id(), origin="machine", attestation=None, content=content, title=title, role=role, now=now)
            self.record.add_event("accepted", role=role, payload={"route": "submit", "doc_id": doc.doc_id, "subject_id": doc.subject_id})
        self.projection.index_document(doc, chunks, now=now)
        return self._written(doc)

    def relay(self, *, content: str, conversation_ref: str, title: str | None, role: str) -> dict:
        if not (conversation_ref or "").strip():
            raise ValueError("conversation_ref is required: a relayed record carries where the Commander said it")
        now = self._now()
        with self.record.transaction():
            doc, chunks = self._store_text(subject_id=new_id(), origin="human", attestation="relayed", content=content, title=title, role=role,
                                           now=now, conversation_ref=conversation_ref)
            self.record.add_event("accepted", role=role, payload={"route": "relay", "doc_id": doc.doc_id, "subject_id": doc.subject_id,
                                                                  "conversation_ref": conversation_ref})
        self.projection.index_document(doc, chunks, now=now)
        return self._written(doc)

    def _live_latest(self, subject_id: str) -> Document:
        latest = self.record.latest_document(subject_id)
        if latest is None:
            raise KeyError(subject_id)
        if self.record.tombstone_for(subject_id) is not None:
            raise ValueError(f"subject {subject_id} has been forgotten")
        return latest

    def confirm(self, *, subject_id: str, role: str) -> dict:
        """P2: promotion inserts a new version at the direct rung; the relayed version stays as it was."""
        latest = self._live_latest(subject_id)
        if latest.origin != "human" or latest.attestation != "relayed":
            raise ValueError(f"only a human/relayed record can be promoted; this one is {latest.origin}/{latest.attestation}")
        content = self.record.text(latest.doc_id)
        if content is None:
            raise ValueError("the relayed record has no stored text to promote")
        now = self._now()
        with self.record.transaction():
            doc, chunks = self._store_text(subject_id=subject_id, origin="human", attestation="direct", content=content, title=latest.title,
                                           role=role, now=now, conversation_ref=latest.conversation_ref, promotion_of=latest.doc_id)
            self.record.add_event("promotion", role=role, payload={"subject_id": subject_id, "from_doc_id": latest.doc_id, "to_doc_id": doc.doc_id,
                                                                   "from": "relayed", "to": "direct"})
        self.projection.index_document(doc, chunks, now=now)
        return {**self._written(doc), "promoted_from": latest.doc_id}

    def forget(self, *, subject_id: str, reason: str, role: str) -> dict:
        """P4: forgetting inserts a tombstone and retires the projection. The record keeps what was forgotten and why."""
        latest = self._live_latest(subject_id)
        now = self._now()
        with self.record.transaction():
            tomb = self.record.add_tombstone(subject_id=subject_id, reason=reason, ordered_by=role, created_at=now)
            self.record.add_event("tombstone", role=role, payload={"subject_id": subject_id, "doc_id": latest.doc_id, "reason": reason,
                                                                   "origin": latest.origin, "attestation": latest.attestation})
        self.projection.retire_subject(subject_id, reason="forgotten", now=now)
        return {"subject_id": subject_id, "tombstone": tomb.model_dump(mode="json")}

    def scan(self, *, role: str) -> dict:
        scan_id, started = new_id(), self._now()
        roots = scan_roots(self.settings.roots, record=self.record, work=self.work, scan_id=scan_id, now=started,
                           max_file_bytes=self.settings.max_file_bytes)
        inbox = process_inbox(self.inbox, record=self.record, projection=self.projection, settings=self.settings, scan_id=scan_id, now=started)
        work = drain(record=self.record, work=self.work, projection=self.projection, roots=self.roots, settings=self.settings, now=started)
        finished = self._now()
        report = {"scan_id": scan_id, "started_at": started.isoformat(), "finished_at": finished.isoformat(),
                  "roots": [r.model_dump() for r in roots], "inbox": inbox.model_dump(), "work": work.model_dump()}
        self.record.add_scan(scan_id=scan_id, started_at=started, finished_at=finished, report=report)
        self.record.add_event("scan", role=role, payload={"scan_id": scan_id, "roots": [(r.name, r.reachable, r.seen) for r in roots],
                                                          "inbox": (inbox.recorded, inbox.failed), "work": work.model_dump()})
        return report

    def reindex(self, *, role: str) -> dict:
        n = self.projection.rebuild(now=self._now())
        self.record.add_event("reindex", role=role, payload={"chunks_indexed": n})
        return {"chunks_indexed": n, "projection": self.projection.state_counts()}

    # ----- reads -----

    def _location(self, doc: Document) -> tuple[str, str | None, str | None]:
        if doc.origin == "source":
            s = self.record.latest_sighting(doc.subject_id)
            if s is not None:
                return f"{s.root}:{s.path}", s.root, s.path
        return f"{doc.origin}:{doc.subject_id}", None, None

    def search(self, query: str, k: int) -> dict:
        k = max(1, min(int(k), self.settings.search_k_max))
        results = []
        for hit in self.projection.search(query, k * 2):
            chunk = self.record.chunk(hit.chunk_id)
            doc = self.record.document(chunk.doc_id) if chunk else None
            if doc is None or self.record.tombstone_for(doc.subject_id) is not None:
                continue  # the projection outran the record; coverage still tells the truth
            location, root, path = self._location(doc)
            results.append({"chunk_id": chunk.chunk_id, "doc_id": doc.doc_id, "subject_id": doc.subject_id, "version_no": doc.version_no,
                            "origin": doc.origin, "attestation": doc.attestation, "title": doc.title, "location": location, "root": root,
                            "path": path, "seq": chunk.seq, "start_char": chunk.start_char, "end_char": chunk.end_char,
                            "score": hit.score, "snippet": hit.snippet, "content": chunk.text})
            if len(results) == k:
                break
        return {"query": query, "results": results, "coverage": self.coverage()}

    def coverage(self) -> dict:
        counts = self.record.coverage_counts()
        wq = self.work.counts()
        last = self.record.last_scan()
        reported = {r["name"]: r for r in (last or {}).get("report", {}).get("roots", [])}
        roots = []
        for name, path in self.settings.roots.items():
            r = reported.get(name)
            roots.append({"name": name, "path": str(path), "reachable": bool(r and r["reachable"]),
                          "last_scan_at": last["finished_at"] if r else None})
        complete = (counts["documents"] == counts["documents_indexed"] and wq["pending"] == 0 and wq["failed"] == 0
                    and all(r["reachable"] for r in roots))
        return {**counts, "work_pending": wq["pending"], "work_failed": wq["failed"], "roots": roots,
                "last_scan_at": last["finished_at"] if last else None, "complete": complete}

    def document(self, doc_id: str) -> dict | None:
        doc = self.record.document(doc_id)
        if doc is None:
            return None
        states = dict(self.record.conn.execute("SELECT chunk_id, state FROM projection WHERE kind = 'fts'").fetchall())
        location, _, _ = self._location(doc)
        tomb = self.record.tombstone_for(doc.subject_id)
        return {"document": doc.model_dump(mode="json"), "location": location,
                "versions": [d.model_dump(mode="json") for d in self.record.documents_for(doc.subject_id)],
                "sightings": [s.model_dump(mode="json") for s in self.record.sightings_for(doc.subject_id)] if doc.origin == "source" else [],
                "chunks": [{**c.model_dump(), "projection_state": states.get(c.chunk_id, "pending")} for c in self.record.chunks_for(doc.doc_id)],
                "content": self.record.text(doc.doc_id), "tombstone": tomb.model_dump(mode="json") if tomb else None}

    def status(self) -> dict:
        last = self.record.last_scan()
        return {"coverage": self.coverage(), "work": self.work.counts(), "work_failed": [w.model_dump(mode="json") for w in self.work.failed(limit=20)],
                "inbox": {"pending": len(self.inbox.pending()), "failed": sum(1 for p in self.inbox.failed_dir.iterdir() if not p.name.endswith(".error.json"))},
                "projection": self.projection.state_counts(), "last_scan": last["report"] if last else None}

    def journal(self, limit: int = 50) -> list[dict]:
        return [e.model_dump(mode="json") for e in self.record.events(limit=limit)]

    @staticmethod
    def _written(doc: Document) -> dict:
        return {"subject_id": doc.subject_id, "doc_id": doc.doc_id, "version_no": doc.version_no, "origin": doc.origin, "attestation": doc.attestation}
