#pragma once

#include <cstdint>

/**
 * RC522 reader.
 *
 * Returns the card UID as uppercase hex. The UID is what the backend matches
 * against `employees.badge_id`, so the formatting here is part of the
 * contract with the database — a card registered as "A1B2C3D4" will not
 * match a reader that emits "a1:b2:c3:d4".
 */
class RfidReader {
 public:
  static constexpr uint8_t kUidBufferSize = 24;

  void begin();

  /// Reads a card if one is present. Returns false when there is none.
  /// `out_uid` receives a null-terminated uppercase hex string.
  bool read(char* out_uid, uint8_t out_size);

  /// True when the reader answered its self-test at startup. A reader that
  /// never initialized would otherwise look identical to "no card present".
  bool healthy() const { return healthy_; }

 private:
  bool healthy_ = false;
};
