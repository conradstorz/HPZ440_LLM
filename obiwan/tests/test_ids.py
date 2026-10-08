from datetime import UTC

from obiwan.core.ids import new_id, sha256_file, sha256_text, utcnow


def test_new_id_is_32_hex_and_unique():
    a, b = new_id(), new_id()
    assert len(a) == 32 and int(a, 16) >= 0 and a != b


def test_utcnow_is_timezone_aware_utc():
    assert utcnow().tzinfo is UTC


def test_sha256_of_file_matches_sha256_of_its_text(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello\n", encoding="utf-8", newline="\n")
    assert sha256_file(p) == sha256_text("hello\n")
    assert sha256_file(p) == "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
