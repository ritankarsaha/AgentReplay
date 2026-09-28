from __future__ import annotations

from agentreplay.testgen._fileio import warn_if_overwriting_different_content


def test_no_warning_when_path_does_not_exist(tmp_path, capsys):
    warn_if_overwriting_different_content(tmp_path / "missing.py", "new content")
    assert capsys.readouterr().err == ""


def test_no_warning_when_content_is_identical(tmp_path, capsys):
    path = tmp_path / "f.py"
    path.write_text("same")
    warn_if_overwriting_different_content(path, "same")
    assert capsys.readouterr().err == ""


def test_warns_when_content_differs(tmp_path, capsys):
    path = tmp_path / "f.py"
    path.write_text("old")
    warn_if_overwriting_different_content(path, "new")
    err = capsys.readouterr().err
    assert "overwriting existing file with different content" in err
    assert str(path) in err
