/* Private, board-specific Sonoff 4CH Pro R3 lease gate. GPL-3.0-or-later. */
#ifndef SONOFF_LEASE_GATE_H
#define SONOFF_LEASE_GATE_H

#ifdef USE_SONOFF_LEASE
void SonoffLeaseEarlyPinsOff(void);
void SonoffLeaseFixedBoard(void);
void SonoffLeaseNativePower(uint32_t requested, uint32_t source);
void SonoffLeaseNativeOff(void);
void SonoffLeaseMqttConnected(void);
void SonoffLeaseMqttDisconnected(void);
bool SonoffLeaseMqttMessage(const char *topic, const uint8_t *data, size_t length,
                           bool retained);
bool SonoffLeaseBlockCommand(const char *command, size_t data_length);
#endif

#endif
