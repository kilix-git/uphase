# Calibration

> **Draft.** The ATM90E36 procedure below is an outline to be verified against
> the datasheet and application note, and refined as it is done for real.
> Tracked in the GitHub issue "ATM90E36 calibration procedure".

## Why calibrate

The ATM90E36 measures raw voltages at its inputs. To turn them into correct
values on the primary side, the whole chain has to be calibrated: voltage
transformer ratio and phase shift, CT ratio and phase shift, burden resistor
tolerance, and the IC's own offsets. Each phase is calibrated separately.

## Equipment

- A reference meter that is more accurate than the target (for example a
  calibrated power analyzer or a class 0.5 energy meter).
- A stable, mostly resistive load (heater, incandescent lamps) for gain
  calibration, and an inductive load (motor, choke) or a known PF for phase
  calibration.
- For a safe bench setup: a low-voltage AC source instead of mains where
  possible, and several turns of wire through the CT to increase the test
  current.

## Procedure outline (ATM90E36)

The ATM90E36 keeps its configuration in groups of registers, each protected by
a checksum register (CS0-CS3). After writing a group, the matching checksum
must be updated, or the chip flags a checksum error.

1. **Configuration (CS0 group).** Set the line frequency (50Hz), PGA gains for
   the current channels, metering mode, startup thresholds and the
   pulse/energy constant (PLconst).
2. **Offset calibration.** With no voltage and no current applied, read the
   residual voltage and current values and write the voltage/current offset
   registers. Then do the same for the power offset registers.
3. **Voltage and current gain (measurement calibration group).** Apply a known
   voltage (for example 230V) and current (for example 5A, resistive load).
   Compare the readings with the reference meter and adjust the voltage and
   current gain registers per phase.
4. **Energy/power gain and phase (metering calibration group).** At PF=1,
   adjust the power gain registers until active power matches the reference.
   At PF=0.5 inductive, adjust the phase angle registers until active and
   reactive power match. This compensates the phase shift of the
   transformers and CTs.
5. **Harmonic/fundamental calibration (CS3 group)**, if fundamental and
   harmonic values are used.
6. **Verify** at several points: low and high current, PF=1 and PF=0.5,
   and record the errors.
7. **Store** the final register values in the firmware or the host
   configuration, together with the serial numbers of the transformer and CT
   used on each channel. Recalibrate if a sensor is swapped.

## Recording results

- Raw readings: `measurements/raw/YYYY-MM-DD_calibration_<phase>.csv`
- Final register values and verification errors: in the journal entry for that
  day, and in this file once stable.

| Date | Channel | Sensor | Register | Value | Error after |
|---|---|---|---|---|---|
| | | | | | |
