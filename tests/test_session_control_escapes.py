"""tmux control mode does not carry raw bytes — it octal-escapes them."""

from flock.session.control import _unescape_control

ESC = b"\x1b"


def test_octal_escapes_become_the_bytes_they_stand_for():
    # ⚠ An operator saw screenfuls of `\033[?25l` rendered as prose because
    # %output was published unchanged. This is that bug.
    assert _unescape_control(b"\\033[?25l") == ESC + b"[?25l"
    assert _unescape_control(b"\\033[31;1mred\\033[0m") == ESC + b"[31;1mred" + ESC + b"[0m"
    assert _unescape_control(b"\\015\\012") == b"\r\n"


def test_a_literal_backslash_arrives_doubled_and_leaves_single():
    assert _unescape_control(b"a\\\\b") == b"a\\b"


def test_ordinary_text_is_untouched():
    assert _unescape_control(b"hello world") == b"hello world"
