#!/usr/bin/env python3
"""Read a PZEM-004T v3 over Modbus RTU (USB-UART, e.g. CP2102).

Usage:  python3 pzem.py [/dev/ttyUSB0] [interval_seconds] [ct_turns]
        ct_turns: number of times the wire loops through the CT (I, P, E are divided by it)
Needs:  pyserial  (Debian: sudo apt install python3-serial)
"""
import struct
import sys
import time

import serial

ADDR = 0xF8  # general address, works with a single PZEM on the bus


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


def read_input_registers(ser, addr, start, count):
    req = struct.pack(">BBHH", addr, 0x04, start, count)
    ser.reset_input_buffer()
    ser.write(req + crc16(req))
    expected = 5 + 2 * count  # addr, func, bytecount, data, crc(2)
    resp = ser.read(expected)
    if len(resp) < 5:
        raise IOError(f"no response ({len(resp)} bytes) - is mains connected to the PZEM?")
    if resp[1] & 0x80:
        raise IOError(f"Modbus exception code {resp[2]}")
    if len(resp) != expected:
        raise IOError(f"short response: {resp.hex(' ')}")
    if crc16(resp[:-2]) != resp[-2:]:
        raise IOError(f"CRC mismatch: {resp.hex(' ')}")
    return struct.unpack(f">{count}H", resp[3:-2])


def u32(lo, hi):
    return (hi << 16) | lo


def check_plausible(u, i, p, f, pf):
    """Reject frames that pass CRC but contain nonsense (seen once: 2786V, 981kA).
    Limits are on the raw values (before dividing by CT turns)."""
    if not 50 <= u <= 300:
        raise IOError(f"implausible voltage {u}V")
    if not 0 <= i <= 120:
        raise IOError(f"implausible current {i}A")
    if not 40 <= f <= 70:
        raise IOError(f"implausible frequency {f}Hz")
    if not 0 <= pf <= 1:
        raise IOError(f"implausible power factor {pf}")
    if p > u * i * 1.05 + 1:
        raise IOError(f"implausible power {p}W > U*I = {u * i:.1f}VA")


def reset_energy(ser, addr=ADDR):
    """Set the PZEM's internal energy counter to zero (Modbus function 0x42)."""
    req = struct.pack(">BB", addr, 0x42)
    ser.reset_input_buffer()
    ser.write(req + crc16(req))
    resp = ser.read(4)
    if len(resp) == 0:
        raise IOError("no response to energy reset")
    if len(resp) >= 3 and resp[1] == 0xC2:
        raise IOError(f"energy reset refused, Modbus exception code {resp[2]}")
    if resp != req + crc16(req):
        raise IOError(f"unexpected reply to energy reset: {resp.hex(' ')}")


def open_port(port):
    return serial.Serial(port, 9600, bytesize=8, parity="N", stopbits=1, timeout=0.5)


def read_values(ser, turns=1):
    """One reading as a dict: u [V], i [A], p [W], e [Wh], f [Hz], pf.
    I, P and E are divided by the number of CT passes. Raises IOError on any problem."""
    r = read_input_registers(ser, ADDR, 0x0000, 10)
    u = r[0] / 10
    i_raw = u32(r[1], r[2]) / 1000
    p_raw = u32(r[3], r[4]) / 10
    f = r[7] / 10
    pf = r[8] / 100
    check_plausible(u, i_raw, p_raw, f, pf)
    return {"u": u, "i": i_raw / turns, "p": p_raw / turns,
            "e": u32(r[5], r[6]) / turns, "f": f, "pf": pf}


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    turns = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    with open_port(port) as ser:
        if turns > 1:
            print(f"CT turns: {turns} (I, P, E divided by {turns})")
        print(f"{'U [V]':>7} {'I [A]':>7} {'P [W]':>8} {'E [Wh]':>8} {'f [Hz]':>6} {'PF':>5}")
        while True:
            try:
                v = read_values(ser, turns)
                print(f"{v['u']:7.1f} {v['i']:7.3f} {v['p']:8.1f} {v['e']:8.1f} {v['f']:6.1f} {v['pf']:5.2f}")
            except IOError as ex:
                print("error:", ex)
            time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
