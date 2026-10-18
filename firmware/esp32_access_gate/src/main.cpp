/**
 * EPI-AI-Vision-Control — gate firmware.
 *
 * Reads a badge, asks the backend whether the person may pass, and releases
 * the lock only when the answer says so.
 *
 * The device decides nothing about PPE. It reports a badge and obeys a
 * decision, which keeps the rules in one place — the backend — where they
 * can be changed without reflashing anything.
 *
 * Everything here is non-blocking. The loop must keep turning even while a
 * verification is pending, because the relock timer runs on it: a blocking
 * wait would leave the lock open if the network stalled at the wrong moment.
 */

#include <Arduino.h>

#include "access_state.h"
#include "config.h"
#include "indicators.h"
#include "lock.h"
#include "net.h"
#include "pins.h"
#include "rfid.h"

namespace {

gate::Config make_config() {
  gate::Config c;
  c.decision_timeout_ms = DECISION_TIMEOUT_MS;
  c.unlock_duration_ms = UNLOCK_DURATION_MS;
  c.denied_display_ms = DENIED_DISPLAY_MS;
  c.badge_cooldown_ms = BADGE_COOLDOWN_MS;
  return c;
}

gate::StateMachine machine(make_config());
RfidReader rfid;
Lock lock;
Indicators leds;

bool was_online = false;

void apply(const gate::Outcome& outcome, const char* badge_id = nullptr) {
  switch (outcome.action) {
    case gate::Action::Unlock:
      lock.unlock();
      leds.set(Indicators::Mode::Granted);
      Serial.println(F("acesso liberado"));
      break;

    case gate::Action::Relock:
      lock.relock();
      leds.set(Indicators::Mode::Idle);
      Serial.println(F("fechadura retrancada"));
      break;

    case gate::Action::ShowWaiting:
      leds.set(Indicators::Mode::Waiting);
      break;

    case gate::Action::ShowGranted:
      leds.set(Indicators::Mode::Granted);
      break;

    case gate::Action::ShowDenied:
      leds.set(Indicators::Mode::Denied);
      Serial.println(F("acesso negado"));
      break;

    case gate::Action::ShowIdle:
      leds.set(Indicators::Mode::Idle);
      break;

    case gate::Action::ShowOffline:
      leds.set(Indicators::Mode::Offline);
      break;

    case gate::Action::None:
      break;
  }

  if (outcome.publish_scan && badge_id != nullptr) {
    if (!net.publish_scan(machine.current_session(), badge_id)) {
      // The scan never left. Treating this as a refusal is the honest
      // outcome: nobody is going to answer a message that was not sent.
      Serial.println(F("falha ao publicar leitura"));
      apply(machine.on_connectivity(false, millis()));
    } else {
      Serial.print(F("leitura publicada: "));
      Serial.println(badge_id);
    }
  }
}

void on_decision(uint32_t session_token, bool granted, const char* missing_ppe) {
  if (!granted && missing_ppe != nullptr && missing_ppe[0] != '\0') {
    Serial.print(F("EPI faltando: "));
    Serial.println(missing_ppe);
  }
  apply(machine.on_decision(session_token, granted, millis()));
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println(F("\nEPI-AI-Vision-Control — portao"));

  // The lock is put in its resting state before anything that can fail, so
  // an error further down never leaves the gate released.
  lock.begin();
  leds.begin();

  rfid.begin();
  if (!rfid.healthy()) {
    // Without a reader there is nothing to verify. Saying so is better than
    // standing there looking ready.
    Serial.println(F("ERRO: leitor RFID nao respondeu — verifique a ligacao SPI"));
    leds.set(Indicators::Mode::Offline);
  }

  net.begin(on_decision);
  Serial.print(F("portao: "));
  Serial.println(GATE_CODE);
}

void loop() {
  const uint32_t now = millis();

  net.loop(now);

  const bool online = net.online();
  if (online != was_online) {
    was_online = online;
    Serial.println(online ? F("conectado ao servidor") : F("sem conexao com o servidor"));
    apply(machine.on_connectivity(online, now));
  }

  if (rfid.healthy()) {
    char uid[RfidReader::kUidBufferSize];
    if (rfid.read(uid, sizeof(uid))) {
      apply(machine.on_badge(uid, now), uid);
    }
  }

  // A fresh reading: a decision handled in net.loop() above was stamped
  // after `now` was taken.
  apply(machine.tick(millis()));
  leds.update(now);
}
