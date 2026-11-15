# 3-phase power analyzer (uConsole)

A DIY 3-phase power analyzer for general use. A small insulated front-end box
measures the three phases with an ATM90E36 metering IC driven by a Raspberry Pi
Pico, and sends the results over one cable to a Clockwork uConsole, which acts
as host, display, recorder.

This repository is the single place for progress, ideas, measurements and
decisions. When the project is finished it is meant to double as a build guide.

> [!WARNING]
> **This project connects to mains and 3-phase voltages (230V / 400V and above).**
> Contact with these voltages can kill you, and faults on 3-phase installations
> can release enough energy to cause arc-flash burns. Do not build or use this
> unless you are qualified to work on live electrical installations.
> **Read [docs/safety.md](docs/safety.md) before anything else.**
> Everything here is provided as-is and you build and use it at your own risk.

## Status

Early stage (November 2026). The proof of concept works and measures: a
PZEM-004T + CP2102 single-phase analyzer with a terminal program running on the
uConsole, written in Python. It is called pzemlyzer, see
[host/pzemlyzer-poc/](host/pzemlyzer-poc/). The 3-phase hardware is being
collected. See the [journal](docs/journal/) for details.

## Roadmap

| Milestone | Goal | Status |
|---|---|---|
| `v0.1-pzem-poc` | Proof of concept: read a single-phase PZEM-004T over a CP2102 USB-UART on the uConsole and show the values. | Done, software available in [host/pzemlyzer-poc/](host/pzemlyzer-poc/) |
| `v0.2-pihat-alive` | ATM90E36 on the IPEM PiHat Lite talks to the Pico over SPI; raw voltage/current registers read back on the bench (safe low-voltage source first). | Not started |
| `v0.3-pico-usb-link` | Pico streams measurements to the uConsole over the wired link with a defined protocol; host shows live values. | Not started |

Later (not yet scheduled): calibration against a reference meter, insulated box
build, harmonics display, logging, Rogowski coils.

Milestones are tagged in git with the names above when they are reached.

## Hardware

| Part | Role | Notes |
|---|---|---|
| Clockwork uConsole | Host and display | Raspberry Pi CM5 8GB Lite, Rex's Debian 12 Bookworm lite image (kernel 6.12). The Trixie 7.1.4 lite image failed to boot. |
| IPEM PiHat Lite (ATM90E36) | 3-phase metering front end | Voltage, current, power, energy, harmonics. |
| Raspberry Pi Pico 2 | Front-end MCU | Drives the ATM90E36 over SPI, talks to the uConsole over USB. |
| Iron-core split CTs | Current sensing | Clamp around insulated conductors. Rogowski coils may come later. |
| 230V/9V mains transformers (3x) | Voltage sensing | Small PCB transformers; still to be tested. |
| Insulated enclosure | Houses PiHat, Pico and transformers | One cable to the uConsole. Power source still open (uConsole USB or separate 230V/5V supply). |
| PZEM-004T + CP2102 | Proof of concept only | Single-phase; on order. |

The full parts list lives in [hardware/bom.csv](hardware/bom.csv).

## Repository layout

```
docs/journal/        dated progress notes (start from TEMPLATE.md)
docs/design/         decision records: what was decided and why
docs/calibration.md  calibration procedure
docs/safety.md       safety information - read first
hardware/kicad/      KiCad projects (enclosure wiring, adapter boards)
hardware/datasheets/ datasheets of the parts used
hardware/bom.csv     bill of materials
firmware/pico/       Raspberry Pi Pico firmware
host/                software running on the uConsole
measurements/raw/    raw captures, never edited after recording
measurements/analysis/ scripts and results derived from raw data
media/               photos, screenshots, videos
```

## Licence

Everything in this repository (hardware, firmware, host software,
documentation, media and measurements) is under the
[Beerware licence](LICENSE): keep the notice and do whatever you want with it.
Datasheets in `hardware/datasheets/` belong to their manufacturers and are not
covered.

Beerware gives no warranty; see the disclaimer in [docs/safety.md](docs/safety.md).
