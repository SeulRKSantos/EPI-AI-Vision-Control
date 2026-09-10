#pragma once

/**
 * Pin assignment and hardware polarity.
 *
 * Wiring
 * ------
 *   RC522 (SPI)        ESP32
 *     SDA / SS   ---->  GPIO 5
 *     SCK        ---->  GPIO 18
 *     MOSI       ---->  GPIO 23
 *     MISO       ---->  GPIO 19
 *     RST        ---->  GPIO 4
 *     3.3V       ---->  3V3        (never 5V: the RC522 is a 3.3V part)
 *     GND        ---->  GND
 *
 *   Relay module       ESP32
 *     IN         ---->  GPIO 26
 *     VCC        ---->  5V (module logic)
 *     GND        ---->  GND        (common ground with the ESP32)
 *
 *   Indicators         ESP32
 *     Green LED  ---->  GPIO 25    (through a 220-330R resistor)
 *     Red LED    ---->  GPIO 27    (through a 220-330R resistor)
 *
 * The 12V lock is powered by its own supply, switched by the relay contacts.
 * The ESP32 never carries lock current, and the two grounds are joined only
 * on the module's low-voltage side.
 */

#include <cstdint>

// --- RC522 --------------------------------------------------------------
constexpr uint8_t PIN_RFID_SS = 5;
constexpr uint8_t PIN_RFID_RST = 4;

// --- Relay --------------------------------------------------------------
constexpr uint8_t PIN_RELAY = 26;

/**
 * Most one-channel relay boards sold for hobby use are driven low: the coil
 * energizes when the input is pulled to ground. Set this false only after
 * checking the board — getting it wrong inverts the lock, which on a
 * fail-secure installation means the gate sits open.
 */
constexpr bool RELAY_ACTIVE_LOW = true;

/**
 * Whether energizing the relay releases the lock.
 *
 *   true  — fail-secure hardware (electric strike). The lock is closed at
 *           rest and the relay releases it. Loss of power leaves it locked.
 *           This is the assumption the firmware is written for.
 *
 *   false — fail-safe hardware (magnetic lock). The lock is held closed by
 *           power and releases when de-energized. Loss of power opens the
 *           door, which is what an emergency exit requires but which also
 *           means an outage removes the barrier entirely.
 *
 * Whichever is installed, the escape route must not depend on this firmware:
 * a mechanical release on the inside is required regardless.
 */
constexpr bool RELAY_ENERGIZE_TO_UNLOCK = true;

// --- Indicators ---------------------------------------------------------
constexpr uint8_t PIN_LED_GREEN = 25;
constexpr uint8_t PIN_LED_RED = 27;

/// True when the LEDs are wired from the pin to ground through a resistor,
/// which is the usual arrangement.
constexpr bool LED_ACTIVE_HIGH = true;
