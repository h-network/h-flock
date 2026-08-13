import json
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from flock.bus import EnvelopeError, build, emit, is_member, members, parse, prefix, receive, send, vab
from flock.bus.envelope import parse_for_switch
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

    def lpop(self, key):
        values = self.lists.get(key, [])
        return values.pop(0) if values else None

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
            prefix("acme", "hq", resource="all")
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

    def test_bare_and_qualified_local_destinations_have_identical_l2(self):
        bare = build("Message", "alice", "bob", {}, pod="acme", tenant="hq")
        qualified = build(
            "Message", "alice", "acme:hq:bob", {}, pod="acme", tenant="hq"
        )
        self.assertEqual(bare["l2"], qualified["l2"])
        self.assertEqual(qualified["l3"]["destination"], "acme:hq:bob")

    def test_flat_v1_is_not_accepted_on_v2_wire(self):
        with self.assertRaisesRegex(EnvelopeError, "unsupported frame version"):
            parse(json.dumps({"v": 1, "producer": "alice", "recipient": "bob"}))

    def test_switch_parser_does_not_validate_or_read_l3(self):
        frame = build("Message", "alice", "bob", {})
        frame["l3"] = "opaque-to-the-switch"
        self.assertEqual(parse_for_switch(json.dumps(frame))["l2"]["destination"], "bob")
        with self.assertRaisesRegex(EnvelopeError, "l3 must be an object"):
            parse(json.dumps(frame))

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

    def test_empty_roster_waits_instead_of_spinning(self):
        self.r.hashes[self.roster] = {}
        with patch("flock.router.service.time.sleep") as sleep:
            self.assertFalse(Router(self.r, pod="acme", tenant="hq", poll_seconds=5).step())
        sleep.assert_called_once_with(5)

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

    def test_non_local_destination_fails_at_sender_and_is_recorded(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(
            EnvelopeError, "no route to non-local destination"
        ):
            send(
                self.r,
                pod="acme",
                tenant="hq",
                producer="alice",
                recipient="acme:sales:bob",
                payload={},
            )
        self.assertNotIn(prefix("acme", "hq", "alice", "egress"), self.r.lists)
        record = json.loads(output.getvalue())
        self.assertEqual(record["event"], "send_refused")
        self.assertEqual(record["producer"], "alice")
        self.assertEqual(record["recipient"], "acme:sales:bob")

    def test_kicked_receive_returns_immediately_when_ingress_is_empty(self):
        class EmptyIngressRedis(FakeRedis):
            def blpop(self, keys, timeout=0):
                raise AssertionError("kicked receive must not wait in BLPOP")

        receive(
            EmptyIngressRedis(),
            pod="acme",
            tenant="hq",
            agent="bob",
            openers={},
            timeout=60,
            blocking=False,
        )

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
        self.assertEqual(envelope["l2"]["destination"], "sme-2")

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

    def test_router_stamps_forged_producer_from_egress_queue(self):
        envelope = build("Message", "carol", "bob", {"text": "forged"})
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), json.dumps(envelope))

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())

        raw = self.r.lists[prefix("acme", "hq", "bob", "ingress")][0]
        self.assertEqual(json.loads(raw)["l2"]["source"], "alice")
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [record["event"] for record in records],
            ["popped", "producer_stamped", "forwarded"],
        )
        stamped = records[1]
        self.assertEqual(stamped["producer"], "alice")
        self.assertEqual(stamped["stream_id"], envelope["stream_id"])
        self.assertEqual(
            stamped["reason"],
            "claimed producer 'carol' stamped from egress sender 'alice'",
        )

    def test_router_does_not_log_stamp_when_producer_matches_queue(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            producer="alice",
            recipient="bob",
            payload={"text": "honest"},
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())

        events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
        self.assertEqual(events, ["popped", "forwarded"])

    def test_forged_broadcast_is_stamped_and_excludes_queue_sender(self):
        envelope = build("Message", "carol", "all", {"text": "forged broadcast"})
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), json.dumps(envelope))

        self.assertTrue(Router(self.r, pod="acme", tenant="hq").step())

        self.assertNotIn(prefix("acme", "hq", "alice", "ingress"), self.r.lists)
        for agent in ("bob", "carol"):
            raw = self.r.lists[prefix("acme", "hq", agent, "ingress")][0]
            self.assertEqual(json.loads(raw)["l2"]["source"], "alice")

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
            self.assertEqual(json.loads(raw)["l2"]["destination"], "all")
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
