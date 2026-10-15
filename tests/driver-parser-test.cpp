#include <assert.h>
#include <iostream>
#include <string>
#include <stdint.h>
#include "sonoff_lease_json.h"

static size_t checks = 0;
static bool parse(const std::string& body) {
  sonoff_lease_wire::Message request;
  ++checks;
  return sonoff_lease_wire::Parser(reinterpret_cast<const uint8_t*>(body.data()), body.size()).parse(request);
}
static std::string changed(std::string body, const std::string& before, const std::string& after) {
  const size_t position = body.find(before);
  assert(position != std::string::npos);
  body.replace(position, before.size(), after);
  return body;
}
int main() {
  const std::string get = "{\"v\":1,\"op\":\"get\",\"id\":\"test_1\",\"device\":\"AA:BB:CC:DD:EE:FF\"}";
  const std::string acquire = "{\"v\":1,\"op\":\"acquire\",\"id\":\"test_2\",\"device\":\"AA:BB:CC:DD:EE:FF\",\"generation\":\"11111111111111111111111111111111\",\"challenge\":\"22222222222222222222222222222222\",\"owner\":\"master-1\",\"treatment\":1,\"seq\":1,\"mask\":15,\"ttl_ms\":900000,\"end_ms\":9007199254740991}";
  const std::string renew = changed(changed(acquire, "\"acquire\"", "\"renew\""), "\"owner\"", "\"token\":\"33333333333333333333333333333333\",\"owner\"");
  const std::string release = "{\"v\":1,\"op\":\"release\",\"id\":\"test_3\",\"device\":\"AA:BB:CC:DD:EE:FF\",\"generation\":\"11111111111111111111111111111111\",\"owner\":\"master-1\",\"treatment\":1,\"seq\":3,\"token\":\"33333333333333333333333333333333\"}";
  assert(parse(get)); assert(parse(" \r\n" + get + "\t"));
  assert(parse(changed(get, "\"get\"", "\"challenge\"")));
  assert(parse(acquire)); assert(parse(renew)); assert(parse(release));
  assert(!parse(changed(get, "\"v\":1", "\"v\":1,\"v\":1")));
  assert(!parse(changed(get, "\"v\":1", "\"extra\":1,\"v\":1")));
  assert(!parse(changed(get, "\"v\":1", "\"v\":\"1\"")));
  assert(!parse(changed(get, "\"v\":1", "\"v\":true")));
  assert(!parse(changed(get, "\"v\":1", "\"v\":01")));
  assert(!parse(changed(get, "\"v\":1", "\"v\":1.0")));
  assert(!parse(changed(get, "\"v\":1", "\"v\":1e0")));
  assert(!parse(changed(get, "\"v\":1", "\"v\":-1")));
  assert(!parse(changed(get, "\"get\"", "\"GET\"")));
  assert(!parse(changed(get, "test_1", "test\\u005f1")));
  assert(!parse(changed(get, "test_1", "test 1")));
  assert(!parse(changed(get, "test_1", std::string(41, 'a'))));
  assert(!parse(changed(get, "test_1", "")));
  assert(!parse(changed(get, "AA:BB", "aa:bb")));
  assert(!parse(changed(get, ",\"id\":\"test_1\"", "")));
  assert(!parse(changed(get, "\"op\":\"get\"", "\"op\":{\"name\":\"get\"}")));
  assert(!parse(changed(acquire, "\"mask\":15", "\"mask\":16")));
  assert(!parse(changed(acquire, "\"mask\":15", "\"mask\":256")));
  assert(!parse(changed(acquire, "\"ttl_ms\":900000", "\"ttl_ms\":900001")));
  assert(!parse(changed(acquire, "\"ttl_ms\":900000", "\"ttl_ms\":0")));
  assert(!parse(changed(acquire, "\"treatment\":1", "\"treatment\":4294967296")));
  assert(!parse(changed(acquire, "\"treatment\":1", "\"treatment\":0")));
  assert(!parse(changed(acquire, "9007199254740991", "9007199254740992")));
  assert(!parse(changed(acquire, "9007199254740991", std::string(80, '9'))));
  assert(!parse(changed(acquire, "22222222222222222222222222222222", "2222222222222222222222222222222G")));
  assert(!parse(changed(release, "\"op\":\"release\"", "\"op\":\"acquire\"")));
  assert(!parse(changed(acquire, "\"acquire\"", "\"renew\"")));
  assert(!parse(get + "{}")); assert(!parse(get + std::string(1, '\0')));
  assert(!parse(get.substr(0, get.size()-1) + ",}"));
  assert(!parse("[" + get + "]")); assert(!parse(std::string(641, ' ')));
  for (const std::string& body : {get, acquire, renew, release}) {
    for (size_t length = 0; length < body.size(); ++length) assert(!parse(body.substr(0, length)));
    // Exhaustive single-byte substitutions exercise bounds and invalid encodings.
    for (size_t position = 0; position < body.size(); ++position) {
      for (uint32_t byte = 0; byte < 256; ++byte) {
        std::string mutated = body; mutated[position] = static_cast<char>(byte);
        parse(mutated);
      }
    }
  }
  uint32_t random = 0x65432109;
  for (size_t n = 0; n < 20000; ++n) {
    random = random * 1664525U + 1013904223U;
    std::string bytes(random % 700, '\0');
    for (char& c : bytes) { random = random * 1664525U + 1013904223U; c = static_cast<char>(random >> 24); }
    parse(bytes);
  }
  std::cout << "Strict parser: " << checks << " adversarial inputs checked\n";
}
