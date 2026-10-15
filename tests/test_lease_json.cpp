// The real Arduino core defines bit(): preserve this compile boundary.
#define bit(b) (1UL << (b))
#include "sonoff_lease_json.h"
#include <algorithm>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <utility>
#include <vector>

using sonoff_lease_wire::Message;
using sonoff_lease_wire::Operation;
using sonoff_lease_wire::Parser;
typedef std::vector<std::pair<std::string, std::string> > Fields;

static unsigned checks = 0;
static unsigned failures = 0;
static const char* group = "initial";
static void check(bool ok, const char* expression, unsigned line) {
  ++checks;
  if (!ok) { ++failures; fprintf(stderr, "%s:%u: %s\n", group, line, expression); }
}
#define CHECK(x) check((x), #x, __LINE__)
static bool parses(const std::string& body) {
  Message message;
  return Parser(reinterpret_cast<const uint8_t*>(body.data()), body.size()).parse(message);
}
static std::string object(const Fields& fields) {
  std::string out = "{";
  for (size_t i = 0; i < fields.size(); ++i) {
    if (i) out += ',';
    out += '"' + fields[i].first + "\":" + fields[i].second;
  }
  return out + '}';
}
static Fields base(const char* op = "get") {
  Fields fields;
  fields.push_back({"v", "1"});
  fields.push_back({"op", std::string("\"") + op + '"'});
  fields.push_back({"id", "\"read-example\""});
  fields.push_back({"device", "\"AA:BB:CC:DD:EE:FF\""});
  return fields;
}
static Fields mutation(const char* op = "acquire") {
  Fields fields = base(op);
  fields.push_back({"generation", "\"11111111111111111111111111111111\""});
  fields.push_back({"owner", "\"owner-A\""});
  fields.push_back({"treatment", "1"});
  fields.push_back({"seq", std::string(op) == "acquire" ? "1" : "2"});
  if (std::string(op) != "release") {
    fields.push_back({"challenge", "\"22222222222222222222222222222222\""});
    fields.push_back({"mask", "15"});
    fields.push_back({"ttl_ms", "900000"});
    fields.push_back({"end_ms", "1800000"});
  }
  if (std::string(op) != "acquire")
    fields.push_back({"token", "\"33333333333333333333333333333333\""});
  return fields;
}
static Fields replacing(Fields fields, const char* key, const std::string& value) {
  for (size_t i = 0; i < fields.size(); ++i)
    if (fields[i].first == key) { fields[i].second = value; return fields; }
  fields.push_back({key, value});
  return fields;
}
static void basicOperations() {
  group = "five canonical operations";
  CHECK(parses(object(base())));
  CHECK(parses(object(base("challenge"))));
  CHECK(parses(object(mutation("acquire"))));
  CHECK(parses(object(mutation("renew"))));
  CHECK(parses(object(mutation("release"))));
  Message parsed;
  const std::string body = object(mutation("renew"));
  CHECK(Parser(reinterpret_cast<const uint8_t*>(body.data()), body.size()).parse(parsed));
  CHECK(parsed.operation == Operation::Renew);
  CHECK(parsed.request.op == sonoff_lease::Op::Renew);
  CHECK(parsed.request.mask == 15 && parsed.request.ttlMs == 900000);
  CHECK(parsed.request.treatmentEndMs == 1800000);
  CHECK(parsed.request.seq == 2 && parsed.request.treatment == 1);
  CHECK(std::string(parsed.device) == "AA:BB:CC:DD:EE:FF");

  group = "required fields and operation-specific exact schemas";
  const char* operations[] = {"get", "challenge", "acquire", "renew", "release"};
  for (size_t op = 0; op < 5; ++op) {
    const Fields good = op < 2 ? base(operations[op]) : mutation(operations[op]);
    for (size_t field = 0; field < good.size(); ++field) {
      Fields missing = good;
      missing.erase(missing.begin() + field);
      CHECK(!parses(object(missing)));
      Fields duplicate = good;
      duplicate.push_back(good[field]);
      CHECK(!parses(object(duplicate)));
    }
    Fields unknown = good; unknown.push_back({"unexpected", "1"});
    CHECK(!parses(object(unknown)));
  }
  CHECK(!parses(object(replacing(base(), "mask", "1"))));
  CHECK(!parses(object(replacing(base("challenge"), "token", "\"33333333333333333333333333333333\""))));
  CHECK(!parses(object(replacing(mutation("acquire"), "token", "\"33333333333333333333333333333333\""))));
  CHECK(!parses(object(replacing(mutation("release"), "challenge", "\"22222222222222222222222222222222\""))));
  CHECK(!parses(object(replacing(mutation("release"), "mask", "1"))));
  CHECK(!parses(object(replacing(mutation("release"), "ttl_ms", "1"))));
  CHECK(!parses(object(replacing(mutation("release"), "end_ms", "1"))));
}

static void malformedAndBounds() {
  group = "malformed values and framing";
  const char* malformed[] = {
    "", "{}", "[]", "null", "{", "}", "{,}", "{\"v\":1,}",
    "{\"v\":1 \"op\":\"get\"}", "{\"v\" 1}", "{v:1}",
    "{\"v\":1}//comment", "{\"v\":1}\n{}", "{\"v\":1}\x01"
  };
  for (size_t i = 0; i < sizeof(malformed)/sizeof(malformed[0]); ++i) CHECK(!parses(malformed[i]));
  const std::string good = object(base());
  CHECK(parses(" \r\n\t" + good + "\t \n"));
  CHECK(!parses(good + "x"));
  CHECK(!parses(good + std::string(1, '\0')));
  std::string embedded = good; embedded.insert(embedded.find("read") + 2, 1, '\0');
  CHECK(!parses(embedded));
  Message emptyMessage;
  CHECK(!Parser(nullptr, good.size()).parse(emptyMessage));

  const char* invalidString[] = {"null", "true", "1", "{}", "[]", "\"bad\\nname\"",
    "\"bad\\u0041name\"", "\"bad\\\"name\"", "\"bad name\"", "\"bad/name\"", "\"\""};
  for (size_t i = 0; i < sizeof(invalidString)/sizeof(invalidString[0]); ++i)
    CHECK(!parses(object(replacing(base(), "id", invalidString[i]))));
  CHECK(!parses(object(replacing(base(), "id", std::string("\"bad") + char(0x80) + "name\""))));
  CHECK(!parses(object(replacing(base(), "op", "\"GET\""))));
  CHECK(!parses(object(replacing(base(), "op", "\"unsupported\""))));

  group = "maximum payload length";
  CHECK(good.size() < 640);
  CHECK(parses(good + std::string(640 - good.size(), ' ')));
  CHECK(!parses(good + std::string(641 - good.size(), ' ')));

  group = "name 40-byte boundary";
  CHECK(parses(object(replacing(base(), "id", '"' + std::string(40, 'A') + '"'))));
  CHECK(!parses(object(replacing(base(), "id", '"' + std::string(41, 'A') + '"'))));
  CHECK(parses(object(replacing(mutation(), "owner", '"' + std::string(40, 'a') + '"'))));
  CHECK(!parses(object(replacing(mutation(), "owner", '"' + std::string(41, 'a') + '"'))));
  CHECK(!parses(object(replacing(mutation(), "owner", "\"owner.with.dot\""))));

  group = "canonical hardware MAC";
  const char* invalidMac[] = {"aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "AABBCCDDEEFF",
    "AA:BB:CC:DD:EE:F", "AA:BB:CC:DD:EE:FFF", "AG:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF ", ""};
  for (size_t i = 0; i < sizeof(invalidMac)/sizeof(invalidMac[0]); ++i)
    CHECK(!parses(object(replacing(base(), "device", std::string("\"") + invalidMac[i] + '"'))));

  group = "nonce format and bounds";
  const char* invalidNonce[] = {"", "short", "1111111111111111111111111111111",
    "111111111111111111111111111111111", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "gggggggggggggggggggggggggggggggg", "1111111111111111111111111111111 "};
  const char* nonceKeys[] = {"generation", "challenge", "token"};
  for (size_t key = 0; key < 3; ++key)
    for (size_t i = 0; i < sizeof(invalidNonce)/sizeof(invalidNonce[0]); ++i)
      CHECK(!parses(object(replacing(mutation("renew"), nonceKeys[key], std::string("\"") + invalidNonce[i] + '"'))));
}

static void numericTypesAndOverflow() {
  group = "strict numeric grammar and types";
  const char* values[] = {"-1", "+1", "1.0", "1e0", "01", "00", "\"1\"", "true", "false", "null", "[]", "{}"};
  const char* numeric[] = {"v", "treatment", "seq", "mask", "ttl_ms", "end_ms"};
  for (size_t field = 0; field < 6; ++field)
    for (size_t i = 0; i < sizeof(values)/sizeof(values[0]); ++i)
      CHECK(!parses(object(replacing(mutation(), numeric[field], values[i]))));
  CHECK(!parses(object(replacing(base(), "v", "2"))));
  CHECK(!parses(object(replacing(base(), "v", "0"))));
  CHECK(!parses(object(replacing(mutation(), "treatment", "0"))));
  CHECK(!parses(object(replacing(mutation(), "seq", "0"))));
  CHECK(parses(object(replacing(mutation(), "treatment", "4294967295"))));
  CHECK(parses(object(replacing(mutation("renew"), "seq", "4294967295"))));
  CHECK(!parses(object(replacing(mutation(), "treatment", "4294967296"))));
  CHECK(!parses(object(replacing(mutation(), "seq", "4294967296"))));
  CHECK(!parses(object(replacing(mutation(), "end_ms", "9007199254740992"))));
  CHECK(!parses(object(replacing(mutation(), "end_ms", "18446744073709551615"))));
  CHECK(!parses(object(replacing(mutation(), "end_ms", "18446744073709551616"))));
  CHECK(!parses(object(replacing(mutation(), "end_ms", std::string(150, '9')))));
  CHECK(parses(object(replacing(mutation(), "end_ms", "9007199254740991"))));
  CHECK(!parses(object(replacing(mutation(), "end_ms", "0"))));
  CHECK(parses(object(replacing(mutation(), "ttl_ms", "1"))));
  CHECK(!parses(object(replacing(mutation(), "ttl_ms", "0"))));
  CHECK(!parses(object(replacing(mutation(), "ttl_ms", "900001"))));

  group = "mask validated before uint8 narrowing";
  const char* invalidMask[] = {"0", "16", "255", "256", "257", "271", "4294967295", "4294967296"};
  for (size_t i = 0; i < sizeof(invalidMask)/sizeof(invalidMask[0]); ++i)
    CHECK(!parses(object(replacing(mutation(), "mask", invalidMask[i]))));
  for (unsigned mask = 1; mask < 16; ++mask) {
    char value[12]; snprintf(value, sizeof(value), "%u", mask);
    CHECK(parses(object(replacing(mutation(), "mask", value))));
  }
}

static void fieldOrderAndTruncation() {
  group = "field-order permutations";
  uint32_t random = 0x81726354U;
  const char* operations[] = {"get", "challenge", "acquire", "renew", "release"};
  for (size_t op = 0; op < 5; ++op) {
    Fields fields = op < 2 ? base(operations[op]) : mutation(operations[op]);
    for (unsigned repeat = 0; repeat < 200; ++repeat) {
      for (size_t i = fields.size(); i > 1; --i) {
        random = random * 1664525U + 1013904223U;
        std::swap(fields[i - 1], fields[random % i]);
      }
      CHECK(parses(object(fields)));
    }
    const std::string valid = object(fields);
    group = "every truncated prefix rejects";
    for (size_t end = 0; end < valid.size(); ++end) CHECK(!parses(valid.substr(0, end)));
    group = "field-order permutations";
  }
}

int main() {
  basicOperations();
  malformedAndBounds();
  numericTypesAndOverflow();
  fieldOrderAndTruncation();
  printf("%u strict-parser assertions; %u failures\n", checks, failures);
  return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
