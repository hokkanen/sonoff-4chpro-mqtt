# Validation status

**Project 0.1.0 is an initial local candidate, not a published release.** This
record separates portable tests, the built firmware and unloaded board observations.
It contains no installation addresses, hardware identifiers or private captures.

## Portable verification

The bounded C++11 lease core passed **34,547 assertions** under ASan/UBSan and an
optimized build without exceptions/RTTI. Cases include every nonzero relay mask,
challenge freshness and transit delay, immutable end, non-cycling renewal,
duplicates after expiry, terminal replay, owner/token/sequence fencing, reconnect,
clock reversal, extended 32-bit rollover and numeric bounds.

A separate strict-parser suite passed **2,171 assertions** under ASan/UBSan,
including Arduino macro compatibility, exact field sets, duplicate/unknown keys,
escapes/NUL/nested values, numeric coercion/overflow, MAC/name/payload boundaries,
field-order permutations and truncation. The driver's separate adversarial parser
harness passed **226,923 input checks** under C++11 ASan/UBSan.

Independent source review covered central native ON blocking, early inactive pin
setup, fixed mapping, deadline-preserving timer arming, atomic output application,
sticky expiry retirement, reconnection generation, retained-message handling and
reply/readback consistency. These checks do not substitute for physical testing.

## First public-release audit

The first public-release review adds **5,963 actual-driver host assertions** under
ASan/UBSan and optimized compilation. The harness includes the checked-in driver
with synthetic GPIO, timer, clock and MQTT replacements. It covers callback/apply
deadline races, all masks, maximum expiry, rollover, unchanged-output renewal,
stale callbacks, faults, publication failure and the complete JSON wire lifecycle.
This models driver behavior; it does not establish real SDK scheduling or contact
timing. The audit found no confirmed blocking firmware defect and changed no
actuation implementation.

Release preparation additionally checks source, the index, all stored Git objects,
approved Git attribution, local Markdown links, schemas, strict archives and exact
publication-artifact contents. It preserves the platform/framework source and
notices as well as project/Tasmota source. See [release preparation](releasing.md),
[dependency provenance](dependencies.md) and [security boundaries](../SECURITY.md).
Approval of existing Git author attribution does not permit personal data or
installation secrets in source, messages, paths or artifacts.

This release audit performs no device commands, deployment or physical testing.
Earlier bench results below remain scoped to their original installed images.
The release bundle's source/build metadata and checksums identify the actual
candidate; local validation does not imply publication or a successful hosted CI
run. Host-tool version constraints are separate from archive integrity and do not
claim every download is hermetic or vulnerability-free.

## Unloaded bench observations

The initial preparation used a Sonoff 4CH Pro R3 without connected external loads.
The coordinating commissioning run reported these observations on 2026-10-15:

| Check | Observed scope |
| --- | --- |
| Four independent physical relay pulses | Passed under the preceding stock Tasmota commissioning image; selected contacts switched and the others stayed OFF. |
| Inactive contact baseline | Each relay's unloaded COM–NC/COM–NO baseline was checked separately. |
| Built and installed custom image | A real DOUT/40 MHz/1 MB ESP8285 build succeeded; device sketch checksum matched its reviewed binary. A fresh build through this repository also succeeded with matching actuation source. |
| Custom short local expiry and fixed-end checks | Passed through the custom protocol and live GPIO feedback. This is not continuous mechanical contact sensing. |
| Owner/token/generation/end fencing and replay | Wrong owner/token/generation/end and retired-treatment requests were rejected in live checks. Additional device/sequence checks are recorded below. |
| Known broker disconnect | Custom lease released; reconnect required fresh generation. |
| Warm restart | Custom firmware returned inactive without reacquisition. |
| Wi-Fi recovery | Reconnected while already OFF. Active-lease Wi-Fi interruption remains a separate scenario. |
| Physical identity and active sequence checks | Wrong-device read/activation and stale-sequence renewal were rejected live; a later valid sequence and confirmed release succeeded. |
| Full 900-second local expiry | Passed with the controlling client disconnected, zero renewal/polling commands and 30 fresh passive telemetry reports. Unsolicited expired/OFF state carried the original device deadline; a correlated follow-up read confirmed OFF. |
| Custom-firmware cold startup | Passed after the owner disconnected 12 V for 10 seconds and restored normal power. Passive telemetry showed a new connection generation and 11-second uptime with all four outputs OFF; fresh protocol readback and installed-image checksum matched. |
| Physical button behavior under custom firmware | The owner briefly pressed each front button separately and confirmed no relay clicks or contact changes. |
| Final custom-firmware contact positions | The owner confirmed all four COM–NC contacts closed and COM–NO contacts open before and after the cold boot; fresh GPIO readback also confirmed all four OFF. |

An earlier full-duration attempt was invalidated by an MQTT reconnection and an
observer that did not record its connection lifecycle. The successful repeat
recorded observer lifecycle, passive heartbeat freshness and all control traffic.
Transient reply delay/reconnection also caused supplemental checks to stop safely;
fresh challenges and a new isolated run completed the checks. Maintenance queries
intentionally terminate a lease and must not overlap an expiry/renewal experiment.

The unloaded device preparation is complete within these recorded checks. Build
timestamps may change image bytes; the exact installed image and the later
repository build are separate artifacts. Do not relabel observations from the
preceding firmware as tests of a later image.

## Remaining installation limits

No external loads were controlled. No heating circuit was assigned or enabled.
Mechanical contact observations are discrete commissioning evidence; the firmware
has no independent continuous contact sensor. Valve travel, water flow, electrical
installation safety and delivered heat remain unqualified.
RF remote activation paths were not separately exercised. Older Pro/R2 DIP-switch
instructions were not applied to the tested R3 board.

The future ST-MQ adapter, its durable release behavior and master/standby handover
are not implemented or tested here. Raspberry Pi/Linux host tests and a successful
firmware build are separate from live device behavior. Publication, deployment and
real connected-load commissioning need their own explicit authorization.
