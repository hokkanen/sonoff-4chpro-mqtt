# Working rules

This repository owns the Sonoff 4CH Pro R3 device firmware, its versioned MQTT
lease protocol, build tooling, tests and operating documentation. The ST-MQ host
adapter, application configuration, master/standby authority and durable release
obligations belong in ST-MQ. Do not edit or deploy ST-MQ as part of firmware work.

Read the protocol and safety/operation documentation before changing actuation.
Support one current protocol; reject unknown fields and unsupported versions.
Do not emulate Shelly identities or add compatibility aliases for earlier drafts.

Keep the fixed board and inactive startup behavior. Only a current device-bound
lease may energize outputs. Preserve challenge-anchored deadlines, immutable
treatment ends, owner/token/sequence fencing, terminal replay rejection and local
OFF on expiry, known disconnect, restart or maintenance. Renewal must not cycle
unchanged outputs. No timer or native command may bypass the lease gate.

Command publication, correlated acceptance, GPIO readback, measured contact
continuity and behavior of connected equipment are separate evidence. Preserve
unknown states. A passing host test or successful build does not establish live
hardware behavior or an electrically commissioned installation.

Keep credentials, actual network addresses, hardware identifiers, settings/flash
backups, live MQTT tokens and household logs outside this repository and its Git
history. Ignored files are not a private storage boundary. Use synthetic examples
and explicit staging; inspect the final index and archives before committing.

Use pinned, integrity-checked upstream source and preserve corresponding editable
source with firmware artifacts. Keep the patch focused and reviewable. Run host
tests and a real ESP8285 build for firmware changes; use independent review for
actuation, deadline, parsing and release changes. Report validation limits plainly.

Offline checks must not contact or actuate household devices. Live commissioning
requires its own explicit authorization and unloaded/safe hardware. Preserve a
verified original backup before destructive flash operations. Ask before manual
hardware intervention or a production host reboot. Do not publish or push merely
because local preparation and tests passed.
