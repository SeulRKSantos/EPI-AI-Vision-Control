#pragma once

#include <cstdint>

/**
 * WiFi and MQTT connectivity.
 *
 * Reconnection is non-blocking: the loop must keep running so the relock
 * timer still fires if the network drops while the lock is open.
 *
 * The topics and the payload shape here mirror
 * `backend/app/schemas/messages.py`. Changing either side alone breaks the
 * gate silently — the scan is published, nobody answers, and every attempt
 * times out into a refusal.
 */

class Net {
 public:
  /// Called when a decision arrives. `session_token` is the value echoed
  /// back from the scan we published.
  using DecisionHandler = void (*)(uint32_t session_token, bool granted,
                                   const char* missing_ppe);

  void begin(DecisionHandler handler);
  void loop(uint32_t now_ms);

  bool online() const;

  /// Publishes a badge scan. Returns false when the broker is unreachable,
  /// in which case no verification was started.
  bool publish_scan(uint32_t session_token, const char* badge_id);

  /// Availability message, also used as the Last Will payload.
  void publish_status(bool online);

 private:
  void ensure_wifi(uint32_t now_ms);
  void ensure_broker(uint32_t now_ms);
  void subscribe();

  uint32_t last_wifi_attempt_ms_ = 0;
  uint32_t last_broker_attempt_ms_ = 0;
  uint32_t last_heartbeat_ms_ = 0;
};

extern Net net;
