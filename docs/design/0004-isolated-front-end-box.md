# 0004 - Front end in a separate insulated box

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

The analyzer connects to 230/400V 3-phase installations. The uConsole is a
consumer handheld with no measurement category rating, no isolation
design for mains inputs, and a device the user holds in their hands.

## Decision

Put everything that is connected to mains or sits next to mains-connected
parts (voltage transformers, CT inputs, IPEM PiHat Lite, Pico) in a small,
fully insulated box. Only one low-voltage cable (USB) goes from the box to the
uConsole.

## Reasons

- **Keep mains away from the user's hands.** The handheld never carries mains
  voltage, only the isolated low-voltage link.
- **Short mains leads.** The box can sit at the distribution board, close to
  the measurement points, so the hazardous wiring is short and fixed.
- **Clear isolation barrier.** Mains side and low-voltage side are separated
  in one place, inside one enclosure that can be inspected and insulation
  tested (see [safety.md](../safety.md#isolation-concept)).
- **Noise.** Analog signals stay short and inside the box; only digital data
  travels over the cable.
- **Reusable.** The box could later work with another host (laptop, Pi) with
  no changes.

## Consequences

- The box needs its own power (open issue: uConsole USB or a separate
  230V/5V supply).
- Enclosure design, terminals, strain relief and internal separation must be
  planned (creepage/clearance, barrier between mains and low-voltage areas).
- Two pieces to carry instead of one.

## Alternatives considered

- **Everything inside or attached to the uConsole.** Most compact, but puts
  mains-connected parts in a handheld device. Rejected for safety.
- **Commercial DIN-rail meter with Modbus output.** Safe and certified, but
  does not meet the goal of building the analyzer, and gives less access to
  raw data and harmonics. The PZEM-004T proof of concept follows a similar
  idea at small scale.
