# Gate firmware — ESP32

Reads a badge, asks the backend whether the person may pass, and releases the lock only when the answer says so.

The device decides nothing about PPE. It reports a badge and obeys a decision, which keeps the rules in the backend where they can be changed without reflashing anything.

## Circuit

| Component | Connection | ESP32 |
|---|---|---|
| RC522 | SDA / SS | GPIO 5 |
| | SCK | GPIO 18 |
| | MOSI | GPIO 23 |
| | MISO | GPIO 19 |
| | RST | GPIO 4 |
| | VCC | **3V3** |
| Relay module | IN | GPIO 26 |
| | VCC | **3V3** (see below) |
| Green LED | anode via 220–330 Ω | GPIO 25 |
| Red LED | anode via 220–330 Ω | GPIO 27 |

The RC522 is a 3.3 V part; powering it from 5 V damages it.

The relay module is fed from **3V3**, not 5V. Common 5V relay boards with an optocoupler input do not switch off from the ESP32's 3.3 V high level when fed from 5V: the relay stays on or chatters. Fed from 3V3, the input works at the pin's level, and the 5V coil on this board still pulls in reliably. If a different board does not pull in at 3.3 V, see the options in `include/pins.h`.

The lock is wired to the relay's **NC** contact: it is a lock that holds while powered, so at rest the relay is off and the lock is powered and closed; a grant energizes the relay, which cuts the lock's power for the release period. Loss of the 12 V supply releases the door, which is the expected behaviour on an escape route. The 12 V lock runs from its own supply and is switched by the relay contacts — the ESP32 never carries lock current. Grounds are joined only on the module's low-voltage side.

## Hardware bring-up

Before flashing the gate, check the wiring with the bench program in `src/hwtest`. It needs no `config.h` and no network:

```bash
pio run -e hwtest -t upload
pio device monitor -e hwtest
```

It reports whether the RC522 answers, prints the UID of every card held to the reader (in the exact format to register as a badge in the panel), and lets you drive the relay pin and the LEDs by hand from the serial monitor.

Use it to settle the two polarity constants:

1. With the lock disconnected, type `1` and `0`. The level that lights the relay module's LED energizes the coil. If that is `LOW`, keep `RELAY_ACTIVE_LOW = true`; if it is `HIGH`, set it to `false`.
2. With the lock connected, energize the coil. If the lock releases, keep `RELAY_ENERGIZE_TO_UNLOCK = true`; if it closes, set it to `false`.
3. Reflash the bench program and type `a`. The lock should open for three seconds and close again, exactly as the gate does on a grant.

## Lock polarity

Two settings in `include/pins.h` decide how the relay is driven, and both must match the hardware:

`RELAY_ACTIVE_LOW` — most one-channel boards energize when the input is pulled to ground. Check the board before trusting the default.

`RELAY_ENERGIZE_TO_UNLOCK` — `true` for fail-secure hardware (an electric strike, closed at rest, released by the relay); `false` for fail-safe hardware (a magnetic lock, held closed by power). Getting this backwards leaves the gate open at rest.

Whichever is installed, the escape route must not depend on this firmware. A mechanical release on the inside is required regardless.

## Indicators

| Pattern | Meaning |
|---|---|
| Green pulsing slowly | Ready, waiting for a badge |
| Green and red alternating | Verification in progress |
| Green steady | Access granted, lock released |
| Red steady | Access denied |
| Red blinking | No connection to the server; badges are not read |
| Both on | Starting up |

## Behaviour

The lock opens only on an explicit granted decision matching the verification currently in flight. Every other path leaves it closed: a timeout, a decision for an unknown session, a duplicate decision, a lost connection, a scan that could not be published.

Silence is refusal. If the backend does not answer within `DECISION_TIMEOUT_MS`, the attempt is denied rather than left hanging — a person should not be left in front of a gate that never responds.

A decision that arrives after its verification has ended is discarded. This covers the late answer, the duplicate delivery, and any message that was not asked for.

Losing the broker connection during a verification turns it into a refusal. Losing it while the lock is already open does not cut the release short: the person was cleared, and interrupting mid-passage would trap them.

The same badge is ignored for `BADGE_COOLDOWN_MS` after a read, so a card held against the reader does not start a second verification. The window is per badge — one person's scan does not block the next in line.

## Message contract

Mirrors `backend/app/schemas/messages.py`. Changing either side alone breaks the gate silently: the scan is published, nobody answers, and every attempt times out.

Published to `access/{gate_code}/badge/scan`:

```json
{ "session_id": "<uuid>", "gate_code": "gate-01", "badge_id": "A1B2C3D4" }
```

Received on `access/{gate_code}/decision`:

```json
{ "session_id": "<uuid>", "granted": true, "reason": "compliant", "missing_ppe": [] }
```

Availability is published to `access/{gate_code}/status`, also registered as the Last Will so the backend learns about a gate that disappeared without saying goodbye.

`badge_id` is the card UID as uppercase hex, which is what the backend matches against `employees.badge_id`. A card registered as `A1B2C3D4` will not match a reader emitting `a1:b2:c3:d4` — the formatting is part of the contract.

`scanned_at` is deliberately omitted: the gate has no reliable clock, and timestamps from a single source keep the audit log consistent.

## Timing

`DECISION_TIMEOUT_MS` must exceed the backend's `SESSION_TIMEOUT_SECONDS`. If the gate gives up first, a legitimate decision still in flight arrives to a closed session and the person is refused for no reason. The default leaves 4 seconds of margin over a backend configured at 8 seconds.

## Building

```bash
cp include/config.h.example include/config.h   # fill in WiFi, broker, gate code
pio run                                        # build
pio run -t upload                              # flash
pio device monitor                             # serial output at 115200
```

`config.h` is not versioned: it carries the credentials of the site where the gate is installed.

## Tests

The state machine holds the safety rules and has no Arduino dependency, so it runs on the desktop — no board, no flashing:

```bash
pio test -e native
```

Or directly:

```bash
g++ -std=c++17 -Isrc test/test_access_state/test_main.cpp src/access_state.cpp -o t && ./t
```

44 checks, weighted towards the paths that must never open the lock: late grants, unknown sessions, duplicate decisions, timeouts, disconnection during verification.

## Testing without hardware

The backend's simulation endpoint publishes a scan identical to the one this firmware emits, so the whole cycle can be exercised before a board exists:

```bash
curl -X POST http://<host>:8000/api/v1/gates/gate-01/simulate-scan \
  -H 'Content-Type: application/json' -d '{"badge_id":"BADGE001"}'
```

Watching `access/+/decision` on the broker shows what the gate would have received.
