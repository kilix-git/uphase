# 0003 - Wired USB link instead of wifi

- **Status:** Accepted (isolation of the link still open)
- **Date:** 2026-11-06

## Context

The front-end box ([0004](0004-isolated-front-end-box.md)) has to send
measurements to the uConsole. The environment is industrial: distribution
boards in metal cabinets, VFDs, contactors, large motors, harmonics, and
strong magnetic fields near busbars. The link must be robust against all of
that.

## Decision

Use a single wired USB cable between the box and the uConsole, with the Pico
as a USB device.

## Reasons

- **Radio is unreliable in metal cabinets.** A distribution board is close to
  a Faraday cage, and industrial sites often have crowded or restricted 2.4GHz
  bands. A measurement tool that drops out when the cabinet door closes is not
  useful.
- **One cable for data and power.** USB can also power the box (see open issue
  on box power), avoiding batteries or a second supply.
- **Simple and deterministic.** USB CDC on the Pico appears as a serial port on
  Linux, with no pairing, no network setup, and no extra stack.
- **Some sites do not allow wireless devices** in electrical rooms.
- **USB has differential signalling and CRC** at the protocol level, which
  helps against common-mode noise.

## Consequences

- **Conducted noise and ground loops.** The cable connects the box's ground to
  the uConsole. Mitigations: shielded cable, ferrite cores at both ends, a
  short cable, and possibly a USB digital isolator (for example ADuM3160 /
  ADuM4160 based) in the box. Whether the isolator is needed is to be decided
  after testing.
- **Cable length** is limited to a few metres for USB 2.0. If longer runs are
  needed, RS-485 (differential, long distance, easy to isolate) is the fallback.
- **Application-level robustness** is still needed: framing, checksums and
  resynchronisation in the Pico <-> uConsole protocol (open issue), and the host
  must cope with the device disconnecting and reconnecting.

## Alternatives considered

- **Wifi / BLE.** No cable and full galvanic separation, but unreliable inside
  cabinets, sometimes not allowed, needs a radio-capable MCU and power in the
  box.
- **RS-485.** Very robust and long range, but needs transceivers at both ends
  and a USB adapter on the uConsole. Kept as fallback.
- **Optical fibre / optocoupled UART.** Perfect isolation, but more parts and
  more effort than justified at this stage.
