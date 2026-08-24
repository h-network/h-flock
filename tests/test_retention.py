from conftest import FakeRedis as RetentionRedis
from flock.bus import prefix
from flock.switch.retention import RetentionTrimmer



def test_switch_retention_keeps_newest_done_tickets_and_dead_letters():
    r = RetentionRedis()
    done = prefix("acme", "hq", "sme-2", "tasks.done")
    dead = prefix("acme", "hq", "sme-2", "dead")
    r.lists[done] = [f"ticket-{number}" for number in range(600)]
    r.lists[dead] = [f"envelope-{number}" for number in range(12)]

    RetentionTrimmer(r, pod="acme", tenant="hq", board_done_max=500, dead_max=5).poll({"sme-2"})

    assert r.lists[done] == [f"ticket-{number}" for number in range(100, 600)]
    assert r.lists[dead] == [f"envelope-{number}" for number in range(7, 12)]
    assert r.trimmed == [(done, -500, -1), (dead, -5, -1)]


def test_retention_covers_each_agent_in_one_pipeline():
    r = RetentionRedis()
    RetentionTrimmer(r, pod="acme", tenant="hq").poll({"sme-3", "architect", "sme-2"})
    assert len(r.trimmed) == 6
    assert [key for key, _, _ in r.trimmed] == [
        prefix("acme", "hq", agent, resource)
        for agent in ("architect", "sme-2", "sme-3")
        for resource in ("tasks.done", "dead")
    ]
