import os

import pytest

from obiwan.core.paths import is_contained


def test_a_child_is_contained(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.md").write_text("x", encoding="utf-8")
    assert is_contained(tmp_path / "a" / "f.md", tmp_path)
    assert is_contained(tmp_path, tmp_path)


def test_dotdot_that_resolves_outside_is_not_contained(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    assert not is_contained(root / ".." / "secret.md", root)
    assert not is_contained(root / "sub" / ".." / ".." / "secret.md", root)


def test_a_sibling_with_a_shared_prefix_is_not_contained(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "root-evil").mkdir()
    assert not is_contained(tmp_path / "root-evil" / "f.md", tmp_path / "root")


def test_resolve_errors_mean_not_contained(tmp_path, monkeypatch):
    def boom(self, strict=False):
        raise RuntimeError("symlink loop")
    monkeypatch.setattr(type(tmp_path), "resolve", boom)
    assert not is_contained(tmp_path / "f", tmp_path)


def test_symlink_out_is_not_contained_and_symlink_in_is(tmp_path):
    root, out = tmp_path / "root", tmp_path / "out"
    root.mkdir()
    out.mkdir()
    (out / "o.md").write_text("x", encoding="utf-8")
    (root / "in.md").write_text("x", encoding="utf-8")
    try:
        os.symlink(out / "o.md", root / "escape.md")
        os.symlink(root / "in.md", root / "alias.md")
    except OSError:
        pytest.skip("symlinks unavailable")
    assert not is_contained(root / "escape.md", root)
    assert is_contained(root / "alias.md", root)
