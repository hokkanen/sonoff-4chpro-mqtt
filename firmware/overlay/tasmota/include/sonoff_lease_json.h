/* Strict fixed-memory wire parser for the private Sonoff lease protocol.
 * GPL-3.0-or-later. Only the documented flat ASCII object is accepted: no
 * duplicate/unknown keys, escapes, nested values, coercions, or trailing data.
 */
#ifndef SONOFF_LEASE_JSON_H
#define SONOFF_LEASE_JSON_H
#include "sonoff_lease_core.h"
namespace sonoff_lease_wire {
static const size_t kMaximumRequestBytes = 640;
enum class Operation : uint8_t { Get, Challenge, Acquire, Renew, Release };
struct Message {
  Operation operation = Operation::Get;
  char device[18] = {};
  sonoff_lease::Request request;
};

class Parser {
 public:
  Parser(const uint8_t* data, size_t length) : data_(data), length_(length) {}
  bool parse(Message& message) {
    if (!data_ || !length_ || length_ > kMaximumRequestBytes || !take('{')) return false;
    uint16_t seen = 0;
    while (true) {
      char key[17];
      if (!string(key, sizeof(key)) || !take(':')) return false;
      const int field = fieldIndex(key);
      if (field < 0 || (seen & (1U << field))) return false;
      seen |= 1U << field;
      uint64_t number = 0;
      switch (field) {
        case Version:
          if (!integer(number) || number != 1) return false;
          break;
        case Op: {
          char value[10];
          if (!string(value, sizeof(value))) return false;
          if (!strcmp(value, "get")) message.operation = Operation::Get;
          else if (!strcmp(value, "challenge")) message.operation = Operation::Challenge;
          else if (!strcmp(value, "acquire")) { message.operation = Operation::Acquire; message.request.op = sonoff_lease::Op::Acquire; }
          else if (!strcmp(value, "renew")) { message.operation = Operation::Renew; message.request.op = sonoff_lease::Op::Renew; }
          else if (!strcmp(value, "release")) { message.operation = Operation::Release; message.request.op = sonoff_lease::Op::Release; }
          else return false;
          break;
        }
        case Id:
          if (!string(message.request.id, sizeof(message.request.id)) || !name(message.request.id)) return false;
          break;
        case Device:
          if (!string(message.device, sizeof(message.device)) || !mac(message.device)) return false;
          break;
        case Generation:
          if (!string(message.request.generation, sizeof(message.request.generation)) || !sonoff_lease::detail::nonce(message.request.generation)) return false;
          break;
        case Owner:
          if (!string(message.request.owner, sizeof(message.request.owner)) || !name(message.request.owner)) return false;
          break;
        case Treatment:
        case Sequence:
        case Mask:
        case Ttl:
          if (!integer(number) || number > UINT32_MAX) return false;
          if (field == Treatment) message.request.treatment = static_cast<uint32_t>(number);
          if (field == Sequence) message.request.seq = static_cast<uint32_t>(number);
          if (field == Mask) {
            if (number < 1 || number > 15) return false;
            message.request.mask = static_cast<uint8_t>(number);
          }
          if (field == Ttl) {
            if (!number || number > sonoff_lease::kMaximumLeaseMs) return false;
            message.request.ttlMs = static_cast<uint32_t>(number);
          }
          break;
        case Challenge:
          if (!string(message.request.challenge, sizeof(message.request.challenge)) || !sonoff_lease::detail::nonce(message.request.challenge)) return false;
          break;
        case Token:
          if (!string(message.request.token, sizeof(message.request.token)) || !sonoff_lease::detail::nonce(message.request.token)) return false;
          break;
        case End:
          if (!integer(number) || !number) return false;
          message.request.treatmentEndMs = number;
          break;
      }
      whitespace();
      if (position_ < length_ && data_[position_] == '}') { ++position_; break; }
      if (!take(',')) return false;
    }
    whitespace();
    if (position_ != length_) return false;
    const uint16_t common = fieldBit(Version) | fieldBit(Op) | fieldBit(Id) | fieldBit(Device);
    const uint16_t mutation = common | fieldBit(Generation) | fieldBit(Owner) | fieldBit(Treatment) | fieldBit(Sequence);
    uint16_t required = common;
    if (message.operation == Operation::Acquire || message.operation == Operation::Renew) {
      required = mutation | fieldBit(Challenge) | fieldBit(Mask) | fieldBit(Ttl) | fieldBit(End);
      if (message.operation == Operation::Renew) required |= fieldBit(Token);
    } else if (message.operation == Operation::Release) {
      required = mutation | fieldBit(Token);
    }
    if (seen != required) return false;
    return required == common || (message.request.treatment > 0 && message.request.seq > 0);
  }

  static bool name(const char* value) {
    size_t length = 0;
    for (; value[length]; ++length) {
      const char c = value[length];
      if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    }
    return length > 0 && length <= sonoff_lease::kNameChars;
  }

 private:
  enum Field : uint8_t { Version, Op, Id, Device, Generation, Owner, Treatment, Sequence, Challenge, Token, Mask, Ttl, End };
  const uint8_t* data_;
  size_t length_;
  size_t position_ = 0;
  static uint16_t fieldBit(Field field) { return 1U << field; }
  static int fieldIndex(const char* key) {
    static const char* const keys[] = {"v", "op", "id", "device", "generation", "owner", "treatment", "seq", "challenge", "token", "mask", "ttl_ms", "end_ms"};
    for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i) if (!strcmp(key, keys[i])) return static_cast<int>(i);
    return -1;
  }
  void whitespace() {
    while (position_ < length_ && (data_[position_] == ' ' || data_[position_] == '\t' || data_[position_] == '\r' || data_[position_] == '\n')) ++position_;
  }
  bool take(char expected) {
    whitespace();
    if (position_ >= length_ || data_[position_] != static_cast<uint8_t>(expected)) return false;
    ++position_;
    return true;
  }
  bool string(char* output, size_t capacity) {
    if (!take('"')) return false;
    size_t used = 0;
    while (position_ < length_) {
      const uint8_t c = data_[position_++];
      if (c == '"') { output[used] = '\0'; return true; }
      if (c < 0x20 || c > 0x7e || c == '\\' || used + 1 >= capacity) return false;
      output[used++] = static_cast<char>(c);
    }
    return false;
  }
  bool integer(uint64_t& result) {
    whitespace();
    if (position_ >= length_ || data_[position_] < '0' || data_[position_] > '9') return false;
    const bool leadingZero = data_[position_] == '0';
    size_t digits = 0;
    result = 0;
    while (position_ < length_ && data_[position_] >= '0' && data_[position_] <= '9') {
      const uint8_t digit = data_[position_++] - '0';
      if (++digits > 1 && leadingZero) return false;
      if (result > (sonoff_lease::kMaximumProtocolTimeMs - digit) / 10) return false;
      result = result * 10 + digit;
    }
    return true;
  }
  static bool mac(const char* value) {
    if (strlen(value) != 17) return false;
    for (size_t i = 0; i < 17; ++i) {
      if (i % 3 == 2) { if (value[i] != ':') return false; }
      else if (!((value[i] >= '0' && value[i] <= '9') || (value[i] >= 'A' && value[i] <= 'F'))) return false;
    }
    return true;
  }
};
}  // namespace sonoff_lease_wire
#endif
