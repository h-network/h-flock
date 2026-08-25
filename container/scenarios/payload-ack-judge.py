#!/usr/bin/env python3
import json, sys
records=[]
ignored=0
scope = sys.argv[3] if len(sys.argv) > 3 else 'payload-'
for line in open(sys.argv[1], errors='replace'):
    try:
        r=json.loads(line)
        if not (str(r.get('source','')).startswith(scope) or str(r.get('destination','')).startswith(scope)):
            ignored += 1; continue
        records.append(r)
    except Exception: continue
generic={r.get('stream_id') for r in records if r.get('event')=='sent'}
ack_ids={r.get('stream_id') for r in records if r.get('event')=='ack_sent'}
sent=generic-ack_ids
opened={r.get('stream_id') for r in records if r.get('event')=='opened'} & sent
verified={r.get('stream_id') for r in records if r.get('event')=='payload_verified'} & sent
ack_sent={r.get('correlation_id') for r in records if r.get('event')=='ack_sent' and r.get('correlation_id')}
ack_opened={r.get('correlation_id') for r in records if r.get('event')=='ack_opened' and r.get('correlation_id')}
malformed={r.get('stream_id') for r in records if r.get('event')=='ack_sent' and not r.get('correlation_id')}
invalid={r.get('stream_id') for r in records if r.get('event')=='payload_invalid'}
if len(sys.argv)>2 and sys.argv[2]=='--ack-count':
 print(len(ack_opened)); raise SystemExit(0)
# ⚠ THE ONLY NON-CIRCULAR CHECK HERE. Every count above is read from the log, so
# a DROPPED RECORD lowers both sides and the books still balance. The harness
# knows how many it submitted without asking the log. 0 means no count was given.
expected=int(sys.argv[2]) if len(sys.argv)>2 and sys.argv[2].isdigit() else 0
print(f'ACK_OPENED_UNIQUE {len(ack_opened)}')
print(f'PAYLOAD_SCOPE ignored_out_of_scope={ignored} sent={len(sent)} opened={len(opened)} verified={len(verified)} ack_sent={len(ack_sent)} ack_opened={len(ack_opened)}')
if expected:
 short=[f'{n}={len(s)}' for n,s in (('sent',sent),('opened',opened),('verified',verified),('ack_sent',ack_sent),('ack_opened',ack_opened)) if len(s)!=expected]
 print(f'PAYLOAD_EXPECTED submitted_by_harness={expected} stages_matching={5-len(short)}/5')
 if short: print(f"PAYLOAD_RESULT rc=6 reason=log_disagrees_with_harness expected={expected} short={','.join(short)}"); raise SystemExit(6)
if malformed: print(f'PAYLOAD_RESULT rc=3 reason=ack_missing_correlation ids={sorted(malformed)}'); raise SystemExit(3)
if ack_sent-sent: print(f'PAYLOAD_RESULT rc=3 reason=ack_for_unsent ids={sorted(ack_sent-sent)}'); raise SystemExit(3)
if ack_sent-ack_opened: print(f'PAYLOAD_RESULT rc=5 reason=ack_leg_unknown ids={sorted(ack_sent-ack_opened)}'); raise SystemExit(5)
if invalid: print(f'PAYLOAD_RESULT rc=4 reason=payload_corrupt ids={sorted(invalid)}'); raise SystemExit(4)
if sent-opened: print(f'PAYLOAD_RESULT rc=1 reason=payload_never_landed ids={sorted(sent-opened)}'); raise SystemExit(1)
if opened-ack_sent: print(f'PAYLOAD_RESULT rc=2 reason=payload_landed_ack_not_sent ids={sorted(opened-ack_sent)}'); raise SystemExit(2)
if sent-verified: print(f'PAYLOAD_RESULT rc=4 reason=payload_not_verified ids={sorted(sent-verified)}'); raise SystemExit(4)
print('PAYLOAD_RESULT rc=0 reason=clean')
