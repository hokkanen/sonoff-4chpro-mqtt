# Installation, commissioning and recovery

Keep a verified original full-flash backup and a pre-change settings/flash backup
in private storage outside every checkout. Record hashes and the associated image
version. The build tools prepare artifacts only; they do not authorize flashing,
host reboot, physical wiring changes or connected-load tests.

## Initial installation

1. Identify the exact R3 board, ESP and flash size. Verify pin orientation, polarity,
   a measured stable 3.3 V programming supply and electrical isolation. Disconnect
   mains, normal board power and external loads before serial work. Do not infer
   electrical correctness from a wiring diagram.
2. Follow the official [model-specific serial instructions](https://tasmota.github.io/docs/devices/Sonoff-4CH-Pro/).
   Preserve and verify the original complete flash before modifying it. Initial
   stock serial installation must use an appropriate complete image, not minimal.
   This project's later custom image has its own verified build identity.
3. Build from pinned source and review the binary/source manifest. Flash only with
   suitable settings and the owner's installation authorization. Verify written
   bytes and normal boot. Never reboot a production host without authorization.
4. Configure local 2.4 GHz Wi-Fi and the existing local MQTT broker securely through
   the local administrator interface. Use a stable hostname and a DHCP reservation
   when available. Keep passwords, actual addresses and hardware identity outside
   Git, shell history and diagnostics.
5. Preserve the fixed `sonoff4chpro` topic profile and default native prefixes.
   Do not use native Topic/FullTopic/Prefix changes to configure this build.
   Confirm the custom `get` reply's device, build, `board_ok`, inactive mask and
   matching all-OFF GPIO state. No automatic ON occurs on connection.

Do not connect a normal supply and a serial/programming supply simultaneously.
Before changing physical power or serial connections, stop and confirm the exact
intervention with the owner. A board powered only through its programming rail is
not a completed relay-contact test.

## Unloaded commissioning

Keep all external loads disconnected. Obtain approval before energizing relays.
Record actual contact continuity and sound/indicator observations separately from
MQTT/GPIO readback.

- Test masks `1`, `2`, `4`, `8`, confirming the selected contact switches and the
  other three remain inactive. Confirm COM–NC/COM–NO OFF baselines for each relay.
- Test a short lease and a short planned end without host release. Confirm local
  OFF, terminal replay rejection, unchanged-output renewal without cycling and
  expiry at the maximum lease bound.
- Check wrong device/owner/token, stale generation/sequence, delayed challenge,
  duplicates and retained delivery. Acceptance alone is not an ON observation.
- Terminate the controller, disconnect the broker, interrupt Wi-Fi and restart the
  device. Distinguish immediate known-disconnect release from deadline-bounded
  silent failure. Verify fresh generation after MQTT reconnect and inactive startup.
- Check physical buttons/native commands and cold/warm restart behavior. Native
  commands are maintenance OFF; custom `get` is the ordinary read interface.
- Finish with a fresh all-OFF custom reply and separately observed inactive contacts.

Retained MQTT controls must be removed deliberately from the broker and competing
publishers disabled. MQTT forwarding can hide the original retain flag on a live
delivery; read [the retain-policy limitation](protocol.md#transport-and-evidence).
Restrict command publishers and enforce a non-retaining publisher/broker policy;
ordinary topic ACLs need not provide a retain-flag filter.

## Normal operation and maintenance

Maintain one current owner and use fresh challenges and a fixed treatment end.
Automatic renewals can run every 300 seconds with a 900-second ceiling. Missing
or invalid feedback is unknown; do not optimistically update a display after a
publication. Preserve pending release until fresh OFF is observed.

Every native command, including a status query, terminates the active lease before
processing. Plan local web/console updates as maintenance; use custom `get` for
ongoing monitoring. Native ON remains blocked. Changing administrator or network
settings may interrupt service and must never implicitly reacquire an output.

Before update or recovery, release the lease and independently confirm the safe
installation state. Keep both source and a verified working image available.
Restoring stock Tasmota removes this gate and is not an equivalent control profile.
Never reconnect loads on the assumption that a restored image preserves lease
semantics. Re-run the relevant commissioning checks after any actuation change.

Connecting real equipment requires a separate wiring/function review. For a future
thermostat override, OFF and device power loss must leave the native thermostat
path electrically possible. This repository does not establish that wiring or
authorize assigning any relay to heating.
