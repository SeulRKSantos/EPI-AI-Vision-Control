#pragma once

/**
 * Access gate state machine.
 *
 * Deliberately free of Arduino, WiFi and MQTT: it takes events and a
 * monotonic clock, and returns the actions the caller should perform. That
 * makes the part of the firmware where safety lives testable on a desktop,
 * without a board attached.
 *
 * The machine never opens the lock on its own. It opens only on an explicit
 * granted decision that matches the session currently in flight. Every other
 * path — timeout, unknown session, denial, disconnection — leaves the lock
 * where it is.
 */

#include <cstdint>

namespace gate {

enum class State : uint8_t {
  Idle,             // waiting for a badge
  AwaitingDecision, // scan published, waiting for the backend
  Granted,          // lock released, relock timer running
  Denied,           // refusal being shown to the person
  Offline,          // no broker connection; badges are not read
};

enum class Action : uint8_t {
  None,
  PublishScan,   // send the badge to the backend
  Unlock,        // energize the release
  Relock,        // return the lock to its resting state
  ShowWaiting,   // indicators: verification in progress
  ShowGranted,
  ShowDenied,
  ShowIdle,
  ShowOffline,
};

struct Config {
  /// How long to wait for the backend before refusing. Must exceed the
  /// backend's own session timeout, otherwise the gate gives up while a
  /// legitimate decision is still on its way.
  uint32_t decision_timeout_ms = 10000;
  /// How long the lock stays released after a grant.
  uint32_t unlock_duration_ms = 5000;
  /// How long the refusal is displayed before returning to idle.
  uint32_t denied_display_ms = 3000;
  /// Ignore repeated reads of the same badge within this window. Stops a
  /// card held against the reader from starting a second verification.
  uint32_t badge_cooldown_ms = 5000;
};

/// What the caller should do after feeding an event in.
struct Outcome {
  Action action = Action::None;
  bool publish_scan = false;
};

class StateMachine {
 public:
  explicit StateMachine(const Config& config) : config_(config) {}

  State state() const { return state_; }
  uint32_t current_session() const { return session_token_; }

  /// A badge was read. Returns whether the scan should be published.
  /// Refused while a verification is running, during cooldown for the same
  /// badge, or while offline.
  Outcome on_badge(const char* badge_id, uint32_t now_ms);

  /// A decision arrived for `session_token`. A token that does not match the
  /// session in flight is ignored: a late answer must not open the gate for
  /// an attempt that already ended.
  Outcome on_decision(uint32_t session_token, bool granted, uint32_t now_ms);

  /// Called every loop. Drives timeouts and the relock.
  Outcome tick(uint32_t now_ms);

  /// Broker connectivity changed. Losing the connection while waiting turns
  /// the attempt into a refusal rather than leaving it hanging.
  Outcome on_connectivity(bool online, uint32_t now_ms);

 private:
  static constexpr uint8_t kBadgeLen = 32;

  Outcome enter_denied(uint32_t now_ms);
  Outcome enter_idle();
  bool same_badge(const char* badge_id) const;
  void remember_badge(const char* badge_id);

  Config config_;
  State state_ = State::Offline;
  uint32_t state_since_ms_ = 0;
  uint32_t session_token_ = 0;
  uint32_t next_token_ = 1;

  char last_badge_[kBadgeLen] = {0};
  uint32_t last_badge_at_ms_ = 0;
  bool has_last_badge_ = false;
};

}  // namespace gate
