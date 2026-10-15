/* Fixed-board Sonoff 4CH Pro R3 lease gate. GPL-3.0-or-later.
 * Native commands are maintenance/emergency-OFF only. The dedicated protocol is
 * the only GPIO-ON path. GPIO readback does not sense relay contacts or loads.
 */
#ifdef USE_SONOFF_LEASE
#if !defined(ESP8266) || !defined(FIRMWARE_LITE)
#error "Sonoff lease gate requires the dedicated ESP8285 FIRMWARE_LITE build"
#endif
#if defined(USE_RULES) || defined(USE_SCRIPT) || defined(USE_LIGHT) || defined(USE_TIMERS) || defined(USE_DEVICE_GROUPS) || defined(USE_SHUTTER) || defined(USE_TUYA_MCU) || defined(USE_ARDUINO_OTA) || defined(USE_DEEPSLEEP) || defined(USE_EMULATION)
#error "Alternative actuation/scheduling drivers are forbidden in the lease build"
#endif

#include "../include/sonoff_lease_json.h"
#include <Ticker.h>
extern "C" {
#include "osapi.h"
}
#define XDRV_123 123

static const uint8_t kSonoffLeasePins[4] = {12, 5, 4, 15};
static const uint32_t kSonoffLeasePinMask = (1UL << 12) | (1UL << 5) | (1UL << 4) | (1UL << 15);
static const char kSonoffLeaseRequestTopic[] = "cmnd/sonoff4chpro/LEASE";
static const char kSonoffLeaseReplyTopic[] = "stat/sonoff4chpro/LEASE";
static volatile bool SonoffLeaseTimeoutFired = false;
static volatile bool SonoffLeaseCutoffArmed = false;
static volatile uint32_t SonoffLeaseDeadline32 = 0;

// SDK software timer: OFF only, no allocation, core mutation, logging, or I/O.
// This is an additional scheduling safeguard, not a hard realtime guarantee.
void IRAM_ATTR SonoffLeaseCutoff(void) {
  if (SonoffLeaseCutoffArmed &&
      static_cast<int32_t>(millis() - SonoffLeaseDeadline32) >= 0) {
    GPOC = kSonoffLeasePinMask;
    SonoffLeaseTimeoutFired = true;
    SonoffLeaseCutoffArmed = false;
  }
}

class SonoffLeaseDriver {
 public:
  sonoff_lease::Core core;
  Ticker cutoff;
  bool initialized = false;
  bool boardOk = false;
  bool gpioFault = false;
  bool clockStarted = false;
  bool pendingState = false;
  uint32_t last32 = 0;
  uint64_t extended = 0;
  uint64_t armedUntil = 0;
  uint8_t lastMask = 0;
  sonoff_lease::Reason lastReason = sonoff_lease::Reason::Boot;
  bool lastConnected = false;
  char device[18] = {};
  char sketchMd5[33] = {};

  uint64_t now() {
    const uint32_t current = millis();
    if (!clockStarted) { extended = current; clockStarted = true; }
    else { extended += static_cast<uint32_t>(current - last32); }
    last32 = current;
    return extended;
  }

  bool validBoard() const {
    if (Settings->module != SONOFF_4CHPRO || TasmotaGlobal.module_type != SONOFF_4CHPRO ||
        TasmotaGlobal.devices_present != 4 || TasmotaGlobal.rel_inverted || TasmotaGlobal.rel_bistable) return false;
    for (uint32_t i = 0; i < 4; ++i) {
      if (!PinUsed(GPIO_REL1, i) || Pin(GPIO_REL1, i) != kSonoffLeasePins[i]) return false;
    }
    return true;
  }

  uint8_t gpioMask() const {
    uint8_t mask = 0;
    for (uint32_t i = 0; i < 4; ++i) if (digitalRead(kSonoffLeasePins[i])) mask |= 1U << i;
    return mask;
  }

  static void decimal(uint64_t value, char* output) {
    char reverse[21];
    size_t length = 0;
    do { reverse[length++] = '0' + value % 10; value /= 10; } while (value);
    for (size_t i = 0; i < length; ++i) output[i] = reverse[length - i - 1];
    output[length] = '\0';
  }

  bool nonce(char* output) {
    // Called only on an established Wi-Fi/MQTT connection, with RF entropy live.
    if (WiFi.status() != WL_CONNECTED) return false;
    uint8_t bytes[16];
    if (os_get_random(bytes, sizeof(bytes)) != 0) return false;
    uint8_t any = 0;
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < sizeof(bytes); ++i) {
      any |= bytes[i];
      output[2*i] = hex[bytes[i] >> 4]; output[2*i+1] = hex[bytes[i] & 15];
    }
    output[32] = '\0';
    return any != 0;
  }

  void drainTimeout(uint64_t current) {
    if (!SonoffLeaseTimeoutFired) return;
    cutoff.detach();
    SonoffLeaseCutoffArmed = false;
    armedUntil = 0;
    core.update(current);  // Retire the treatment before any possible GPIO apply.
    if (core.status().active) core.revoke(sonoff_lease::Reason::ClockFault, current);
    SonoffLeaseTimeoutFired = false;
  }

  void apply(uint64_t current) {
    drainTimeout(current);
    core.update(current);
    uint8_t desired = initialized && boardOk && !gpioFault ? core.outputMask() : 0;
    if (desired && core.status().leaseUntilMs > current) {
      if (armedUntil != core.status().leaseUntilMs) {
        SonoffLeaseCutoffArmed = false;
        cutoff.detach();
        // Extended clock retains millis()' low 32 bits: never reanchor a lease
        // relative to elapsed parsing/apply time.
        SonoffLeaseDeadline32 = static_cast<uint32_t>(core.status().leaseUntilMs);
        const int32_t remaining = static_cast<int32_t>(SonoffLeaseDeadline32 - millis());
        armedUntil = core.status().leaseUntilMs;
        if (remaining > 0) {
          SonoffLeaseCutoffArmed = true;
          cutoff.once_ms(static_cast<uint32_t>(remaining), SonoffLeaseCutoff);
        } else {
          SonoffLeaseTimeoutFired = true;
        }
      }
    } else {
      desired = 0;
      SonoffLeaseCutoffArmed = false;
      cutoff.detach();
      armedUntil = 0;
    }
    uint32_t desiredPins = 0;
    for (uint32_t i = 0; i < 4; ++i) if ((desired >> i) & 1) desiredPins |= 1UL << kSonoffLeasePins[i];
    // The final deadline check and GPIO writes form one tiny critical section.
    // A cutoff cannot clear pins and then have an older desired mask restore ON.
    const uint32_t interruptState = xt_rsil(15);
    if (SonoffLeaseTimeoutFired || (desired &&
        static_cast<int32_t>(millis() - SonoffLeaseDeadline32) >= 0)) {
      GPOC = kSonoffLeasePinMask;
      SonoffLeaseTimeoutFired = true;
      desired = 0;
    } else {
      // Clear desired-OFF pins only: renewal never inserts an OFF/ON pulse.
      GPOC = kSonoffLeasePinMask & ~desiredPins;
      GPOS = desiredPins;
    }
    uint8_t observed = gpioMask();
    xt_wsr_ps(interruptState);
    if (SonoffLeaseTimeoutFired) {
      current = now();
      drainTimeout(current);
      desired = 0;
      observed = gpioMask();
    }
    if (observed != desired) {
      gpioFault = true;
      core.nativeOff(current);
      GPOC = kSonoffLeasePinMask;
      SonoffLeaseCutoffArmed = false;
      cutoff.detach();
      armedUntil = 0;
    }
    TasmotaGlobal.power = gpioMask();
    TasmotaGlobal.last_power = TasmotaGlobal.power;
    TasmotaGlobal.blink_mask = 0;
    TasmotaGlobal.power_on_delay_state = 0;
    TasmotaGlobal.power_on_delay = 0;
  }

  void service() {
    const uint64_t current = now();
    drainTimeout(current);
    if (initialized && !validBoard()) {
      boardOk = false;
      core.nativeOff(current);
    }
    if (core.status().connected &&
        (!MqttIsConnected() || WiFi.status() != WL_CONNECTED ||
         TasmotaGlobal.restart_flag || TasmotaGlobal.ota_state_flag)) {
      core.revoke(sonoff_lease::Reason::Disconnected, current);
    }
    apply(current);
    const sonoff_lease::State& state = core.status();
    if (lastMask != state.mask || lastReason != state.reason || lastConnected != state.connected) pendingState = true;
    lastMask = state.mask; lastReason = state.reason; lastConnected = state.connected;
  }

  void disconnect() {
    const uint64_t current = now();
    drainTimeout(current);
    core.revoke(sonoff_lease::Reason::Disconnected, current);
    apply(current);
    pendingState = true;
  }

  void nativeOff() {
    const uint64_t current = now();
    drainTimeout(current);
    core.nativeOff(current);
    apply(current);
    pendingState = true;
  }

  void publish(const char* kind, const char* id, const char* op, bool accepted,
               bool duplicate, const char* code, bool token, bool challenge) {
    service();
    if (!MqttIsConnected()) return;
    const sonoff_lease::State state = core.status();
    const uint8_t observed = gpioMask();
    char nowText[21], untilText[21], endText[21], issuedText[21];
    decimal(state.nowMs, nowText); decimal(state.leaseUntilMs, untilText);
    decimal(state.treatmentEndMs, endText); decimal(state.challengeIssuedMs, issuedText);
    Response_P(PSTR("{\"v\":1,\"build\":\"sonoff4chpro-lease-v1\",\"sketch_md5\":\"%s\",\"kind\":\"%s\",\"id\":\"%s\",\"op\":\"%s\",\"accepted\":%s,\"duplicate\":%s,\"code\":\"%s\",\"device\":\"%s\",\"generation\":\"%s\",\"connected\":%s,\"active\":%s,\"mask\":%u,\"gpio_mask\":%u,\"gpio_match\":%s,\"state_evidence\":\"gpio_output_readback\",\"board_ok\":%s,\"now_ms\":%s,\"lease_until_ms\":%s,\"end_ms\":%s,\"owner\":\"%s\",\"treatment\":%u,\"seq\":%u,\"highwater\":%u,\"reason\":\"%s\",\"max_lease_ms\":900000"),
      sketchMd5, kind, id, op, accepted ? "true" : "false", duplicate ? "true" : "false", code,
      device, state.generation, state.connected ? "true" : "false", state.active ? "true" : "false",
      state.mask, observed, observed == state.mask ? "true" : "false",
      boardOk && !gpioFault ? "true" : "false", nowText, untilText, endText, state.owner,
      state.treatment, state.seq, state.highwater, sonoff_lease::reasonName(state.reason));
    if (token && state.active) ResponseAppend_P(PSTR(",\"token\":\"%s\""), state.token);
    if (challenge && state.challengeValid) ResponseAppend_P(PSTR(",\"challenge\":\"%s\",\"issued_ms\":%s,\"lifetime_ms\":2000"), state.challenge, issuedText);
    ResponseJsonEnd();
    // Bypass ordinary MQTT logging: replies can contain temporary capabilities.
    const bool sent = MqttPublishLib(kSonoffLeaseReplyTopic, reinterpret_cast<const uint8_t*>(ResponseData()), ResponseLength(), false);
    ResponseClear();  // Do not leave a lease capability in the native reply buffer.
    if (!sent) disconnect();
    service();
  }

  bool message(const char* topic, const uint8_t* data, size_t length, bool retained) {
    if (strcmp(topic, kSonoffLeaseRequestTopic)) return false;
    service();
    sonoff_lease_wire::Message message;
    const bool parsed = sonoff_lease_wire::Parser(data, length).parse(message);
    const char* id = sonoff_lease_wire::Parser::name(message.request.id) ? message.request.id : "";
    if (!parsed || retained) {
      publish("reply", id, "invalid", false, false, retained ? "retained-forbidden" : "invalid-request", false, false);
      return true;
    }
    if (strcmp(message.device, device)) {
      publish("reply", id, "invalid", false, false, "wrong-device", false, false);
      return true;
    }
    if (!boardOk || gpioFault) {
      publish("reply", id, "invalid", false, false, "hardware-fault", false, false);
      return true;
    }
    const uint64_t current = now();
    drainTimeout(current);
    if (message.operation == sonoff_lease_wire::Operation::Get) {
      publish("reply", id, "get", true, false, "ok", false, false);
    } else if (message.operation == sonoff_lease_wire::Operation::Challenge) {
      char value[33];
      bool ok = nonce(value);
      if (ok) ok = core.issueChallenge(value, current);
      else core.revoke(sonoff_lease::Reason::NonceFailure, current);
      apply(current);
      publish("reply", id, "challenge", ok, false, ok ? "ok" : "challenge-unavailable", false, ok);
    } else {
      char value[33] = {};
      if (message.operation == sonoff_lease_wire::Operation::Acquire && !nonce(value)) {
        core.revoke(sonoff_lease::Reason::NonceFailure, current);
        apply(current);
        publish("reply", id, "acquire", false, false, "nonce-failure", false, false);
      } else {
        const sonoff_lease::Result result = core.submit(message.request, current, value);
        apply(current);
        publish("reply", id, sonoff_lease::opName(message.request.op), result.accepted,
                result.duplicate, sonoff_lease::codeName(result.code),
                result.accepted && message.operation == sonoff_lease_wire::Operation::Acquire, false);
      }
    }
    return true;
  }
};

static SonoffLeaseDriver SonoffLease;

void SonoffLeaseEarlyPinsOff(void) {
  for (uint32_t i = 0; i < 4; ++i) {
    digitalWrite(kSonoffLeasePins[i], LOW);
    pinMode(kSonoffLeasePins[i], OUTPUT);
  }
}

void SonoffLeaseFixedBoard(void) {
  SonoffLeaseEarlyPinsOff();
  Settings->module = SONOFF_4CHPRO;
  Settings->last_module = SONOFF_4CHPRO;
  Settings->fallback_module = SONOFF_4CHPRO;
  memset(Settings->my_gp.io, 0, sizeof(Settings->my_gp.io));
  Settings->power = 0;
  Settings->poweronstate = POWER_ALL_OFF;
  Settings->flag.save_state = 0;
  Settings->flag.interlock = 0;
  Settings->power_lock = 0;
  Settings->param[P_POWER_ON_DELAY2] = 0;
  for (uint32_t i = 0; i < MAX_PULSETIMERS; ++i) {
    Settings->pulse_timer[i] = 0;
    TasmotaGlobal.pulse_timer[i] = 0;
  }
  SettingsUpdateText(SET_MQTT_TOPIC, "sonoff4chpro");
  SettingsUpdateText(SET_MQTT_FULLTOPIC, "%prefix%/sonoff4chpro/");
  TasmotaGlobal.power = 0;
  TasmotaGlobal.rel_inverted = 0;
  TasmotaGlobal.rel_bistable = 0;
}

void SonoffLeaseNativePower(uint32_t requested, uint32_t source) {
  SonoffLease.service();
  if ((requested & SonoffLease.core.outputMask()) != SonoffLease.core.outputMask()) SonoffLease.nativeOff();
  // Native ON can never add a bit: only the core's existing authorized mask is applied.
  SonoffLease.apply(SonoffLease.now());
  TasmotaGlobal.last_source = source;
}

void SonoffLeaseNativeOff(void) { SonoffLease.nativeOff(); }
void SonoffLeaseMqttDisconnected(void) { SonoffLease.disconnect(); }
void SonoffLeaseMqttConnected(void) {
  SonoffLease.service();
  char value[33];
  const uint64_t current = SonoffLease.now();
  if (SonoffLease.nonce(value)) SonoffLease.core.begin(value, current);
  else SonoffLease.core.revoke(sonoff_lease::Reason::NonceFailure, current);
  SonoffLease.apply(current);
  SonoffLease.pendingState = true;
}
bool SonoffLeaseMqttMessage(const char* topic, const uint8_t* data, size_t length, bool retained) {
  return SonoffLease.message(topic, data, length, retained);
}
bool SonoffLeaseBlockCommand(const char* command, size_t data_length) {
  return data_length && (!strcmp(command, "MODULE") || !strcmp(command, "GPIO") ||
                        !strcmp(command, "TEMPLATE"));
}

bool Xdrv123(uint32_t function) {
  switch (function) {
    case FUNC_INIT:
      SonoffLease.initialized = true;
      SonoffLease.boardOk = SonoffLease.validBoard();
      WiFi.macAddress().toCharArray(SonoffLease.device, sizeof(SonoffLease.device));
      ESP.getSketchMD5().toCharArray(SonoffLease.sketchMd5, sizeof(SonoffLease.sketchMd5));
      SonoffLease.service();
      break;
    case FUNC_LOOP:
    case FUNC_SLEEP_LOOP:
      SonoffLease.service();
      if (SonoffLease.pendingState && MqttIsConnected()) {
        SonoffLease.pendingState = false;
        SonoffLease.publish("state", "", "state", true, false, "ok", false, false);
      }
      break;
    case FUNC_ABOUT_TO_RESTART:
      SonoffLease.disconnect();
      break;
  }
  return false;
}
#endif  // USE_SONOFF_LEASE
