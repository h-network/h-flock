from flock.bus import prefix
from flock.router.retention import RetentionTrimmer


class RetentionRedis:
    def __init__(self):
        self.lists = {}
        self.trimmed = []

    def pipeline(self):
        return self

    def ltrim(self, key, start, end):
        self.trimmed.append((key, start, end))
        values = self.lists.get(key, [])
        start = max(0, len(values) + start) if start < 0 else start
        end = len(values) + end if end < 0 else end
        self.lists[key] = values[start : end + 1]
        return self

    def execute(self):
        return [True] * len(self.trimmed)


def test_router_retention_keeps_newest_done_tickets_and_dead_letters():
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
