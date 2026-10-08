import pytest

from obiwan.auth import FORBIDDEN_PAYLOAD_KEYS, Gate, Refused, bearer, role_for_token
from obiwan.core.config import Settings
from obiwan.record import Record


@pytest.fixture
def gate(data_dir, settings):
    record = Record(data_dir / "record.sqlite")
    yield Gate(record, settings)
    record.close()


def test_bearer_parsing():
    assert bearer("Bearer abc") == "abc" and bearer("bearer abc ") == "abc"
    assert bearer(None) == "" and bearer("Basic abc") == "" and bearer("abc") == ""


def test_role_for_token_is_exact_and_never_matches_an_unset_token(settings):
    assert role_for_token("r-token", settings) == "reader"
    assert role_for_token("w-token", settings) == "writer"
    assert role_for_token("c-token", settings) == "commander"
    assert role_for_token("", settings) is None and role_for_token("R-TOKEN", settings) is None
    blank = Settings(_env_file=None, reader_token="", writer_token="", commander_token="")
    assert role_for_token("", blank) is None  # an unconfigured credential authenticates nobody


def test_unknown_credential_is_401_and_journaled(gate):
    with pytest.raises(Refused) as e:
        gate.authorize("Bearer nope", "search")
    assert e.value.status == 401
    ev = gate.record.events(limit=1)[0]
    assert ev.kind == "refused" and ev.role is None and ev.payload == {"power": "search", "reason": "unknown credential"}


def test_powers_come_from_the_table(gate):
    assert gate.authorize("Bearer r-token", "search") == "reader"
    assert gate.authorize("Bearer w-token", "submit") == "writer"
    assert gate.authorize("Bearer c-token", "confirm") == "commander"
    assert gate.authorize("Bearer c-token", "search") == "commander"
    for header, power in (("Bearer r-token", "submit"), ("Bearer w-token", "confirm"), ("Bearer w-token", "forget")):
        with pytest.raises(Refused) as e:
            gate.authorize(header, power)
        assert e.value.status == 403
    refused = gate.record.events(limit=10, kind="refused")
    assert [(e.role, e.payload["power"]) for e in refused] == [("writer", "forget"), ("writer", "confirm"), ("reader", "submit")]
    assert gate.record.events(limit=10, kind="accepted") == []  # authorize does not journal acceptance; routes do


def test_amending_the_powers_table_changes_the_answer_without_a_deploy(gate):
    gate.record.conn.execute("INSERT INTO powers(role, power, granted_at) VALUES ('reader', 'submit', 'now')")
    assert gate.authorize("Bearer r-token", "submit") == "reader"


def test_claimed_provenance_in_a_payload_is_refused_with_400(gate):
    assert FORBIDDEN_PAYLOAD_KEYS == frozenset({"origin", "attestation"})
    gate.refuse_claimed_provenance({"content": "x"}, role="writer", route="submit")
    with pytest.raises(Refused) as e:
        gate.refuse_claimed_provenance({"content": "x", "origin": "human", "attestation": "direct"}, role="writer", route="submit")
    assert e.value.status == 400 and "attestation, origin" in e.value.reason
    ev = gate.record.events(limit=1)[0]
    assert ev.kind == "refused" and ev.role == "writer" and ev.payload["keys"] == ["attestation", "origin"] and ev.payload["route"] == "submit"


def test_a_token_shared_by_two_roles_authenticates_nobody():
    shared = Settings(_env_file=None, reader_token="r-token", writer_token="same", commander_token="same")
    assert role_for_token("same", shared) is None
    assert role_for_token("r-token", shared) == "reader"
