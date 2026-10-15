# Change log

## 0.1.0 — initial local candidate

- Add a focused Tasmota 15.6.0 ESP8285 firmware profile for Sonoff 4CH Pro R3.
- Introduce strict MQTT protocol v1 with independently selected board relay masks,
  fresh challenges, device/owner/token fencing and terminal replay protection.
- Bound local leases to 900 seconds and an immutable treatment end; preserve ON
  across valid renewal without cycling and release on expiry, known disconnect,
  restart or native maintenance.
- Block native activation and separate correlated acceptance, GPIO readback and
  physical contact evidence.
- Add portable/parser tests, pinned build tooling, synthetic schemas/examples and
  operating/integration documentation. ST-MQ host integration remains future work.

This entry records a candidate. Publication and connected-load qualification are
not claimed; see [validation status](docs/status.md).
