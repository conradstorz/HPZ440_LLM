"""Writes tests/fixtures/*.json: Gmail users.messages.get(format=full) payloads and raw bytes."""

from __future__ import annotations

import base64
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


def b64url(s: bytes) -> str:
    return base64.urlsafe_b64encode(s).decode().rstrip("=")


def headers(**kw: str) -> list[dict]:
    return [{"name": k.replace("_", "-"), "value": v} for k, v in kw.items()]


def plain() -> dict:
    body = b"Hi Conrad,\n\nCan you approve the invoice by Friday?\n\nThanks,\nAlice"
    return {
        "id": "18f1a2b3c4d5e6f7",
        "threadId": "18f1a2b3c4d5e6f7",
        "internalDate": "1759190400000",
        "snippet": "Can you approve the invoice by Friday?",
        "payload": {
            "mimeType": "text/plain",
            "headers": headers(From="Alice Example <alice@example.com>", To="Conrad <conradstorz@gmail.com>",
                               Subject="Invoice approval needed", Date="Mon, 29 Sep 2025 20:00:00 +0000",
                               Message_ID="<abc123@example.com>"),
            "body": {"size": len(body), "data": b64url(body)},
        },
    }


def html_with_attachment() -> dict:
    html = b"<html><body><p>Your <b>September statement</b> is attached.</p><p>Regards,<br>Billing</p></body></html>"
    return {
        "id": "18f1a2b3c4d5e6f8",
        "threadId": "18f1a2b3c4d5e6f8",
        "internalDate": "1759276800000",
        "snippet": "Your September statement is attached.",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": headers(From="billing@utility.example", To="conradstorz@gmail.com",
                               Subject="September statement", Date="Tue, 30 Sep 2025 20:00:00 +0000",
                               Message_ID="<stmt-0930@utility.example>", In_Reply_To="<stmt-0831@utility.example>"),
            "parts": [
                {"mimeType": "text/html", "body": {"size": len(html), "data": b64url(html)}},
                {"mimeType": "application/pdf", "filename": "statement.pdf",
                 "body": {"size": 11, "attachmentId": "ATT-1"}},
            ],
        },
    }


def main() -> None:
    FIX.mkdir(exist_ok=True)
    (FIX / "gmail_message_plain.json").write_text(json.dumps(plain(), indent=2), encoding="utf-8")
    (FIX / "gmail_message_html_with_attachment.json").write_text(json.dumps(html_with_attachment(), indent=2), encoding="utf-8")
    (FIX / "gmail_attachment_ATT-1.bin").write_bytes(b"%PDF-1.4 x\n")
    (FIX / "gmail_raw_plain.eml").write_bytes(
        b"From: Alice Example <alice@example.com>\r\nTo: conradstorz@gmail.com\r\nSubject: Invoice approval needed\r\n\r\nHi Conrad,\r\n\r\nCan you approve the invoice by Friday?\r\n"
    )
    (FIX / "gmail_raw_html.eml").write_bytes(b"From: billing@utility.example\r\nSubject: September statement\r\n\r\n(html)\r\n")


if __name__ == "__main__":
    main()
