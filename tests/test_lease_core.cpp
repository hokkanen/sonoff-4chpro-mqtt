#include "sonoff_lease_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>

using namespace sonoff_lease;

static unsigned checks = 0;
static unsigned failures = 0;
static const char* testName = "initial";
static const char* GEN = "11111111111111111111111111111111";
static const char* GEN2 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static const char* TOKEN = "33333333333333333333333333333333";

static void check(bool ok, const char* expression, unsigned line) {
  ++checks;
  if (!ok) { ++failures; fprintf(stderr, "%s:%u: %s\n", testName, line, expression); }
}
#define CHECK(x) check((x), #x, __LINE__)
#define CASE(x) testName = x
#define CODE(r,c) CHECK((r).code == Code::c)

struct Fixture {
  Core core;
  uint64_t now = 1000;
  unsigned challengeCounter = 100;
  unsigned idCounter = 1;
  Fixture() { CHECK(core.begin(GEN, now)); challenge(); }
  void challenge() {
    char nonce[33];
    snprintf(nonce, sizeof(nonce), "%032x", ++challengeCounter);
    CHECK(core.issueChallenge(nonce, now));
  }
  Request acquire(uint8_t mask = 15, uint32_t ttl = 900000,
                  uint64_t end = 0, uint32_t treatment = 1) {
    Request r;
    strcpy(r.generation, core.status().generation);
    strcpy(r.challenge, core.status().challenge);
    strcpy(r.owner, "owner-A");
    r.treatment = treatment; r.seq = 1;
    snprintf(r.id, sizeof(r.id), "id-%u", idCounter++);
    r.mask = mask; r.ttlMs = ttl; r.treatmentEndMs = end ? end : now + 1800000;
    return r;
  }
  Request renew(uint8_t mask = 15, uint32_t ttl = 900000) {
    Request r;
    r.op = Op::Renew;
    strcpy(r.generation, core.status().generation);
    strcpy(r.challenge, core.status().challenge);
    strcpy(r.owner, core.status().owner);
    strcpy(r.token, core.status().token);
    r.treatment = core.status().treatment; r.seq = core.status().seq + 1;
    snprintf(r.id, sizeof(r.id), "id-%u", idCounter++);
    r.mask = mask; r.ttlMs = ttl; r.treatmentEndMs = core.status().treatmentEndMs;
    return r;
  }
  Request release() {
    Request r;
    r.op = Op::Release;
    strcpy(r.generation, core.status().generation);
    strcpy(r.owner, core.status().owner);
    strcpy(r.token, core.status().token);
    r.treatment = core.status().treatment; r.seq = core.status().seq + 1;
    snprintf(r.id, sizeof(r.id), "id-%u", idCounter++);
    return r;
  }
  Result start(uint8_t mask = 15, uint32_t ttl = 900000, uint64_t end = 0) {
    return core.submit(acquire(mask, ttl, end), now, TOKEN);
  }
};

static void startupAndBasicLease() {
  CASE("boot-is-off");
  Core c;
  CHECK(!c.status().connected && !c.status().active && c.outputMask() == 0);
  CHECK(!c.begin("short", 0));
  CHECK(c.status().reason == Reason::NonceFailure && !c.status().connected);
  CHECK(!c.begin("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 0));
  CHECK(c.begin(GEN, 0));
  CHECK(c.outputMask() == 0 && c.status().highwater == 0);
  CHECK(!c.begin(GEN, 0));
  CHECK(!c.status().connected && c.outputMask() == 0);
  CHECK(c.begin(GEN2, 0));

  CASE("grant-and-expire-all-relays");
  Fixture f;
  const Result r = f.start();
  CODE(r, Ok); CHECK(r.accepted && r.outputChanged && !r.duplicate);
  CHECK(f.core.outputMask() == 15 && f.core.status().active);
  CHECK(f.core.status().leaseUntilMs == 901000);
  CHECK(f.core.status().treatmentEndMs == 1801000);
  CHECK(f.core.status().highwater == 1 && f.core.status().seq == 1);
  CHECK(!f.core.status().challengeValid);
  CHECK(strcmp(f.core.status().token, TOKEN) == 0);
  CHECK(!f.core.update(900999)); CHECK(f.core.outputMask() == 15);
  CHECK(f.core.update(901000)); CHECK(f.core.outputMask() == 0);
  CHECK(!f.core.status().active && f.core.status().reason == Reason::Expired);
  CHECK(f.core.status().highwater == 1 && f.core.status().token[0] == '\0');
  CHECK(!f.core.update(901001));

  CASE("all-independent-masks");
  for (uint8_t mask = 1; mask < 16; ++mask) {
    Fixture each;
    CODE(each.start(mask, 5000), Ok);
    CHECK(each.core.outputMask() == mask);
    each.core.nativeOff(each.now + 1);
    CHECK(each.core.outputMask() == 0 && !each.core.status().active);
  }
}

static void delayAndChallengeBoundaries() {
  CASE("delay-cannot-extend-grant");
  Fixture f;
  Request r = f.acquire();
  const uint64_t issued = f.now;
  CODE(f.core.submit(r, f.now + 1999, TOKEN), Ok);
  CHECK(f.core.status().leaseUntilMs == issued + 900000);

  CASE("stale-at-exact-challenge-boundary");
  Fixture boundary;
  r = boundary.acquire();
  CODE(boundary.core.submit(r, boundary.now + 2000, TOKEN), MissingChallenge);
  CHECK(boundary.core.outputMask() == 0 && boundary.core.status().highwater == 0);

  CASE("ttl-expired-in-transit");
  Fixture delayed;
  r = delayed.acquire(1, 200);
  CODE(delayed.core.submit(r, delayed.now + 200, TOKEN), DeadlineExpired);
  CHECK(delayed.core.outputMask() == 0);
  CHECK(delayed.core.status().challengeValid);

  CASE("wrong-challenge-does-not-consume-right-challenge");
  Fixture wrong;
  r = wrong.acquire(); Request good = r;
  strcpy(r.challenge, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
  CODE(wrong.core.submit(r, wrong.now, TOKEN), StaleChallenge);
  CODE(wrong.core.submit(good, wrong.now, TOKEN), Ok);

  CASE("new-challenge-invalidates-old");
  Fixture rotated;
  r = rotated.acquire(); rotated.now += 1; rotated.challenge();
  CODE(rotated.core.submit(r, rotated.now, TOKEN), StaleChallenge);
  CHECK(rotated.core.outputMask() == 0);

  CASE("planned-end-caps-grant");
  Fixture cap;
  CODE(cap.start(15, 900000, cap.now + 100), Ok);
  CHECK(cap.core.status().leaseUntilMs == cap.now + 100);
  CHECK(cap.core.update(cap.now + 100));

  CASE("planned-end-must-be-future");
  Fixture past;
  r = past.acquire(1, 500, past.now);
  CODE(past.core.submit(r, past.now, TOKEN), DeadlineExpired);
  CHECK(past.core.outputMask() == 0);

  CASE("nonce-failure-revokes-authority");
  Fixture entropy;
  CODE(entropy.start(), Ok);
  CHECK(!entropy.core.issueChallenge(GEN, entropy.now));
  CHECK(entropy.core.outputMask() == 0 && !entropy.core.status().connected);
  CHECK(entropy.core.status().reason == Reason::NonceFailure);

  CASE("challenge-nonce-must-not-repeat");
  Fixture repeat;
  char old[33]; strcpy(old, repeat.core.status().challenge);
  CODE(repeat.start(), Ok);
  CHECK(!repeat.core.issueChallenge(old, repeat.now));
  CHECK(repeat.core.outputMask() == 0);

  CASE("new-token-must-be-valid-and-distinct");
  Fixture token;
  r = token.acquire();
  CODE(token.core.submit(r, token.now, r.challenge), NonceFailure);
  CHECK(token.core.outputMask() == 0 && !token.core.status().connected);
}

static void duplicatesAndTerminals() {
  CASE("duplicate-grant-never-renews");
  Fixture f;
  Request r = f.acquire(15, 5000);
  CODE(f.core.submit(r, f.now, TOKEN), Ok);
  const uint64_t deadline = f.core.status().leaseUntilMs;
  Result duplicate = f.core.submit(r, f.now + 1000);
  CODE(duplicate, Duplicate);
  CHECK(duplicate.accepted && duplicate.duplicate && !duplicate.outputChanged);
  CHECK(f.core.status().leaseUntilMs == deadline && f.core.status().seq == 1);
  Request changed = r; changed.ttlMs += 1;
  CODE(f.core.submit(changed, f.now + 1001), DuplicateMismatch);
  changed = r; changed.mask = 1;
  CODE(f.core.submit(changed, f.now + 1001), DuplicateMismatch);
  changed = r; strcpy(changed.owner, "owner-B");
  CODE(f.core.submit(changed, f.now + 1001), DuplicateMismatch);

  CASE("expire-before-duplicate-cache-hit");
  duplicate = f.core.submit(r, deadline);
  CODE(duplicate, Duplicate);
  CHECK(duplicate.accepted && duplicate.duplicate && duplicate.outputChanged);
  CHECK(!f.core.status().active && f.core.outputMask() == 0);
  CHECK(f.core.status().reason == Reason::Expired && f.core.status().leaseUntilMs == 0);

  CASE("duplicate-after-native-off-cannot-rearm");
  Fixture native;
  r = native.acquire(); CODE(native.core.submit(r, native.now, TOKEN), Ok);
  native.core.nativeOff(native.now + 1);
  CODE(native.core.submit(r, native.now + 2), Duplicate);
  CHECK(native.core.outputMask() == 0 && native.core.status().reason == Reason::NativeOff);

  CASE("release-is-terminal-and-idempotent");
  Fixture released;
  Request acquire = released.acquire();
  CODE(released.core.submit(acquire, released.now, TOKEN), Ok);
  Request release = released.release();
  CODE(released.core.submit(release, released.now + 1), Ok);
  CHECK(released.core.outputMask() == 0 && released.core.status().highwater == 1);
  CODE(released.core.submit(release, released.now + 2), Duplicate);
  CODE(released.core.submit(acquire, released.now + 3, TOKEN), RetiredTreatment);
  released.now += 4; released.challenge();
  Request resurrect = released.acquire();
  CODE(released.core.submit(resurrect, released.now, TOKEN), RetiredTreatment);
  resurrect = released.acquire(2, 5000, 0, 2);
  CODE(released.core.submit(resurrect, released.now, TOKEN), Ok);
  CHECK(released.core.outputMask() == 2 && released.core.status().highwater == 2);

  CASE("expired-renew-replay-cannot-rearm");
  Fixture expired;
  CODE(expired.start(1, 5000), Ok);
  expired.now += 100; expired.challenge();
  Request renew = expired.renew(1, 5000);
  CODE(expired.core.submit(renew, expired.now), Ok);
  const uint64_t until = expired.core.status().leaseUntilMs;
  CODE(expired.core.submit(renew, until), Duplicate);
  CHECK(expired.core.outputMask() == 0);
  expired.now = until + 1; expired.challenge();
  renew = expired.renew(1, 5000);
  strcpy(renew.token, TOKEN);
  CODE(expired.core.submit(renew, expired.now), RetiredTreatment);
  CHECK(expired.core.outputMask() == 0);
}

static void renewalAndOwnership() {
  CASE("renew-preserves-end-and-output-without-cycling");
  Fixture f;
  CODE(f.start(15), Ok);
  const uint64_t treatmentEnd = f.core.status().treatmentEndMs;
  f.now += 300000; f.challenge();
  Request r = f.renew();
  Result renewal = f.core.submit(r, f.now + 1000);
  CODE(renewal, Ok);
  CHECK(!renewal.outputChanged && f.core.outputMask() == 15);
  CHECK(f.core.status().leaseUntilMs == f.now + 900000);
  CHECK(f.core.status().treatmentEndMs == treatmentEnd);
  const uint64_t deadline = f.core.status().leaseUntilMs;
  CODE(f.core.submit(r, f.now + 2000), Duplicate);
  CHECK(f.core.status().leaseUntilMs == deadline);

  CASE("fresh-renewal-can-select-independent-mask");
  f.now += 3000; f.challenge();
  r = f.renew(5);
  CODE(f.core.submit(r, f.now), Ok);
  CHECK(f.core.outputMask() == 5);

  CASE("renewal-cannot-extend-immutable-end");
  f.now += 1; f.challenge();
  r = f.renew(5); r.treatmentEndMs += 1;
  CODE(f.core.submit(r, f.now), EndChanged);
  CHECK(f.core.status().challengeValid && f.core.status().treatmentEndMs == treatmentEnd);
  r.treatmentEndMs = treatmentEnd;
  CODE(f.core.submit(r, f.now), Ok);

  CASE("renewal-caps-at-original-end");
  Fixture capped;
  CODE(capped.start(15, 900000, capped.now + 10000), Ok);
  capped.now += 5000; capped.challenge();
  r = capped.renew(15, 900000);
  CODE(capped.core.submit(r, capped.now), Ok);
  CHECK(capped.core.status().leaseUntilMs == 11000);
  CHECK(capped.core.update(11000) && capped.core.outputMask() == 0);

  CASE("wrong-owner-token-treatment-sequence");
  Fixture own;
  CODE(own.start(), Ok); own.now += 1; own.challenge();
  r = own.renew(); Request good = r;
  strcpy(r.owner, "owner-B"); CODE(own.core.submit(r, own.now), WrongOwner);
  r = good; r.treatment += 1; CODE(own.core.submit(r, own.now), WrongTreatment);
  r = good; strcpy(r.token, "44444444444444444444444444444444");
  CODE(own.core.submit(r, own.now), InvalidToken);
  r = good; r.seq = 1; CODE(own.core.submit(r, own.now), StaleSequence);
  CHECK(own.core.status().seq == 1 && own.core.status().challengeValid);
  CODE(own.core.submit(good, own.now), Ok);

  CASE("active-treatment-cannot-be-replaced");
  own.now += 1; own.challenge();
  r = own.acquire(1, 1000, 0, 2);
  CODE(own.core.submit(r, own.now, TOKEN), Busy);
  CHECK(own.core.outputMask() == 15 && own.core.status().highwater == 1);

  CASE("release-does-not-require-challenge");
  Request release = own.release();
  CODE(own.core.submit(release, own.now + 3000), Ok);
  CHECK(own.core.outputMask() == 0 && own.core.status().reason == Reason::Released);

  CASE("uint32-sequence-does-not-wrap");
  Fixture sequence;
  CODE(sequence.start(), Ok); sequence.now += 1; sequence.challenge();
  r = sequence.renew(); r.seq = UINT32_MAX;
  CODE(sequence.core.submit(r, sequence.now), Ok);
  sequence.now += 1; sequence.challenge();
  r = sequence.renew(); r.seq = 0;
  CODE(sequence.core.submit(r, sequence.now), InvalidRequest);
  r.seq = 1; CODE(sequence.core.submit(r, sequence.now), StaleSequence);
  CHECK(sequence.core.outputMask() == 15);

  CASE("uint32-treatment-highwater-does-not-wrap");
  Fixture counter;
  r = counter.acquire(1, 1000, 0, UINT32_MAX);
  CODE(counter.core.submit(r, counter.now, TOKEN), Ok);
  counter.core.nativeOff(counter.now);
  counter.challenge(); r = counter.acquire();
  CODE(counter.core.submit(r, counter.now, TOKEN), RetiredTreatment);
  r.treatment = 0; CODE(counter.core.submit(r, counter.now, TOKEN), InvalidRequest);
}

static void lifecycleAndClocks() {
  CASE("disconnect-and-reconnect-invalidates-old-authority");
  Fixture f;
  Request old = f.acquire(); CODE(f.core.submit(old, f.now, TOKEN), Ok);
  f.now += 1; f.core.revoke(Reason::Disconnected, f.now);
  CHECK(f.core.outputMask() == 0 && !f.core.status().connected);
  CODE(f.core.submit(old, f.now + 1, TOKEN), NotConnected);
  CHECK(f.core.begin(GEN2, f.now + 2));
  CHECK(f.core.outputMask() == 0 && f.core.status().highwater == 0);
  CODE(f.core.submit(old, f.now + 2, TOKEN), WrongGeneration);
  f.now += 2; f.challenge();
  Request fresh = f.acquire(); CODE(f.core.submit(fresh, f.now, TOKEN), Ok);
  CHECK(f.core.outputMask() == 15);

  CASE("restart-revokes-immediately");
  f.core.revoke(Reason::Restart, f.now + 1);
  CHECK(f.core.outputMask() == 0 && f.core.status().reason == Reason::Restart);

  CASE("monotonic-clock-crosses-32-bit-wrap");
  Fixture wrap;
  wrap.now = UINT64_C(0xffffffff) - 100;
  wrap.challenge();
  CODE(wrap.start(1, 500), Ok);
  CHECK(wrap.core.status().leaseUntilMs == UINT64_C(0xffffffff) + 400);
  CHECK(!wrap.core.update(UINT64_C(0xffffffff) + 399));
  CHECK(wrap.core.outputMask() == 1);
  CHECK(wrap.core.update(UINT64_C(0xffffffff) + 400));
  CHECK(wrap.core.outputMask() == 0);

  CASE("unextended-32-bit-wrap-fails-off");
  Fixture backwards;
  CODE(backwards.start(), Ok);
  CHECK(backwards.core.update(backwards.now - 1));
  CHECK(backwards.core.outputMask() == 0 && !backwards.core.status().connected);
  CHECK(backwards.core.status().reason == Reason::ClockFault);
  CHECK(!backwards.core.begin(GEN2, backwards.now - 1));
  CHECK(backwards.core.begin(GEN2, backwards.now));

  CASE("maximum-safe-json-time-does-not-overflow");
  Fixture horizon;
  horizon.now = kMaximumProtocolTimeMs - 100;
  horizon.challenge();
  CODE(horizon.start(15, 900000, kMaximumProtocolTimeMs), Ok);
  CHECK(horizon.core.status().leaseUntilMs == kMaximumProtocolTimeMs);
  CHECK(horizon.core.update(kMaximumProtocolTimeMs));
  CHECK(horizon.core.outputMask() == 0);
  horizon.core.update(kMaximumProtocolTimeMs + 1);
  CHECK(horizon.core.status().reason == Reason::ClockFault);
  CHECK(!horizon.core.status().connected);

  CASE("uint64-overflow-horizon-fails-off");
  Fixture overflow;
  CODE(overflow.start(), Ok);
  CHECK(overflow.core.update(UINT64_MAX));
  CHECK(overflow.core.outputMask() == 0 && !overflow.core.status().connected);
  CHECK(!overflow.core.begin(GEN2, UINT64_MAX));
}

static void strictRequests() {
  CASE("strict-version-types-and-shapes");
  for (unsigned mutation = 0; mutation < 20; ++mutation) {
    Fixture f;
    Request r = f.acquire();
    switch (mutation) {
      case 0: r.version = 0; break;
      case 1: r.version = 2; break;
      case 2: r.op = static_cast<Op>(99); break;
      case 3: r.generation[0] = 'Z'; break;
      case 4: r.challenge[0] = '\0'; break;
      case 5: r.owner[0] = '\0'; break;
      case 6: r.owner[0] = '/'; break;
      case 7: memset(r.owner, 'a', sizeof(r.owner)); break;
      case 8: r.id[0] = '\0'; break;
      case 9: r.id[0] = ' '; break;
      case 10: memset(r.id, 'a', sizeof(r.id)); break;
      case 11: r.mask = 0; break;
      case 12: r.mask = 16; break;
      case 13: r.ttlMs = 0; break;
      case 14: r.ttlMs = 900001; break;
      case 15: r.treatment = 0; break;
      case 16: r.seq = 2; break;
      case 17: strcpy(r.token, TOKEN); break;
      case 18: r.treatmentEndMs = UINT64_MAX; break;
      case 19: r.treatmentEndMs = 0; break;
    }
    CODE(f.core.submit(r, f.now, TOKEN), InvalidRequest);
    CHECK(f.core.outputMask() == 0 && f.core.status().highwater == 0);
  }

  CASE("invalid-release-shape-does-not-release");
  for (unsigned mutation = 0; mutation < 4; ++mutation) {
    Fixture f; CODE(f.start(), Ok); Request r = f.release();
    switch (mutation) {
      case 0: strcpy(r.challenge, "22222222222222222222222222222222"); break;
      case 1: r.mask = 1; break;
      case 2: r.ttlMs = 1; break;
      case 3: r.treatmentEndMs = 1; break;
    }
    CODE(f.core.submit(r, f.now), InvalidRequest);
    CHECK(f.core.outputMask() == 15);
    f.core.nativeOff(f.now); CHECK(f.core.outputMask() == 0);
  }
}

static void adversarialSchedule() {
  CASE("adversarial-mixed-fake-clock-schedule");
  uint32_t random = 0x12345678;
  Fixture f;
  uint32_t treatment = 0;
  uint64_t knownUntil = 0;
  for (unsigned i = 0; i < 10000; ++i) {
    random = random * 1664525U + 1013904223U;
    f.now += random % 201;
    f.core.update(f.now);
    const uint8_t before = f.core.outputMask();
    const unsigned action = (random >> 16) % 7;
    if (!f.core.status().active) {
      if (action == 0) {
        f.challenge();
        Request r = f.acquire(static_cast<uint8_t>((random % 15) + 1),
          100 + random % 2000, f.now + 5000, ++treatment);
        const Result result = f.core.submit(r, f.now, TOKEN);
        CODE(result, Ok);
        knownUntil = f.core.status().leaseUntilMs;
      }
    } else if (action == 1) {
      f.challenge();
      Request r = f.renew(before, 100 + random % 2000);
      CODE(f.core.submit(r, f.now), Ok);
      knownUntil = f.core.status().leaseUntilMs;
    } else if (action == 2) {
      Request r = f.release(); CODE(f.core.submit(r, f.now), Ok);
    } else if (action == 3) {
      f.core.nativeOff(f.now);
    } else if (action == 4) {
      f.challenge();
      Request r = f.renew(before, 1000); r.seq = 1;
      CODE(f.core.submit(r, f.now), StaleSequence);
      CHECK(f.core.outputMask() == before && f.core.status().leaseUntilMs == knownUntil);
    }
    CHECK(f.core.outputMask() <= 15);
    CHECK(f.core.status().active == (f.core.outputMask() != 0));
    if (f.core.status().active) {
      CHECK(f.core.status().leaseUntilMs > f.now);
      CHECK(f.core.status().leaseUntilMs <= f.core.status().treatmentEndMs);
      CHECK(f.core.status().leaseUntilMs - f.now <= kMaximumLeaseMs);
    }
  }
}

int main() {
  startupAndBasicLease();
  delayAndChallengeBoundaries();
  duplicatesAndTerminals();
  renewalAndOwnership();
  lifecycleAndClocks();
  strictRequests();
  adversarialSchedule();
  printf("%u assertions; %u failures; Core=%zu bytes Request=%zu bytes\n",
    checks, failures, sizeof(Core), sizeof(Request));
  return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
