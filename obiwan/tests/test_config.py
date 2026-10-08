import pytest

from obiwan.core.config import Settings


def test_defaults_are_the_container_paths():
    s = Settings(_env_file=None)
    assert str(s.data_dir).replace("\\", "/") == "/data"
    assert str(s.inbox_dir).replace("\\", "/") == "/inbox"
    assert s.roots == {}
    assert s.reader_token == "" and s.writer_token == "" and s.commander_token == ""
    assert s.chunk_chars == 1500 and s.max_attempts == 5 and s.lease_seconds == 300


def test_roots_parse_name_equals_path_separated_by_semicolons():
    s = Settings(_env_file=None, source_roots="corpus=/sources/corpus; notes=/sources/notes ;")
    assert {k: str(v).replace("\\", "/") for k, v in s.roots.items()} == {"corpus": "/sources/corpus", "notes": "/sources/notes"}


@pytest.mark.parametrize("bad", ["corpus", "=/x", "corpus=", "inbox=/x"])
def test_malformed_or_reserved_root_entries_are_refused(bad):
    with pytest.raises(ValueError):
        Settings(_env_file=None, source_roots=bad).roots


def test_env_prefix_is_obiwan(monkeypatch):
    monkeypatch.setenv("OBIWAN_CHUNK_CHARS", "700")
    assert Settings(_env_file=None).chunk_chars == 700
