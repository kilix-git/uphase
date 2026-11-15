# Host software (uConsole)

Software running on the Clockwork uConsole (Debian 12 Bookworm).

| Directory | What |
|---|---|
| [pzem-poc/](pzem-poc/) | Proof of concept: reads a PZEM-004T v3 over a CP2102 USB-UART (Modbus RTU) and prints the values. Milestone `v0.1-pzem-poc`. |

Licence: Beerware (see [LICENSE](../LICENSE)).

## pzem-poc

```
sudo apt install python3-serial
python3 pzem-poc/pzem.py /dev/ttyUSB0 1
```

The PZEM-004T only answers when its voltage input is connected to mains. The
PZEM is a mains-connected module: read [docs/safety.md](../docs/safety.md)
first and keep it in a closed enclosure.
