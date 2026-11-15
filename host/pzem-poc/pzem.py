#!/usr/bin/env python3
"""Read a PZEM-004T v3 over Modbus RTU (USB-UART, e.g. CP2102).

Usage:  python3 pzem.py [/dev/cuaU0] [interval_seconds]
Needs:  pyserial  (FreeBSD: pkg install py311-pyserial)
"""
import struct
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cuaU0"
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
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


def main():
    with serial.Serial(PORT, 9600, bytesize=8, parity="N", stopbits=1, timeout=0.5) as ser:
        print(f"{'U [V]':>7} {'I [A]':>7} {'P [W]':>8} {'E [Wh]':>8} {'f [Hz]':>6} {'PF':>5}")
        while True:
            try:
                r = read_input_registers(ser, ADDR, 0x0000, 10)
                u = r[0] / 10
                i = u32(r[1], r[2]) / 1000
                p = u32(r[3], r[4]) / 10
                e = u32(r[5], r[6])
                f = r[7] / 10
                pf = r[8] / 100
                print(f"{u:7.1f} {i:7.3f} {p:8.1f} {e:8d} {f:6.1f} {pf:5.2f}")
            except IOError as ex:
                print("error:", ex)
            time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
