#include "indicators.h"

#include <Arduino.h>

#include "pins.h"

namespace {
constexpr uint32_t kWaitingPeriodMs = 300;
constexpr uint32_t kOfflinePeriodMs = 800;
constexpr uint32_t kIdlePeriodMs = 2000;
}  // namespace

void Indicators::begin() {
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  set(Mode::Starting);
}

void Indicators::write(bool green, bool red) {
  const bool g = LED_ACTIVE_HIGH ? green : !green;
  const bool r = LED_ACTIVE_HIGH ? red : !red;
  digitalWrite(PIN_LED_GREEN, g ? HIGH : LOW);
  digitalWrite(PIN_LED_RED, r ? HIGH : LOW);
}

void Indicators::set(Mode mode) {
  mode_ = mode;
  phase_start_ms_ = millis();
  phase_ = false;

  switch (mode) {
    case Mode::Granted:  write(true, false); break;
    case Mode::Denied:   write(false, true); break;
    case Mode::Starting: write(true, true);  break;
    default:             write(false, false); break;
  }
}

void Indicators::update(uint32_t now_ms) {
  uint32_t period = 0;
  switch (mode_) {
    case Mode::Waiting: period = kWaitingPeriodMs; break;
    case Mode::Offline: period = kOfflinePeriodMs; break;
    case Mode::Idle:    period = kIdlePeriodMs;    break;
    default: return;  // steady modes need no work
  }

  if (now_ms - phase_start_ms_ < period) return;
  phase_start_ms_ = now_ms;
  phase_ = !phase_;

  switch (mode_) {
    case Mode::Waiting:
      // Alternating: unmistakably different from either decision colour.
      write(phase_, !phase_);
      break;
    case Mode::Offline:
      write(false, phase_);
      break;
    case Mode::Idle:
      // A brief green pulse: the gate is alive and waiting for a badge.
      write(phase_, false);
      break;
    default:
      break;
  }
}
