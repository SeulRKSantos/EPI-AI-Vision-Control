/**
 * Hardware bring-up for the gate.
 *
 * A bench program, not the gate firmware. It checks the wiring one part at a
 * time and answers the two questions the gate cannot answer for itself:
 * which pin level energizes the relay, and whether an energized relay opens
 * or closes the lock. Both answers go into include/pins.h.
 *
 * Cards are read with the same driver the gate uses, so the UID printed here
 * is exactly the badge identifier to register in the panel.
 *
 * Build and run:
 *   pio run -e hwtest -t upload && pio device monitor -e hwtest
 *
 * Commands are single characters typed in the serial monitor.
 */

#include <Arduino.h>

#include "pins.h"
#include "../rfid.h"

namespace {

RfidReader rfid;

constexpr uint8_t kMaxCards = 16;
char seen[kMaxCards][RfidReader::kUidBufferSize];
uint8_t seen_count = 0;

bool relay_pin_high = false;
bool green_on = false;
bool red_on = false;
uint32_t flash_until_ms = 0;

// --- Relay ------------------------------------------------------------------

bool coil_energized(bool pin_high) {
  return RELAY_ACTIVE_LOW ? !pin_high : pin_high;
}

bool lock_released(bool pin_high) {
  return coil_energized(pin_high) == RELAY_ENERGIZE_TO_UNLOCK;
}

void write_relay_pin(bool high) {
  relay_pin_high = high;
  digitalWrite(PIN_RELAY, high ? HIGH : LOW);
}

/// The level the gate firmware holds at rest: lock closed, per pins.h.
bool resting_level() {
  const bool energized = !RELAY_ENERGIZE_TO_UNLOCK;
  return RELAY_ACTIVE_LOW ? !energized : energized;
}

void report_relay() {
  Serial.printf("  pino GPIO%u = %s\n", PIN_RELAY, relay_pin_high ? "HIGH" : "LOW");
  Serial.printf("  pelo pins.h atual (RELAY_ACTIVE_LOW=%s): bobina %s\n",
                RELAY_ACTIVE_LOW ? "true" : "false",
                coil_energized(relay_pin_high) ? "ENERGIZADA" : "desenergizada");
  Serial.printf("  pelo pins.h atual (RELAY_ENERGIZE_TO_UNLOCK=%s): fechadura %s\n",
                RELAY_ENERGIZE_TO_UNLOCK ? "true" : "false",
                lock_released(relay_pin_high) ? "LIBERADA" : "travada");
  Serial.println(F("  -> confira no modulo: LED do rele aceso = bobina energizada"));
}

void pulse_relay() {
  Serial.println(F("Pulsando o rele 5 vezes (ouca o clique)..."));
  for (int i = 0; i < 10; ++i) {
    write_relay_pin(!relay_pin_high);
    delay(400);
  }
  write_relay_pin(resting_level());
  Serial.println(F("Rele de volta ao repouso."));
}

void open_like_the_gate() {
  // Exactly what the gate does on a grant, using the constants in pins.h.
  // Run this last, after both constants are set, to confirm them together.
  Serial.println(F("Abrindo como o portao abriria (3 s)..."));
  write_relay_pin(!resting_level());
  digitalWrite(PIN_LED_GREEN, LED_ACTIVE_HIGH ? HIGH : LOW);
  delay(3000);
  write_relay_pin(resting_level());
  digitalWrite(PIN_LED_GREEN, LED_ACTIVE_HIGH ? LOW : HIGH);
  green_on = false;
  Serial.println(F("Retrancado. A fechadura abriu e fechou? Entao o pins.h esta certo."));
}

// --- LEDs -------------------------------------------------------------------

void write_led(uint8_t pin, bool on) {
  digitalWrite(pin, (on == LED_ACTIVE_HIGH) ? HIGH : LOW);
}

void blink_both() {
  Serial.println(F("Piscando os dois LEDs 3 vezes..."));
  for (int i = 0; i < 3; ++i) {
    write_led(PIN_LED_GREEN, true);
    write_led(PIN_LED_RED, false);
    delay(300);
    write_led(PIN_LED_GREEN, false);
    write_led(PIN_LED_RED, true);
    delay(300);
  }
  write_led(PIN_LED_RED, false);
  green_on = red_on = false;
}

// --- Reader -----------------------------------------------------------------

void start_reader() {
  rfid.begin();
  Serial.printf("RC522: VersionReg = 0x%02X -> ", rfid.version());
  if (!rfid.healthy()) {
    Serial.println(F("SEM RESPOSTA"));
    Serial.println(F("  Confira com a placa desligada:"));
    Serial.println(F("  - VCC no 3V3 (nunca 5V) e GND comum"));
    Serial.println(F("  - SDA->GPIO5  SCK->GPIO18  MOSI->GPIO23  MISO->GPIO19  RST->GPIO4"));
    Serial.println(F("  - jumpers firmes; protoboard com mau contato e a causa mais comum"));
    Serial.println(F("  Depois digite 'i' para tentar de novo."));
  } else if (rfid.version() == 0x91 || rfid.version() == 0x92) {
    Serial.println(F("ok (chip original)"));
  } else {
    Serial.println(F("ok (clone; costuma funcionar normalmente)"));
  }
}

void remember(const char* uid, bool* is_new) {
  for (uint8_t i = 0; i < seen_count; ++i) {
    if (strcmp(seen[i], uid) == 0) {
      *is_new = false;
      return;
    }
  }
  *is_new = true;
  if (seen_count < kMaxCards) {
    strncpy(seen[seen_count], uid, RfidReader::kUidBufferSize - 1);
    seen[seen_count][RfidReader::kUidBufferSize - 1] = '\0';
    ++seen_count;
  }
}

void list_cards() {
  if (seen_count == 0) {
    Serial.println(F("Nenhum cartao lido ainda."));
    return;
  }
  Serial.println(F("Cartoes lidos nesta sessao (use como 'Cracha' no painel):"));
  for (uint8_t i = 0; i < seen_count; ++i) {
    Serial.printf("  %u. %s\n", i + 1, seen[i]);
  }
}

// --- Menu -------------------------------------------------------------------

void help() {
  Serial.println(F("\nComandos:"));
  Serial.println(F("  1  pino do rele em HIGH"));
  Serial.println(F("  0  pino do rele em LOW"));
  Serial.println(F("  p  pulsar o rele 5 vezes"));
  Serial.println(F("  a  abrir como o portao abriria (usa o pins.h; teste final)"));
  Serial.println(F("  g  LED verde liga/desliga"));
  Serial.println(F("  r  LED vermelho liga/desliga"));
  Serial.println(F("  l  piscar os dois LEDs"));
  Serial.println(F("  c  listar cartoes lidos"));
  Serial.println(F("  i  reiniciar o leitor RFID"));
  Serial.println(F("  s  estado do rele"));
  Serial.println(F("  h  esta ajuda"));
  Serial.println(F("Aproxime um cartao do leitor a qualquer momento.\n"));
}

void handle(char command) {
  switch (command) {
    case '1': write_relay_pin(true);  report_relay(); break;
    case '0': write_relay_pin(false); report_relay(); break;
    case 'p': pulse_relay(); break;
    case 'a': open_like_the_gate(); break;
    case 'g':
      green_on = !green_on;
      write_led(PIN_LED_GREEN, green_on);
      Serial.printf("LED verde %s\n", green_on ? "ligado" : "desligado");
      break;
    case 'r':
      red_on = !red_on;
      write_led(PIN_LED_RED, red_on);
      Serial.printf("LED vermelho %s\n", red_on ? "ligado" : "desligado");
      break;
    case 'l': blink_both(); break;
    case 'c': list_cards(); break;
    case 'i': start_reader(); break;
    case 's': report_relay(); break;
    case 'h': help(); break;
    case '\r':
    case '\n':
    case ' ':
      break;
    default:
      Serial.printf("Comando '%c' desconhecido. Digite h para ajuda.\n", command);
  }
}

}  // namespace

void setup() {
  // The relay is put at rest before anything else, as the gate does.
  pinMode(PIN_RELAY, OUTPUT);
  write_relay_pin(resting_level());
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  write_led(PIN_LED_GREEN, false);
  write_led(PIN_LED_RED, false);

  Serial.begin(115200);
  delay(300);
  Serial.println(F("\n=== EPI-AI-Vision-Control: teste de hardware ==="));
  start_reader();
  Serial.println(F("Rele em repouso:"));
  report_relay();
  help();
}

void loop() {
  while (Serial.available() > 0) {
    handle(static_cast<char>(Serial.read()));
  }

  if (rfid.healthy()) {
    char uid[RfidReader::kUidBufferSize];
    if (rfid.read(uid, sizeof(uid))) {
      bool is_new = false;
      remember(uid, &is_new);
      Serial.printf("Cartao: %s%s\n", uid, is_new ? "   (novo)" : "");
      write_led(PIN_LED_GREEN, true);
      flash_until_ms = millis() + 300;
    }
  }

  if (flash_until_ms != 0 && static_cast<int32_t>(millis() - flash_until_ms) >= 0) {
    flash_until_ms = 0;
    write_led(PIN_LED_GREEN, green_on);
  }
}
