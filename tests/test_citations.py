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


def test_recognizer_is_case_insensitive_so_silence_is_not_a_pass(tmp_path, capsys):
    """⚠ `path.MD:1` matched NOTHING, so a dead path reported zero failures.

    The checker was not lenient about the file — it was BLIND to the citation,
    which is worse: no finding is indistinguishable from a clean run, and every
    "0 hard failures" I quoted covered only lower-case citations.

    Constructed by `bus` while attacking `docs/TEST-SIGNOFF.md` (build 78). This
    pins both arms, because a fix verified only on the failing arm proves the
    recogniser fires, not that it fires on the right population.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "upper.md").write_text("gone.MD:1\n", encoding="utf-8")
    assert check_citations.main(["--root", str(tmp_path), "docs"]) == 1
    assert "gone.MD:1: path does not exist" in capsys.readouterr().out

    (docs / "upper.md").write_text("gone.Py:9\n", encoding="utf-8")
    assert check_citations.main(["--root", str(tmp_path), "docs"]) == 1
    capsys.readouterr()

    # ⚠ The other arm, and I expected the wrong answer here first. A miscased
    # citation to a file that DOES exist is still a dead path on a
    # case-sensitive filesystem — a reader following `live.PY:1` gets
    # file-not-found. So it must be REPORTED, not forgiven. Recognise
    # case-insensitively; resolve exactly.
    (tmp_path / "live.py").write_text("one line\n", encoding="utf-8")
    (docs / "upper.md").write_text("live.PY:1\n", encoding="utf-8")
    assert check_citations.main(["--root", str(tmp_path), "docs"]) == 1
    assert "live.PY:1: path does not exist" in capsys.readouterr().out

    # And the same citation written correctly passes, so the rule is about the
    # path being real rather than about case.
    (docs / "upper.md").write_text("live.py:1\n", encoding="utf-8")
    assert check_citations.main(["--root", str(tmp_path), "docs"]) == 0
