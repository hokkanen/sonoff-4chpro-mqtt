# Development and verification

Read [the working rules](../AGENTS.md), [protocol](protocol.md) and
[operations](operations.md) before changing actuation. Keep one current protocol
and fixed board profile. Update schema, parser, core, driver, examples and tests
together; do not add aliases for obsolete drafts.

The repository stores an overlay and focused patch against pinned upstream
Tasmota. `upstream.lock.json` records the source and build-tool identity;
`project.json` records project version 0.1.0. All upstream/build caches, generated
firmware and private commissioning data belong outside the checkout, including
ignored paths.

The build entry point is `tools/build.py`. Supply external `--work-dir` and
`--output-dir` paths; `--prepare-only` verifies/prepares source without compiling.
Optional `--archive` and `--platformio` select an existing pinned archive/tool.
The tool does not flash, configure a broker or contact devices. Read its `--help`
for the installed command's exact options.

The platform and framework archives in `dependencies.lock.json` are also verified
before use, selected as local PlatformIO inputs and preserved with firmware.
The build applies the separately reviewed platform-only compatibility patch in
the project source, uses the single constrained host environment and selects the
derived platform directory directly. It does not bootstrap an older nested Core.
`--dependency-cache` can select their external cache. `--no-download` requires the
source archives to be present; it does not by itself make PlatformIO's host-tool
installation air-gapped. See [dependency provenance](dependencies.md).

Install [requirements-check.txt](../requirements-check.txt) and
[requirements-build.txt](../requirements-build.txt) in an external Python 3.11+
environment. The checked-in requirements pin the validator and PlatformIO;
do not install a tool environment inside the checkout. `--platformio` can select
that environment's executable explicitly.

`tools/check.py` runs offline host tests and structural/privacy checks. The tests
compile the checked-in core and parser into an external temporary directory. Offline
checks must not use real hardware, network credentials or live MQTT captures.

Core tests use adversarial fake monotonic clocks and verify outcomes independently
of implementation arithmetic. Parser tests cover malformed bounded wire inputs,
including Arduino macro compatibility. A real ESP8285 build remains required for
firmware changes; portable compilation cannot prove embedded compatibility.
An additional host harness includes the actual driver with synthetic SDK/GPIO,
clock and MQTT shims. It checks callback/apply races and response behavior, without
claiming actual SDK scheduling, radio behavior or mechanical contact sensing.
Source review must inspect every ON path, OFF timing, startup, timer races,
notification/readback consistency and MQTT lifecycle hooks.

Keep requests and responses bounded and avoid dynamic allocation in the lease
core/parser. A release timer cannot promise hard realtime behavior under every
blocked firmware or hardware fault. Observe actual timing and preserve its limits
in [validation status](status.md), rather than inventing a conservative timing
allowance or treating a successful command as physical proof.

`tools/check_docs.py` checks local Markdown targets/anchors and current project
metadata. The release/history checks additionally review Git object paths and
metadata; see [the local release procedure](releasing.md).
