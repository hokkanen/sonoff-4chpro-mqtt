# Sonoff 4CH Pro R3 MQTT lease controller 0.1.0

Initial release candidate for the Sonoff 4CH Pro R3 with ESP8285 and 1 MB flash,
based on Tasmota 15.6.0. Project version 0.1.0, protocol v1 and upstream firmware
version are separate identifiers. This document does not announce publication.

## Included

- Four independently selected outputs under one board-wide owner lease.
- Fresh device-bound challenge exchanges, owner/token/sequence fencing,
  idempotent duplicates and rejection of terminated-treatment replay.
- A maximum local lease of 900 seconds and an immutable treatment end; valid
  renewal preserves unchanged outputs without cycling.
- Inactive startup and local release on expiry, known disconnect, restart or
  native maintenance. Native ON commands cannot acquire a lease.
- Bounded strict JSON, schemas, synthetic examples, portable tests, focused
  upstream modifications, and offline build/release verification tooling.

## Operating requirements

Use the custom `LEASE` protocol. Native Tasmota status queries are maintenance
operations and end active leases. Use custom `get` for routine monitoring.
Commands are non-retained, and command acceptance is separate from current GPIO
state. The profile uses one fixed broker topic namespace and trusted local
HTTP/MQTT transports; read [security boundaries](SECURITY.md).

No ST-MQ host adapter, automatic heating control or circuit assignments are
included. Device identity, broker permissions, host authority, durable release
obligations and actual wiring must be commissioned separately.

## Validation and limitations

The [validation record](docs/status.md) distinguishes host tests, embedded builds
and earlier unloaded bench observations. The first public-release audit performs
offline tests and source/artifact review only; it does not flash firmware, contact
the device or repeat physical tests. Earlier live observations must not be
relabelled as tests of a rebuilt release image.

GPIO readback is not continuous contact sensing. No connected loads, valve travel,
water flow or delivered heat are qualified. RF paths and unexpected active-lease
Wi-Fi loss remain untested physical scenarios. Timers are not hard real-time
protection against arbitrary firmware stalls, electrical faults or hardware damage.

## Distribution

Keep firmware, matching editable source, dependency source/notices, build metadata
and checksums together as described in [release preparation](docs/releasing.md).
Checksums establish artifact integrity, not a maintainer signature or electrical
certification. Install only after verifying the exact board and safe power/load
conditions. Restoring stock firmware removes the custom lease protections.
