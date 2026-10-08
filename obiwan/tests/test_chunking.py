import pytest

from obiwan.chunking import ChunkSpec, chunk_text


def test_empty_and_whitespace_text_yield_no_chunks():
    assert chunk_text("") == [] and chunk_text("  \n\n \n") == []


def test_positions_always_point_back_into_the_source_text():
    text = "Para one.\n\nPara two is here.\n\n\n  Para three  \n"
    chunks = chunk_text(text, chunk_chars=1000)
    assert len(chunks) == 1 and chunks[0] == ChunkSpec(0, 0, len("Para one.\n\nPara two is here.\n\n\n  Para three"), text[0:len("Para one.\n\nPara two is here.\n\n\n  Para three")])
    for c in chunk_text(text, chunk_chars=12):
        assert text[c.start_char:c.end_char] == c.text
        assert c.text.strip() == c.text


def test_paragraphs_are_packed_up_to_the_limit_and_split_in_order():
    text = "aaaa\n\nbbbb\n\ncccc\n\ndddd"
    chunks = chunk_text(text, chunk_chars=10)
    assert [c.text for c in chunks] == ["aaaa\n\nbbbb", "cccc\n\ndddd"]
    assert [c.seq for c in chunks] == [0, 1]


def test_a_paragraph_longer_than_the_limit_is_hard_split_at_whitespace():
    text = "word " * 50
    chunks = chunk_text(text.strip(), chunk_chars=23)
    assert all(len(c.text) <= 23 for c in chunks)
    assert "".join(c.text.replace(" ", "") for c in chunks) == "word" * 50
    assert all(not c.text.startswith(" ") for c in chunks)


def test_a_word_longer_than_the_limit_is_split_by_characters():
    chunks = chunk_text("x" * 25, chunk_chars=10)
    assert [c.text for c in chunks] == ["x" * 10, "x" * 10, "x" * 5]


def test_chunking_is_deterministic():
    text = "one\n\ntwo " * 40
    assert chunk_text(text, chunk_chars=50) == chunk_text(text, chunk_chars=50)


def test_chunk_chars_must_be_positive():
    with pytest.raises(ValueError):
        chunk_text("abc", chunk_chars=0)
