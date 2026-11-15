# 0001 - Raspberry Pi Pico 2 as front-end MCU

- **Status:** Accepted
- **Date:** 2026-11-06
- **Updated:** 2026-11-15 (variant chosen: Pico 2)

## Context

The IPEM PiHat Lite carries an ATM90E36 3-phase metering IC with an SPI
interface. It is designed to sit on a Raspberry Pi header. The host here is a
Clockwork uConsole (CM5), which is a closed handheld with no convenient header
for a HAT, and the measurement electronics must not be inside the handheld
anyway (see [0004](0004-isolated-front-end-box.md)). So something has to
drive the ATM90E36 inside the front-end box and send the results to the
uConsole.

## Decision

Use a Raspberry Pi Pico 2 (RP2350) in the front-end box. It reads the
ATM90E36 over SPI and talks to the uConsole over USB.

### Why the Pico 2 rather than the original Pico (RP2040)

Added 2026-11-15, before any Pico was bought.

- **More memory:** 520KB RAM and 4MB flash instead of 264KB and 2MB. That
  leaves room for buffering, calibration data and possible on-board recording
  later.
- **Hardware floating point** (Cortex-M33 FPU), useful for scaling,
  calibration and averaging on the Pico.
- **Same board size, pinout and SDK**, at almost the same price. Everything
  below applies to both.

## Reasons

- **Native USB device.** The Pico can appear as a USB CDC serial port (or a
  custom USB class) without an extra USB-UART chip. Fewer parts in the box.
- **3.3V logic** matches the ATM90E36, so no level shifting.
- **Real-time work stays out of Linux.** Polling registers, reacting to the
  ATM90E36 IRQ/warning pins and timestamping is easy on a bare-metal MCU and
  is not disturbed by load on the host.
- **SPI stays short.** SPI is not meant for long cables. With the Pico next to
  the PiHat, the only long cable is USB, which is built for it.
- **Low power** (well under 100mA), so it can be powered from the uConsole's
  USB if that is the chosen option.
- **Cheap, available, and well documented**, with the C/C++ SDK and
  MicroPython/CircuitPython as options. Easy for others to rebuild.

## Consequences

- Need to write Pico firmware (`firmware/pico/`) and define a protocol
  between Pico and uConsole (open issue).
- The PiHat has a Pi header, so an adapter (wiring or a small KiCad board in
  `hardware/kicad/`) is needed to connect it to the Pico.
- Firmware updates require access to the Pico's USB/BOOTSEL inside the box,
  unless updates over the link are added later.

## Alternatives considered

- **PiHat on a separate Pi Zero/Pi in the box.** Works with existing
  software, but needs a full Linux system in the box: higher power, SD card
  wear, longer boot, more to go wrong.
- **SPI directly from the CM5 over a cable.** Long SPI lines in an industrial
  environment are unreliable, and it would bring the measurement circuit's
  ground straight into the uConsole.
- **ESP32.** Wifi/BLE not wanted (see [0003](0003-wired-usb-link.md)); USB on
  most ESP32 variants is a separate UART bridge or less mature.
