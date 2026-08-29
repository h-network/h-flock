from flock.openshell.naming import MAX_NAME_LENGTH, sandbox_name, short_name, workspace_name


def test_short_value_passes_through_unchanged():
    assert short_name("dave") == "dave"


def test_value_at_exact_limit_passes_through_unchanged():
    value = "a" * MAX_NAME_LENGTH
    assert short_name(value) == value


def test_long_value_is_shortened_to_max_length():
    value = "a-very-long-agent-name-that-exceeds-the-limit"
    result = short_name(value)
    assert len(result) == MAX_NAME_LENGTH


def test_shortening_is_deterministic():
    value = "a-very-long-agent-name-that-exceeds-the-limit"
    assert short_name(value) == short_name(value)


def test_different_long_values_shorten_differently():
    a = short_name("a-very-long-agent-name-that-exceeds-the-limit-a")
    b = short_name("a-very-long-agent-name-that-exceeds-the-limit-b")
    assert a != b


def test_sandbox_name_matches_short_name():
    agent = "a-very-long-agent-name-that-exceeds-the-limit"
    assert sandbox_name(agent) == short_name(agent)
    assert len(sandbox_name(agent)) <= MAX_NAME_LENGTH


def test_workspace_name_combines_pod_and_tenant():
    assert workspace_name("acme", "hq") == "acme-hq"
    assert len(workspace_name("acme", "hq")) <= MAX_NAME_LENGTH


def test_workspace_name_shortens_when_combined_length_exceeds_limit():
    result = workspace_name("a-fairly-long-pod-name", "a-fairly-long-tenant-name")
    assert len(result) <= MAX_NAME_LENGTH
