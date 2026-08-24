import json
import os
import pytest
from flock.bus.resp import Redis as RespRedis, ResponseError

os.environ.setdefault("PASTE_ENTER_DELAY", "0")


class FakePipeline:
    def __init__(self, redis_instance):
        self.r = redis_instance
        self._redis = redis_instance
        self.commands = []
        self._commands = self.commands
        self._keys = []

    def rpush(self, key, *values):
        val = values[0] if len(values) == 1 else values
        self.commands.append((key, val))
        self._keys.append(key)
        return self

    def lrange(self, key, start, end):
        self.commands.append((key, start, end))
        self._keys.append(key)
        return self

    def ltrim(self, key, start, end):
        self.commands.append((key, start, end))
        self._keys.append(key)
        self._redis.ltrim(key, start, end)
        return self

    def execute(self):
        results = []
        for cmd in self.commands:
            if len(cmd) == 2:
                key, val = cmd
                if isinstance(val, (tuple, list)):
                    results.append(self._redis.rpush(key, *val))
                else:
                    results.append(self._redis.rpush(key, val))
            elif len(cmd) == 3:
                key, start, end = cmd
                results.append(self._redis.lrange(key, start, end))
        self.commands.clear()
        return results


class FakeRespRedis:
    """In-memory double for flock.bus.resp.Redis (short-lived port/office client).
    Exposes EXACTLY the 24 methods of flock.bus.resp.Redis — no more, no less."""

    def __init__(
        self,
        data_or_events=None,
        *,
        data=None,
        agents=None,
        roster=None,
        roster_agents=None,
        port_type_map=None,
        launch_map=None,
        profile_map=None,
        provider_map=None,
        cause_map=None,
        events=None,
        ingress_depth=0,
        roster_port_type=None,
        account_profiles=None,
        fails_on=None,
        fail_at=None,
        fail_after=None,
        fail_xadd=False,
    ):
        if isinstance(data_or_events, (list, tuple, set)):
            if all(isinstance(x, str) for x in data_or_events):
                self.roster_agents = set(data_or_events)
                self.agents = tuple(data_or_events)
                self.port_type_map = port_type_map or {a: "tmux" for a in data_or_events}
                self.roster = {a.encode(): self.port_type_map[a].encode() if isinstance(self.port_type_map[a], str) else self.port_type_map[a] for a in self.port_type_map}
                self.events = data_or_events if events is None and not data_or_events else events
                self.values = dict(data) if data else {}
            else:
                self.events = data_or_events
                self.roster_agents = set(roster_agents) if roster_agents is not None else None
                self.port_type_map = port_type_map or ({a: "tmux" for a in roster_agents} if roster_agents else None)
                self.roster = dict(self.port_type_map) if self.port_type_map else None
                self.values = dict(data) if data else {}
        elif isinstance(data_or_events, dict):
            self.events = events
            self.values = dict(data_or_events)
            self.roster_agents = set(roster_agents) if roster_agents is not None else None
            self.port_type_map = port_type_map or ({a: "tmux" for a in roster_agents} if roster_agents else None)
            self.roster = dict(self.port_type_map) if self.port_type_map else None
        else:
            self.events = events
            self.values = dict(data) if data else {}
            self.roster_agents = set(roster_agents) if roster_agents is not None else None
            self.port_type_map = port_type_map or ({a: "tmux" for a in roster_agents} if roster_agents else None)
            self.roster = dict(self.port_type_map) if self.port_type_map else None

        self.kv = self.values
        self.data = self.values
        self.hashes = {}
        self.lists = {}
        self.sets = {}
        self.streams = {}
        self.writes = []
        self.calls = []
        self.moves = []
        self.deleted = []
        self.trimmed = []
        self.xrange_calls = []
        self.reverse_counts = []
        self.lengths = {}

        self.agents = agents or (tuple(self.roster_agents) if self.roster_agents else None)
        if roster is not None:
            self.roster = dict(roster)
        elif self.roster is None:
            self.roster = {
                b"architect": b"tmux",
                b"sme-2": b"tmux",
                b"frontend": b"tmux",
                b"backend": b"tmux",
                b"alice": b"tmux",
                b"bob": b"tmux",
                b"api": b"api",
                b"host": b"control",
                b"telegram": b"api",
            }

        self.launch_map = launch_map if launch_map is not None else {}
        self.profile_map = profile_map if profile_map is not None else {}
        self.provider_map = provider_map if provider_map is not None else {}
        self.cause_map = cause_map if cause_map is not None else {}

        self.ingress_depth = ingress_depth
        self.roster_port_type = roster_port_type
        self.account_profiles = account_profiles or set()

        self.fails_on = dict(fails_on) if fails_on else {}
        self.fail_at = fail_at
        self.fail_after = fail_after
        self.fail_xadd = fail_xadd
        self._call_count = 0

    def _check_fault(self, command_name, *args):
        self._call_count += 1
        if command_name in self.fails_on:
            err = self.fails_on[command_name]
            if isinstance(err, type) and issubclass(err, Exception):
                raise err(f"Simulated fault on {command_name}")
            elif isinstance(err, Exception):
                raise err
            elif callable(err):
                res = err(*args)
                if res is not None:
                    return res
        if self.fail_at is not None and self._call_count == self.fail_at:
            raise ConnectionError(f"Simulated failure at call {self._call_count}")
        if self.fail_after is not None and self._call_count > self.fail_after:
            raise ConnectionError(f"Simulated failure after call {self.fail_after}")
        return None

    # --- 24 RESP Methods ---
    def get(self, key):
        if self.events is not None:
            self.events.append(("get", key))
        fault = self._check_fault("get", key)
        if fault is not None:
            return fault
        self.calls.append(("get", key))
        if key in self.values:
            val = self.values[key]
            return val.encode() if isinstance(val, str) and (":launch" in str(key) or ":profile" in str(key)) else val
        if hasattr(self, "cause_map"):
            for agent, cause in self.cause_map.items():
                if f":agent:{agent}:window.cause" in str(key) or f":{agent}:window.cause" in str(key):
                    return cause.encode("utf-8") if isinstance(cause, str) else cause
        if hasattr(self, "launch_map"):
            for agent, cli in self.launch_map.items():
                if f":agent:{agent}:launch" in str(key) or f":{agent}:launch" in str(key):
                    return cli.encode("utf-8") if isinstance(cli, str) else cli
        if hasattr(self, "profile_map"):
            for agent, prof in self.profile_map.items():
                if f":agent:{agent}:profile" in str(key) or f":{agent}:profile" in str(key):
                    return prof.encode("utf-8") if isinstance(prof, str) else prof
        if hasattr(self, "provider_map"):
            for agent, provider in self.provider_map.items():
                if f":agent:{agent}:provider" in str(key) or f":{agent}:provider" in str(key):
                    return provider.encode("utf-8") if isinstance(provider, str) else provider
        return None

    def set(self, key, value, ex=None):
        if self.events is not None:
            self.events.append(("set", key, value))
        fault = self._check_fault("set", key, value, ex)
        if fault is not None:
            return fault
        self.calls.append(("set", key, value))
        self.writes.append(("set", key, value, ex))
        self.values[key] = value
        if ":window.cause" in str(key):
            parts = str(key).split(":")
            for i, p in enumerate(parts):
                if p == "agent" and i + 1 < len(parts):
                    self.cause_map[parts[i + 1]] = value
                    break
        elif ":launch" in str(key):
            parts = str(key).split(":")
            for i, p in enumerate(parts):
                if p == "agent" and i + 1 < len(parts):
                    self.launch_map[parts[i + 1]] = value
                    break
        return True

    def getdel(self, key):
        if self.events is not None:
            self.events.append(("getdel", key))
        fault = self._check_fault("getdel", key)
        if fault is not None:
            return fault
        self.calls.append(("getdel", key))
        self.writes.append(("getdel", key))
        val = self.get(key)
        self.values.pop(key, None)
        if hasattr(self, "cause_map"):
            for agent in list(self.cause_map):
                if f":agent:{agent}:window.cause" in str(key) or f":{agent}:window.cause" in str(key):
                    val = self.cause_map.pop(agent)
                    return val.encode("utf-8") if isinstance(val, str) else val
        return val

    def delete(self, *keys):
        if self.events is not None:
            self.events.append(("delete", *keys))
        fault = self._check_fault("delete", *keys)
        if fault is not None:
            return fault
        self.calls.append(("delete", *keys))
        self.writes.append(("delete", *keys))
        self.deleted.extend(keys)
        count = 0
        for k in keys:
            if k in self.values:
                del self.values[k]
                count += 1
            if k in self.hashes:
                del self.hashes[k]
                count += 1
            if k in self.lists:
                del self.lists[k]
                count += 1
            if k in self.sets:
                del self.sets[k]
                count += 1
            if k in self.streams:
                del self.streams[k]
                count += 1
        return count or len(keys)

    def rpush(self, key, *values):
        if self.events is not None:
            self.events.append(("rpush", key, *values))
        fault = self._check_fault("rpush", key, *values)
        if fault is not None:
            return fault
        self.calls.append((key, values))
        self.writes.append(("rpush", key, values))
        lst = self.lists.setdefault(key, [])
        for v in values:
            lst.append(v)
        return len(lst)

    def lpop(self, key):
        if self.events is not None:
            self.events.append(("lpop", key))
        fault = self._check_fault("lpop", key)
        if fault is not None:
            return fault
        self.calls.append(("lpop", key))
        lst = self.lists.get(key, [])
        if lst:
            return lst.pop(0)
        return None

    def blpop(self, keys, timeout=0):
        if self.events is not None:
            self.events.append(("blpop", keys, timeout))
        fault = self._check_fault("blpop", keys, timeout)
        if fault is not None:
            return fault
        self.calls.append(("blpop", keys, timeout))
        if isinstance(keys, (str, bytes)):
            keys = [keys]
        for k in keys:
            lst = self.lists.get(k, [])
            if lst:
                val = lst.pop(0)
                return [k, val]
        return None

    def lrange(self, key, start, stop):
        if self.events is not None:
            self.events.append(("lrange", key, start, stop))
        fault = self._check_fault("lrange", key, start, stop)
        if fault is not None:
            return fault
        self.calls.append(("lrange", key, start, stop))
        lst = self.lists.get(key, [])
        if stop == -1:
            return list(lst[start:])
        return list(lst[start : stop + 1])

    def llen(self, key):
        if self.events is not None:
            self.events.append(("llen", key))
        fault = self._check_fault("llen", key)
        if fault is not None:
            return fault
        self.calls.append(("llen", key))
        if hasattr(self, "ingress_depth") and self.ingress_depth and ":ingress" in str(key):
            return self.ingress_depth
        if key in self.lengths:
            return self.lengths[key]
        return len(self.lists.get(key, []))

    def lrem(self, key, count, value):
        if self.events is not None:
            self.events.append(("lrem", key, count, value))
        fault = self._check_fault("lrem", key, count, value)
        if fault is not None:
            return fault
        self.calls.append(("lrem", key, count, value))
        lst = self.lists.get(key, [])
        removed = 0
        if count == 0:
            while value in lst:
                lst.remove(value)
                removed += 1
        elif count > 0:
            while value in lst and removed < count:
                lst.remove(value)
                removed += 1
        else:
            for _ in range(-count):
                if value in lst:
                    idx = len(lst) - 1 - lst[::-1].index(value)
                    lst.pop(idx)
                    removed += 1
        return removed

    def hset(self, key, field=None, value=None, mapping=None):
        if mapping is not None:
            if self.events is not None:
                self.events.append(("hset", key, mapping))
            fault = self._check_fault("hset", key, mapping)
            if fault is not None:
                return fault
            self.calls.append(("hset", key, mapping))
            self.writes.append(("hset", key, mapping))
            self.hashes.setdefault(key, {}).update(mapping)
            if ":roster" in str(key):
                for f, v in mapping.items():
                    if hasattr(self, "roster_agents") and self.roster_agents is not None:
                        self.roster_agents.add(f)
                    if hasattr(self, "port_type_map") and self.port_type_map is not None:
                        self.port_type_map[f] = v
            return len(mapping)
        else:
            if self.events is not None:
                self.events.append(("hset", key, field, value))
            fault = self._check_fault("hset", key, field, value)
            if fault is not None:
                return fault
            self.calls.append(("hset", key, field, value))
            self.writes.append(("hset", key, {field: value}))
            self.hashes.setdefault(key, {})[field] = value
            if ":roster" in str(key):
                if hasattr(self, "roster_agents") and self.roster_agents is not None:
                    self.roster_agents.add(field)
                if hasattr(self, "port_type_map") and self.port_type_map is not None:
                    self.port_type_map[field] = value
            return 1

    def hsetnx(self, key, field, value):
        if self.events is not None:
            self.events.append(("hsetnx", key, field, value))
        fault = self._check_fault("hsetnx", key, field, value)
        if fault is not None:
            return fault
        self.calls.append(("hsetnx", key, field, value))
        h = self.hashes.setdefault(key, {})
        if field not in h:
            h[field] = value
            return 1
        return 0

    def hget(self, key, field):
        if self.events is not None:
            self.events.append(("hget", key, field))
        fault = self._check_fault("hget", key, field)
        if fault is not None:
            return fault
        self.calls.append(("hget", key, field))
        if key in self.hashes:
            val = self.hashes[key].get(field)
            if val is None and isinstance(field, str):
                val = self.hashes[key].get(field.encode())
            elif val is None and isinstance(field, bytes):
                val = self.hashes[key].get(field.decode("utf-8", "replace"))
            if val is not None:
                return val
        if hasattr(self, "roster_port_type") and self.roster_port_type is not None:
            return self.roster_port_type
        if hasattr(self, "port_type_map") and self.port_type_map and field in self.port_type_map:
            val = self.port_type_map[field]
            return val.encode() if isinstance(val, str) else val
        if hasattr(self, "roster") and isinstance(self.roster, dict):
            f_str = field.decode("utf-8") if isinstance(field, bytes) else field
            f_bytes = field.encode() if isinstance(field, str) else field
            if f_bytes in self.roster:
                val = self.roster[f_bytes]
                return val.decode("utf-8") if isinstance(field, str) and isinstance(val, bytes) else val
            if f_str in self.roster:
                val = self.roster[f_str]
                return val.encode("utf-8") if isinstance(field, bytes) and isinstance(val, str) else val
        return None

    def hgetall(self, key):
        if self.events is not None:
            self.events.append(("hgetall", key))
        fault = self._check_fault("hgetall", key)
        if fault is not None:
            return fault
        self.calls.append(("hgetall", key))
        if key in self.hashes:
            return dict(self.hashes[key])
        if key in self.values:
            val = self.values[key]
            return dict(val) if isinstance(val, dict) else val
        if ":roster" in str(key) and hasattr(self, "roster"):
            return dict(self.roster)
        return {}

    def hkeys(self, key):
        if self.events is not None:
            self.events.append(("hkeys", key))
        fault = self._check_fault("hkeys", key)
        if fault is not None:
            return fault
        self.calls.append(("hkeys", key))
        if key in self.hashes:
            return list(self.hashes[key].keys())
        if hasattr(self, "roster_agents") and self.roster_agents is not None:
            return [a.encode("utf-8") for a in self.roster_agents]
        if hasattr(self, "agents") and self.agents is not None:
            return list(self.agents)
        if hasattr(self, "roster") and self.roster:
            return list(self.roster.keys())
        return []

    def hexists(self, key, field):
        if self.events is not None:
            self.events.append(("hexists", key, field))
        fault = self._check_fault("hexists", key, field)
        if fault is not None:
            return fault
        self.calls.append(("hexists", key, field))
        if key in self.hashes:
            return (
                field in self.hashes[key]
                or (isinstance(field, str) and field.encode() in self.hashes[key])
                or (isinstance(field, bytes) and field.decode("utf-8", "replace") in self.hashes[key])
            )
        if hasattr(self, "roster_agents") and self.roster_agents is not None:
            return field in self.roster_agents or (isinstance(field, bytes) and field.decode() in self.roster_agents)
        if hasattr(self, "roster") and isinstance(self.roster, dict):
            f_str = field.decode("utf-8") if isinstance(field, bytes) else field
            f_bytes = field.encode() if isinstance(field, str) else field
            return field in self.roster or f_bytes in self.roster or f_str in self.roster
        return False

    def hdel(self, key, *fields):
        if self.events is not None:
            for f in fields:
                self.events.append(("hdel", key, f))
        fault = self._check_fault("hdel", key, *fields)
        if fault is not None:
            return fault
        self.calls.append(("hdel", key, fields))
        self.writes.append(("hdel", key, fields))
        h = self.hashes.get(key, {})
        count = 0
        for f in fields:
            if f in h:
                del h[f]
                count += 1
            elif isinstance(f, str) and f.encode() in h:
                del h[f.encode()]
                count += 1
            elif isinstance(f, bytes) and f.decode("utf-8", "replace") in h:
                del h[f.decode("utf-8", "replace")]
                count += 1
        return count or len(fields)

    def smembers(self, key):
        if self.events is not None:
            self.events.append(("smembers", key))
        fault = self._check_fault("smembers", key)
        if fault is not None:
            return fault
        self.calls.append(("smembers", key))
        if key in self.sets:
            return set(self.sets[key])
        if self.account_profiles:
            return {p.encode("utf-8") if isinstance(p, str) else p for p in self.account_profiles}
        if hasattr(self, "roster_agents") and self.roster_agents is not None and ":roster" in str(key):
            return {a.encode("utf-8") for a in self.roster_agents}
        return set()

    def xadd(self, key, fields, maxlen=None, approximate=True, id="*"):
        if self.events is not None:
            self.events.append(("xadd", key, fields))
        fault = self._check_fault("xadd", key, fields)
        if fault is not None:
            return fault
        if getattr(self, "fail_xadd", False) and key.endswith(":usage"):
            raise RuntimeError("Simulated Redis write failure")
        self.calls.append(("xadd", key, fields))
        self.writes.append(("xadd", key, fields))
        stream = self.streams.setdefault(key, [])
        entry_id = f"{len(stream) + 1}-0" if id == "*" else id
        stream.append((entry_id, dict(fields)))
        if maxlen is not None and len(stream) > maxlen:
            del stream[:-maxlen]
        return entry_id

    def xrange(self, key, min="-", max="+", count=None):
        if self.events is not None:
            self.events.append(("xrange", key, min, max, count))
        fault = self._check_fault("xrange", key, min, max, count)
        if fault is not None:
            return fault
        self.calls.append(("xrange", key, min, max, count))
        self.xrange_calls.append((key, min, max))
        entries = self.streams.get(key, [])
        result = []
        exclusive = False
        min_str = min
        if isinstance(min_str, bytes):
            min_str = min_str.decode("utf-8", "replace")
        if isinstance(min_str, str) and min_str.startswith("("):
            exclusive = True
            min_str = min_str[1:]

        for entry in entries:
            entry_id, fields = entry[0], entry[1]
            eid = entry_id.decode("utf-8", "replace") if isinstance(entry_id, bytes) else str(entry_id)
            if min_str != "-":
                if exclusive and eid <= min_str:
                    continue
                if not exclusive and eid < min_str:
                    continue
            result.append((entry_id, fields))
            if count and len(result) >= count:
                break
        return result

    def xrevrange(self, key, max="+", min="-", count=None):
        if self.events is not None:
            self.events.append(("xrevrange", key, max, min, count))
        fault = self._check_fault("xrevrange", key, max, min, count)
        if fault is not None:
            return fault
        self.calls.append(("xrevrange", key, max, min, count))
        if count is not None:
            self.reverse_counts.append(count)
        stream = self.streams.get(key, [])
        reversed_stream = list(reversed(stream))
        if count is not None:
            return reversed_stream[:count]
        return reversed_stream

    def xdel(self, key, *ids):
        if self.events is not None:
            self.events.append(("xdel", key, *ids))
        fault = self._check_fault("xdel", key, *ids)
        if fault is not None:
            return fault
        self.calls.append(("xdel", key, *ids))
        self.deleted.extend([(key, i) for i in ids])
        stream = self.streams.get(key, [])
        id_set = set(ids)
        self.streams[key] = [entry for entry in stream if entry[0] not in id_set]
        return len(ids)

    def xlen(self, key):
        if self.events is not None:
            self.events.append(("xlen", key))
        fault = self._check_fault("xlen", key)
        if fault is not None:
            return fault
        self.calls.append(("xlen", key))
        return len(self.streams.get(key, []))

    def eval(self, script, numkeys, *keys_and_args):
        if self.events is not None:
            self.events.append(("eval", numkeys, *keys_and_args))
        fault = self._check_fault("eval", script, numkeys, *keys_and_args)
        if fault is not None:
            return fault
        self.calls.append(("eval", script, numkeys, keys_and_args))
        args = list(keys_and_args)
        if numkeys == 2 and len(args) == 5:
            cause_key, roster_key, correlation_id, agent, agent_port_type = args
            self.values[cause_key] = correlation_id
            if ":window.cause" in str(cause_key):
                parts = str(cause_key).split(":")
                for i, p in enumerate(parts):
                    if p == "agent" and i + 1 < len(parts):
                        self.cause_map[parts[i + 1]] = correlation_id
                        break
            self.hashes.setdefault(roster_key, {})[agent] = agent_port_type
            if hasattr(self, "roster_agents") and self.roster_agents is not None:
                self.roster_agents.add(agent)
            if hasattr(self, "port_type_map") and self.port_type_map is not None:
                self.port_type_map[agent] = agent_port_type
            return 1
        if "SET" in script:
            key = args[0]
            val = args[1] if len(args) > 1 else ""
            self.values[key] = val
            return 1
        stream_key = args[0] if numkeys >= 1 else ""
        seen_key = args[1] if numkeys >= 2 else ""
        attributed_key = args[2] if numkeys >= 3 else ""
        request_id = args[numkeys] if len(args) > numkeys else ""
        raw_usage = args[numkeys + 1] if len(args) > numkeys + 1 else ""
        stream_id = args[numkeys + 2] if len(args) > numkeys + 2 else ""

        if "SISMEMBER" in script and request_id and seen_key:
            if request_id in self.sets.get(seen_key, set()):
                return 0
        if "XADD" in script and stream_key and raw_usage:
            self.xadd(stream_key, {"usage": raw_usage})
        if "SADD" in script:
            if request_id and seen_key:
                self.sets.setdefault(seen_key, set()).add(request_id)
            if stream_id and attributed_key:
                self.sets.setdefault(attributed_key, set()).add(stream_id)
        return 1


class FakeRedis(FakeRespRedis):
    """In-memory double for redis-py (long-lived daemons: switch, watchdog, api).
    Extends FakeRespRedis with daemon methods: pipeline, exists, lindex, rpop, ltrim, sadd, sismember, keys, scan_iter."""

    def ping(self):
        return True

    def flushdb(self):
        self.values.clear()
        self.hashes.clear()
        self.lists.clear()
        self.sets.clear()
        self.streams.clear()

    def pipeline(self, transaction=True):
        fault = self._check_fault("pipeline", transaction)
        if fault is not None:
            return fault
        return FakePipeline(self)

    def exists(self, *keys):
        fault = self._check_fault("exists", *keys)
        if fault is not None:
            return fault
        count = 0
        for k in keys:
            if k in self.values or k in self.hashes or k in self.lists or k in self.sets or k in self.streams:
                count += 1
        return count

    def lindex(self, key, index):
        fault = self._check_fault("lindex", key, index)
        if fault is not None:
            return fault
        lst = self.lists.get(key, [])
        if lst and 0 <= index < len(lst):
            return lst[index]
        return None

    def rpop(self, key):
        fault = self._check_fault("rpop", key)
        if fault is not None:
            return fault
        lst = self.lists.get(key, [])
        if lst:
            return lst.pop()
        return None

    def ltrim(self, key, start, stop):
        fault = self._check_fault("ltrim", key, start, stop)
        if fault is not None:
            return fault
        self.trimmed.append((key, start, stop))
        values = self.lists.get(key, [])
        start_idx = max(0, len(values) + start) if start < 0 else start
        stop_idx = len(values) + stop if stop < 0 else stop
        self.lists[key] = values[start_idx : stop_idx + 1]
        return True

    def sadd(self, key, *members):
        fault = self._check_fault("sadd", key, *members)
        if fault is not None:
            return fault
        s = self.sets.setdefault(key, set())
        for m in members:
            s.add(m)
        return len(members)

    def sismember(self, key, member):
        fault = self._check_fault("sismember", key, member)
        if fault is not None:
            return fault
        return member in self.sets.get(key, set())

    def keys(self, pattern="*"):
        fault = self._check_fault("keys", pattern)
        if fault is not None:
            return fault
        all_k = set(self.values.keys()) | set(self.hashes.keys()) | set(self.lists.keys()) | set(self.sets.keys()) | set(self.streams.keys())
        import fnmatch
        return [k for k in all_k if fnmatch.fnmatch(k, pattern)]

    def scan_iter(self, match="*"):
        fault = self._check_fault("scan_iter", match)
        if fault is not None:
            return fault
        return iter(self.keys(match))

    def incr(self, key):
        fault = self._check_fault("incr", key)
        if fault is not None:
            return fault
        val = int(self.values.get(key, 0)) + 1
        self.values[key] = val
        return val

    def lmove(self, source, destination, wherefrom="LEFT", whereto="RIGHT"):
        fault = self._check_fault("lmove", source, destination, wherefrom, whereto)
        if fault is not None:
            return fault
        self.moves.append((source, destination, wherefrom, whereto))
        src_list = self.lists.get(source, [])
        if not src_list:
            return None
        val = src_list.pop(0) if wherefrom == "LEFT" else src_list.pop()
        dst_list = self.lists.setdefault(destination, [])
        if whereto == "RIGHT":
            dst_list.append(val)
        else:
            dst_list.insert(0, val)
        return val


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def fake_resp_redis():
    return FakeRespRedis()


WatchRedis = FakeRedis
UsageRedis = FakeRedis
StatefulRedis = FakeRedis
RetentionRedis = FakeRedis
RecordingRedis = FakeRedis
VerifyRedis = FakeRedis
ActivityRedis = FakeRedis
PresenceRedis = FakeRedis
LogRedis = FakeRedis
MockSimRedis = FakeRedis
StubRedis = FakeRedis
