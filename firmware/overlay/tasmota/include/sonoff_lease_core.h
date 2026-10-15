#ifndef SONOFF_LEASE_CORE_H
#define SONOFF_LEASE_CORE_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace sonoff_lease {

static const uint32_t kProtocolVersion = 1;
static const uint32_t kChallengeLifetimeMs = 2000;
static const uint32_t kMaximumLeaseMs = 900000;
static const uint64_t kMaximumProtocolTimeMs = UINT64_C(9007199254740991);
static const size_t kNonceChars = 32;
static const size_t kNameChars = 40;

enum class Op : uint8_t { Acquire, Renew, Release };
enum class Code : uint8_t {
  Ok, Duplicate, InvalidRequest, NotConnected, WrongGeneration,
  DuplicateMismatch, MissingChallenge, StaleChallenge, InvalidToken,
  WrongOwner, WrongTreatment, RetiredTreatment, StaleSequence, Busy,
  DeadlineExpired, EndChanged, ClockFault, NonceFailure
};
enum class Reason : uint8_t {
  Boot, Connected, Acquired, Renewed, Released, Expired, Disconnected,
  NativeOff, Restart, ClockFault, NonceFailure
};

struct Request {
  uint32_t version = kProtocolVersion;
  Op op = Op::Acquire;
  char generation[kNonceChars + 1] = {};
  char challenge[kNonceChars + 1] = {};
  char owner[kNameChars + 1] = {};
  uint32_t treatment = 0;
  uint32_t seq = 0;
  char token[kNonceChars + 1] = {};
  char id[kNameChars + 1] = {};
  uint8_t mask = 0;
  uint32_t ttlMs = 0;
  uint64_t treatmentEndMs = 0;
};

struct State {
  bool connected = false;
  bool active = false;
  uint8_t mask = 0;
  char generation[kNonceChars + 1] = {};
  bool challengeValid = false;
  char challenge[kNonceChars + 1] = {};
  uint64_t challengeIssuedMs = 0;
  uint64_t nowMs = 0;
  uint64_t leaseUntilMs = 0;
  uint64_t treatmentEndMs = 0;
  char owner[kNameChars + 1] = {};
  uint32_t treatment = 0;
  uint32_t seq = 0;
  uint32_t highwater = 0;
  char token[kNonceChars + 1] = {};
  char lastRequestId[kNameChars + 1] = {};
  Reason reason = Reason::Boot;
};

struct Result {
  Code code;
  bool accepted;
  bool duplicate;
  bool outputChanged;
};

inline const char* codeName(Code code);
inline const char* reasonName(Reason reason);
inline const char* opName(Op op);

// All clocks are extended monotonic milliseconds. Driver generates nonces.
// No dynamic allocation, persistence, GPIO, networking or JSON occurs here.
class Core {
 public:
  bool begin(const char* generation, uint64_t nowMs);
  bool issueChallenge(const char* challenge, uint64_t nowMs);
  void revoke(Reason reason, uint64_t nowMs);
  void nativeOff(uint64_t nowMs);
  bool update(uint64_t nowMs);
  Result submit(const Request& request, uint64_t nowMs,
                const char* newLeaseToken = nullptr);
  uint8_t outputMask() const { return state_.mask; }
  const State& status() const { return state_; }

 private:
  State state_;
  Request last_;
  bool haveLast_ = false;
  char lastChallenge_[kNonceChars + 1] = {};

  bool advance(uint64_t nowMs);
  void stop(Reason reason);
  void clearChallenge();
  void remember(const Request& request);
  static bool valid(const Request& request);
  static bool same(const Request& a, const Request& b);
};

namespace detail {
inline bool nonce(const char* value) {
  if (!value) return false;
  for (size_t i = 0; i < kNonceChars; ++i) {
    const char c = value[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return value[kNonceChars] == '\0';
}
inline bool name(const char* value) {
  if (!value || value[0] == '\0') return false;
  for (size_t i = 0; i <= kNameChars; ++i) {
    const char c = value[i];
    if (c == '\0') return true;
    if (i == kNameChars || !((c >= 'A' && c <= 'Z') ||
        (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
        c == '_' || c == '-')) return false;
  }
  return false;
}
template<size_t N> inline void copy(char (&to)[N], const char* from) {
  size_t i = 0;
  while (i + 1 < N && from[i] != '\0') { to[i] = from[i]; ++i; }
  to[i] = '\0';
}
inline Result result(Code code, bool changed = false) {
  return {code, code == Code::Ok || code == Code::Duplicate,
    code == Code::Duplicate, changed};
}
}  // namespace detail

inline const char* opName(Op op) {
  switch (op) {
    case Op::Acquire: return "acquire";
    case Op::Renew: return "renew";
    case Op::Release: return "release";
  }
  return "invalid";
}

inline const char* codeName(Code code) {
  switch (code) {
    case Code::Ok: return "ok";
    case Code::Duplicate: return "duplicate";
    case Code::InvalidRequest: return "invalid-request";
    case Code::NotConnected: return "not-connected";
    case Code::WrongGeneration: return "wrong-generation";
    case Code::DuplicateMismatch: return "duplicate-mismatch";
    case Code::MissingChallenge: return "missing-challenge";
    case Code::StaleChallenge: return "stale-challenge";
    case Code::InvalidToken: return "invalid-token";
    case Code::WrongOwner: return "wrong-owner";
    case Code::WrongTreatment: return "wrong-treatment";
    case Code::RetiredTreatment: return "retired-treatment";
    case Code::StaleSequence: return "stale-sequence";
    case Code::Busy: return "busy";
    case Code::DeadlineExpired: return "deadline-expired";
    case Code::EndChanged: return "end-changed";
    case Code::ClockFault: return "clock-fault";
    case Code::NonceFailure: return "nonce-failure";
  }
  return "invalid-code";
}

inline const char* reasonName(Reason reason) {
  switch (reason) {
    case Reason::Boot: return "boot";
    case Reason::Connected: return "connected";
    case Reason::Acquired: return "acquired";
    case Reason::Renewed: return "renewed";
    case Reason::Released: return "released";
    case Reason::Expired: return "expired";
    case Reason::Disconnected: return "disconnected";
    case Reason::NativeOff: return "native-off";
    case Reason::Restart: return "restart";
    case Reason::ClockFault: return "clock-fault";
    case Reason::NonceFailure: return "nonce-failure";
  }
  return "invalid-reason";
}

inline void Core::clearChallenge() {
  state_.challengeValid = false;
  state_.challenge[0] = '\0';
  state_.challengeIssuedMs = 0;
}

inline void Core::stop(Reason reason) {
  state_.active = false;
  state_.mask = 0;
  state_.leaseUntilMs = 0;
  state_.token[0] = '\0';
  state_.reason = reason;
  clearChallenge();
  // owner/treatment/seq/end/highwater remain terminal historical context.
}

inline bool Core::advance(uint64_t nowMs) {
  if (nowMs < state_.nowMs || nowMs > kMaximumProtocolTimeMs) {
    state_.connected = false;
    stop(Reason::ClockFault);
    return false;
  }
  state_.nowMs = nowMs;
  if (state_.active && nowMs >= state_.leaseUntilMs) stop(Reason::Expired);
  if (state_.challengeValid &&
      nowMs - state_.challengeIssuedMs >= kChallengeLifetimeMs) clearChallenge();
  return true;
}

inline bool Core::begin(const char* generation, uint64_t nowMs) {
  if (nowMs < state_.nowMs || nowMs > kMaximumProtocolTimeMs) {
    state_.connected = false;
    stop(Reason::ClockFault);
    return false;
  }
  if (!detail::nonce(generation) ||
      (state_.generation[0] && strcmp(generation, state_.generation) == 0)) {
    state_.connected = false;
    stop(Reason::NonceFailure);
    return false;
  }
  State fresh;
  state_ = fresh;
  state_.nowMs = nowMs;
  state_.connected = true;
  state_.reason = Reason::Connected;
  detail::copy(state_.generation, generation);
  haveLast_ = false;
  last_ = Request();
  lastChallenge_[0] = '\0';
  return true;
}

inline bool Core::issueChallenge(const char* challenge, uint64_t nowMs) {
  if (!advance(nowMs) || !state_.connected) return false;
  if (!detail::nonce(challenge) ||
      strcmp(challenge, state_.generation) == 0 ||
      (state_.token[0] && strcmp(challenge, state_.token) == 0) ||
      (lastChallenge_[0] && strcmp(challenge, lastChallenge_) == 0)) {
    state_.connected = false;
    stop(Reason::NonceFailure);
    return false;
  }
  detail::copy(state_.challenge, challenge);
  detail::copy(lastChallenge_, challenge);
  state_.challengeIssuedMs = nowMs;
  state_.challengeValid = true;
  return true;
}

inline void Core::revoke(Reason reason, uint64_t nowMs) {
  if (!advance(nowMs)) return;
  state_.connected = false;
  stop(reason);
}

inline void Core::nativeOff(uint64_t nowMs) {
  if (!advance(nowMs)) return;
  stop(Reason::NativeOff);
}

inline bool Core::update(uint64_t nowMs) {
  const uint8_t before = state_.mask;
  advance(nowMs);
  return state_.mask != before;
}

inline bool Core::valid(const Request& r) {
  if (r.version != kProtocolVersion || !detail::nonce(r.generation) ||
      !detail::name(r.owner) || !detail::name(r.id) ||
      r.treatment == 0 || r.seq == 0) return false;
  if (r.op == Op::Acquire || r.op == Op::Renew) {
    if (!detail::nonce(r.challenge) || r.mask == 0 || r.mask > 15 ||
        r.ttlMs == 0 || r.ttlMs > kMaximumLeaseMs ||
        r.treatmentEndMs == 0 || r.treatmentEndMs > kMaximumProtocolTimeMs)
      return false;
    return r.op == Op::Acquire ? r.token[0] == '\0' && r.seq == 1 :
      detail::nonce(r.token);
  }
  return r.op == Op::Release && detail::nonce(r.token) &&
    r.challenge[0] == '\0' && r.mask == 0 && r.ttlMs == 0 &&
    r.treatmentEndMs == 0;
}

inline bool Core::same(const Request& a, const Request& b) {
  return a.version == b.version && a.op == b.op &&
    strcmp(a.generation, b.generation) == 0 &&
    strcmp(a.challenge, b.challenge) == 0 &&
    strcmp(a.owner, b.owner) == 0 && a.treatment == b.treatment &&
    a.seq == b.seq && strcmp(a.token, b.token) == 0 &&
    strcmp(a.id, b.id) == 0 && a.mask == b.mask &&
    a.ttlMs == b.ttlMs && a.treatmentEndMs == b.treatmentEndMs;
}

inline void Core::remember(const Request& request) {
  last_ = request;
  haveLast_ = true;
  detail::copy(state_.lastRequestId, request.id);
}

inline Result Core::submit(const Request& r, uint64_t nowMs,
                           const char* newLeaseToken) {
  const uint8_t previousMask = state_.mask;
  if (!advance(nowMs)) return detail::result(Code::ClockFault, previousMask != state_.mask);
  if (!valid(r)) return detail::result(Code::InvalidRequest, previousMask != state_.mask);
  if (!state_.connected) return detail::result(Code::NotConnected, previousMask != state_.mask);
  if (strcmp(r.generation, state_.generation) != 0)
    return detail::result(Code::WrongGeneration, previousMask != state_.mask);
  if (haveLast_ && strcmp(r.id, last_.id) == 0)
    return detail::result(same(r, last_) ? Code::Duplicate : Code::DuplicateMismatch,
      previousMask != state_.mask);

  if (r.op == Op::Acquire) {
    if (r.treatment <= state_.highwater) return detail::result(Code::RetiredTreatment, previousMask != state_.mask);
    if (state_.active) return detail::result(Code::Busy);
  } else {
    if (!state_.active) return detail::result(Code::RetiredTreatment, previousMask != state_.mask);
    if (strcmp(r.owner, state_.owner) != 0) return detail::result(Code::WrongOwner);
    if (r.treatment != state_.treatment) return detail::result(Code::WrongTreatment);
    if (strcmp(r.token, state_.token) != 0) return detail::result(Code::InvalidToken);
    if (r.seq <= state_.seq) return detail::result(Code::StaleSequence);
    if (r.op == Op::Renew && r.treatmentEndMs != state_.treatmentEndMs)
      return detail::result(Code::EndChanged);
  }

  if (r.op == Op::Release) {
    state_.seq = r.seq;
    stop(Reason::Released);
    remember(r);
    return detail::result(Code::Ok, previousMask != state_.mask);
  }

  if (!state_.challengeValid) return detail::result(Code::MissingChallenge, previousMask != state_.mask);
  if (strcmp(r.challenge, state_.challenge) != 0) return detail::result(Code::StaleChallenge);
  // Clamp before addition: no UINT64 wrap, even with adversarial input.
  if (r.treatmentEndMs <= state_.challengeIssuedMs)
    return detail::result(Code::DeadlineExpired);
  const uint64_t remaining = r.treatmentEndMs - state_.challengeIssuedMs;
  const uint64_t duration = remaining < r.ttlMs ? remaining : r.ttlMs;
  const uint64_t until = state_.challengeIssuedMs + duration;
  if (until <= nowMs) return detail::result(Code::DeadlineExpired);

  if (r.op == Op::Acquire) {
    if (!detail::nonce(newLeaseToken) ||
        strcmp(newLeaseToken, state_.generation) == 0 ||
        strcmp(newLeaseToken, state_.challenge) == 0) {
      state_.connected = false;
      stop(Reason::NonceFailure);
      return detail::result(Code::NonceFailure, previousMask != state_.mask);
    }
    detail::copy(state_.owner, r.owner);
    detail::copy(state_.token, newLeaseToken);
    state_.treatment = r.treatment;
    state_.highwater = r.treatment;
    state_.treatmentEndMs = r.treatmentEndMs;
  }
  state_.active = true;
  state_.mask = r.mask;
  state_.seq = r.seq;
  state_.leaseUntilMs = until;
  state_.reason = r.op == Op::Acquire ? Reason::Acquired : Reason::Renewed;
  clearChallenge();
  remember(r);
  return detail::result(Code::Ok, previousMask != state_.mask);
}

}  // namespace sonoff_lease
#endif
