# Revokyte Telemetry Protocol v1

**Status:** Draft for v1.1 (wire-compatible with 1.0 — see Revision history) · **License:** [CC-BY 4.0](../LICENSES/CC-BY-4.0.txt) (see [§9](#9-license-and-intellectual-property))

The Revokyte Telemetry Protocol carries real-time vehicle telemetry from a
*sender* (a game-specific feed program) to a *receiver* (a Revokyte instrument
cluster) as JSON frames over UDP. It is intentionally simple: one self-contained
JSON object per datagram, no handshake, no session, no acknowledgement. A
receiver renders whatever channels the sender provides and leaves the rest of
its gauges inactive.

This document is the normative specification. Version 1 **codifies the wire
behavior of shipped Revokyte devices and feeds**; it does not redesign it.
Anyone may implement it, including in proprietary software, without any
license from the Revokyte project (see §9).

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted
as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

A machine-readable JSON Schema for the frame accompanies this document:
[`telemetry-frame.v1.schema.json`](telemetry-frame.v1.schema.json) (CC0-1.0).

---

## 1. Roles and terminology

| Term | Meaning |
|---|---|
| **Frame** | One JSON object describing the vehicle state at an instant. The unit of transmission. |
| **Sender** | Any program that emits frames: a feed proxy running on the cluster appliance (e.g. the GT7 feed), an agent running on the game PC (e.g. the ACC shared-memory agent), or third-party software (e.g. a SimHub plugin). |
| **Receiver** | The instrument cluster application listening on a UDP port, or any other conforming consumer. |
| **Channel** | One field of the frame. Channels are independent: each is optional, and a sender fills only what its source game provides. |

The protocol is strictly one-directional. A receiver never sends anything to a
sender; discovery and configuration happen out of band (§2.5).

## 2. Transport

### 2.1 Datagram framing

- A frame is one JSON object ([RFC 8259](https://www.rfc-editor.org/rfc/rfc8259)),
  encoded as **UTF-8**, sent as the payload of **one UDP datagram**.
- The **datagram is the frame boundary**. Senders MUST NOT put more than one
  JSON object in a datagram and MUST NOT split a frame across datagrams. A
  receiver MUST discard any datagram whose payload is not exactly one valid
  JSON object (a batched datagram is discarded *whole*).
- Senders SHOULD terminate the object with a single `\n` (newline). Receivers
  MUST accept frames with or without trailing whitespace. (The newline makes a
  captured stream a valid NDJSON file; on the wire it is cosmetic.)
- There is no compression, no encryption and no framing header in v1.

### 2.2 Size limits

- Receivers MUST accept datagram payloads up to **4096 bytes** and MAY discard
  larger ones. (The reference receiver reads with a 4096-byte buffer; a larger
  datagram is truncated by the socket layer and then discarded as malformed.)
- Senders on a network path SHOULD keep frames at or below **1400 bytes** so a
  frame fits one Ethernet/Wi-Fi MTU. Larger datagrams are IP-fragmented: they
  still arrive (reassembled, up to the 4096-byte cap) but the loss of any one
  fragment loses the whole frame, which measurably hurts on Wi-Fi. A frame
  carrying every defined channel fits in ~1.3 kB; staying under the limit is a
  matter of not sending undefined keys.
- Loopback senders (feed proxies on the appliance itself) are exempt from the
  1400-byte recommendation but not from the 4096-byte cap.

### 2.3 Send rate

- Senders SHOULD emit frames at the rate their source provides, up to **60 Hz**.
  60 Hz matches the receiver's render loop; sending faster is wasted work
  (the receiver keeps only the latest frame).
- Senders SHOULD sustain at least **5 Hz** while a session is active, even if
  the underlying source updates more slowly (e.g. a game API polled every
  100 ms), so that receiver liveness (§2.4) is comfortably maintained.
- There is no pacing, batching or retransmission. Loss is acceptable; the next
  frame supersedes everything before it.

### 2.4 Liveness

Receivers treat the *arrival of a valid frame* as proof of life:

- A receiver declares the link **stale** when no valid frame has arrived for
  **1 second** (relaxed to **10 seconds** while the most recent frame declared
  `flags.paused` or `flags.loading_or_processing` true). A stale link is
  surfaced to the driver; gauge values are retained but marked untrusted.
- Only a frame that **parses and validates** resets staleness. Malformed,
  oversized or batched datagrams do not.
- Frames are receiver-stamped on arrival (§3.4 `received_time`); a re-sent
  frame with identical content therefore counts as fresh.

Sender guidance that follows from this:

- **Keep sending while paused.** When the game is paused or loading, senders
  SHOULD continue emitting frames with `flags.paused` (or
  `flags.loading_or_processing`) set true, rather than going silent. A sender
  that goes silent without ever sending a paused frame will trip the 1-second
  threshold and the receiver will report signal loss.
- **Bridge short gaps by replaying.** When the source goes quiet unexpectedly
  (Wi-Fi loss burst, game-side re-registration), senders SHOULD re-send the
  last frame every ~250 ms for up to **3 seconds**, then stop. This holds the
  readout through transient gaps while still letting a real outage surface as
  signal loss. Replayed frames are byte-identical re-sends; no field needs to
  change.

### 2.5 Addressing and discovery

- The receiver listens on UDP port **5600**.
- **Local senders** (feed proxies installed on the appliance) send to
  `127.0.0.1:5600`. When only local senders are in use, the reference receiver
  binds `127.0.0.1` and additionally ignores datagrams whose source address is
  not `127.0.0.1`.
- **Network senders** (game-PC agents, third-party feeds) send to the
  cluster's LAN address on port 5600. The reference receiver binds `0.0.0.0`
  once a network sender has been paired. There is no firewall on the
  appliance; the port is reachable whenever the receiver is bound to it.
- A sender configured with both a **hostname** and a **literal IP** for the
  receiver MUST prefer the hostname while it resolves and fall back to the
  literal IP while it does not. Hostname resolution MUST happen off the send
  path (a blocked mDNS lookup can take seconds) and SHOULD be refreshed
  periodically (the reference agent re-resolves every 30 s) so the sender
  follows the receiver across DHCP lease changes.
- The cluster's hostname is `instrument-cluster.local` on shipped devices.
  **Whether that name is resolvable is deployment-dependent in v1**: some
  images and networks advertise it via mDNS, others do not. The literal-IP
  fallback is therefore mandatory, not optional, for network senders.
- **Configuration handoff:** when the cluster hands a sender bundle to the
  game PC (over its pairing web page), it rewrites the bundle's `config.json`
  with two keys:

  ```json
  {
    "output": "udp://192.168.1.62:5600",
    "output_mdns": "udp://instrument-cluster.local:5600"
  }
  ```

  `output` is the always-usable literal address; `output_mdns` is the
  preferred hostname address and MAY be absent. Third-party senders that want
  zero-configuration pairing SHOULD accept the same two keys with the same
  precedence. Sender-local overrides (CLI flags, environment) take precedence
  over `config.json`.

### 2.6 Single active sender

Exactly **one sender** may target a receiver at a time. The receiver has no
sender identity, no demultiplexing and no session concept: it keeps the last
valid frame regardless of origin. Two concurrent senders interleave at frame
granularity — gauges alternate between the two sources at up to 60 Hz — which
is a misconfiguration, not a supported mode. Sender packages SHOULD actively
prevent double-sending (the reference ACC agent takes a per-login-session
mutex and its installer kills a previously running instance).

## 3. Frame format

### 3.1 Encoding rules — the tolerant reader contract

These rules are the heart of the protocol's compatibility story and are
**normative for every implementation**:

1. **Receivers MUST ignore unknown fields**, at the top level and inside every
   nested object. This is what lets senders evolve ahead of receivers.
2. **Senders MAY omit any field.** Every field has a defined
   absent-interpretation (§3.5). Omitting a channel means "I don't have this",
   and the receiver leaves the corresponding gauges inactive or applies the
   documented default. Senders MUST NOT send explicit JSON `null` for a field
   unless the field is marked *nullable* in §3.5 — for non-nullable fields,
   absence and `null` are **not** equivalent, and a `null` invalidates the
   **entire frame** (rule 3).
3. **A frame is atomic.** A receiver MUST either accept a frame whole or
   discard it whole. A frame containing a type-invalid or range-invalid value
   in any field is discarded entirely; the receiver keeps its previous state.
   Receivers MUST survive arbitrary invalid input indefinitely and SHOULD
   rate-limit any logging of it.
4. **Numeric leniency:** receivers SHOULD accept an integer where a number is
   specified (and coerce). Senders MUST emit the specified type.

### 3.2 Protocol version field

A frame MAY carry a version marker:

```json
{ "v": 1, "car_speed": 42.1, ... }
```

- `v` absent means **v1**. All currently shipped senders omit it.
- For this specification, `v` when present MUST be `1`.
- A receiver seeing a **higher** `v` than it implements MUST NOT discard the
  frame for that reason alone: it SHOULD log the situation once and continue
  best-effort parsing under its own rules (unknown fields ignored, invalid
  frames dropped). A dashboard must never crash mid-race because the feed is
  newer than the image.
- Version-change policy — what may change without bumping `v` — is defined in
  §5.

### 3.3 Top-level fields

All fields are optional (§3.1 rule 2). *Nullable* means an explicit JSON
`null` is a valid wire value with the stated meaning; non-nullable fields must
be omitted instead (§3.1 rule 2).

| Field | Type | Nullable | Absent ⇒ | Meaning / unit |
|---|---|---|---|---|
| `v` | integer | no | v1 | Protocol version (§3.2). |
| `received_time` | number | no | — | Reserved to the receiver (§3.4). Senders MAY include it; receivers MUST ignore the wire value. |
| `car_id` | integer | no | −1 | Game-specific opaque vehicle id. −1 = unknown. Ids are only comparable between frames of the same sender. |
| `car_speed` | number ≥ 0 | no | 0.0 | Vehicle ground speed, **m/s**. Non-negative even when reversing. |
| `engine_rpm` | number ≥ 0 | no | 0.0 | Engine speed, RPM. |
| `current_gear` | integer ≥ −1 | no | 0 | Gear, cluster convention: **0 = reverse, −1 = neutral, 1… = forward** (§3.6). |
| `throttle` | number 0.0–1.0 | no | 0.0 | Throttle input fraction (§3.6). |
| `brake` | number 0.0–1.0 | no | 0.0 | Brake input fraction (§3.6). |
| `steering` | number | no | 0.0 | Steering input. **Sender-defined calibration** (sign and scale vary by source); receivers MUST NOT assume a unit. Effectively reserved. |
| `gas_level` | number ≥ 0 | no | 0.0 | Remaining fuel, in **sender-defined fuel units** (§3.6). |
| `gas_capacity` | number ≥ 0 | no | 0.0 | Fuel tank capacity in the same units. **0 = no fuel model** (e.g. EV): receivers disable fuel gauges. |
| `lap_count` | integer ≥ 0 | yes | null | Completed/current lap counter as the game defines it. `null` = not in a lap-counted session. |
| `laps_in_race` | integer ≥ 0 | yes | null | Total laps of the race. `null` = not applicable (practice, time trial). |
| `best_lap_time` | integer ≥ 0 | yes | null | Session best lap, **milliseconds**. |
| `last_lap_time` | integer ≥ 0 | yes | null | Previous lap, **milliseconds**. |
| `current_lap_time` | integer ≥ 0 | yes | null | Running current-lap clock, **milliseconds**. `null` = no timed lap active. |
| `flags` | object | **no** | all false | Boolean status flags (§3.5.1). Omit, never null. |
| `rpm_alert` | object | **no** | receiver default (7500/8000) | Shift-warning band (§3.5.2). Omit, never null. Senders SHOULD omit it when the source reports no band (e.g. out of session) rather than sending zeros. |
| `wheels` | object | **no** | wheel gauges inactive | Four wheel corners (§3.5.3). Omit, never null. |
| `position` | object | yes | null | Vehicle world position (§3.5.6). |
| `gear_ratios` | array of number | **no** | shift-point lights inactive | Drivetrain ratios for forward gears 1…N, index 0 = 1st gear (§3.5.5). Consumed by the receiver's shift-point calculation; **relative** values are what matters, so gearbox-only or overall (× final drive) ratios are equally valid. Omit, never null; omit unknown ratios rather than sending 0. |
| `engine` | object | **no** | receiver's own car database / default profile | Engine curve summary for the shift-point calculation (§3.5.5). Omit, never null. |
| `native_delta_ms` | integer | yes | null | Source-computed delta to the reference lap, **signed milliseconds, negative = ahead** (§3.6). When present, receivers republish it instead of computing their own delta. |
| `track_name` | string | yes | null | Source-provided track name, free text. When present, receivers display it instead of running their own track identification. |

### 3.4 `received_time` — receiver-owned freshness

Freshness is decided by the receiver, never the sender. The reference receiver
stamps every accepted frame with its own local monotonic clock *on arrival*,
overwriting whatever the sender put in `received_time`. Consequences:

- Senders MUST NOT rely on `received_time` surviving to any consumer.
- Sender clock skew is irrelevant to liveness.
- Heartbeat replays (§2.4) need no field changed to count as fresh.

The field exists on the wire for one reason: captured streams and recordings
retain a timestamp column. Treat it as diagnostic.

### 3.5 Nested objects

Inside every nested object, unknown keys are ignored (§3.1 rule 1) and new
keys may be added by minor revisions (§5).

#### 3.5.1 `flags`

All members are booleans, all optional, all defaulting to `false`.

| Key | Meaning |
|---|---|
| `car_on_track` | Vehicle is on track (pit lane included — receivers blank speed/gear displays when false, and a live speedometer in the pits is wanted). |
| `paused` | Game is paused. Extends the receiver's staleness allowance (§2.4). |
| `loading_or_processing` | Game is loading / between sessions. Same staleness effect as `paused`. |
| `in_gear` | Drivetrain engaged; false while shifting or stationary in neutral. |
| `has_turbo` | Vehicle has a turbocharger (enables boost-related UI). |
| `rev_limiter_alert_active` | Rev limiter / shift warning active. Senders SHOULD keep this consistent with `rpm_alert` (same threshold). |
| `hand_brake_active` | Handbrake applied. |
| `lights_active` | Main lights on. |
| `lights_high_beams_active` | High beams on. |
| `lights_low_beams_active` | Low beams on. |
| `asm_active` | Stability assist currently intervening. |
| `tcs_active` | Traction control currently intervening. |

#### 3.5.2 `rpm_alert`

```json
"rpm_alert": { "min": 8550.0, "max": 9000.0 }
```

| Key | Type | Meaning |
|---|---|---|
| `min` | number | RPM at which the shift warning begins. |
| `max` | number | RPM of the rev limiter. |

Both optional (receiver defaults 7500 / 8000). When the source has no
meaningful band (e.g. menus report a max RPM of 0), senders SHOULD omit the
whole object — a 0/0 band is worse than the receiver's default.

#### 3.5.3 `wheels`

```json
"wheels": {
  "front_left":  { "suspension_height": 0.42, "radius": 0.33, "rps": 21.2, "ground_speed": 44.0, "temperature": 87.6 },
  "front_right": { ... }, "rear_left": { ... }, "rear_right": { ... }
}
```

When `wheels` is present, all four corners (`front_left`, `front_right`,
`rear_left`, `rear_right`) MUST be present. Per corner:

| Key | Type | Required | Meaning / unit |
|---|---|---|---|
| `suspension_height` | number **0.0–1.0** | yes | Normalized suspension compression (0 = fully extended). **Strictly enforced**: an out-of-range value invalidates the whole frame — senders MUST clamp (suspension travel goes out of range over kerbs). |
| `radius` | number | yes | Tyre radius, meters. |
| `rps` | number | yes | Wheel rotation, **revolutions per second** (not rad/s). Signed; negative when rolling backwards. |
| `ground_speed` | number | yes | Contact-patch speed (ω·r), m/s. Receivers compare it against `car_speed` for wheelspin/lockup — **by magnitude**: the sign is a sender's own convention (GT7's feed reports it negative going forward), unlike `rps`, whose sign is specified above. |
| `temperature` | number | no (default 20.0) | Tyre temperature, °C. |

#### 3.5.5 `engine` and `gear_ratios` — shift-point data

The receiver computes per-gear optimal shift points by finding where wheel
torque in the next gear overtakes the current one. That needs two things a
sender may know and telemetry alone may not carry: a summary of the engine's
torque curve, and the drivetrain ratios.

```json
"engine": { "max_power_kw": 380.0, "max_power_rpm": 7200.0,
            "max_torque_nm": 650.0, "max_torque_rpm": 5500.0,
            "power_to_limiter": true },
"gear_ratios": [2.917, 2.31, 1.85, 1.52, 1.30, 1.14]
```

| Key | Type | Required | Meaning |
|---|---|---|---|
| `max_power_kw` | number > 0 | yes | Peak power. Only the *shape* of the curve matters to the receiver (absolute scale cancels out of the gear comparison), so an estimate with the right peaks is useful. |
| `max_power_rpm` | number > 0 | yes | RPM of peak power. |
| `max_torque_nm` | number > 0 | yes | Peak torque. |
| `max_torque_rpm` | number > 0 | yes | RPM of peak torque. |
| `power_to_limiter` | boolean | no (default `false`) | The engine holds power all the way to the rev limiter. |

Notes for senders:

- The redline is **not** part of `engine`; it already travels as
  `rpm_alert.max`.
- `power_to_limiter` exists because the four peak numbers above do not
  contain the one thing the shift point most depends on: how fast power
  falls off *past* the peak. A BOP'd race engine holds it almost flat and is
  shifted at the limiter; a small turbo road car falls off a cliff and wants
  an early upshift. Both can report identical peaks, so a receiver
  synthesizing a curve from them has to guess, and guessing costs ~6% of the
  rev range either way. Set it when the source knows — GT7's feed derives it
  from the car's group tag (Gr.1–Gr.4 and Gr.X are purpose-built racers) —
  and omit it otherwise. Receivers that predate it fall back to their own
  falloff assumption, which is the pre-existing behaviour, so it is safe to
  send unconditionally.
- `gear_ratios` may be sourced from the game (GT7 transmits them), from a
  per-car table, or **measured live** as `engine_rpm ÷ wheel rpm` while the
  drivetrain is engaged and not slipping — since only relative ratios
  matter, overall ratios measured that way are exactly as good. Send the
  longest known prefix of consecutive gears (a shift point for gear N needs
  N and N+1); it is normal for the list to grow over the first laps of a
  session while ratios are being learned.
- When `engine` is absent the receiver MAY fall back to a car database of
  its own keyed by `car_id` (the reference receiver does, for GT7) or to a
  generic profile; when `gear_ratios` is absent the shift-point lights stay
  inactive. Senders that can provide both SHOULD — it is the only way the
  feature works for receivers that have no data for the sender's game.

#### 3.5.6 `position`

```json
"position": { "x": 12.0, "y": 0.0, "z": 34.5 }
```

`x`/`y`/`z` numbers, meters, each defaulting to 0.0. Game-specific coordinate
frame: `x`/`z` span the horizontal plane, `y` is vertical. Origins and axis
orientation differ per game; receivers use position only for same-sender
geometric work (e.g. track identification from GT7 traces), never across
senders.

### 3.6 Value conventions

- **Gear:** `0` = reverse, `−1` = neutral, `1`+ = forward gears. This is the
  cluster's native convention; senders MUST map their game's encoding onto it
  (ACC's −1 R / 0 N / n maps via R→0, N→−1; GT7's raw gear nibble `0` R /
  `15` N maps via R→0, 15→−1). `null` is **not** a valid gear.
- **Delta:** `native_delta_ms` is signed milliseconds relative to the
  sender's reference lap; **negative means ahead** (faster) — matching the
  on-screen convention of a GT3 delta display.
- **Pedals:** `throttle` and `brake` are fractions 0.0–1.0. Sources that
  report bytes (0–255) MUST divide by 255.
- **Speed** is m/s everywhere (`car_speed`, `ground_speed`). Sources
  reporting km/h divide by 3.6.
- **Times** are integer milliseconds.
- **Fuel** is a ratio contract, not a unit contract: `gas_level` and
  `gas_capacity` share one sender-defined unit (GT7 exposes percent-points of
  a nominal tank, capacity 100 for cars / 5 for karts / 0 for EVs; ACC
  reports liters). Receivers MUST only rely on `gas_level / gas_capacity`
  and on level differences over time in the same session, and MUST treat
  `gas_capacity == 0` as "no fuel model".

## 4. Receiver behavior summary

Normative requirements for any conforming receiver, restated in one place:

1. Keep only the **latest** valid frame; earlier frames have no meaning.
2. Ignore unknown fields everywhere (§3.1).
3. Discard invalid frames whole; never carry a partial frame (§3.1).
4. Never crash or stop listening because of wire input, including sustained
   garbage, oversized datagrams and higher-`v` frames (§3.1, §3.2).
5. Stamp freshness on arrival with a local clock; ignore the sender's
   `received_time` (§3.4).
6. Declare staleness per §2.4 and surface it to the user; absent channels
   render as inactive gauges, not as zeros pretending to be data.

## 5. Versioning and evolution

The deployment reality this policy serves: **receivers ship inside OS images**
(slow, pinned, sometimes never updated) while **senders ship as feed releases**
(fast, fetched at runtime). Sender/receiver version skew in both directions is
the *normal* operating condition, not an edge case.

**Minor changes** — allowed without bumping `v`, because rule §3.1(1) makes
them invisible to older receivers:

- Adding a new optional top-level field or a new key inside `flags` or another
  nested object.
- Documenting a previously reserved field (e.g. giving
  `steering` defined semantics), provided the wire type is unchanged.
- Loosening sender obligations (e.g. widening an accepted range receivers
  already tolerate).

A new sender MUST NOT *require* receiver support for a minor addition: the
channel must degrade to "gauge inactive" on receivers that predate it.

**Major changes** — require bumping `v` (and are expected to be rare):

- Changing the type, unit, sign or semantics of an existing field.
- Making a previously optional field required, or changing an
  absent-interpretation.
- Changing framing, encoding or transport.

Receivers implementing v1 that see `v: 2` follow §3.2: warn once, best-effort
parse. A future v2 sender that wants to serve old receivers unchanged should
therefore keep v1 semantics for every field it emits under a v1 name.

**Rollout asymmetry, spelled out:** a change that needs new *receiver*
behavior reaches devices only with the next OS image release; a change that
needs new *sender* behavior reaches devices with the next feed release (and
reaches paired game-PC agents on their next pairing). Protocol changes should
therefore be designed to put the burden on senders whenever possible.

## 6. Security and trust model

**v1 trusts the local network by design.** There is no authentication,
integrity protection or encryption. When bound to a LAN interface, the
receiver accepts frames from any host that can send UDP to port 5600. The
threat this admits is spoofed or disruptive telemetry on a hostile LAN; the
data itself is not sensitive. Deployments are assumed to be home networks.

Mitigations present in v1: local-only binding when no network sender is
paired (with source-address filtering on loopback), frame validation (§3.1),
and staleness surfacing (§2.4). None of these resist a deliberate attacker on
the LAN.

**Sketch of a future authenticated mode** (not part of v1, not implemented):
the pairing handoff (§2.5) already moves a config file from receiver to
sender out of band; it could additionally carry a per-pairing shared secret.
Each frame would then carry `"auth": {"ts": <ms>, "tag": <base64>}` — an HMAC
over the frame bytes and a timestamp, letting the receiver reject unsigned
frames and replays older than its staleness window, at the cost of ~50 bytes
per frame and HMAC verification at 60 Hz. `v` stays 1: an `auth` field is a
minor addition (older receivers ignore it); *requiring* it would be a
receiver-side policy, not a wire change.

## 7. Conformance

A **sender** conforms if every frame it emits validates against
[`telemetry-frame.v1.schema.json`](telemetry-frame.v1.schema.json) and it
observes the transport rules of §2 (sizes, single-sender, liveness guidance).
The schema encodes sender obligations (§3 types, ranges and
nullability) — it is deliberately stricter than receiver tolerance (§3.1), so
"validates against the schema" implies "accepted by every conforming
receiver", not vice versa.

A **receiver** conforms if it satisfies §2.4, §3.1, §3.2 and §4.

Golden sample frames and a validator CLI accompany the schema (see
`tools/`, permissively licensed) so conformance can be checked without
Revokyte hardware.

## 8. Known deviations of shipped v1.0 senders

The following shipped-sender behaviors predate this specification. They are
documented so third parties do not copy them; receivers tolerate them, and
they are being corrected in feed releases:

| Sender | Deviation | Effect | Status |
|---|---|---|---|
| GT7 feed proxy | Emits `current_gear: null` when the gearbox is in neutral (raw nibble 15 passed through). | Violates §3.6; receivers discard those frames whole, so gauges freeze while in neutral. | To fix: map to `−1`. |
| GT7 feed proxy | Emits `throttle`/`brake` as raw 0–255 integers. | Violates §3.6. Harmless today (no shipped receiver gauge consumes pedals) but non-conformant. | To fix: divide by 255. |
| GT7 feed proxy | Emits `wheels[*].ground_speed` **negative** while the car drives forward (measured: `car_speed` 45.2, all four corners −45.2…−46.3). | §3.5.4 gives `ground_speed` no sign rule (only `rps` has one), so this is underspecified rather than illegal — but a receiver comparing it against `car_speed` signed sees ~200% slip on every sample. | Receivers MUST compare magnitudes; the sign rule belongs in §3.5.4. |
| GT7 feed proxy | Dumps ~20 undefined keys (velocity, rotation, oil data, …) per frame, ≈ 2.3 kB. | Exceeds the §2.2 LAN recommendation. Tolerated because this sender is loopback-only. | Acceptable on loopback; MUST NOT be imitated by network senders. |
| GT7 feed proxy | Drops frames while the game is paused instead of sending `paused: true`. | Receiver shows signal loss ~1 s into every pause (§2.4). | To fix: forward paused frames. |
| GT7 feed proxy | No silence-bridging replay (§2.4). | Brief source gaps surface as signal loss. | Optional improvement. |

The ACC feed proxy and the ACC PC agent are conformant as shipped.

## 9. License and intellectual property

- **This specification text** is licensed under
  [Creative Commons Attribution 4.0](../LICENSES/CC-BY-4.0.txt) (CC-BY 4.0).
- **The JSON Schema** (`telemetry-frame.v1.schema.json`) **and all conformance
  sample data** are dedicated to the public domain under
  [CC0 1.0](../LICENSES/CC0-1.0.txt).
- **Implementing this protocol requires no license from the Revokyte
  project.** The protocol is open: anyone may implement senders or receivers,
  for any purpose, in software under any license including proprietary
  licenses, with no fee, notification or attribution requirement (attribution
  applies only when reproducing this document's text itself).
- The Revokyte cluster application is GPL-3.0-licensed. That license covers
  its code, **not** this protocol, the schema, or data exchanged over the
  wire. Interoperating with a Revokyte device over this protocol creates no
  GPL obligation for the interoperating software.

---

## Revision history

- **1.1 (draft)** — wire-compatible minor revision, `v` stays `1`:
  - Added the optional `engine` object (§3.5.5) so senders can supply the
    engine-curve summary the shift-point calculation needs.
  - **Erratum:** 1.0 marked `gear_ratios` "reserved — no receiver consumes
    it". That was wrong: the reference receiver's shift-light system has
    always consumed it (GT7 supplies it). §3.5.5 now documents the real
    semantics; the wire type is unchanged, so no shipped sender or receiver
    is affected.
- **1.0** — initial specification, codifying shipped behavior.

## Appendix A: recording envelope format (non-normative)

Receivers and tools store captured sessions as NDJSON files in an envelope
that adds a relative timestamp; this is a **file format**, not a wire format:

```json
{"dt": 0.000, "frame": { ... a frame exactly as specified above ... }}
{"dt": 0.016, "frame": { ... }}
```

`dt` is seconds since the start of the recording, monotonically
non-decreasing. The embedded `frame` objects follow this specification and
can be validated with the same schema. `received_time` inside a recorded
frame is the recorder's arrival stamp and is replayed as-is.

## Appendix B: example frames (non-normative)

**Minimal live frame** (a sender that only knows speed and RPM — every other
gauge stays inactive):

```json
{"car_speed": 33.4, "engine_rpm": 5200.0, "flags": {"car_on_track": true}}
```

**Typical full-featured frame** (a game-PC agent; ~1.2 kB with realistic
float precision):

```json
{"v": 1, "received_time": 1723200000.123, "car_id": 42, "car_speed": 47.2,
 "engine_rpm": 6900.0, "current_gear": 3, "throttle": 0.83, "brake": 0.0,
 "steering": -0.12, "gas_level": 41.5, "gas_capacity": 120.0,
 "lap_count": 6, "laps_in_race": 12, "best_lap_time": 103862,
 "last_lap_time": 104510, "current_lap_time": 63180,
 "native_delta_ms": -220, "track_name": "monza",
 "flags": {"car_on_track": true, "in_gear": true},
 "rpm_alert": {"min": 8550.0, "max": 9000.0},
 "wheels": {
   "front_left":  {"suspension_height": 0.44, "radius": 0.33, "rps": 22.8, "ground_speed": 47.3, "temperature": 88.1},
   "front_right": {"suspension_height": 0.46, "radius": 0.33, "rps": 22.7, "ground_speed": 47.1, "temperature": 89.4},
   "rear_left":   {"suspension_height": 0.41, "radius": 0.34, "rps": 22.1, "ground_speed": 47.2, "temperature": 91.0},
   "rear_right":  {"suspension_height": 0.40, "radius": 0.34, "rps": 22.2, "ground_speed": 47.4, "temperature": 90.2}
 },
 "position": {"x": 128.5, "y": 2.1, "z": -404.9}}
```
