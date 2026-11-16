# Host software (uConsole)

Software running on the Clockwork uConsole (Debian 12 Bookworm).

| Directory | What |
|---|---|
| [pzemlyzer-poc/](pzemlyzer-poc/) | pzemlyzer: terminal power analyzer for a PZEM-004T v3 over a CP2102 USB-UART (Modbus RTU). Milestone `v0.1-pzem-poc`. |

Licence: Beerware (see [LICENSE](../LICENSE)).

## pzemlyzer-poc

**Status: complete.** Tested on the uConsole with a PZEM-004T v3 and a CP2102.

Proof of concept: reads a PZEM-004T v3 over a CP2102 USB-UART (Modbus RTU) and
does all kinds of neat things with it. At first it was a simple program that
wrote the readings directly to stdout (pzem.py, still usable); I expanded it into quite a nice mains
analyzer.

Requirements:
- Python 3.10 or newer
- pyserial: `sudo apt install python3-serial` (FreeBSD: `pkg install py311-pyserial`)
- a terminal with UTF-8 and Braille characters for the graphs

```
python3 pzemlyzer-poc/pzemlyzer.py
```

The serial port is chosen in Setup > Device port and saved in
`~/.config/pzemlyzer/settings.json`. The plain reader still works on its own:
`python3 pzemlyzer-poc/pzem.py /dev/ttyUSB0 1`.

The PZEM-004T only answers when its voltage input is connected to mains. The
PZEM is a mains-connected module: read [docs/safety.md](../docs/safety.md)
first and keep it in a closed enclosure.

Features of the software:
- interactive CLI-only (Linux/FreeBSD) software with menu-driven control
- measures voltage, current, active power, power factor, frequency, energy
- shows real-time measurement values, draws graphs with data received, graphs scale according to the amount of data
- graphs can be zoomed in and analyzed in detail, zoomed in area is retained across menus (for example: you zoom into current, then switch to voltage and it shows you the exact same spot, but in voltage)
- long runs (days, weeks) stay fast and small: the graphs keep every reading of the last 24h, older data is kept as one point per minute (min, max and average of each value, plus the energy), so memory grows by less than 1MB per day instead of ~40MB
- zooming into data older than 24h is limited to a 10min window and the zoom line shows "1min resolution", so the graph never pretends to show detail that is no longer kept; for second-by-second data over longer runs use the CSV logger with a 1s interval
- allows data logging, exports all data to CSV file
- logger can be fully autonomous, user is able to choose interval, start time, end time, which data to save (U, I, f, PF, P)
- when choosing interval, for example 100s, data is saved to the CSV file once per 100s, three values are stored - max value (out of those 100 measurements), min value and average of all measured values, so no important data is lost
- there is an option to calibrate the software, if you need to do that, max allowed is ±20%. In my case, there was no need to do any calibration: on every load I tested (resistive, motor, switch-mode, from ~60 mA to ~96 A through the CT), the pzemlyzer agreed with a calibrated Metrel MI3309 within the Metrel's stated accuracy (±5% + 5 digits). See [docs/journal/2026-11-16.md](../docs/journal/2026-11-16.md).
- you can also choose the number of turns around the CT, 1 means direct conductor, 2 means one loop
