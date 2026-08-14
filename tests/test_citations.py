from pathlib import Path

from tools import check_citations


def test_checker_catches_deleted_path_and_line_past_eof(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "live.py").write_text("one line\n", encoding="utf-8")
    (docs / "claims.md").write_text(
        "deleted.py:1\nlive.py:2\n",
        encoding="utf-8",
    )

    assert check_citations.main(["--root", str(tmp_path), "docs"]) == 1
    output = capsys.readouterr().out
    assert "citations checked: 2 (2 unique)" in output
    assert "deleted.py:1: path does not exist" in output
    assert "live.py:2: line outside file (1-1)" in output
    assert "hard failures: 2" in output


def test_checker_reports_symbol_near_miss_without_failing(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "live.py").write_text("def actual():\n    pass\n", encoding="utf-8")
    (docs / "claims.md").write_text("`expected` — live.py:1\n", encoding="utf-8")

    assert check_citations.main(["--root", str(tmp_path), "docs"]) == 0
    output = capsys.readouterr().out
    assert "symbol 'expected' not within 3 lines" in output
    assert "hard failures: 0" in output
    assert "near misses: 1" in output
