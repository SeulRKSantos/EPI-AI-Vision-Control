#include "lock.h"

#include <Arduino.h>

#include "pins.h"

void Lock::begin() {
  pinMode(PIN_RELAY, OUTPUT);
  // Resting state is applied before anything else runs, so a reset never
  // leaves the lock released while the firmware is still starting.
  relock();
}

void Lock::write_relay(bool energized) {
  const bool level = RELAY_ACTIVE_LOW ? !energized : energized;
  digitalWrite(PIN_RELAY, level ? HIGH : LOW);
}

void Lock::unlock() {
  write_relay(RELAY_ENERGIZE_TO_UNLOCK);
  unlocked_ = true;
}

void Lock::relock() {
  write_relay(!RELAY_ENERGIZE_TO_UNLOCK);
  unlocked_ = false;
}
