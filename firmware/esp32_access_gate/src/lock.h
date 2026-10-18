#pragma once

/**
 * Electric lock, driven through a one-channel relay.
 *
 * The class knows two independent inversions — whether the relay board is
 * driven low, and whether energizing the lock releases it — because getting
 * either wrong silently turns the gate into an open door.
 */

class Lock {
 public:
  void begin();

  void unlock();
  void relock();

  bool is_unlocked() const { return unlocked_; }

 private:
  void write_relay(bool energized);
  bool unlocked_ = false;
};
