# Fluora / PixelAir local protocols

This document separates observations from deductions. “APK” means the
`Fluora_1.0.3_APKPure.xapk` supplied with this project (SHA-256
`24b4de695dd33324e3f97d918ac17e1e3058368be44e3272685c27190a5622d8`).

## Confidence labels

- **Device-verified**: observed directly against Fluora Mini firmware 3.1.6.
- **Capture-verified**: exact bytes exist in a supplied PCAP/log.
- **APK-verified**: reconstructed from disassembled Hermes v96 bytecode.
- **Test-verified**: covered by an automated local test.
- **Unverified**: requires more reverse engineering or a physical-device test.

## Firmware generations

Legacy firmware uses OSC on UDP 6767 with FlatBuffers state/control payloads.
The existing `libpixelair` implementation is the reference behavior for this
generation. It must remain isolated from PA3 because PA3 uses a different
service, state model, and payload envelope. The Home Assistant adapter uses
the maintained `libpixelair` package for this generation.

Firmware 3.x announces a plain JSON object by IPv4 broadcast to UDP 5684 every
approximately three seconds. The actual CoAP service is UDP 5683; neither 5684
nor 6767 responded to CoAP probes. PA3 does not advertise through mDNS.
Identity is the serial, not the IP address. **Capture-verified,
device-verified.**

The broadcast and `/discovery` use different field spellings:

| Meaning | UDP 5684 broadcast | `GET /discovery` |
| --- | --- | --- |
| IP | `ip_address` | `ip_address` |
| Serial | `serial` | `serial_number` |
| Firmware | `firmware_version` | `version` |
| Name | `nickname` | `name` |
| Model | `model` | `platform` |
| Protocol | `protocol` | `protocol` |
| Boot generation | absent | `boot_count` |

The firmware 3.1.6 `/discovery` payload is JSON text but has no Content-Format
option. **Device-verified.**

## CoAP resource directory

`GET /.well-known/core` returns `2.05 Content`, Content-Format 40:

```text
</discovery>,</ping>,</domain>,</global>,</schedule>,</parameter>,</command>,</revisions>;obs,</deltas>;obs
```

The parsing test uses these exact captured bytes. **Capture-verified,
device-verified, test-verified.**

Read-only enumeration on firmware 3.1.6:

| Request | Result | Payload |
| --- | --- | --- |
| `GET /discovery` | `2.05` | discovery JSON, no Content-Format |
| `GET /ping` | `2.05` | empty |
| `GET /domain` | `4.00` | `{"error":"Invalid domain request body"}` |
| `GET /global` | `4.00` | `{"error":"Invalid global request body"}` |
| `GET /schedule` | `2.05` | `{"rrules":[]}` |
| `GET /parameter` | `4.00` | `{"error":"No payload data"}` |
| `GET /command` | `4.05` | `Method Not Allowed` |
| `GET /revisions` | `2.05`, CF 50 | revision map |
| `GET /deltas` | `2.05`, CF 50 | `{}` when no pending delta |

`/getState` is not a PA3 endpoint and returns `4.04 Not Found`.
**Capture-verified and device-verified.**

## Observe

The resource directory marks `/revisions` and `/deltas` with `obs`.
The firmware accepted `GET` with Observe option 6 set to zero:

- `/revisions` returned an ACK carrying Observe sequence `2`, Content-Format
  50, and the complete revision map.
- `/deltas` returned an ACK carrying Observe sequence `96`, no payload, and no
  Content-Format in the initial response.

No state changed during the short observation window, so a subsequent
notification is still a **physical-device test requirement**. The client ACKs
confirmable notifications, correlates by token, and suppresses duplicate
message IDs as required by RFC 7252/7641.

## PA3 mutations recovered from the APK

The formats below were recovered from the APK. The original 3.1.6 capture
was read-only; subsequent write validation is listed under Additional
hardware validation below.

The app builds these JSON envelopes with UTF-8 `JSON.stringify` and sends to
UDP 5683. Its builder does not add a Content-Format option.

Command:

```json
{
  "protocol": "1.1",
  "type": "command",
  "method": "POST",
  "timestamp": "<Date.toISOString()>",
  "request_id": "<provided value or Date.now()>",
  "payload": {"command": "<command string>"}
}
```

On the wire the URI is `/command`, the method is confirmable POST, and the
complete object shown above is JSON encoded. **APK-verified.**

Parameter:

```json
{
  "protocol": "1.1",
  "type": "parameter",
  "method": "PUT",
  "timestamp": "<Date.toISOString()>",
  "request_id": "<provided value or Date.now()>",
  "payload": {"id": "<parameter ID>", "value": "<value>"}
}
```

The URI is `/parameter`. `getCoAPParameterMethod` selects POST for string,
bool/boolean, int, and trigger descriptors. Float dragging uses non-confirmable
PUT; its final value uses confirmable POST. **APK-verified, test-verified.**

Parameter IDs are device-issued, not stable constants. The client refreshes
`/global` and uses `engine.is_displaying` for power,
`engine.master_brightness` for brightness, and the hue/saturation descriptors
under `mode/manual.palette`. Hue degrees are divided by 360 and saturation
percent by 100. **APK-verified, device-state-verified, test-verified; physical
write unverified.**

Scene selection writes mode value 1, waits 500 ms, then writes the
device-derived active scene index. Auto, Scene, and Manual mode values are 0,
1, and 2 respectively.

The animation mapping is conclusive: `getPA3AnimationItems` maps
`payload.animations` in its original order and assigns the JavaScript array
index. Filtering retains that value as `originalIndex`; `onAnimationChange`
writes `originalIndex` through `mode/manual.anim_index`. `sendAnimation`
independently performs `findIndex` on the same ordered label array and sends
the result through the same route. Indices are zero-based, so the captured
catalog maps Twinkle=0, Leaf Swirl=1, Mirage=2, and so on. **APK-verified,
device-state-verified, test-verified; physical write unverified.**

`mode/manual.anim_manual.v` is the manual bank's stored selection.
`dashboard.anim_index` is the currently loaded dashboard animation. They can
differ when the engine is in another mode; in the captured snapshot
`engine.mode.v` is 1 (Scene), so the apparent manual value 1 versus dashboard
value 2 is not an index-mapping contradiction.

PA3 effect writes are exposed for explicit physical testing. The client
switches to Manual mode before animation selection and conservatively uses
the same 500 ms transition interval observed in the APK's scene switch path
before writing the proven original catalog index.
The same Manual-mode transition is performed before HS palette writes.
Physical validation of response/delta timing remains pending.

Every CLI write requires `--allow-write`.

## Global snapshot

The APK sends `GET /global` with an envelope containing `protocol: "1.1"`,
`type: "global"`, `method: "GET"`, ISO timestamp, and request ID. It requests
Block2 and firmware 3.1.6 returned a snapshot with identity, engine routes,
palettes, five scenes, and 35 animations. Its redacted structure is covered by
the fake-server and model tests. **APK-verified, device-verified,
test-verified.**

## Standards basis

Encoding follows RFC 7252 for message headers, token length, extended option
delta/length, payload marker, confirmable retransmission, and empty ACKs;
RFC 7641 for Observe registration and notification handling; and RFC 6690 for
the CoRE Link Format resource directory.

The APK’s mutation builder is narrower than the general codec: it uses a
two-byte token and short single-segment Uri-Path options. The reusable Python
codec implements extended options and segmented paths rather than copying
that limitation.

## Additional hardware validation

The following samples were exercised on physical devices; they do not
establish compatibility with every animation or firmware version.

- **Monos 2.1.9** (reported as `3/2.1.9`): manual IP setup and state reads
  worked after sending `/fluoraDiscovery` with the receiver's IPv4 address
  encoded as ASCII integer arguments. This path returned a fragmented binary
  snapshot without the JSON discovery response required by the old config
  flow. Same-value power and brightness writes, HS color, Solid Color,
  Rainbow, and Focus were exercised and checked against device state.
- **Fluora Mini and Monos 3.7.3**: state parsing, HS color at 220 degrees and
  80 percent saturation, Solid Color, Rainbow, and Focus were checked through
  Home Assistant with direct state readback. The Monos was returned to Auto
  with its prior power, brightness, palette, and stored selections restored.
  A short observation window showed no additional restarts; this does not
  establish long-term uptime or the cause of earlier restarts.
- **Concurrent CoAP exchanges**: a delayed UDP responder reproduced a lost
  reply when polling and a service call read the same client socket at once.
  Both the standalone and HA-bundled clients now serialize exchanges. The
  regression test requires both concurrent callers to receive their own reply.

Shared legacy-listener lifetime, binary-only probing, send failure, and
cancellation cleanup are covered by isolated transport tests. Simultaneous
control of two physical legacy devices has not been verified.
