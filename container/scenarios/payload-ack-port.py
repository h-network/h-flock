#!/usr/bin/env python3
"""Application adapter for BUILD-120: verify payloads and acknowledge them."""
import argparse, hashlib, os, sys, time
sys.path.insert(0, "/app/src")
os.environ["FLOCK_WRITER"] = "payload-port"
import redis
from flock.bus import parse, prefix
from flock.bus.doors import _emit_for_recipient, send
from flock.bus.logging import log_record

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--pod", required=True); ap.add_argument("--tenant", required=True); ap.add_argument("--count", type=int, required=True); ap.add_argument("--prefix", default="payload-"); ap.add_argument("--idle-exit", type=float, default=30); args = ap.parse_args()
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    keys = [prefix(args.pod, args.tenant, f"{args.prefix}{i}", "ingress") for i in range(1, args.count + 1)]
    last = time.time(); handled = 0
    while True:
        item = r.blpop(keys, timeout=2)
        if item is None:
            if time.time() - last > args.idle_exit: break
            continue
        last = time.time(); key, raw = item; agent = key.decode().split(":")[-2] if isinstance(key, bytes) else key.split(":")[-2]
        try: envelope = parse(raw)
        except Exception as exc:
            _emit_for_recipient("payload-port", "dead_lettered", {}, agent, str(exc)); continue
        _emit_for_recipient("payload-port", "received", envelope, agent)
        _emit_for_recipient("payload-port", "opened", envelope, agent)
        payload = envelope.get("payload", {})
        if envelope.get("kind") == "Message":
            marker = payload.get("marker"); checksum = payload.get("checksum")
            expected = hashlib.sha256(marker.encode()).hexdigest() if isinstance(marker, str) else ""
            if checksum != expected:
                _emit_for_recipient("payload-port", "payload_invalid", envelope, agent, "marker checksum mismatch")
                continue
            _emit_for_recipient("payload-port", "payload_verified", envelope, agent)
            ack_id = send(r, pod=args.pod, tenant=args.tenant, source=agent, destination=envelope["l2"]["source"], kind="Ack", correlation_id=envelope["stream_id"], payload={"ack_for": envelope["stream_id"], "marker": marker, "checksum": checksum})
            log_record("payload-port", "ack_sent", stream_id=ack_id, correlation_id=envelope["stream_id"], source=agent, destination=envelope["l2"]["source"])
            
        elif envelope.get("kind") == "Ack":
            _emit_for_recipient("payload-port", "ack_verified", envelope, agent)
            _emit_for_recipient("payload-port", "ack_opened", envelope, agent)
        handled += 1
    print(f"payload-port: handled {handled}", flush=True)
if __name__ == "__main__": raise SystemExit(main())
