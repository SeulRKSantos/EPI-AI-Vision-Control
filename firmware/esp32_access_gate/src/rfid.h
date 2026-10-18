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

  /// Re-initializes the reader. The RC522 can stop detecting cards after a
  /// dip or spike on its supply — the relay switching on a shared 3.3V rail
  /// does exactly that — while still looking alive. A re-init clears it.
  /// Returns whether the reader answered afterwards.
  bool reinit();

  /// Reads the version register now. False when nothing answers on the bus.
  bool responsive();

  /// Reads a card if one is present. Returns false when there is none.
  /// `out_uid` receives a null-terminated uppercase hex string.
  bool read(char* out_uid, uint8_t out_size);

  /// True when the reader answered its self-test at startup. A reader that
  /// never initialized would otherwise look identical to "no card present".
  bool healthy() const { return healthy_; }

  /// Raw VersionReg value read at startup. Genuine chips answer 0x91 or
  /// 0x92; clones often report other values and still work. 0x00 or 0xFF
  /// means nothing answered on the SPI bus.
  uint8_t version() const { return version_; }

 private:
  bool healthy_ = false;
  uint8_t version_ = 0;
};
