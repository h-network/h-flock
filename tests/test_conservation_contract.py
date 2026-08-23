from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "container" / "scenarios" / "conservation.sh"


def test_forward_unknown_is_not_folded_into_forwarded_or_loss():
    text = SCRIPT.read_text()

    classification = text.index('rec.get("event") == "forward_unknown"')
    loss_attribution = text.index("cause = switch_kill_bracket")
    assert classification < loss_attribution
    assert 'indeterminate.append((seq, sid))' in text
    assert 'print("INDETERMINATE_FORWARD", *row)' in text
    assert "5 if indeterminate" in text

