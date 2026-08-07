import json
import time
import threading
import redis
from typing import Callable

from flock.bus import receive, prefix, log_record
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
            try:
                message_opener(
                    r=r,
                    pod=self.pod,
                    tenant=self.tenant,
                    agent=self.agent,
                    envelope=env,
                    session_name=self.session_name,
                    socket=self.socket,
                )
            except Exception as e:
                stream_id = env.get("stream_id", "")
                corr_id = env.get("correlation_id")
                producer = env.get("producer")
                recipient = env.get("recipient", self.agent)
                dead_key = prefix(self.pod, self.tenant, agent=self.agent, resource="dead")
                try:
                    r.rpush(dead_key, json.dumps(env))
                except Exception:
                    pass
                log_record(
                    "adapter",
                    "dead_lettered",
                    stream_id=stream_id,
                    correlation_id=corr_id,
                    producer=producer,
                    recipient=recipient,
                    reason=f"Opener exception: {e}",
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
                    log_record("adapter", "error", recipient=self.agent, reason=f"Consumer loop error: {e}")
                    time.sleep(1.0)
