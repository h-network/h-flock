"""Apply count-based retention in the router's existing tenant pass."""

from flock.bus import prefix


class RetentionTrimmer:
    def __init__(self, r, *, pod: str, tenant: str, board_done_max: int = 500, dead_max: int = 500):
        if board_done_max < 1 or dead_max < 1:
            raise ValueError("retention caps must be positive")
        self.r = r
        self.pod = pod
        self.tenant = tenant
        self.board_done_max = board_done_max
        self.dead_max = dead_max

    def poll(self, agents) -> None:
        pipe = self.r.pipeline()
        for agent in sorted(agents):
            pipe.ltrim(prefix(self.pod, self.tenant, agent, "tasks.done"), -self.board_done_max, -1)
            pipe.ltrim(prefix(self.pod, self.tenant, agent, "dead"), -self.dead_max, -1)
        pipe.execute()
