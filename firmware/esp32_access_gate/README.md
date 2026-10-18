# Gate firmware — ESP32

Reads a badge, asks the backend whether the person may pass, and releases the lock only when the answer says so.

The device decides nothing about PPE. It reports a badge and obeys a decision, which keeps the rules in the backend, where they change without reflashing anything.

## Circuit

| Component | Connection | ESP32 |
|---|---|---|
| RC522 | SDA / SS | GPIO 5 |
| | SCK | GPIO 18 |
| | MOSI | GPIO 23 |
| | MISO | GPIO 19 |
| | RST | GPIO 4 |
| | VCC | **3V3** |
| | IRQ | not connected |
| Relay module | IN | GPIO 26 |
| | VCC | **3V3** (see below) |
| | GND | GND |
| Green LED | anode via 220–330 Ω | GPIO 25 |
| Red LED | anode via 220–330 Ω | GPIO 27 |

The RC522 is a 3.3 V part; 5 V damages it.

**The relay module is fed from 3V3, not 5V.** Common 5V relay boards with an optocoupler input do not switch off from the ESP32's 3.3 V high level when fed from 5V: the relay stays on or chatters. No pin mode fixes this, open drain included, because the ESP32's protection diodes hold any pin at about 3.3 V. Fed from 3V3, the input works at the pin's level, and the 5V coil on this board still pulls in reliably. Other boards may not; `include/pins.h` describes the alternatives (a series diode, or an NPN transistor, which is the proper fix).

Sharing the 3V3 rail has a cost: switching the coil disturbs the reader's supply, and the RC522 can come out of it deaf to cards. The firmware re-initializes the reader after every relock and checks every 10 s that it still answers. 100 µF + 100 nF across the reader's supply, and moving the relay to its own driver, remove the cause.

**The lock is wired to the relay's NC contact.** It is a lock that holds while powered: at rest the relay is off and the lock is powered and closed; a grant energizes the relay, which cuts the lock's power for the release period.

```
12 V supply (+) ── COM
NC ─────────────── lock (+)
lock (−) ───────── 12 V supply (−)
```

The 12 V supply is not connected to the ESP32; the relay contacts isolate the two circuits. A 1N4007 across the lock terminals (cathode to +) protects the contact from the coil's switch-off spike.

Failure modes of this arrangement: if the ESP32 resets or hangs, the relay drops and the lock **stays closed**; if the 12 V supply fails, the lock **releases**, which is the expected behaviour on an escape route. Whichever lock is installed, the way out must not depend on this firmware: a mechanical release on the inside is required.

## Hardware bring-up

Before flashing the gate, check the wiring with the bench program in `src/hwtest`. It needs no `config.h` and no network:

```bash
pio run -e hwtest -t upload
pio device monitor -e hwtest
```

It reports whether the RC522 answers (`VersionReg` 0x91 or 0x92 is a genuine chip; clones report other values and usually work; 0x00 means nothing answered), prints the UID of every card held to the reader in the exact format to register in the panel, and drives the relay pin and the LEDs by hand: `1`/`0` relay pin high/low, `p` pulse, `a` open as the gate would, `g`/`r`/`l` LEDs, `c` list cards, `i` re-init reader, `h` help.

Use it to settle the two polarity constants in `include/pins.h`:

1. With the lock disconnected, type `1` and `0`. The level that lights the relay module's LED energizes the coil. `LOW` → keep `RELAY_ACTIVE_LOW = true`; `HIGH` → set it to `false`.
2. With the lock connected, energize the coil. If the lock releases, keep `RELAY_ENERGIZE_TO_UNLOCK = true`; if it closes, set it to `false`.
3. Reflash and type `a`. The lock should open for three seconds and close again.

`RELAY_ENERGIZE_TO_UNLOCK` answers one question: does energizing the relay release the lock? The answer depends on both the lock and the contact used. A lock that holds while powered, wired to NC (this installation), and a strike that releases when powered, wired to NO, are both `true`. Keep it `true` whenever possible, so the coil is energized only during a release.

## Indicators

| Pattern | Meaning |
|---|---|
| Green pulsing slowly | Ready, waiting for a badge |
| Green and red alternating | Verification in progress |
| Green steady | Access granted, lock released |
| Red steady (3 s) | Access denied |
| Red blinking | No connection to the server; badges are not read |
| Both on | Starting up |

## Behaviour

The lock opens only on an explicit granted decision whose session id is exactly that of the scan in flight. Every other path leaves it closed: a timeout, a decision for another session, a duplicate, a lost connection, a scan that could not be published.

Silence is refusal. If no decision arrives within `DECISION_TIMEOUT_MS`, the attempt is denied rather than left hanging.

Session ids carry the chip id, a random number drawn at every boot and a counter. Without the boot number, the counter restarting at 1 after a reset would reuse ids the backend already recorded, and every scan after a reboot would be rejected.

During the release period, and for `BADGE_COOLDOWN_MS` after any read of the same card, badges are ignored: a person who was cleared does not start a second verification. Losing the broker connection during a verification turns it into a refusal; losing it while the lock is open does not cut the release short.

Elapsed times are computed so that an event stamped a few milliseconds after the loop read the clock, as a decision is, never reads as hours in the past, and they survive `millis()` wrapping after 49 days.

## Message contract

Mirrors `backend/app/schemas/messages.py`. Changing either side alone breaks the gate silently.

Published to `access/{gate_code}/badge/scan`:

```json
{ "session_id": "<uuid>", "gate_code": "gate-01", "badge_id": "769F8205" }
```

Received on `access/{gate_code}/decision`:

```json
{ "session_id": "<uuid>", "granted": true, "reason": "compliant", "missing_ppe": [] }
```

Availability is published, retained, to `access/{gate_code}/status` (`online`/`offline`), also registered as the Last Will so the backend learns about a gate that disappeared without saying goodbye.

`badge_id` is the card UID as uppercase hex, the format the backend stores. `scanned_at` is omitted on purpose: the gate has no reliable clock, and timestamps from one source keep the audit log consistent.

## Configuration

`include/config.h` (copied from `config.h.example`, never committed: it holds the Wi-Fi password):

| Setting | Default | Purpose |
|---|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | — | A **2.4 GHz** network; the ESP32 has no 5 GHz radio |
| `MQTT_HOST` / `MQTT_PORT` | — / `1883` | The server's LAN address (`hostname -I`) |
| `GATE_CODE` | `gate-01` | Must exist in the backend's `gates` table |
| `DECISION_TIMEOUT_MS` | `12000` | Must exceed the backend's `SESSION_TIMEOUT_SECONDS` |
| `UNLOCK_DURATION_MS` | `20000` | How long the lock stays released after a grant |
| `DENIED_DISPLAY_MS` | `3000` | How long a refusal is shown |
| `BADGE_COOLDOWN_MS` | `5000` | Repeated reads of the same card ignored |
| `HEARTBEAT_INTERVAL_MS` | `30000` | Availability message interval |

Pins and relay polarity live in `include/pins.h`.

## Building and flashing

One-time setup on Linux:

```bash
pip install --user platformio
sudo usermod -aG dialout $USER     # then log out and back in
curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/platformio/assets/system/99-platformio-udev.rules \
  | sudo tee /etc/udev/rules.d/99-platformio-udev.rules
```

On Ubuntu, if the board connects and immediately disappears, `sudo apt remove brltty`.

```bash
cp include/config.h.example include/config.h   # fill in Wi-Fi, broker, gate code
pio run -e esp32dev -t upload                  # build and flash
pio device monitor -e esp32dev -f time         # serial output, timestamped
```

If the upload stalls at `Connecting....`, hold the board's BOOT button. The port may change between `/dev/ttyACM0` and `ttyACM1` after reconnecting; `pio device list` shows it. Opening the monitor resets the board on most DevKits, and the gate is offline for a few seconds while it reconnects. The gate prints only on events, so a quiet monitor is normal: press EN or present a card.

The ESP32 Arduino toolchain compiles as **C++11**. Code that builds in the desktop tests (C++17) can still fail on the board; aggregates with default member initializers are the usual trap.

## Watching it work

```bash
docker compose exec mosquitto mosquitto_sub -v -t 'access/#' -t 'vision/#'
```

shows every scan, vision request and result, decision and status message as they happen.

## Tests

The state machine holds the safety rules and has no Arduino dependency, so it runs on the desktop, no board needed:

```bash
pio test -e native
```

or, without PlatformIO:

```bash
g++ -std=c++17 -Isrc test/test_access_state/test_main.cpp src/access_state.cpp -o t && ./t
```

21 tests, 52 checks, weighted towards the paths that must never open the lock (late grants, unknown sessions, duplicates, timeouts, disconnection during verification) and towards timing: a decision stamped after the loop's clock reading, and `millis()` wrapping around.

## Testing without hardware

The backend's simulation endpoint publishes a scan identical to the one this firmware emits:

```bash
curl -X POST http://<host>:8000/api/v1/gates/gate-01/simulate-scan \
  -H 'Content-Type: application/json' -d '{"badge_id":"BADGE001"}'
```
