# Future ST-MQ adapter boundary

This repository owns device firmware and its current versioned MQTT protocol.
ST-MQ owns its application adapter, configuration, UI, master/standby authority,
durable physical obligations and eventual circuit assignment. No host adapter is
implemented here; firmware preparation does not enable an ST-MQ feature.

Reuse the behavior of ST-MQ's existing Shelly paths where appropriate: actual
device identity, fresh correlated readback, bounded requests, original observation
clocks and authority checked through asynchronous publication. Reuse its MQTT
publication gate and durable executor rather than adding a parallel control daemon.
Do not invent Shelly RPC identities, component IDs or replies for this device.

## Host obligations

Before publishing ON, durably record the release obligation bound to the actual
device, source/connection, current owner, treatment, mask and immutable planned end.
Command publication, acceptance and current GPIO state are separate outcomes.
Lost, stale, invalid or mismatching feedback remains unknown. Unconfirmed release
blocks a replacement treatment and survives restart, repair, reconfiguration and
paired handover. A replacement device does not inherit old permission.

Only the current authorized master may acquire or renew. A standby, copied state,
retained Online or observed timeout must not create authority or automatic
promotion. Cancel queued requests on role loss or connection change and recheck
authority at the actual MQTT write boundary. Complete owned release while the old
master still controls the device before graceful handover. The firmware cannot
identify the correct application master independently of the host/broker policy.

Expose four separately identified channels and preserve exact state/quality
changes. Bitmasks `1`, `2`, `4`, `8` address them individually; `15` selects all.
A future pooled treatment requires fresh confirmation of all selected outputs;
partial activation or lost feedback must initiate release of the whole owned lease.
GPIO readback is not mechanical contact, valve, flow or delivered-heat evidence.

## Lease and commissioning interface

The expected adapter behavior includes availability/status, a bounded
`lease({owner,until,now})`, `release()`/`finishLease()`, connection/readback ingestion
and durable pending-release handling. Renew every 300 seconds with at most 900
seconds granted and the fixed original treatment end. Manual timed treatments must
not gain time through retries. Use the [causal deadline mapping](../protocol.md#local-lifecycle-and-deadlines)
and custom `get`; native commands terminate the active lease as maintenance.

Reject stale or duplicate activation and preserve terminal treatment fencing.
An idempotent historical acceptance after expiry is not fresh ON. A local timeout
does not erase the host's obligation to obtain current OFF evidence. Separate
heat-pump restoration cannot be performed by a relay timer through a broken link.

Keep automatic control disabled until the adapter exists and actual wiring is
commissioned. Verify the intended function of each output and the safe unpowered
contact path. A thermostat override must release without blocking native thermostat
heating. Firmware tests, device identity and a configuration flag do not prove that
electrical installation. No circuit names or household mappings are shipped here.
