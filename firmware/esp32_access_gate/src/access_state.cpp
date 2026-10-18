#include "access_state.h"

#include <cstring>

namespace gate {

namespace {

/**
 * Time from `since_ms` to `now_ms`, never negative.
 *
 * Events and ticks are stamped at slightly different moments: a decision is
 * stamped while the network is serviced, after the loop already read the
 * clock for its tick. Plain unsigned subtraction would turn "a few
 * milliseconds in the future" into roughly 49 days, ending every timed
 * state the instant it began — the lock would relock right after opening.
 * The signed difference is correct for any span under 24 days and also
 * survives millis() wrapping around.
 */
uint32_t elapsed_since(uint32_t now_ms, uint32_t since_ms) {
  const int32_t delta = static_cast<int32_t>(now_ms - since_ms);
  return delta > 0 ? static_cast<uint32_t>(delta) : 0;
}

}  // namespace

bool StateMachine::same_badge(const char* badge_id) const {
  return has_last_badge_ && std::strncmp(last_badge_, badge_id, kBadgeLen - 1) == 0;
}

void StateMachine::remember_badge(const char* badge_id) {
  std::strncpy(last_badge_, badge_id, kBadgeLen - 1);
  last_badge_[kBadgeLen - 1] = '\0';
  has_last_badge_ = true;
}

Outcome StateMachine::enter_idle() {
  state_ = State::Idle;
  session_token_ = 0;
  return {Action::ShowIdle, false};
}

Outcome StateMachine::enter_denied(uint32_t now_ms) {
  state_ = State::Denied;
  state_since_ms_ = now_ms;
  session_token_ = 0;
  return {Action::ShowDenied, false};
}

Outcome StateMachine::on_badge(const char* badge_id, uint32_t now_ms) {
  if (badge_id == nullptr || badge_id[0] == '\0') return {};

  // Without a broker there is nobody to decide, and a decision is the only
  // thing that opens this gate. Reading the badge would only mislead.
  if (state_ == State::Offline) return {Action::ShowOffline, false};

  // Only a settled gate starts a new verification.
  if (state_ != State::Idle) return {};

  if (same_badge(badge_id) &&
      elapsed_since(now_ms, last_badge_at_ms_) < config_.badge_cooldown_ms) {
    return {};
  }

  remember_badge(badge_id);
  last_badge_at_ms_ = now_ms;

  session_token_ = next_token_++;
  if (next_token_ == 0) next_token_ = 1;  // 0 marks "no session in flight"

  state_ = State::AwaitingDecision;
  state_since_ms_ = now_ms;
  return {Action::ShowWaiting, true};
}

Outcome StateMachine::on_decision(uint32_t session_token, bool granted, uint32_t now_ms) {
  // A decision for a session that is not in flight is discarded. This covers
  // the late answer that arrives after a timeout, a duplicate delivery, and
  // any message that was not asked for.
  if (state_ != State::AwaitingDecision) return {};
  if (session_token == 0 || session_token != session_token_) return {};

  if (!granted) return enter_denied(now_ms);

  state_ = State::Granted;
  state_since_ms_ = now_ms;
  session_token_ = 0;
  return {Action::Unlock, false};
}

Outcome StateMachine::tick(uint32_t now_ms) {
  const uint32_t elapsed = elapsed_since(now_ms, state_since_ms_);

  switch (state_) {
    case State::AwaitingDecision:
      // Silence is refusal. Leaving the attempt open would strand the person
      // in front of a gate that never answers.
      if (elapsed >= config_.decision_timeout_ms) return enter_denied(now_ms);
      return {};

    case State::Granted:
      if (elapsed >= config_.unlock_duration_ms) {
        state_ = State::Idle;
        return {Action::Relock, false};
      }
      return {};

    case State::Denied:
      if (elapsed >= config_.denied_display_ms) return enter_idle();
      return {};

    default:
      return {};
  }
}

Outcome StateMachine::on_connectivity(bool online, uint32_t now_ms) {
  if (!online) {
    // A grant already given is honoured to its end: the person was cleared,
    // and cutting the release early would trap them mid-passage. Anything
    // still awaiting a decision becomes a refusal.
    if (state_ == State::Granted) return {};

    const bool was_waiting = (state_ == State::AwaitingDecision);
    state_ = State::Offline;
    state_since_ms_ = now_ms;
    session_token_ = 0;
    return {was_waiting ? Action::ShowDenied : Action::ShowOffline, false};
  }

  if (state_ == State::Offline) return enter_idle();
  return {};
}

}  // namespace gate
