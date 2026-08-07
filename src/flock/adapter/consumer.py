import threading
import redis
from typing import Callable

from flock.bus import receive
from .openers import message_opener


class AgentConsumerThread(threading.Thread):
    def __init__(
        self,
        agent: str,
        pod: str,
        tenant: str,
        redis_url: str,
        session_name: str,
        socket: str | None = None,
    ):
        super().__init__(name=f"ConsumerThread-{agent}", daemon=True)
        self.agent = agent
        self.pod = pod
        self.tenant = tenant
        self.redis_url = redis_url
        self.session_name = session_name
        self.socket = socket
        self._stop_requested = threading.Event()

    def stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        r = redis.Redis.from_url(self.redis_url)

        def handle_message(env: dict) -> None:
            message_opener(
                r=r,
                pod=self.pod,
                tenant=self.tenant,
                agent=self.agent,
                envelope=env,
                session_name=self.session_name,
                socket=self.socket,
            )

        openers: dict[str, Callable[[dict], None]] = {
            "Message": handle_message
        }

        while not self._stop_requested.is_set():
            try:
                receive(
                    r,
                    pod=self.pod,
                    tenant=self.tenant,
                    agent=self.agent,
                    openers=openers,
                    timeout=1,
                )
            except Exception as e:
                if not self._stop_requested.is_set():
                    pass
