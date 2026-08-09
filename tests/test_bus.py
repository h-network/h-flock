import json
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from flock.bus import EnvelopeError, build, emit, is_member, members, parse, prefix, receive, send, vab
from flock.router.service import Router


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.hashes = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def blpop(self, keys, timeout=0):
        if isinstance(keys, str):
            keys = [keys]
        for key in keys:
            values = self.lists.get(key, [])
            if values:
                return key, values.pop(0)
        return None

    def hkeys(self, key):
        return self.hashes.get(key, {}).keys()

    def hexists(self, key, field):
        return field in self.hashes.get(key, {})

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, r):
        self.r = r
        self.commands = []

    def rpush(self, key, value):
        self.commands.append((key, value))
        return self

    def execute(self):
        for key, value in self.commands:
            self.r.rpush(key, value)
        return [1] * len(self.commands)


class KeysTest(unittest.TestCase):
    def test_scoped_shapes_and_dotted_resources(self):
        self.assertEqual(prefix("acme", "hq"), "pod:acme:tenant:hq")
        self.assertEqual(
            prefix("acme", "hq", "alice", "tasks.todo"),
            "pod:acme:tenant:hq:agent:alice:tasks.todo",
        )

    def test_hyphenated_agent_name_is_preserved_in_key(self):
        self.assertEqual(
            prefix("acme", "hq", "sme-2", "tasks.todo"),
            "pod:acme:tenant:hq:agent:sme-2:tasks.todo",
        )

    def test_rejects_invalid_and_reserved_segments(self):
        for value in ("", "UPPER", "has_underscore", "pod", "a" * 64):
            with self.subTest(value=value), self.assertRaises(KeyError):
                prefix(value, "hq")
        with self.assertRaises(KeyError):
            prefix("acme", "hq", agent="all")
        with self.assertRaises(KeyError):
            prefix("acme", "hq", resource="tasks..todo")


class EnvelopeTest(unittest.TestCase):
    def test_build_and_parse(self):
        envelope = build("Message", "alice", "bob", {"text": "private"})
        self.assertEqual(parse(json.dumps(envelope)), envelope)
        self.assertRegex(envelope["stream_id"], "^[0-9a-f]+$")
        self.assertEqual(len(envelope["correlation_id"]), 32)

    def test_propagates_correlation_id(self):
        cid = "a" * 32
        self.assertEqual(build("Reply", "bob", "alice", {}, cid)["correlation_id"], cid)

    def test_parse_rejects_malformed(self):
        with self.assertRaises(EnvelopeError):
            parse("not-json")
        envelope = build("Message", "alice", "bob", {})
        del envelope["payload"]
        with self.assertRaises(EnvelopeError):
            parse(json.dumps(envelope))

    def test_lifecycle_log_omits_stream_id(self):
        output = io.StringIO()
        with redirect_stdout(output):
            emit("router", "started", {})
        self.assertNotIn("stream_id", json.loads(output.getvalue()))


class DoorsAndRouterTest(unittest.TestCase):
    def setUp(self):
        self.r = FakeRedis()
        self.roster = prefix("acme", "hq", resource="roster")
        self.r.hashes[self.roster] = {"alice": "tmux", "bob": "tmux", "carol": "tmux"}
        self.popen = patch("flock.router.service.subprocess.Popen").start()
        self.addCleanup(patch.stopall)

    def test_roster_reads(self):
        self.assertEqual(members(self.r, pod="acme", tenant="hq"), {"alice", "bob", "carol"})
        self.assertTrue(is_member(self.r, pod="acme", tenant="hq", agent="alice"))
        self.assertEqual(vab(self.r, pod="acme", tenant="hq", agent="alice"), "tmux")
        self.assertIsNone(vab(self.r, pod="acme", tenant="hq", agent="nobody"))

    def test_send_route_receive_round_trip(self):
        stream_id = send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="bob",
            payload={"text": "hello"},
        )
        self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())
        self.popen.assert_called_once_with(["flock.adapter", "bob"])
        opened = []
        receive(
            self.r,
            pod="acme",
            tenant="hq",
            agent="bob",
            openers={"Message": opened.append},
            timeout=1,
        )
        self.assertEqual(opened[0]["stream_id"], stream_id)

    def test_hyphenated_agent_routes_without_name_rewriting(self):
        self.r.hashes[self.roster]["sme-2"] = "tmux"
        stream_id = send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="sme-2",
            payload={"text": "review"},
        )
        self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())
        self.popen.assert_called_once_with(["flock.adapter", "sme-2"])
        raw = self.r.lists[prefix("acme", "hq", "sme-2", "ingress")][0]
        envelope = json.loads(raw)
        self.assertEqual(envelope["stream_id"], stream_id)
        self.assertEqual(envelope["recipient"], "sme-2")

    def test_unknown_recipient_dead_letters_under_sender(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="nobody",
            payload={},
        )
        Router(self.r, pod="acme", tenant="hq").step()
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "alice", "dead")]), 1)
        self.popen.assert_not_called()

    def test_unknown_kind_dead_letters_under_receiver(self):
        envelope = build("Mystery", "alice", "bob", {})
        self.r.rpush(prefix("acme", "hq", "bob", "ingress"), json.dumps(envelope))
        receive(
            self.r,
            pod="acme",
            tenant="hq",
            agent="bob",
            openers={},
            timeout=1,
        )
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "bob", "dead")]), 1)

    def test_api_is_fixed_address(self):
        self.r.hashes[self.roster]["api"] = "api"
        send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="api",
            payload={},
        )
        Router(self.r, pod="acme", tenant="hq").step()
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "api", "ingress")]), 1)
        self.popen.assert_called_once_with(["flock.adapter", "api"])

    def test_kick_spawn_failure_is_logged_and_does_not_lose_ingress(self):
        self.popen.side_effect = FileNotFoundError("flock.adapter not found")
        send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="bob",
            payload={},
        )
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        error = next(record for record in records if record["event"] == "error")
        self.assertEqual(error["recipient"], "bob")
        self.assertNotIn("stream_id", error)
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "bob", "ingress")]), 1)

    def test_broadcast_fans_out_to_roster_except_sender(self):
        self.r.hashes[self.roster]["api"] = "api"
        send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="all",
            payload={"text": "hello room"},
        )
        Router(self.r, pod="acme", tenant="hq").step()
        self.assertNotIn(prefix("acme", "hq", "alice", "ingress"), self.r.lists)
        for agent in ("api", "bob", "carol"):
            raw = self.r.lists[prefix("acme", "hq", agent, "ingress")][0]
            self.assertEqual(json.loads(raw)["recipient"], "all")
        self.assertEqual(
            sorted(call.args[0][1] for call in self.popen.call_args_list),
            ["api", "bob", "carol"],
        )

    def test_broadcast_to_one_agent_is_successful_noop(self):
        self.r.hashes[self.roster] = {"alice": "tmux"}
        send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="all",
            payload={},
        )
        self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())
        self.assertNotIn(prefix("acme", "hq", "alice", "dead"), self.r.lists)
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()


def test_all_digit_agent_names_are_rejected():
    """tmux resolves `session:2` as window INDEX 2, not the window named "2".

    Measured on tmux 3.5a with windows [1:first, 2:second, 3:"2"]: both `s:2`
    and the exact-name form `s:=2` resolve to `second`. An agent named "2" would
    therefore have its messages pasted into whichever agent sits at index 2 —
    the wrong recipient, with an honest `opened` record and nothing to show for
    it. Unaddressable, so it is not a valid name.
    """
    import pytest

    from flock.bus import prefix

    for name in ("sme-2", "a1", "architect", "x"):
        assert prefix("acme", "hq", agent=name, resource="ingress").endswith(f"agent:{name}:ingress")

    for name in ("2", "12", "007"):
        with pytest.raises(KeyError):
            prefix("acme", "hq", agent=name, resource="ingress")
