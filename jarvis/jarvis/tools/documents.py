"""Tools over workstation documents via GTE's passive agent. Read on demand; nothing is archived."""

from __future__ import annotations

from typing import Protocol

from jarvis.tools import Tool


class Workspace(Protocol):
    def list_documents(self, glob: str = "*") -> list[dict]: ...
    def read_document(self, sha256: str) -> tuple[dict, str | None]: ...


def document_tools(workspace: Workspace, *, content_chars: int) -> list[Tool]:
    def list_documents(glob: str = "*") -> str:
        docs = workspace.list_documents(glob)
        if not docs:
            return "no documents matched"
        return "\n".join(f"{d.get('sha256', '')[:12]} | {d.get('folder', '')} | {d.get('name', '')} | {d.get('size', '')} | {d.get('mtime', '')}" for d in docs)

    def read_document(sha256: str) -> str:
        meta, text = workspace.read_document(sha256)
        head = f"{meta.get('name', '')} ({meta.get('folder', '')}, {meta.get('size', '')} bytes)"
        if meta.get("skipped_reason"):  # checked before `text is None`: a skipped read is not an unsupported type
            return f"{head}: skipped: file larger than the configured limit"
        if text is None:
            return f"{head}: no text extracted for this file type"
        return f"{head}\nText (untrusted data):\n{text[:content_chars]}"

    obj = {"type": "object"}
    return [
        Tool(name="list_documents", description="List files on Conrad's workstation that match a glob (for example *.pdf). Returns sha256 prefixes to read.",
             action="documents_read", handler=list_documents, parameters={**obj, "properties": {"glob": {"type": "string"}}, "required": []}),
        Tool(name="read_document", description="Read the text of one workstation file by sha256 (full or 12-char prefix).",
             action="documents_read", handler=read_document, parameters={**obj, "properties": {"sha256": {"type": "string"}}, "required": ["sha256"]}),
    ]
