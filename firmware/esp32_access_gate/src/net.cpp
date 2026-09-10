#include "net.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "config.h"

namespace {

constexpr uint32_t kWifiRetryMs = 5000;
constexpr uint32_t kBrokerRetryMs = 3000;

WiFiClient wifi_client;
PubSubClient broker(wifi_client);
Net::DecisionHandler decision_handler = nullptr;

char topic_scan[96];
char topic_decision[96];
char topic_status[96];
char client_id[48];

/**
 * The backend correlates by `session_id`, a UUID. The gate tracks sessions
 * with a small counter, so the two are bridged by embedding the counter in a
 * UUID whose remaining digits identify this device. The value that comes
 * back is parsed out of the same position.
 */
void session_to_uuid(uint32_t token, char* out, size_t size) {
  const uint32_t chip = static_cast<uint32_t>(ESP.getEfuseMac() & 0xFFFFFFFF);
  snprintf(out, size, "%08x-0000-4000-8000-%04x%08x", chip,
           static_cast<uint16_t>(token >> 16), token);
}

uint32_t uuid_to_session(const char* uuid) {
  // Last 12 hex digits: 4 high bits of the token, then the full 32-bit value.
  const size_t len = strlen(uuid);
  if (len < 12) return 0;
  return static_cast<uint32_t>(strtoul(uuid + len - 8, nullptr, 16));
}

void on_message(char* topic, byte* payload, unsigned int length) {
  if (decision_handler == nullptr) return;
  if (strcmp(topic, topic_decision) != 0) return;

  JsonDocument doc;
  if (deserializeJson(doc, payload, length) != DeserializationError::Ok) {
    Serial.println(F("decisao com payload invalido, descartada"));
    return;
  }

  const char* session_id = doc["session_id"] | "";
  const bool granted = doc["granted"] | false;

  static char missing[96];
  missing[0] = '\0';
  JsonArray items = doc["missing_ppe"].as<JsonArray>();
  for (JsonVariant item : items) {
    if (missing[0] != '\0') strncat(missing, ", ", sizeof(missing) - strlen(missing) - 1);
    strncat(missing, item.as<const char*>(), sizeof(missing) - strlen(missing) - 1);
  }

  decision_handler(uuid_to_session(session_id), granted, missing);
}

}  // namespace

Net net;

void Net::begin(DecisionHandler handler) {
  decision_handler = handler;

  snprintf(topic_scan, sizeof(topic_scan), "access/%s/badge/scan", GATE_CODE);
  snprintf(topic_decision, sizeof(topic_decision), "access/%s/decision", GATE_CODE);
  snprintf(topic_status, sizeof(topic_status), "access/%s/status", GATE_CODE);
  snprintf(client_id, sizeof(client_id), "gate-%s-%08x", GATE_CODE,
           static_cast<uint32_t>(ESP.getEfuseMac() & 0xFFFFFFFF));

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  broker.setServer(MQTT_HOST, MQTT_PORT);
  broker.setCallback(on_message);
  broker.setKeepAlive(15);
  broker.setBufferSize(512);
}

bool Net::online() const { return WiFi.isConnected() && broker.connected(); }

void Net::ensure_wifi(uint32_t now_ms) {
  if (WiFi.isConnected()) return;
  if (now_ms - last_wifi_attempt_ms_ < kWifiRetryMs) return;

  last_wifi_attempt_ms_ = now_ms;
  Serial.println(F("wifi: reconectando"));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void Net::ensure_broker(uint32_t now_ms) {
  if (!WiFi.isConnected() || broker.connected()) return;
  if (now_ms - last_broker_attempt_ms_ < kBrokerRetryMs) return;

  last_broker_attempt_ms_ = now_ms;
  Serial.println(F("mqtt: conectando"));

  // The Last Will is what tells the backend this gate went away without
  // saying goodbye — a power cut, a crash, a pulled cable.
  const bool connected =
      (MQTT_USERNAME[0] == '\0')
          ? broker.connect(client_id, topic_status, 1, true, "offline")
          : broker.connect(client_id, MQTT_USERNAME, MQTT_PASSWORD, topic_status,
                           1, true, "offline");

  if (connected) {
    Serial.println(F("mqtt: conectado"));
    subscribe();
    publish_status(true);
  }
}

void Net::subscribe() { broker.subscribe(topic_decision, 1); }

void Net::loop(uint32_t now_ms) {
  ensure_wifi(now_ms);
  ensure_broker(now_ms);
  broker.loop();

  if (online() && (now_ms - last_heartbeat_ms_ >= HEARTBEAT_INTERVAL_MS)) {
    last_heartbeat_ms_ = now_ms;
    publish_status(true);
  }
}

bool Net::publish_scan(uint32_t session_token, const char* badge_id) {
  if (!online()) return false;

  char session_id[48];
  session_to_uuid(session_token, session_id, sizeof(session_id));

  JsonDocument doc;
  doc["session_id"] = session_id;
  doc["gate_code"] = GATE_CODE;
  doc["badge_id"] = badge_id;
  // `scanned_at` is left out on purpose: the gate has no reliable clock, and
  // the backend timestamps the record from a single source anyway.

  char payload[192];
  const size_t written = serializeJson(doc, payload, sizeof(payload));
  if (written == 0) return false;

  // QoS 1: the decision depends on this message arriving.
  return broker.publish(topic_scan, reinterpret_cast<const uint8_t*>(payload),
                        written, false);
}

void Net::publish_status(bool is_online) {
  if (!broker.connected()) return;
  broker.publish(topic_status, is_online ? "online" : "offline", true);
}
