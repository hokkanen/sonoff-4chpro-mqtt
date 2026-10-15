# Synthetic protocol examples

All identifiers, MAC addresses, nonces, tokens, hashes and clocks in this directory
are synthetic. They are not credentials or values to publish to real equipment.
The actual controller must derive current device/generation/challenge/token fields
from a correlated exchange and preserve its original fixed device deadline.

| File | Meaning | Schema |
| --- | --- | --- |
| [get.json](get.json) | Read current state without ending a lease | [request](../schemas/request.schema.json) |
| [challenge.json](challenge.json) | Request a short-lived challenge | [request](../schemas/request.schema.json) |
| [acquire.json](acquire.json) | Select all four relays within one treatment | [request](../schemas/request.schema.json) |
| [renew.json](renew.json) | Renew unchanged mask with a new challenge and unchanged end | [request](../schemas/request.schema.json) |
| [release.json](release.json) | Release the entire board lease without a challenge | [request](../schemas/request.schema.json) |
| [reply.json](reply.json) | Accepted acquisition plus its current GPIO snapshot | [state](../schemas/state.schema.json) |
| [challenge-reply.json](challenge-reply.json) | Challenge and its issue clock while inactive | [state](../schemas/state.schema.json) |
| [duplicate-expired.json](duplicate-expired.json) | Historical acceptance with current OFF after expiry | [state](../schemas/state.schema.json) |
| [state.json](state.json) | Unsolicited inactive snapshot after expiry | [state](../schemas/state.schema.json) |

Wire objects must also satisfy the 640-byte/ASCII/strict-parser rules and current
lease state. JSON Schema alone cannot validate duplicate keys, encoded byte length,
ownership, freshness, terminal replay or GPIO/contact reality. See
[the full protocol](../docs/protocol.md).
