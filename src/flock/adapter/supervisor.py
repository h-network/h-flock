import time
import redis
from typing import Dict

from flock.bus import members, log_record
from .consumer import AgentConsumerThread


class AdapterSupervisor:
    def __init__(
        self,
        pod: str,
        tenant: str,
        redis_url: str,
        poll_seconds: float = 5.0,
        session_name: str | None = None,
        socket: str | None = None,
    ):
        self.pod = pod
        self.tenant = tenant
        self.redis_url = redis_url
        self.poll_seconds = poll_seconds
        self.session_name = session_name or tenant
        self.socket = socket
        self.consumers: Dict[str, AgentConsumerThread] = {}

    def run_forever(self) -> None:
        r = redis.Redis.from_url(self.redis_url)
        log_record("adapter", "started", reason=f"session={self.session_name}")

        while True:
            try:
                current_members = members(r, pod=self.pod, tenant=self.tenant)

                # Start consumers for new members
                for agent in current_members:
                    existing = self.consumers.get(agent)
                    if existing is None or not existing.is_alive():
                        t = AgentConsumerThread(
                            agent=agent,
                            pod=self.pod,
                            tenant=self.tenant,
                            redis_url=self.redis_url,
                            session_name=self.session_name,
                            socket=self.socket,
                        )
                        t.start()
                        self.consumers[agent] = t

                # Stop consumers for agents no longer in roster
                removed_agents = [a for a in self.consumers if a not in current_members]
                for agent in removed_agents:
                    t = self.consumers[agent]
                    t.stop()
                    t.join()  # Join until dead before removing
                    del self.consumers[agent]
                    log_record("adapter", "stopped", recipient=agent)

            except Exception as e:
                log_record("adapter", "error", reason=f"Supervisor exception: {e}")

            time.sleep(self.poll_seconds)
