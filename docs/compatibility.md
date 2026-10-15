# Supported hardware and firmware

The candidate targets **Sonoff 4CH Pro R3, ESP8285, 1 MB flash** using a focused
custom Tasmota 15.6.0 Lite build. It is not a generic Tasmota module, a Shelly RPC
device or a promise to support earlier Sonoff revisions and arbitrary pin maps.

| Relay | Bitmap bit | Fixed ESP GPIO |
| --- | --- | --- |
| 1 | `1` | 12 |
| 2 | `2` | 5 |
| 3 | `4` | 4 |
| 4 | `8` | 15 |

The build fixes the Sonoff 4CH Pro module mapping, active-high non-latching outputs,
inactive startup and the `sonoff4chpro` command profile. It blocks native activation
and competing actuation/scheduling features. A mismatching board mapping fails
OFF. Changing native Topic, FullTopic or Prefix is unsupported profile maintenance
and can interrupt MQTT reachability; do not treat those fields as generic setup
options for this build.

The official [Tasmota Sonoff 4CH Pro documentation](https://tasmota.github.io/docs/devices/Sonoff-4CH-Pro/)
distinguishes R3 serial entry from older revisions and describes older board DIP
settings. Inspect the actual hardware; absent switches are not evidence of a
particular operating mode. Test independent unloaded outputs instead of assigning
older-revision switch instructions to a different board.

Normal relay operation needs the board's proper supply. Powering only the 3.3 V
programming rail can run the ESP without proving coil or contact operation.
GPIO readback is not contact sensing. Preserve the separation between normal-power
unloaded bench evidence and a commissioned installation with connected loads.

The firmware drives outputs low at the beginning of setup and retains local
expiry/OFF paths. Software cannot prove absence of a pulse before firmware runs,
during brownout, or after a hardware failure. Actual board power-up and contact
tests remain part of commissioning.

Wi-Fi/MQTT are local services. The lease gate requires a broker and a current
device-bound exchange; it does not require eWeLink or a vendor cloud. Broker
authentication, topic permissions and physical network deployment are installation
responsibilities. No live credentials or installation identifiers are shipped.
