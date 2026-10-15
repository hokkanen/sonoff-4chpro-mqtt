/* Offline SDK/GPIO model around the actual checked-in driver. GPL-3.0-or-later.
 * No device, network or credentials are used. These are deterministic host
 * assertions about driver transitions, not evidence of embedded timing or
 * mechanical relay behavior. check.py supplies empty Ticker.h/osapi.h shims in
 * its external temporary directory; the SDK replacements live only here.
 */
#include <stdint.h>
#include <stddef.h>
#include <cstring>
#include <cstdio>
#include <cstdarg>
#include <cstdlib>
#include <string>
#include <vector>

class Ticker {
 public:
  void (*callback)() = nullptr;
  uint32_t due = 0;
  bool attached = false;
  void once_ms(uint32_t milliseconds, void (*function)());
  void detach() { attached = false; callback = nullptr; }
};
#define USE_SONOFF_LEASE
#define ESP8266
#define FIRMWARE_LITE
#define IRAM_ATTR
#define LOW 0
#define OUTPUT 1
#define WL_CONNECTED 3
#define GPIO_REL1 1
#define SONOFF_4CHPRO 23
#define POWER_ALL_OFF 0
#define P_POWER_ON_DELAY2 0
#define MAX_PULSETIMERS 4
#define SET_MQTT_TOPIC 0
#define SET_MQTT_FULLTOPIC 1
#define FUNC_INIT 1
#define FUNC_LOOP 2
#define FUNC_SLEEP_LOOP 3
#define FUNC_ABOUT_TO_RESTART 4
#define PSTR(x) x

static uint64_t fakeTime = 0;
static uint32_t gpio = 0;
static bool irqMasked = false;
static bool mqtt = true;
static bool publishSuccess = true;
static int wifiStatus = WL_CONNECTED;
static uint32_t stuckHighPins = 0;
static uint32_t fallingEdges = 0;
static uint32_t stepPerMillis = 0;
static uint32_t randomCounter = 0;
static const uint32_t allPins = (1U << 12) | (1U << 5) | (1U << 4) | (1U << 15);
static unsigned checks = 0;
static uint64_t expectedDeadline = 0;
static std::vector<std::string> events;

static void check(bool ok, const char* label) {
  ++checks;
  if (!ok) {
    fprintf(stderr, "FAIL time=%llu gpio=%x: %s\n",
            static_cast<unsigned long long>(fakeTime), gpio, label);
    exit(1);
  }
}
struct Register {
  bool set;
  void operator=(uint32_t bits) {
    const uint32_t before = gpio;
    if (set) gpio |= bits;
    else gpio &= ~bits;
    fallingEdges |= before & ~gpio;
  }
};
static Register GPOC{false}, GPOS{true};
static Ticker* ticker = nullptr;
void Ticker::once_ms(uint32_t ms, void (*function)()) {
  due = static_cast<uint32_t>(fakeTime) + ms;
  callback = function;
  attached = true;
  ticker = this;
}
static void runTimer() {
  if (ticker && ticker->attached && !irqMasked &&
      static_cast<int32_t>(static_cast<uint32_t>(fakeTime) - ticker->due) >= 0) {
    auto function = ticker->callback;
    ticker->attached = false;
    function();
  }
}
uint32_t millis() { fakeTime += stepPerMillis; runTimer(); return static_cast<uint32_t>(fakeTime); }
uint32_t xt_rsil(int) { const bool was = irqMasked; irqMasked = true; return was; }
void xt_wsr_ps(uint32_t old) { irqMasked = old; runTimer(); }
void digitalWrite(uint8_t pin, uint8_t state) {
  if (state) gpio |= 1U << pin;
  else gpio &= ~(1U << pin);
}
void pinMode(uint8_t, uint8_t) {}
int digitalRead(uint8_t pin) { return ((gpio | stuckHighPins) >> pin) & 1; }
uint32_t Pin(uint32_t, uint32_t i) { const uint32_t pins[] = {12, 5, 4, 15}; return pins[i]; }
bool PinUsed(uint32_t, uint32_t) { return true; }
struct Global {
  uint32_t module_type = SONOFF_4CHPRO, devices_present = 4, rel_inverted = 0, rel_bistable = 0;
  uint32_t restart_flag = 0, ota_state_flag = 0, power = 0, last_power = 0, blink_mask = 0;
  uint32_t power_on_delay_state = 0, power_on_delay = 0, last_source = 0, pulse_timer[4] = {};
} TasmotaGlobal;
struct SettingsType {
  uint32_t module = SONOFF_4CHPRO, last_module = 0, fallback_module = 0;
  uint32_t power = 0, poweronstate = 0, power_lock = 0;
  struct { uint32_t io[17] = {}; } my_gp;
  struct { uint32_t save_state = 0, interlock = 0; } flag;
  uint32_t param[1] = {}, pulse_timer[4] = {};
} settings;
SettingsType* Settings = &settings;
void SettingsUpdateText(uint32_t, const char*) {}
struct SmallString {
  std::string value;
  void toCharArray(char* out, size_t length) { snprintf(out, length, "%s", value.c_str()); }
};
struct WiFiType {
  int status() { return wifiStatus; }
  SmallString macAddress() { return {"AA:BB:CC:DD:EE:FF"}; }
} WiFi;
struct ESPType {
  SmallString getSketchMD5() { return {"00000000000000000000000000000000"}; }
} ESP;
extern "C" int os_get_random(unsigned char* bytes, size_t length) {
  ++randomCounter;
  for (size_t i = 0; i < length; ++i) bytes[i] = static_cast<unsigned char>(randomCounter + i);
  return 0;
}
bool MqttIsConnected() { return mqtt; }
static std::string response;
void Response_P(const char* format, ...) {
  char data[2048]; va_list args; va_start(args, format);
  vsnprintf(data, sizeof(data), format, args); va_end(args); response = data;
}
void ResponseAppend_P(const char* format, ...) {
  char data[2048]; va_list args; va_start(args, format);
  vsnprintf(data, sizeof(data), format, args); va_end(args); response += data;
}
void ResponseJsonEnd() { response += '}'; }
const char* ResponseData() { return response.c_str(); }
size_t ResponseLength() { return response.size(); }
void ResponseClear() { response.clear(); }
bool MqttPublishLib(const char*, const uint8_t* data, size_t length, bool retained) {
  check(!retained, "no retained state");
  events.emplace_back(reinterpret_cast<const char*>(data), length);
  return publishSuccess;
}

#include "../firmware/overlay/tasmota/include/sonoff_lease_gate.h"
#include "../firmware/overlay/tasmota/tasmota_xdrv_driver/xdrv_123_sonoff_lease.ino"
using namespace sonoff_lease;
static const char* GEN = "11111111111111111111111111111111";
static const char* TOKEN = "33333333333333333333333333333333";
static void reset(uint64_t time) {
  stepPerMillis = 0;
  SonoffLease.cutoff.detach(); SonoffLease.core = Core{};
  SonoffLease.clockStarted = false; SonoffLease.extended = 0; SonoffLease.armedUntil = 0;
  SonoffLease.lastMask = 0; SonoffLease.lastReason = Reason::Boot;
  SonoffLease.lastConnected = false; SonoffLease.pendingState = false;
  SonoffLease.gpioFault = false; SonoffLease.initialized = true; SonoffLease.boardOk = true;
  SonoffLeaseTimeoutFired = false; SonoffLeaseCutoffArmed = false; SonoffLeaseDeadline32 = 0;
  fakeTime = 0; gpio = 0; stuckHighPins = 0; fallingEdges = 0; irqMasked = false;
  mqtt = true; publishSuccess = true; wifiStatus = WL_CONNECTED; events.clear();
  TasmotaGlobal.module_type = SONOFF_4CHPRO; Settings->module = SONOFF_4CHPRO;
  TasmotaGlobal.restart_flag = 0; TasmotaGlobal.ota_state_flag = 0;
  strcpy(SonoffLease.device, "AA:BB:CC:DD:EE:FF");
  strcpy(SonoffLease.sketchMd5, "00000000000000000000000000000000");
  SonoffLease.now();
  // Extend uptime by observations less than one raw-clock wrap apart; the model
  // never seeds the driver's extended clock directly.
  while (fakeTime < time) {
    const uint64_t remaining = time - fakeTime;
    fakeTime += remaining > UINT32_MAX ? UINT32_MAX : remaining;
    SonoffLease.now();
  }
  check(SonoffLease.now() == time, "driver extends observed raw-clock wraps");
  check(SonoffLease.core.begin(GEN, SonoffLease.now()), "new generation");
}
static Request acquire(uint32_t ttl = 100, uint8_t mask = 15, uint64_t plannedDuration = 1800000) {
  const uint64_t issued = SonoffLease.now();
  check(SonoffLease.core.issueChallenge("22222222222222222222222222222222", issued), "challenge");
  Request request;
  strcpy(request.generation, GEN);
  strcpy(request.challenge, "22222222222222222222222222222222");
  strcpy(request.owner, "test-owner"); strcpy(request.id, "request-1");
  request.treatment = 1; request.seq = 1; request.mask = mask; request.ttlMs = ttl;
  request.treatmentEndMs = issued + plannedDuration;
  check(SonoffLease.core.submit(request, issued, TOKEN).accepted, "accept acquire");
  SonoffLease.apply(issued);
  expectedDeadline = issued + (ttl < plannedDuration ? ttl : plannedDuration);
  return request;
}
static void timerAndClockBoundaries() {
  for (uint64_t anchor : {0ULL, 1000ULL, 4294967245ULL, 4294967296ULL, 8589934590ULL}) {
    for (uint32_t ttl : {1U, 2U, 5U, 100U, 1999U, 900000U}) {
      for (uint8_t mask = 1; mask <= 15; ++mask) {
        reset(anchor); const auto request = acquire(ttl, mask);
        check(SonoffLease.gpioMask() == mask, "initial GPIO matches mask");
        fakeTime = expectedDeadline - 1; runTimer(); SonoffLease.service();
        check(SonoffLease.gpioMask() == mask, "before expiry remains on");
        fakeTime = expectedDeadline; runTimer();
        check(SonoffLease.gpioMask() == 0, "timer expiry independent of loop");
        SonoffLease.service();
        check(!SonoffLease.core.status().active, "loop retires expiry");
        check(!SonoffLease.gpioFault, "ordinary expiry no GPIO fault");
        check(SonoffLease.core.submit(request, SonoffLease.now(), TOKEN).duplicate, "terminal duplicate ack");
        SonoffLease.apply(SonoffLease.now());
        check(SonoffLease.gpioMask() == 0, "duplicate cannot reenergize");
      }
    }
  }
  reset(1000); acquire(900000, 15, 17);
  fakeTime = 1016; runTimer();
  check(SonoffLease.gpioMask() == 15, "planned end not reached");
  fakeTime = 1017; runTimer();
  check(SonoffLease.gpioMask() == 0, "short planned end caps maximum TTL locally");
  for (uint32_t delta = 0; delta < 130; ++delta) {
    reset(500); acquire(100, 15); fakeTime = 500 + delta;
    stepPerMillis = 1; SonoffLease.apply(SonoffLease.now()); stepPerMillis = 0;
    runTimer(); SonoffLease.service();
    if (fakeTime >= expectedDeadline) check(SonoffLease.gpioMask() == 0, "elapsed apply stays off");
    check(!SonoffLease.gpioFault, "deadline crossed in apply is ordinary expiry");
  }
}
static void renewalAndNativeWrites() {
  // Observe clear/set edges rather than inferring no cycle from a final mask.
  for (uint8_t mask = 1; mask <= 15; ++mask) {
    reset(1000); acquire(100, mask); fakeTime = 1050;
    check(SonoffLease.core.issueChallenge("44444444444444444444444444444444", SonoffLease.now()), "renew challenge");
    Request request; request.op = Op::Renew;
    strcpy(request.generation, GEN); strcpy(request.challenge, "44444444444444444444444444444444");
    strcpy(request.owner, "test-owner"); strcpy(request.id, "request-2"); strcpy(request.token, TOKEN);
    request.treatment = 1; request.seq = 2; request.mask = mask; request.ttlMs = 200;
    request.treatmentEndMs = SonoffLease.core.status().treatmentEndMs;
    check(SonoffLease.core.submit(request, SonoffLease.now()).accepted, "renew accepted");
    fallingEdges = 0; SonoffLease.apply(SonoffLease.now());
    check((fallingEdges & allPins) == 0, "unchanged renewal does not pulse off");
    check(SonoffLease.gpioMask() == mask, "renew keeps selected mask");
    fakeTime = 1100; SonoffLeaseCutoff();
    check(SonoffLease.gpioMask() == mask, "stale old timer does not truncate renewal");
    fakeTime = 1250; runTimer();
    check(SonoffLease.gpioMask() == 0, "renewed timer expires without commands");
  }
  for (uint32_t requested = 0; requested < 16; ++requested) {
    reset(1000); acquire(100, 5); SonoffLeaseNativePower(requested, 0);
    check(SonoffLease.gpioMask() == ((requested & 5) == 5 ? 5 : 0), "native write cannot add outputs");
  }
}
static void stopsAndEvidence() {
  for (int mode = 0; mode < 5; ++mode) {
    reset(1000); acquire(100, 15);
    if (mode == 0) mqtt = false;
    if (mode == 1) TasmotaGlobal.restart_flag = 1;
    if (mode == 2) TasmotaGlobal.ota_state_flag = 1;
    if (mode == 3) wifiStatus = 0;
    if (mode == 4) SonoffLeaseNativeOff();
    else SonoffLease.service();
    check(SonoffLease.gpioMask() == 0, "known stop off");
  }
  reset(1000); acquire(100, 15); fakeTime = 1100; runTimer();
  events.clear(); Xdrv123(FUNC_LOOP);
  check(!events.empty() && events.back().find("\"reason\":\"expired\"") != std::string::npos,
        "expiry emits unsolicited state without a query");
  check(events.back().find("\"mask\":0") != std::string::npos, "unsolicited expiry is OFF");
  reset(1000); acquire(100, 15); publishSuccess = false;
  SonoffLease.publish("reply", "get-test", "get", true, false, "ok", false, false);
  check(!SonoffLease.core.status().connected && SonoffLease.gpioMask() == 0,
        "failed publication retires authority");
  reset(1000); acquire(100, 15); Settings->module = 0; SonoffLease.service();
  check(!SonoffLease.boardOk && SonoffLease.gpioMask() == 0, "board mismatch releases all outputs");
  Settings->module = SONOFF_4CHPRO; SonoffLease.service();
  check(!SonoffLease.boardOk, "board mismatch latches until restart");
  reset(1000); acquire(100, 15); stuckHighPins = 1U << 12; SonoffLeaseNativeOff();
  check(SonoffLease.gpioFault && !SonoffLease.core.status().active && (gpio & allPins) == 0,
        "readback mismatch latches fault and clears output register");
  // A cleared output register is not proof a stuck signal/contact was cleared.
  check(SonoffLease.gpioMask() == 1, "stuck readback remains visible");
  for (bool retained : {false, true}) {
    reset(1000); acquire(100, 5);
    const std::string body = "{\"v\":1,\"op\":\"get\",\"id\":\"get-test\",\"device\":\"AA:BB:CC:DD:EE:FF\"}";
    check(SonoffLease.message("cmnd/sonoff4chpro/LEASE", reinterpret_cast<const uint8_t*>(body.data()), body.size(), retained),
          "dedicated topic consumed");
    check(SonoffLease.gpioMask() == 5, "read or rejected retained request does not change active lease");
    check(!events.empty() && events.back().find(retained ? "retained-forbidden" : "\"accepted\":true") != std::string::npos,
          "retained flag is rejected, live get accepted");
  }
}
static bool wire(const std::string& body, bool retained = false) {
  return SonoffLease.message("cmnd/sonoff4chpro/LEASE",
      reinterpret_cast<const uint8_t*>(body.data()), body.size(), retained);
}
static std::string common(const char* op, const char* id, const char* device = "AA:BB:CC:DD:EE:FF") {
  return std::string("{\"v\":1,\"op\":\"") + op + "\",\"id\":\"" + id +
      "\",\"device\":\"" + device + "\"";
}
static void wireLifecycle() {
  reset(1000);
  check(wire(common("challenge", "challenge-1") + "}"), "wire challenge consumed");
  check(SonoffLease.core.status().challengeValid, "wire challenge issued without permission");
  check(SonoffLease.gpioMask() == 0, "challenge cannot energize");
  const std::string mutation = std::string(",\"generation\":\"") + GEN +
      "\",\"owner\":\"test-owner\",\"treatment\":1";
  const std::string acquireFields = mutation + ",\"seq\":1,\"challenge\":\"" +
      SonoffLease.core.status().challenge + "\",\"mask\":1,\"ttl_ms\":100,\"end_ms\":2000}";
  check(wire(common("acquire", "acquire-1", "AA:BB:CC:00:00:01") + acquireFields), "wrong device request consumed");
  check(SonoffLease.gpioMask() == 0, "wire identity mismatch cannot activate");
  const std::string acquisition = common("acquire", "acquire-1") + acquireFields;
  check(wire(acquisition, true), "retained activation consumed");
  check(SonoffLease.gpioMask() == 0, "retained activation cannot energize");
  check(wire(acquisition), "live acquisition consumed");
  check(SonoffLease.gpioMask() == 1 && SonoffLease.core.status().active, "wire acquisition energizes selected bit");
  const std::string token = SonoffLease.core.status().token;
  check(!token.empty() && events.back().find("\"token\":\"" + token + "\"") != std::string::npos,
        "successful wire acquisition reply contains its synthetic token");
  fakeTime = 1050;
  check(wire(common("challenge", "challenge-2") + "}"), "wire renewal challenge consumed");
  const std::string renewal = common("renew", "renew-1") + mutation +
      ",\"seq\":2,\"challenge\":\"" + SonoffLease.core.status().challenge +
      "\",\"token\":\"" + token + "\",\"mask\":5,\"ttl_ms\":200,\"end_ms\":2000}";
  fallingEdges = 0;
  check(wire(renewal), "wire renewal consumed");
  check(SonoffLease.gpioMask() == 5 && SonoffLease.core.status().seq == 2, "wire renewal may add independently owned bit");
  check((fallingEdges & (1U << 12)) == 0, "wire renewal preserves continuously owned bit");
  const std::string release = common("release", "release-1") + mutation +
      ",\"seq\":3,\"token\":\"" + token + "\"}";
  check(wire(release), "wire release consumed");
  check(SonoffLease.gpioMask() == 0 && !SonoffLease.core.status().active, "wire release closes board lease");
  check(wire(release), "wire duplicate release consumed");
  check(SonoffLease.gpioMask() == 0 && events.back().find("\"duplicate\":true") != std::string::npos,
        "wire terminal duplicate acknowledges without activation");
  check(response.empty(), "shared response buffer cleared after capability publication");
}
int main() {
  timerAndClockBoundaries();
  renewalAndNativeWrites();
  stopsAndEvidence();
  wireLifecycle();
  printf("Actual driver with synthetic SDK: %u checks passed\n", checks);
}
