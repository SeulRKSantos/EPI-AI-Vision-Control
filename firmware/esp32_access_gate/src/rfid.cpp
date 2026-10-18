#include "rfid.h"

#include <Arduino.h>
#include <MFRC522.h>
#include <SPI.h>

#include "pins.h"

namespace {
MFRC522 reader(PIN_RFID_SS, PIN_RFID_RST);

char hex_digit(uint8_t value) {
  return value < 10 ? static_cast<char>('0' + value)
                    : static_cast<char>('A' + (value - 10));
}
}  // namespace

void RfidReader::begin() {
  SPI.begin();
  reinit();
}

bool RfidReader::reinit() {
  reader.PCD_Init();
  delay(50);
  return responsive();
}

bool RfidReader::responsive() {
  // A reader that failed to initialize, or fell off the bus, reports version
  // 0x00 or 0xFF.
  version_ = reader.PCD_ReadRegister(MFRC522::VersionReg);
  healthy_ = (version_ != 0x00 && version_ != 0xFF);
  return healthy_;
}

bool RfidReader::read(char* out_uid, uint8_t out_size) {
  if (!healthy_ || out_uid == nullptr || out_size < 3) return false;
  if (!reader.PICC_IsNewCardPresent()) return false;
  if (!reader.PICC_ReadCardSerial()) return false;

  uint8_t written = 0;
  for (uint8_t i = 0; i < reader.uid.size; ++i) {
    if (written + 2 >= out_size) break;  // leave room for the terminator
    out_uid[written++] = hex_digit(reader.uid.uidByte[i] >> 4);
    out_uid[written++] = hex_digit(reader.uid.uidByte[i] & 0x0F);
  }
  out_uid[written] = '\0';

  reader.PICC_HaltA();
  reader.PCD_StopCrypto1();
  return written > 0;
}
