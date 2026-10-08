"""The record's schema. Record tables are INSERT-only, enforced here by triggers; work and projection are operational."""

from __future__ import annotations

ORIGINS = ("source", "human", "machine")
ATTESTATIONS = ("relayed", "direct")
APPEND_ONLY = ("files", "sightings", "documents", "texts", "chunks", "tombstones", "events", "powers", "scans")
SCHEMA_VERSION = 1

# S12: powers are data. Code asks the table, never a role name.
_READER = {"search", "read_document", "status", "journal_read"}
_WRITER = _READER | {"submit", "relay", "scan", "reindex"}
_COMMANDER = _WRITER | {"confirm", "forget"}
POWERS: dict[str, frozenset[str]] = {"reader": frozenset(_READER), "writer": frozenset(_WRITER), "commander": frozenset(_COMMANDER)}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY, root TEXT NOT NULL, first_seen_at TEXT NOT NULL, duplicate_of TEXT
);
CREATE TABLE IF NOT EXISTS sightings (
  id INTEGER PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(file_id), root TEXT NOT NULL, path TEXT NOT NULL,
  content_hash TEXT NOT NULL, size INTEGER NOT NULL, mtime TEXT NOT NULL, seen_at TEXT NOT NULL, scan_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sightings_by_path ON sightings(root, path, id);
CREATE INDEX IF NOT EXISTS sightings_by_file ON sightings(file_id, id);
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, version_no INTEGER NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('source','human','machine')),
  attestation TEXT CHECK (attestation IN ('relayed','direct')),
  content_hash TEXT NOT NULL, size INTEGER, mtime TEXT, media_type TEXT NOT NULL, title TEXT,
  submitted_by TEXT, conversation_ref TEXT, promotion_of TEXT, scan_id TEXT, created_at TEXT NOT NULL,
  UNIQUE (subject_id, version_no),
  CHECK ((origin = 'human') = (attestation IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS texts (
  doc_id TEXT PRIMARY KEY REFERENCES documents(doc_id), content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(doc_id), seq INTEGER NOT NULL,
  start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, text TEXT NOT NULL, UNIQUE (doc_id, seq)
);
CREATE TABLE IF NOT EXISTS tombstones (
  id INTEGER PRIMARY KEY, subject_id TEXT NOT NULL, reason TEXT NOT NULL, ordered_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, role TEXT, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS powers (
  id INTEGER PRIMARY KEY, role TEXT NOT NULL, power TEXT NOT NULL, granted_at TEXT NOT NULL, UNIQUE (role, power)
);
CREATE TABLE IF NOT EXISTS scans (
  scan_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','leased','done','failed')),
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, next_attempt_at TEXT NOT NULL, lease_until TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (kind, target)
);
CREATE TABLE IF NOT EXISTS projection (
  chunk_id TEXT NOT NULL, kind TEXT NOT NULL, model TEXT, model_revision TEXT, dimensions INTEGER,
  state TEXT NOT NULL CHECK (state IN ('pending','current','stale','failed')), reason TEXT, built_at TEXT,
  PRIMARY KEY (chunk_id, kind)
);
"""


def _triggers() -> str:
    out = []
    for t in APPEND_ONLY:
        for op in ("UPDATE", "DELETE"):
            out.append(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                       f"BEGIN SELECT RAISE(ABORT, 'append-only: {t}'); END;")
    return "\n".join(out)


TRIGGERS = _triggers()
