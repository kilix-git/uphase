# 0002 - Iron-core split CTs now, Rogowski coils later

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

Current must be measured on three phases (and possibly neutral) in industrial
installations, without breaking the circuit. The two practical non-invasive
options are split-core current transformers and Rogowski coils.

## Decision

Start with iron-core split CTs. Keep Rogowski coils as a possible later
upgrade, tracked in an issue.

## Reasons

- **No integrator.** A CT with a burden resistor gives a voltage proportional
  to the current, which goes straight into the ATM90E36 current inputs. A
  Rogowski coil outputs di/dt and needs an integrator (analog, or digital in
  the metering IC if supported), which adds design and calibration work.
- **Good signal at 50Hz.** Iron-core CTs give a strong, low-noise output at
  mains frequency, with little sensitivity to nearby conductors.
- **Cheap and already available**, which matters for getting to a working
  first version.
- **Phase error is correctable.** The CT's phase shift can be compensated in
  the ATM90E36 phase calibration registers.

## Consequences

- **Saturation:** iron cores saturate at high currents and with DC components
  (for example from rectifier loads), which distorts readings. Pick CT ranges
  with headroom.
- **Limited bandwidth:** fine for the fundamental and lower harmonics; higher
  harmonics will be attenuated and phase-shifted. Harmonic readings must be
  qualified accordingly.
- **Size:** split CTs have a fixed window and may not fit large cables or
  busbars.
- **Open-secondary hazard** for current-output CTs (see
  [safety.md](../safety.md#current-transformers)).

## Alternatives considered

- **Rogowski coils.** No saturation, wide bandwidth, flexible, fit around large
  conductors, light. But: low output, integrator needed, more sensitive to
  position and external fields, more expensive. Revisit once the CT version
  works and its limits are known.
- **Shunt resistors.** Accurate and wide-band, but put the measurement circuit
  at mains potential. Not acceptable with the isolation concept.
- **Hall-effect sensors.** Handle DC, but need power, have offset/drift, and
  are more expensive for the current ranges needed.
