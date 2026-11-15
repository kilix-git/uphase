# Safety

> **Disclaimer - build at your own risk.**
> This is a hobby project, not a certified measuring instrument. The designs,
> code and instructions in this repository are provided as-is, without any
> warranty and without any claim that they are safe or fit for any purpose.
> If you build or use anything from here, you do so entirely at your own risk
> and you are responsible for complying with the electrical safety rules and
> laws where you live and work. The authors accept no liability for injury,
> death, fire or damage of any kind.

Read this whole page before building or connecting anything.

## Who should build this

Only people who are trained and allowed to work on live low-voltage
installations, and who know the local rules (for example EN 50110 in Europe,
NFPA 70E in the US). If you are not sure whether that is you, it is not you:
stop at the PZEM-004T proof of concept with a pre-built, enclosed module and a
plug-in load, or ask a qualified electrician to make the connections.

## Hazards

### Electric shock

- A 230/400V 3-phase system has 230V between each phase and neutral or earth,
  and 400V between phases. Currents of a few tens of mA through the body can
  be fatal at 50Hz.
- Neutral is not "safe". Under fault conditions, or with a broken neutral, it
  can carry a dangerous voltage.
- Measurement leads, terminal blocks and transformer primaries in the front-end
  box are at full mains potential whenever the box is connected.

### Arc flash and short-circuit energy

- Industrial distribution boards are fed through large transformers and can
  deliver kA of fault current. A slip with a probe or a screwdriver between
  phases can cause an explosive arc that burns and blinds even without direct
  contact.
- This is why voltage taps must be fused right at the point of connection
  (see below) and why the measurement category rating matters.

### Current transformers

- A current-output CT (for example 100A:5A or 100A:50mA without a built-in
  burden) produces a dangerous voltage if its secondary is left open while the
  primary carries current. Always connect the burden resistor or short the
  secondary before clamping it on a live conductor.
- Voltage-output CTs (with an internal burden, for example 0-1V or 0-333mV
  output) do not have this problem. Check which type you have before use.
- Only clamp CTs around insulated conductors. Never on bare busbars unless
  the CT is rated for it and you are qualified to work there.

### Transients

- Mains in an industrial environment carries switching transients from motors,
  contactors and VFDs, and lightning-induced surges. These can reach several kV
  for microseconds and break down insulation that looks fine at 230V. This is
  what measurement categories describe.

## Measurement categories (CAT ratings)

IEC 61010-1 / IEC 61010-2-030 group measurement inputs by where in the
installation they connect, because the available transient energy is higher
the closer you are to the supply.

| Category | Where | Examples |
|---|---|---|
| CAT II | Circuits plugged into socket outlets | Appliances, portable tools, a load plugged into a wall socket |
| CAT III | Fixed installation, distribution level | Distribution boards, sub-panels, 3-phase motor feeds, busbars, fixed industrial equipment |
| CAT IV | Origin of the installation | Service entrance, utility meter, overhead lines, main incoming cable |

The voltage next to the category (for example "CAT III 300V") is the maximum
**line-to-earth** voltage of the system it may be used on. A 230/400V system
has 230V line-to-earth, so it needs at least a 300V rating for that category.

Typical impulse withstand voltages (IEC 61010) for comparison:

| Rating | Impulse withstand |
|---|---|
| CAT II 300V | 2.5kV |
| CAT III 300V | 4kV |
| CAT III 600V | 6kV |
| CAT IV 300V | 6kV |

### What this means for this project

- The intended use (industrial 3-phase distribution boards) is **CAT III**.
- **This DIY device has no CAT rating.** It has not been designed, tested or
  certified to any category. Treat it accordingly.
- Every part that touches mains must be rated at least for the system voltage.
  For the leads and connections to the installation, use commercially made,
  CAT III 600V (or better) rated test leads, fused probes or clips.
- Fuse every voltage tap as close to the connection point as possible, with
  high-breaking-capacity fuses rated for the voltage and the prospective fault
  current (for example ceramic fuses in fused test leads). A small glass fuse
  is not enough on an industrial supply.
- Until the design has been reviewed and the insulation tested, only use the
  analyzer on CAT II circuits (behind a socket outlet with an RCD/RCBO).

## Isolation concept

The goal is that nothing the user can touch, and nothing connected to the
uConsole, is ever at mains potential.

```
 mains side (hazardous)          |  isolation barrier  |  low-voltage side (SELV)
                                 |                     |
 L1/L2/L3/N --fuses--> 230V/9V transformers ---------> ATM90E36 (PiHat) -> Pico -> USB -> uConsole
 conductor  --(insulation)--> split-core CTs --------> burden -> ATM90E36
```

- **Voltage:** the 230V/9V transformers are the isolation barrier. They must
  be safety-isolating transformers (EN 61558-2-6 or equivalent) with
  reinforced/double insulation between primary and secondary. Check the
  datasheet; do not use unknown transformers from salvaged equipment.
- **Current:** the CT's own insulation and the conductor's insulation form the
  barrier. Check the CT's rated insulation voltage.
- **No direct connection** from mains to the ATM90E36 (no resistive dividers).
  Resistive dividers are common in energy meter reference designs, but they put
  the whole low-voltage circuit at mains potential.
- **Creepage and clearance:** keep mains wiring physically separated from the
  low-voltage wiring inside the box. For 230V reinforced insulation, aim for
  at least 6mm creepage and clearance and use barriers or separate compartments
  where that is not possible.
- **Enclosure:** fully insulating plastic (double-insulated, no exposed metal
  parts), with strain relief on all cables, and no way to reach mains terminals
  without a tool.
- **Box power:** if the box is powered from a separate 230V/5V supply, that
  supply must also be a safety-isolated (SELV) type. See the open issue on box
  power source.
- **Cable to the uConsole:** the USB cable connects the low-voltage side of the
  box to the uConsole. This is only safe because the barrier above separates it
  from mains. A USB digital isolator in the box would add a second layer and
  break ground loops; this is being considered (see
  [design/0003-wired-usb-link.md](design/0003-wired-usb-link.md)).

## Testing before first use

1. Visual inspection: correct fuses, no loose strands, strain relief, lid closed.
2. Insulation test between the shorted mains inputs and the low-voltage side
   (USB shield/ground) with an insulation tester, for example 500V DC; expect
   well above 100MΩ.
3. First power-up with a low voltage source (for example a 9V or 12V AC
   transformer) in place of mains, to check wiring and firmware.
4. Then on a single-phase CAT II circuit behind an RCD.
5. Only after that on 3-phase distribution boards, following your local
   working-on-live-equipment procedures.

## Working practice

- Connect and disconnect voltage leads with the circuit de-energised whenever
  possible. Connect the box first, the installation last.
- Wear the PPE your workplace requires for live work at that location.
- Never work alone on live installations.
- If anything smells, crackles, gets warm or reads nonsense: disconnect at the
  installation side first.
