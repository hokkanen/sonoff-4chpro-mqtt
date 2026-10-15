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

## Unloaded bench observations

The initial preparation used a Sonoff 4CH Pro R3 without connected external loads.
The coordinating commissioning run reported these observations on 2026-10-15:

| Check | Observed scope |
| --- | --- |
| Four independent physical relay pulses | Passed under the preceding stock Tasmota commissioning image; selected contacts switched and the others stayed OFF. |
| Inactive contact baseline | Each relay's unloaded COM–NC/COM–NO baseline was checked separately. |
| Custom short local expiry and fixed-end checks | Passed through the custom protocol and live GPIO feedback. This is not continuous mechanical contact sensing. |
| Owner/token/generation/end fencing and replay | Wrong owner/token/generation/end and retired-treatment requests were rejected in live checks. Device/sequence rejection also has portable/source evidence; separate live coverage is not claimed here. |
| Known broker disconnect | Custom lease released; reconnect required fresh generation. |
| Warm restart | Custom firmware returned inactive without reacquisition. |
| Wi-Fi recovery | Reconnected while already OFF. Active-lease Wi-Fi interruption remains a separate scenario. |
| Full 900-second local expiry | Running; result pending coordinating run. |
| Custom-firmware cold startup | Pending coordinating run. |
| Physical button behavior under custom firmware | Pending coordinating run. |

The final build manifest, installed-image identity, full-duration expiry and final
inactive state must be recorded by the coordinating run before declaring device
preparation complete. Do not relabel observations from the preceding firmware as
tests of a later image.

## Remaining installation limits

No external loads were controlled. No heating circuit was assigned or enabled.
Mechanical contact observations are discrete commissioning evidence; the firmware
has no independent continuous contact sensor. Valve travel, water flow, electrical
installation safety and delivered heat remain unqualified.

The future ST-MQ adapter, its durable release behavior and master/standby handover
are not implemented or tested here. Raspberry Pi/Linux host tests and a successful
firmware build are separate from live device behavior. Publication, deployment and
real connected-load commissioning need their own explicit authorization.
