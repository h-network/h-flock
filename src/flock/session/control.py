"""A single tmux control-mode connection shared by all session viewers."""

from __future__ import annotations

import asyncio
import re
import shlex
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


from flock.tmux import require_isolated_tmux


_CONTROL_ESCAPE = re.compile(rb"\\(\\|[0-7]{3})")


def _unescape_control(data: bytes) -> bytes:
    """Turn tmux control-mode escapes back into the bytes they stand for.

    ⚠ `%output` does not carry raw bytes. tmux escapes every non-printable as a
    backslash and three OCTAL digits, so ESC arrives as the four characters
    \\033 and a literal backslash as \\\\. Publishing that unchanged means a
    terminal renders `\\033[?25l` as text instead of hiding the cursor — which
    is exactly what an operator saw: screenfuls of escape sequences as prose.
    """

    def replace(match: "re.Match[bytes]") -> bytes:
        body = match.group(1)
        return b"\\" if body == b"\\" else bytes([int(body, 8)])

    return _CONTROL_ESCAPE.sub(replace, data)


class ControlModeError(RuntimeError):
    """The tmux control-mode stream or a command failed."""


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[dict[str, str]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1000)
    )
    agents: set[str] = field(default_factory=set)
    buffering: dict[str, list[str]] = field(default_factory=dict)


class ControlModeClient:
    def __init__(self, session_name: str, socket: str | None = None) -> None:
        self.session_name = session_name
        self.socket = socket
        self.process: asyncio.subprocess.Process | None = None
        self.pane_to_agent: dict[str, str] = {}
        self.agent_to_pane: dict[str, str] = {}
        self._subscribers: dict[str, set[Subscriber]] = defaultdict(set)
        self._pending: deque[asyncio.Future[list[str]]] = deque()
        self._command_lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self.broken_reason: str | None = None

    async def ensure_connected(self) -> None:
        if not self.broken_reason:
            return
        async with self._command_lock:
            if not self.broken_reason:
                return
            await self.start()

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            await self.stop()
        self.broken_reason = None
        self._ready = asyncio.Event()
        self._pending.clear()
        require_isolated_tmux(self.socket)
        command = ["tmux"]
        if self.socket:
            command.extend(["-S", self.socket])
        command.extend(
            ["-C", "attach-session", "-f", "ignore-size", "-t", self.session_name]
        )
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_control_stream())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=5)
        except TimeoutError as exc:
            await self.stop()
            raise ControlModeError("tmux control mode did not become ready") from exc
        if self.broken_reason:
            raise ControlModeError(self.broken_reason)
        await self.refresh_panes()

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task),
            return_exceptions=True,
        )

    async def command(self, *args: str) -> list[str]:
        await self.ensure_connected()
        process = self.process
        if self.broken_reason:
            raise ControlModeError(self.broken_reason)
        if process is None or process.stdin is None or process.returncode is not None:
            raise ControlModeError("tmux control mode is not running")
        async with self._command_lock:
            future = asyncio.get_running_loop().create_future()
            self._pending.append(future)
            process.stdin.write((shlex.join(args) + "\n").encode())
            try:
                await process.stdin.drain()
                return await future
            except BaseException:
                if not future.done():
                    future.cancel()
                try:
                    self._pending.remove(future)
                except ValueError:
                    pass
                raise

    async def refresh_panes(self) -> None:
        lines = await self.command(
            "list-panes", "-s", "-t", self.session_name, "-F", "#{pane_id}\t#{window_name}"
        )
        pane_to_agent: dict[str, str] = {}
        agent_to_pane: dict[str, str] = {}
        for line in lines:
            pane, separator, agent = line.partition("\t")
            if separator and pane.startswith("%") and agent:
                pane_to_agent[pane] = agent
                if agent not in agent_to_pane:
                    agent_to_pane[agent] = pane
        self.pane_to_agent = pane_to_agent
        self.agent_to_pane = agent_to_pane

    async def update_subscription(
        self, subscriber: Subscriber, agents: set[str], *, refresh: bool = False
    ) -> list[str]:
        await self.ensure_connected()
        if agents - self.agent_to_pane.keys():
            await self.refresh_panes()
        unknown = sorted(agents - self.agent_to_pane.keys())
        if unknown:
            return unknown
        removed = subscriber.agents - agents
        added = agents - subscriber.agents
        # ⚠ `refresh` re-snapshots every requested agent, not just newly added
        # ones — a client that wants a fresh capture-pane without dropping its
        # live stream (a periodic pane-content poll rather than a resize or a
        # reconnect) sends the same agent set again with refresh=true instead
        # of unsubscribing and resubscribing, which would open a gap where a
        # live %output could be missed between the two round trips.
        to_snapshot = set(agents) if refresh else added
        for agent in removed:
            self._subscribers[agent].discard(subscriber)
        for agent in added:
            self._subscribers[agent].add(subscriber)
        for agent in to_snapshot:
            subscriber.buffering[agent] = []
        subscriber.agents = set(agents)

        for agent in sorted(to_snapshot):
            pane = self.agent_to_pane[agent]
            # ⚠ The VISIBLE screen, not the scrollback. `-S -` dumps the whole
            # history, so a client wrote thousands of lines and then received
            # live updates that position the cursor absolutely within a 32-row
            # screen — the two disagreed, and an operator saw the prompt near the
            # top while their own keystrokes echoed far below it.
            snapshot = await self.command("capture-pane", "-p", "-e", "-t", pane)
            # Clear and home first so row 1 of the client is row 1 of the pane,
            # then put the cursor where tmux actually has it. Without this the
            # client's idea of the screen is offset from the pty's for good.
            cursor = await self.command(
                "display-message", "-p", "-t", pane, "#{cursor_y} #{cursor_x}"
            )
            try:
                row, col = (int(v) + 1 for v in cursor[0].split())
            except (IndexError, ValueError):
                row, col = 1, 1
            payload = "\x1b[2J\x1b[H" + "\n".join(snapshot) + f"\x1b[{row};{col}H"
            try:
                subscriber.queue.put_nowait({"agent": agent, "data": payload})
            except asyncio.QueueFull:
                try:
                    subscriber.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                subscriber.queue.put_nowait({"agent": agent, "data": payload})
            for data in subscriber.buffering.pop(agent, []):
                try:
                    subscriber.queue.put_nowait({"agent": agent, "data": data})
                except asyncio.QueueFull:
                    try:
                        subscriber.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    subscriber.queue.put_nowait({"agent": agent, "data": data})
        return []

    def unsubscribe(self, subscriber: Subscriber) -> None:
        for agent in subscriber.agents:
            self._subscribers[agent].discard(subscriber)
        subscriber.agents.clear()
        subscriber.buffering.clear()

    async def send_keys(self, agent: str, data: str) -> None:
        await self.ensure_connected()
        pane = self.agent_to_pane.get(agent)
        if pane is None:
            raise ControlModeError(f"unknown agent: {agent}")
        encoded = data.encode("utf-8")
        if encoded:
            await self.command("send-keys", "-t", pane, "-H", *(f"{byte:02x}" for byte in encoded))

    def _publish(self, pane: str, data: bytes) -> None:
        agent = self.pane_to_agent.get(pane)
        if agent is None:
            return
        text = _unescape_control(data).decode("utf-8", errors="replace")
        for subscriber in tuple(self._subscribers.get(agent, ())):
            buffer = subscriber.buffering.get(agent)
            if buffer is not None:
                buffer.append(text)
            else:
                try:
                    subscriber.queue.put_nowait({"agent": agent, "data": text})
                except asyncio.QueueFull:
                    try:
                        subscriber.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    subscriber.queue.put_nowait({"agent": agent, "data": text})

    def _schedule_refresh(self) -> None:
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh_after_notification())

    async def _refresh_after_notification(self) -> None:
        await asyncio.sleep(0)
        try:
            await self.refresh_panes()
        except ControlModeError:
            pass

    async def _read_control_stream(self) -> None:
        assert self.process and self.process.stdout
        response: list[str] | None = None
        try:
            while raw_line := await self.process.stdout.readline():
                line = raw_line.rstrip(b"\r\n")
                if line.startswith(b"%output "):
                    parts = line.split(b" ", 2)
                    if len(parts) == 3:
                        self._publish(parts[1].decode("ascii", "replace"), parts[2])
                    continue
                if line.startswith((b"%window-add", b"%window-close", b"%window-renamed")):
                    self._schedule_refresh()
                    continue
                if line.startswith(b"%begin "):
                    response = []
                    continue
                if line.startswith(b"%end "):
                    self._resolve_response(response or [])
                    response = None
                    self._ready.set()
                    continue
                if line.startswith(b"%error "):
                    self._reject_response(response or [])
                    response = None
                    self._ready.set()
                    continue
                if line.startswith(b"%exit"):
                    break
                if response is not None:
                    response.append(line.decode("utf-8", "surrogateescape"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.broken_reason = f"tmux stream failed: {exc}"
        finally:
            if self.broken_reason is None:
                self.broken_reason = "tmux stream closed"
            self._ready.set()
            self._fail_pending(self.broken_reason)
            event = {"error": self.broken_reason}
            for subscribers in self._subscribers.values():
                for subscriber in tuple(subscribers):
                    subscriber.queue.put_nowait(event)

    def _resolve_response(self, response: list[str]) -> None:
        if self._pending:
            future = self._pending.popleft()
            if not future.done():
                future.set_result(response)

    def _reject_response(self, response: list[str]) -> None:
        if self._pending:
            future = self._pending.popleft()
            if not future.done():
                future.set_exception(ControlModeError("\n".join(response) or "tmux command failed"))

    def _fail_pending(self, reason: str) -> None:
        while self._pending:
            future = self._pending.popleft()
            if not future.done():
                future.set_exception(ControlModeError(reason))

    async def _drain_stderr(self) -> None:
        assert self.process and self.process.stderr
        while await self.process.stderr.read(4096):
            pass
