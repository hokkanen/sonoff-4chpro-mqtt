# Sonoff 4CH Pro R3 MQTT lease controller

**0.1.0 is the initial local candidate.** This repository prepares firmware and a
versioned device protocol; it is not a published release or an installed heating
system qualification.

A focused custom build of Tasmota 15.6.0 makes the four Sonoff 4CH Pro R3 outputs
independently addressable through bounded local leases. Native ON commands cannot
energize an output. Expiry, known connection loss, restart and maintenance release
the lease locally. Renewing unchanged outputs does not cycle them.

One board lease selects a bitmap: `1`, `2`, `4` and `8` select relays 1–4; `15`
selects all four. Each lease lasts at most **900 seconds**, bounded by an immutable
treatment end. A host may renew every **300 seconds** with a fresh challenge.
The firmware never assigns an output to a circuit or starts an application
automation.

## MQTT contract

| Purpose | Topic |
| --- | --- |
| Version 1 requests | `cmnd/sonoff4chpro/LEASE` |
| Correlated replies and state | `stat/sonoff4chpro/LEASE` |
| Native availability | `tele/sonoff4chpro/LWT` |

Use custom `get` for monitoring, then `challenge` before `acquire` or `renew`.
Release needs the current token but no challenge. Every request binds the actual
device identity. Connection nonces, short-lived challenges, sequence/treatment
fencing and fixed deadlines prevent stale requests from reviving an ended lease.
Commands and custom replies are non-retained; broker delivery and retained Online
are not fresh output confirmation. See [the full contract](docs/protocol.md).

All native commands, including native status queries, are maintenance operations
that release the active lease before processing. Native web buttons and POWER
commands cannot bypass the gate. Use the custom protocol for ordinary operation.

## Evidence and scope

Replies identify their evidence as `gpio_output_readback`. A GPIO observation is
separate from an accepted request, mechanical contact continuity and connected
equipment behavior. Missing feedback stays unknown. No valve movement, water flow,
electrical load safety or heat delivery is inferred from a relay bit.

Unloaded bench checks and portable tests are recorded in [validation status](docs/status.md).
The initial candidate does not include an ST-MQ host adapter. A future adapter must
retain master/standby fencing and durable release obligations; see
[the integration boundary](docs/integrations/stmq.md).

## Build and operation

- [Supported board and boundaries](docs/compatibility.md)
- [Installation, commissioning and recovery](docs/operations.md)
- [Protocol and JSON schemas](docs/protocol.md), [synthetic examples](examples/README.md)
- [Development and offline checks](docs/development.md)
- [Release preparation](docs/releasing.md), [change log](CHANGELOG.md)

The build tooling verifies pinned upstream source and keeps build/output storage
outside the checkout. It does not flash hardware. Installation credentials,
backups, logs and actual device/network identifiers must also remain outside Git.

Install the pinned [check](requirements-check.txt) and [build](requirements-build.txt)
requirements in an environment outside the checkout. Then run:

```sh
python3 tools/check.py
python3 tools/build.py --work-dir "$SONOFF_WORK_DIR" --output-dir "$SONOFF_OUTPUT_DIR"
```

Set both build variables to suitable external directories first; the output
directory must be new or empty. See [development](docs/development.md) for the
source preparation and verification boundaries.

This is an independent project, not manufacturer-endorsed firmware. License and
upstream attribution are recorded in [LICENSE](LICENSE) and [NOTICE](NOTICE).
