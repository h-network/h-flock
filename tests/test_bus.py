from conftest import FakeRedis
import json
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from flock.bus import EnvelopeError, build, emit, encode, is_member, members, parse, prefix, receive, send, port_type, tags_key
from flock.bus.envelope import HEADER_WIDTH, RESERVED_START, parse_for_switch
from flock.switch.service import Switch



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
        self.assertEqual(parse(encode(envelope)), envelope)
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

    def test_flat_v1_is_not_accepted_on_v4_wire(self):
        with self.assertRaises(EnvelopeError):
            parse(json.dumps({"v": 1, "source": "alice", "destination": "bob"}))

    def test_switch_parser_does_not_validate_or_read_l3(self):
        frame = build("Message", "alice", "bob", {})
        raw = encode(frame)
        body = json.loads(raw[HEADER_WIDTH:])
        body["l3"] = "opaque-to-the-switch"
        raw = raw[:HEADER_WIDTH] + json.dumps(body)
        self.assertEqual(parse_for_switch(raw)["l2"]["destination"], "bob")
        with self.assertRaisesRegex(EnvelopeError, "l3 must be an object"):
            parse(raw)

    def test_switch_parser_does_not_decode_body_bytes(self):
        raw = encode(build("Message", "alice", "bob", {})).encode("ascii")
        corrupt = raw[:HEADER_WIDTH] + b"\xffnot-json"
        self.assertEqual(parse_for_switch(corrupt)["l2"]["destination"], "bob")
        with self.assertRaisesRegex(EnvelopeError, "frame is not UTF-8"):
            parse(corrupt)

    def test_parse_rejects_malformed(self):
        with self.assertRaises(EnvelopeError):
            parse("not-json")
        envelope = build("Message", "alice", "bob", {})
        raw = encode(envelope)
        body = json.loads(raw[HEADER_WIDTH:])
        del body["payload"]
        with self.assertRaises(EnvelopeError):
            parse(raw[:HEADER_WIDTH] + json.dumps(body))

    def test_unknown_reserved_bytes_are_ignored(self):
        raw = encode(build("Message", "alice", "bob", {}))
        future = raw[:RESERVED_START] + "x" * (HEADER_WIDTH - RESERVED_START) + raw[HEADER_WIDTH:]
        parsed = parse(future)
        self.assertEqual(parsed["ttl"], 16)
        self.assertEqual(parsed["hops"], 0)

    def test_lifecycle_log_omits_stream_id(self):
        output = io.StringIO()
        with redirect_stdout(output):
            emit("switch", "started", {})
        self.assertNotIn("stream_id", json.loads(output.getvalue()))


class DoorsAndRouterTest(unittest.TestCase):
    def setUp(self):
        self.r = FakeRedis()
        self.roster = prefix("acme", "hq", resource="roster")
        self.r.hashes[self.roster] = {"alice": "tmux", "bob": "tmux", "carol": "tmux"}
        self.popen = patch("flock.switch.service.subprocess.Popen").start()
        self.addCleanup(patch.stopall)

    def test_roster_reads(self):
        self.assertEqual(members(self.r, pod="acme", tenant="hq"), {"alice", "bob", "carol"})
        self.assertTrue(is_member(self.r, pod="acme", tenant="hq", agent="alice"))
        self.assertEqual(port_type(self.r, pod="acme", tenant="hq", agent="alice"), "tmux")
        self.assertIsNone(port_type(self.r, pod="acme", tenant="hq", agent="nobody"))

    def test_empty_roster_waits_instead_of_spinning(self):
        self.r.hashes[self.roster] = {}
        with patch("flock.switch.service.time.sleep") as sleep:
            self.assertFalse(Switch(self.r, pod="acme", tenant="hq", poll_seconds=5).step())
        sleep.assert_called_once_with(5)

    def test_send_route_receive_round_trip(self):
        stream_id = send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={"text": "hello"},
        )
        self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())
        self.popen.assert_called_once_with(["flock.port", "bob"])
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

    def test_broadcast_receive_records_name_each_actual_recipient(self):
        output = io.StringIO()
        opened = {"bob": [], "carol": []}
        with redirect_stdout(output):
            stream_id = send(
                self.r,
                pod="acme",
                tenant="hq",
                source="alice",
                destination="all",
                payload={"text": "hello everyone"},
            )
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())
            for recipient in opened:
                receive(
                    self.r,
                    pod="acme",
                    tenant="hq",
                    agent=recipient,
                    openers={"Message": opened[recipient].append},
                    timeout=1,
                )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        receive_records = [
            record for record in records if record["event"] in {"received", "opened"}
        ]
        self.assertEqual(
            [(record["event"], record["destination"]) for record in receive_records],
            [("received", "bob"), ("opened", "bob"), ("received", "carol"), ("opened", "carol")],
        )
        self.assertEqual({record["stream_id"] for record in receive_records}, {stream_id})
        self.assertTrue(all(items[0]["l2"]["destination"] == "all" for items in opened.values()))

    def test_non_local_destination_fails_at_sender_and_is_recorded(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(
            EnvelopeError, "no route to non-local destination"
        ):
            send(
                self.r,
                pod="acme",
                tenant="hq",
                source="alice",
                destination="acme:sales:bob",
                payload={},
            )
        self.assertNotIn(prefix("acme", "hq", "alice", "egress"), self.r.lists)
        record = json.loads(output.getvalue())
        self.assertEqual(record["event"], "send_refused")
        self.assertEqual(record["source"], "alice")
        self.assertEqual(record["destination"], "acme:sales:bob")

    def test_egress_write_failure_is_logged_without_sent(self):
        output = io.StringIO()
        with (
            patch.object(self.r, "rpush", side_effect=ConnectionError("redis down")),
            redirect_stdout(output),
            self.assertRaisesRegex(ConnectionError, "redis down"),
        ):
            send(
                self.r,
                pod="acme",
                tenant="hq",
                source="alice",
                destination="bob",
                payload={},
            )
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([record["event"] for record in records], ["send_unknown"])
        self.assertEqual(records[0]["reason"], "egress write outcome UNKNOWN after redis down")
        self.assertNotEqual(records[0]["stream_id"], "unknown")

    def test_send_unknown_log_failure_does_not_replace_the_redis_exception(self):
        with (
            patch.object(self.r, "rpush", side_effect=ConnectionError("redis down")),
            patch("flock.bus.doors.emit", side_effect=OSError("stdout closed")),
            self.assertRaisesRegex(ConnectionError, "redis down"),
        ):
            send(
                self.r,
                pod="acme",
                tenant="hq",
                source="alice",
                destination="bob",
                payload={},
            )

    def test_encoding_failure_is_provably_pre_write_not_send_unknown(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(TypeError):
            send(
                self.r,
                pod="acme",
                tenant="hq",
                source="alice",
                destination="bob",
                payload={"not_json": object()},
            )

        self.assertNotIn(prefix("acme", "hq", "alice", "egress"), self.r.lists)
        self.assertEqual(output.getvalue(), "")

    def test_sent_log_failure_cannot_turn_committed_send_into_failure(self):
        with patch("flock.bus.doors.emit", side_effect=OSError("stdout closed")):
            stream_id = send(
                self.r,
                pod="acme",
                tenant="hq",
                source="alice",
                destination="bob",
                payload={},
            )

        self.assertTrue(stream_id)
        egress = self.r.lists[prefix("acme", "hq", "alice", "egress")]
        self.assertEqual(len(egress), 1)

    def test_ingress_write_failure_is_logged_without_forward_or_kick(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={},
        )
        output = io.StringIO()
        with (
            patch.object(self.r, "eval", side_effect=ConnectionError("redis down")),
            redirect_stdout(output),
            self.assertRaisesRegex(ConnectionError, "redis down"),
        ):
            Switch(self.r, pod="acme", tenant="hq").step()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [record["event"] for record in records],
            ["popped", "forward_unknown"],
        )
        self.assertEqual(
            records[-1]["reason"], "ingress write outcome UNKNOWN after redis down"
        )
        self.popen.assert_not_called()

    def test_policy_denial_refuses_before_assembly_and_emits_record(self):
        self.r.hashes[tags_key("acme", "hq", "alice")] = {
            "export": json.dumps(["engineering"])
        }
        self.r.hashes[tags_key("acme", "hq", "bob")] = {
            "import": json.dumps(["finance"])
        }
        output = io.StringIO()
        with patch("flock.bus.doors.build") as assemble, redirect_stdout(output):
            with self.assertRaisesRegex(EnvelopeError, "policy denied"):
                send(
                    self.r,
                    pod="acme",
                    tenant="hq",
                    source="alice",
                    destination="bob",
                    payload={},
                )
        assemble.assert_not_called()
        self.assertNotIn(prefix("acme", "hq", "alice", "egress"), self.r.lists)
        record = json.loads(output.getvalue())
        self.assertEqual(record["event"], "send_refused")
        self.assertEqual(record["source"], "alice")
        self.assertEqual(record["destination"], "bob")
        self.assertIn("no shared export/import tag", record["reason"])

    def test_policy_permits_shared_tag_and_absent_policy(self):
        # No policy is the switchport default: permit.
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={},
        )
        self.r.lists.clear()
        self.r.hashes[tags_key("acme", "hq", "alice")] = {
            "export": json.dumps(["engineering", "reviewers"])
        }
        self.r.hashes[tags_key("acme", "hq", "bob")] = {
            "import": json.dumps(["reviewers", "operations"])
        }
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={},
        )
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "alice", "egress")]), 1)

    def test_switch_forwards_on_l2_without_reading_l3_destination(self):
        frame = build(
            "Message", "alice", "bob", {}, pod="acme", tenant="hq"
        )
        # If the local switch consults L3, this contradictory address sends the
        # frame to carol. L3 is deliberately opaque at this layer.
        frame["l3"]["destination"] = "acme:hq:carol"
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), encode(frame))

        self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        self.assertIn(prefix("acme", "hq", "bob", "ingress"), self.r.lists)
        self.assertNotIn(prefix("acme", "hq", "carol", "ingress"), self.r.lists)

    def test_bare_and_qualified_local_sends_have_same_l2_and_five_records(self):
        observed = []
        for destination in ("bob", "acme:hq:bob"):
            r = FakeRedis()
            r.hashes[self.roster] = {"alice": "tmux", "bob": "tmux"}
            opened = []
            output = io.StringIO()
            with redirect_stdout(output):
                send(
                    r,
                    pod="acme",
                    tenant="hq",
                    source="alice",
                    destination=destination,
                    payload={"text": "same local delivery"},
                )
                self.assertTrue(Switch(r, pod="acme", tenant="hq").step())
                receive(
                    r,
                    pod="acme",
                    tenant="hq",
                    agent="bob",
                    openers={"Message": opened.append},
                    timeout=1,
                )
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(
                [record["event"] for record in records],
                ["sent", "popped", "forwarded", "kick_started", "received", "opened"],
            )
            self.assertEqual(len({record["stream_id"] for record in records}), 1)
            observed.append(opened[0]["l2"])

        self.assertEqual(observed[0], observed[1])

    def test_kicked_receive_returns_immediately_when_ingress_is_empty(self):

        receive(
            FakeRedis(fails_on={"blpop": AssertionError("kicked receive must not wait in BLPOP")}),
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
            source="alice",
            destination="sme-2",
            payload={"text": "review"},
        )
        self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())
        self.popen.assert_called_once_with(["flock.port", "sme-2"])
        raw = self.r.lists[prefix("acme", "hq", "sme-2", "ingress")][0]
        envelope = parse(raw)
        self.assertEqual(envelope["stream_id"], stream_id)
        self.assertEqual(envelope["l2"]["destination"], "sme-2")

    def test_unknown_recipient_dead_letters_under_sender(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="nobody",
            payload={},
        )
        Switch(self.r, pod="acme", tenant="hq").step()
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "alice", "dead")]), 1)
        self.popen.assert_not_called()

    def test_full_ingress_dead_letters_without_kick(self):
        ingress = prefix("acme", "hq", "bob", "ingress")
        self.r.rpush(ingress, "already queued 1")
        self.r.rpush(ingress, "already queued 2")
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={"text": "over the bound"},
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(
                Switch(self.r, pod="acme", tenant="hq", ingress_max=2).step()
            )

        self.assertEqual(len(self.r.lists[ingress]), 2)
        self.assertEqual(
            len(self.r.lists[prefix("acme", "hq", "alice", "dead")]), 1
        )
        self.popen.assert_not_called()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([record["event"] for record in records], ["popped", "dead_lettered"])
        self.assertEqual(records[-1]["destination"], "bob")
        self.assertIn("depth 2 has reached INGRESS_MAX 2", records[-1]["reason"])

    def test_ingress_at_bound_after_push_still_forwards_and_kicks(self):
        ingress = prefix("acme", "hq", "bob", "ingress")
        self.r.rpush(ingress, "already queued")
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={"text": "fits exactly"},
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(
                Switch(self.r, pod="acme", tenant="hq", ingress_max=2).step()
            )

        self.assertEqual(len(self.r.lists[ingress]), 2)
        self.popen.assert_called_once_with(["flock.port", "bob"])
        events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
        self.assertEqual(events, ["popped", "forwarded", "kick_started"])

    def test_popped_is_recorded_before_frame_validation(self):
        frame = build("Message", "alice", "bob", {"text": "visible pop"})
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), encode(frame))
        output = io.StringIO()

        def reject_after_observing(_raw):
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([record["event"] for record in records], ["popped"])
            self.assertEqual(records[0]["stream_id"], frame["stream_id"])
            raise EnvelopeError("negative control: validation stopped")

        with redirect_stdout(output), patch(
            "flock.switch.service.parse_for_switch", side_effect=reject_after_observing
        ):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
        self.assertEqual(events, ["popped", "dead_lettered"])

    def test_switch_stamps_forged_producer_from_egress_queue(self):
        envelope = build("Message", "carol", "bob", {"text": "forged"})
        original = encode(envelope)
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), original)

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        raw = self.r.lists[prefix("acme", "hq", "bob", "ingress")][0]
        self.assertEqual(parse(raw)["l2"]["source"], "alice")
        self.assertEqual(raw[HEADER_WIDTH:], original[HEADER_WIDTH:])
        self.assertEqual(parse(raw)["ttl"], 15)
        self.assertEqual(parse(raw)["hops"], 1)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [record["event"] for record in records],
            ["popped", "source_stamped", "forwarded", "kick_started"],
        )
        stamped = records[1]
        self.assertEqual(stamped["source"], "alice")
        self.assertEqual(stamped["stream_id"], envelope["stream_id"])
        self.assertEqual(
            stamped["reason"],
            "claimed source 'carol' stamped from egress sender 'alice'",
        )

    def test_bad_header_dead_letters_at_switch(self):
        raw = encode(build("Message", "alice", "bob", {}))
        malformed = raw[:65] + "Upper".ljust(63) + raw[128:]
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), malformed)
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([record["event"] for record in events], ["popped", "dead_lettered"])
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "alice", "dead")]), 1)
        self.popen.assert_not_called()

    def test_bad_body_forwards_then_dead_letters_at_port_with_join_key(self):
        frame = build("Message", "alice", "bob", {})
        raw = encode(frame)[:HEADER_WIDTH] + "{not-json"
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), raw)
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())
            receive(
                self.r,
                pod="acme",
                tenant="hq",
                agent="bob",
                openers={},
                timeout=0,
                blocking=False,
            )

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [record["event"] for record in records],
            ["popped", "forwarded", "kick_started", "dead_lettered"],
        )
        dead = records[-1]
        self.assertEqual(dead["module"], "port")
        self.assertEqual(dead["stream_id"], frame["stream_id"])
        self.assertEqual(dead["destination"], "bob")

    def test_ttl_one_dead_letters_without_kick(self):
        frame = build("Message", "alice", "bob", {})
        frame["ttl"] = 1
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), encode(frame))
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([record["event"] for record in records], ["popped", "dead_lettered"])
        self.assertEqual(records[-1]["reason"], "ttl expired at forward")
        dead = self.r.lists[prefix("acme", "hq", "alice", "dead")][0]
        self.assertEqual(parse(dead)["ttl"], 0)
        self.assertEqual(parse(dead)["hops"], 1)
        self.popen.assert_not_called()

    def test_switch_does_not_log_stamp_when_producer_matches_queue(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={"text": "honest"},
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
        self.assertEqual(events, ["popped", "forwarded", "kick_started"])

    def test_forged_broadcast_is_stamped_and_excludes_queue_sender(self):
        envelope = build("Message", "carol", "all", {"text": "forged broadcast"})
        self.r.rpush(prefix("acme", "hq", "alice", "egress"), encode(envelope))

        self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        self.assertNotIn(prefix("acme", "hq", "alice", "ingress"), self.r.lists)
        for agent in ("bob", "carol"):
            raw = self.r.lists[prefix("acme", "hq", agent, "ingress")][0]
            self.assertEqual(parse(raw)["l2"]["source"], "alice")

    def test_unknown_kind_dead_letters_under_receiver(self):
        envelope = build("Mystery", "alice", "bob", {})
        self.r.rpush(prefix("acme", "hq", "bob", "ingress"), encode(envelope))
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
            source="alice",
            destination="api",
            payload={},
        )
        Switch(self.r, pod="acme", tenant="hq").step()
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "api", "ingress")]), 1)
        self.popen.assert_called_once_with(["flock.port", "api"])

    def test_kick_spawn_failure_is_logged_and_does_not_lose_ingress(self):
        self.popen.side_effect = FileNotFoundError("flock.port not found")
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={},
        )
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        error = next(record for record in records if record["event"] == "kick_unknown")
        self.assertEqual(error["destination"], "bob")
        self.assertNotEqual(error["stream_id"], "unknown")
        self.assertEqual(
            error["reason"], "port kick outcome UNKNOWN after flock.port not found"
        )
        self.assertNotIn("kick_started", [record["event"] for record in records])
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "bob", "ingress")]), 1)

    def test_broadcast_fans_out_to_roster_except_sender(self):
        self.r.hashes[self.roster]["api"] = "api"
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="all",
            payload={"text": "hello room"},
        )
        Switch(self.r, pod="acme", tenant="hq").step()
        self.assertNotIn(prefix("acme", "hq", "alice", "ingress"), self.r.lists)
        for agent in ("api", "bob", "carol"):
            raw = self.r.lists[prefix("acme", "hq", agent, "ingress")][0]
            self.assertEqual(parse(raw)["l2"]["destination"], "all")
        self.assertEqual(
            sorted(call.args[0][1] for call in self.popen.call_args_list),
            ["api", "bob", "carol"],
        )

    def test_broadcast_ingress_write_exception_is_unknown(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="all",
            payload={"text": "ambiguous fanout"},
        )
        self.r.fails_on["eval"] = ConnectionError("reply lost after broadcast writes")

        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(
            ConnectionError, "reply lost after broadcast writes"
        ):
            Switch(self.r, pod="acme", tenant="hq").step()

        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([record["event"] for record in records], ["popped", "forward_unknown"])
        self.assertEqual(
            records[-1]["reason"],
            "broadcast ingress write outcome UNKNOWN after reply lost after broadcast writes",
        )
        self.assertNotIn("forwarded", [record["event"] for record in records])
        self.popen.assert_not_called()

    def test_logging_failures_after_pop_and_admission_do_not_stop_forwarding(self):
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="bob",
            payload={"text": "still forward"},
        )
        with (
            patch("flock.switch.service.log_record", side_effect=OSError("stdout closed")),
            patch("flock.switch.service.emit", side_effect=OSError("stdout closed")),
        ):
            self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())

        ingress = self.r.lists[prefix("acme", "hq", "bob", "ingress")]
        self.assertEqual(len(ingress), 1)
        self.assertEqual(
            self.r.lists[prefix("acme", "hq", "alice", "egress")], []
        )
        self.popen.assert_called_once_with(["flock.port", "bob"])

    def test_broadcast_is_all_or_none_when_one_recipient_is_full(self):
        bob_ingress = prefix("acme", "hq", "bob", "ingress")
        self.r.rpush(bob_ingress, "bob is full")
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="all",
            payload={"text": "bounded fanout"},
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(
                Switch(self.r, pod="acme", tenant="hq", ingress_max=1).step()
            )

        self.assertEqual(self.r.lists[bob_ingress], ["bob is full"])
        self.assertNotIn(prefix("acme", "hq", "carol", "ingress"), self.r.lists)
        self.popen.assert_not_called()
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        rejected = next(record for record in records if record["event"] == "dead_lettered")
        self.assertEqual(rejected["destination"], "all")
        self.assertNotIn("forwarded", [record["event"] for record in records])

    def test_atomic_admission_has_no_rpush_rpop_interleaving_seam(self):
        ingress = prefix("acme", "hq", "bob", "ingress")
        self.r.rpush(ingress, "older legitimate envelope")
        send(
            self.r, pod="acme", tenant="hq", source="alice", destination="bob",
            payload={"text": "must be refused"},
        )

        with patch.object(self.r, "rpop", side_effect=AssertionError("rollback used")):
            Switch(self.r, pod="acme", tenant="hq", ingress_max=1).step()

        self.assertEqual(self.r.lists[ingress], ["older legitimate envelope"])
        self.assertEqual(len(self.r.lists[prefix("acme", "hq", "alice", "dead")]), 1)

    def test_broadcast_to_one_agent_is_successful_noop(self):
        self.r.hashes[self.roster] = {"alice": "tmux"}
        send(
            self.r,
            pod="acme",
            tenant="hq",
            source="alice",
            destination="all",
            payload={},
        )
        self.assertTrue(Switch(self.r, pod="acme", tenant="hq").step())
        self.assertNotIn(prefix("acme", "hq", "alice", "dead"), self.r.lists)
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()


def test_all_digit_agent_names_are_rejected():
    """tmux resolves `session:2` as window INDEX 2, not the window named "2".

    Measured on tmux 3.5a with windows [1:first, 2:second, 3:"2"]: both `s:2`
    and the exact-name form `s:=2` resolve to `second`. An agent named "2" would
    therefore have its messages pasted into whichever agent sits at index 2 —
    the wrong destination, with an honest `opened` record and nothing to show for
    it. Unaddressable, so it is not a valid name.
    """
    import pytest

    from flock.bus import prefix

    for name in ("sme-2", "a1", "architect", "x"):
        assert prefix("acme", "hq", agent=name, resource="ingress").endswith(f"agent:{name}:ingress")

    for name in ("2", "12", "007"):
        with pytest.raises(KeyError):
            prefix("acme", "hq", agent=name, resource="ingress")


def test_a_stream_id_the_caller_passes_is_never_silently_dropped(capsys):
    """A record keeps an id it was given, whether or not its event is allowlisted.

    ⚠ `_ENVELOPE_EVENTS` gates the DEFAULT (`unknown`), not the field. It used to
    gate the field, so any event outside the list lost its identity with no error
    — a test adapter's ten records collapsed into one `None` and the run read as
    a delivery failure. Analysis skips records with no id, so the loss is silent
    at both ends. Each case below is one of the three behaviours that must hold.
    """
    from flock.bus.logging import log_record

    log_record("t", "opened", stream_id="s1")            # allowlisted, id given
    log_record("t", "opened")                            # allowlisted, no id
    log_record("t", "payload_verified", stream_id="s2")  # not listed, id given
    log_record("t", "started", reason="boot")            # not listed, no id

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    by_event = {(r["event"], r.get("stream_id")) for r in records}

    assert ("opened", "s1") in by_event
    assert ("opened", "unknown") in by_event, "an allowlisted event always carries the field"
    assert ("payload_verified", "s2") in by_event, "an id the caller passed must survive"
    assert ("started", None) in by_event, "no id is invented for an event that has none"


class UnrepliedTrackingTest(unittest.TestCase):
    """`send()` bookkeeping for LLD-watchdog §2d: does a tmux agent owe a client a reply?"""

    def setUp(self):
        self.r = FakeRedis()
        self.roster = prefix("acme", "hq", resource="roster")
        self.r.hashes[self.roster] = {"alice": "tmux", "bob": "tmux", "telegram": "api"}
        self.key = prefix("acme", "hq", "alice", "unreplied")

    def test_client_message_opens_a_count_for_the_destination_agent(self):
        send(self.r, pod="acme", tenant="hq", source="telegram", destination="alice", payload={"text": "hi"})
        record = json.loads(self.r.hashes[self.key]["telegram"])
        self.assertEqual(record["count"], 1)
        self.assertIn("since", record)

    def test_a_second_client_message_before_any_reply_accumulates_and_keeps_the_earliest_since(self):
        send(self.r, pod="acme", tenant="hq", source="telegram", destination="alice", payload={"text": "one"})
        first_since = json.loads(self.r.hashes[self.key]["telegram"])["since"]
        send(self.r, pod="acme", tenant="hq", source="telegram", destination="alice", payload={"text": "two"})
        record = json.loads(self.r.hashes[self.key]["telegram"])
        self.assertEqual(record["count"], 2)
        self.assertEqual(record["since"], first_since)

    def test_the_agents_own_reply_to_the_same_client_clears_the_count(self):
        send(self.r, pod="acme", tenant="hq", source="telegram", destination="alice", payload={"text": "hi"})
        send(self.r, pod="acme", tenant="hq", source="alice", destination="telegram", payload={"text": "reply"})
        self.assertNotIn("telegram", self.r.hashes.get(self.key, {}))

    def test_peer_to_peer_tmux_traffic_never_opens_a_count(self):
        send(self.r, pod="acme", tenant="hq", source="alice", destination="bob", payload={"text": "hi"})
        self.assertNotIn(self.key, self.r.hashes)

    def test_a_structured_kind_from_a_client_does_not_open_a_count(self):
        send(
            self.r, pod="acme", tenant="hq", source="telegram", destination="alice",
            kind="Command", payload={"op": "noop"},
        )
        self.assertNotIn(self.key, self.r.hashes)

    def test_a_bookkeeping_fault_is_logged_but_never_fails_the_send(self):
        """The message is already durably enqueued by the time this runs (LLD-bus-and-switch §1)."""
        output = io.StringIO()
        with patch.object(self.r, "hset", side_effect=ConnectionError("redis down")), redirect_stdout(output):
            stream_id = send(
                self.r, pod="acme", tenant="hq", source="telegram", destination="alice", payload={"text": "hi"}
            )
        self.assertTrue(stream_id)
        egress = self.r.lists[prefix("acme", "hq", "telegram", "egress")]
        self.assertEqual(len(egress), 1)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["event"] for r in records], ["sent", "unreplied_tracking_failed"])
        self.assertIn("redis down", records[1]["reason"])

    def test_a_bookkeeping_fault_remains_swallowed_when_its_log_also_fails(self):
        with (
            patch.object(self.r, "hset", side_effect=ConnectionError("redis down")),
            patch("flock.bus.doors.emit", side_effect=OSError("stdout closed")),
        ):
            stream_id = send(
                self.r,
                pod="acme",
                tenant="hq",
                source="telegram",
                destination="alice",
                payload={"text": "hi"},
            )

        self.assertTrue(stream_id)
        egress = self.r.lists[prefix("acme", "hq", "telegram", "egress")]
        self.assertEqual(len(egress), 1)
