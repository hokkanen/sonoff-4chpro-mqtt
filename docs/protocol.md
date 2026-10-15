# MQTT lease protocol v1

The protocol version is the integer `v:1`. Project version 0.1.0 and upstream
Tasmota 15.6.0 identify different contracts. Unknown fields, unsupported versions
and earlier draft aliases are rejected. This document describes the fixed board
profile, not generic stock Tasmota behavior.

## Transport and evidence

Requests use `cmnd/sonoff4chpro/LEASE`; replies and state notifications use
`stat/sonoff4chpro/LEASE`. Native availability uses `tele/sonoff4chpro/LWT`.
The custom command/reply topics and board mapping are fixed in this profile.
Changing native topic/prefix settings is unsupported maintenance, not discovery.

Publish commands without retention. Custom replies and notifications are also
non-retained. Reject delivery packets marked retained, and clear stale retained
control records during commissioning. MQTT 3.1.1 normally forwards a newly
published retained message to existing subscribers with the delivery RETAIN flag
cleared; a device cannot reconstruct the publisher's original retain intent from
that flag. A fresh valid retained publication could therefore execute once while
online. Protocol nonces/freshness prevent its stored replay from granting later
authority. Use a trusted non-retaining publisher and broker controls where
supported; ordinary topic ACLs alone do not necessarily reject the retain flag.
See the [MQTT 3.1.1 retain rules, section 3.3.1.3](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).

Never queue activation/renewal for later replay. Treat a broker PUBACK as broker
delivery only. A reply must match device identity, generation, request ID, operation
and expected owner/treatment/sequence; separately evaluate its current deadlines
and GPIO evidence. Retained Online alone cannot establish command readiness.

## Request schema

All payloads are flat ASCII JSON objects of at most **640 bytes**, including
whitespace. The parser rejects duplicate/unknown keys, escapes, embedded NUL,
non-ASCII text, nested values, trailing content, coercions and non-integer numbers.
The [request schema](../schemas/request.schema.json) describes the JSON data
shape; it cannot detect duplicate keys lost by a conventional JSON decoder or
enforce the encoded byte limit, nonce freshness or current ownership.

| Field | Meaning |
| --- | --- |
| `v` | Integer `1`. |
| `op` | `get`, `challenge`, `acquire`, `renew` or `release`. |
| `id` | Request ID: 1–40 ASCII letters, digits, `_` or `-`. |
| `device` | Exact physical MAC, uppercase colon form. A matching topic is insufficient. |
| `generation` | Current MQTT session's 32 lowercase hexadecimal characters. |
| `owner` | Controller identity: the same bounded alphabet as `id`. |
| `treatment` | Integer 1–4294967295, above the connection's acquired treatment high-water. |
| `seq` | Integer 1–4294967295: acquisition requires 1; renew/release strictly increase it. |
| `challenge` | Current unconsumed 32-character lowercase hexadecimal challenge. |
| `token` | Acquisition's 32-character lowercase hexadecimal lease capability. |
| `mask` | Integer 1–15; bits 0–3 select relays 1–4 independently. |
| `ttl_ms` | Integer 1–900000. |
| `end_ms` | Immutable absolute device monotonic treatment end, at most 9007199254740991. |

| Operation | Exact required fields |
| --- | --- |
| `get`, `challenge` | `v`, `op`, `id`, `device` |
| `acquire` | Common four plus `generation`, `owner`, `treatment`, `seq`, `challenge`, `mask`, `ttl_ms`, `end_ms` |
| `renew` | All acquire fields plus `token` |
| `release` | Common four plus `generation`, `owner`, `treatment`, `seq`, `token` |

No optional mutation keys exist. In particular, release has no mask, challenge,
TTL or end. It closes the entire board lease. Changing a selected bit during a
renewal requires the same fresh challenge/ownership checks as renewing unchanged
bits. Mask zero is release, not a valid renewal. See [synthetic exchanges](../examples/README.md).

## Local lifecycle and deadlines

The device starts OFF. Every MQTT session receives a fresh 128-bit generation and
starts OFF; no prior lease token or challenge survives reconnection. Challenge
issuance grants no output permission. One outstanding challenge is valid while
`now_ms - issued_ms < 2000`; requesting another invalidates the earlier challenge.
Serialize challenge/command exchanges.

An acquisition requires sequence 1 and a treatment counter greater than every
accepted acquisition in the current generation. It cannot replace an active
treatment. The device issues a token and fixes the treatment end. Renew/release
must match that active owner, treatment and token and use a later sequence.
Renewal cannot move the end or revive a terminated treatment.

An accepted acquire or renew consumes its challenge and grants:

```
lease_until_ms = min(challenge_issued_ms + ttl_ms, original end_ms)
```

The result must still be strictly in the future when processed. Receipt delay
never extends the lease. Renewal may happen every 300 seconds, with at most 900
seconds granted at a time. Expiry is local; losing the host cannot leave an
indefinite ON. Firmware timers are scheduling safeguards, not hard realtime
guarantees against every hardware or firmware failure.

Use extended monotonic milliseconds, not Unix time. The driver extends the raw
32-bit clock across rollover; a backward clock or a value beyond the exact JSON
integer horizon fails OFF. Counter/sequence wrap never grants new authority.

For a fixed host monotonic deadline `H_end`, record send and receipt times around
the matching challenge. Conservatively choose:

```
end_ms = issued_ms + floor(H_end - H_receive)
```

Reject a stale exchange or nonpositive remaining time. Mapping from the host send
time instead would add reply delay. Store the original device end and echo it
unchanged on every renewal. This addresses transit delay under nominal millisecond
clock rates; clock drift and scheduling latency still need observed qualification.

## Duplicates, release and failures

Time advances and expiry runs before any request, including duplicate lookup. The
exact last accepted ID and identical semantic fields is idempotent: it returns
`accepted:true, duplicate:true` without changing outputs or deadlines. Reusing that
ID with changed valid fields rejects. Older requests are fenced by generation,
treatment high-water and sequence.

**Acceptance records the request's historical acceptance, not present ON.** A
duplicate reply can report current OFF after expiry. Never turn its cached
acceptance into new actuation or fresh electrical evidence.

Release, expiry, native OFF, known disconnect and restart retire authority and
clear the selected outputs. Native command processing releases the entire lease
before processing any command, even a status query. Use custom `get` for monitoring.
An OFF command remains possible despite native PowerLock. Native ON, toggles,
timers and saved startup state cannot create a lease.

Unreachable network failure becomes known only when the transport detects it;
the current lease deadline bounds an otherwise silent outage. A changed device or
connection never inherits old permission. Host-side durable release obligations
must still wait for fresh confirmed OFF, even if local expiry should have occurred.

## Reply and state schema

Replies and notifications follow [the state schema](../schemas/state.schema.json).
`kind:"reply"` carries the request ID/operation; `kind:"state"` is an unsolicited
transition with empty ID and `op:"state"`. Both contain a current snapshot:

- `device`, `generation`, `connected`, `now_ms`, `board_ok` and build identity.
- `active`, authorized `mask`, observed `gpio_mask`, `gpio_match` and
  `state_evidence:"gpio_output_readback"`.
- `lease_until_ms`, `end_ms`, `owner`, `treatment`, `seq`, `highwater`, `reason`.
- `accepted`, `duplicate` and `code`, separate from current state.

Successful active acquisition replies can include `token`. Challenge replies can
include `challenge`, `issued_ms` and `lifetime_ms:2000`. Broadcast state omits these
temporary capabilities. Do not log them. The driver clears its shared reply buffer
after publication.

`mask` is authority, while `gpio_mask` is output logic readback. A mismatch forces
release and a visible hardware fault. Neither value continuously senses relay
contacts. Contact continuity, connected equipment behavior and command readiness
have separate evidence. The reported sketch MD5 helps identify the running image;
use the release/build SHA-256 manifest for artifact integrity.
