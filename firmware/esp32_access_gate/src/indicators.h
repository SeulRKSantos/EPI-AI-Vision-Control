#pragma once

#include <cstdint>

/**
 * Two-LED status display.
 *
 * Steady colours report a decision; blinking reports a condition of the gate
 * itself. Someone standing in front of it should be able to tell "wait" from
 * "refused" without reading anything.
 */
class Indicators {
 public:
  enum class Mode : uint8_t {
    Idle,      // green breathing slowly: gate ready
    Waiting,   // both alternating: verification in progress
    Granted,   // green steady
    Denied,    // red steady
    Offline,   // red blinking: no broker, badges are not read
    Starting,  // both on: boot
  };

  void begin();
  void set(Mode mode);
  /// Called every loop; drives the blinking patterns.
  void update(uint32_t now_ms);

 private:
  void write(bool green, bool red);

  Mode mode_ = Mode::Starting;
  uint32_t phase_start_ms_ = 0;
  bool phase_ = false;
};
