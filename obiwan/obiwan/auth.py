"""Who is calling, and what the powers table lets them do (S1, S7, S9, S12). Refusals are first-class events."""

from __future__ import annotations

import hmac

from obiwan.core.config import Settings
from obiwan.record import Record

ROLES = ("commander", "writer", "reader")
FORBIDDEN_PAYLOAD_KEYS = frozenset({"origin", "attestation"})


class Refused(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def bearer(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.strip().partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def role_for_token(token: str, settings: Settings) -> str | None:
    configured = {"commander": settings.commander_token, "writer": settings.writer_token, "reader": settings.reader_token}
    for role in ROLES:
        expected = configured[role]
        if token and expected and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
            return role
    return None


class Gate:
    def __init__(self, record: Record, settings: Settings) -> None:
        self.record = record
        self._settings = settings

    def authorize(self, authorization: str | None, power: str) -> str:
        role = role_for_token(bearer(authorization), self._settings)
        if role is None:
            self.record.add_event("refused", role=None, payload={"power": power, "reason": "unknown credential"})
            raise Refused(401, "unknown credential")
        if power not in self.record.powers_for(role):
            self.record.add_event("refused", role=role, payload={"power": power, "reason": "power not held"})
            raise Refused(403, f"role {role!r} does not hold the power {power!r}")
        return role

    def refuse_claimed_provenance(self, body: dict, *, role: str, route: str) -> None:
        """S1/E5: a payload that names its own origin or attestation is refused, never corrected."""
        keys = sorted(k for k in body if k in FORBIDDEN_PAYLOAD_KEYS)
        if keys:
            self.record.add_event("refused", role=role, payload={"route": route, "reason": "provenance claimed in payload", "keys": keys})
            raise Refused(400, f"{', '.join(keys)}: provenance is derived from the credential and the channel, never from the payload")
