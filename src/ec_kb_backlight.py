#!/usr/bin/env python3
"""Single-color keyboard backlight control via EC.

Usage:
  python ec_kb_backlight.py status      Show current backlight state
  python ec_kb_backlight.py off         Turn backlight off
  python ec_kb_backlight.py dim         Dim backlight
  python ec_kb_backlight.py bright      Bright backlight (alias: on)
  python ec_kb_backlight.py level 2     Set level 0-4 (0=off, 4=bright)

Register: EC[1932] (ADDR_SINGLEKBL_ENABLE)
  bit1   = power (0=on, 1=off)
  bit4   = 0x10 always set
  bits5-7 = brightness level 0-4

Source: SingleColorKeyboard.cs (BacklightLevel, EcBacklightLevel, SetPower)
"""
import argparse, ctypes, struct, sys

GENERIC_READ = 0x80000000; GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 3; OPEN_EXISTING = 3
IOCTL_EC_READ = 2621482120; IOCTL_EC_WRITE = 2621482124
DEVICE_PATH = r'\\.\ACPIDriver'
kernel32 = ctypes.windll.kernel32

LEVEL_LABELS = {0: 'off', 1: 'level1', 2: 'dim', 3: 'level3', 4: 'bright'}

def open_dev():
    h = kernel32.CreateFileW(DEVICE_PATH, GENERIC_READ|GENERIC_WRITE,
                             FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
    if h in (-1, 0xFFFFFFFFFFFFFFFF):
        raise OSError(f'Cannot open {DEVICE_PATH}')
    return h

def ec_read(h, a):
    o = ctypes.c_int(0)
    kernel32.DeviceIoControl(h, IOCTL_EC_READ, struct.pack('<II',a,1), 8,
                              ctypes.byref(o), 4, None, None)
    return o.value & 0xFF

def ec_write(h, a, v):
    o = ctypes.c_int(0)
    kernel32.DeviceIoControl(h, IOCTL_EC_WRITE, struct.pack('<II',a,v), 8,
                              ctypes.byref(o), 4, None, None)

def parse_level(reg):
    return (reg >> 5) & 7

def status(h):
    reg = ec_read(h, 1932)
    lvl = parse_level(reg)
    on = not (reg & 2)
    label = LEVEL_LABELS.get(lvl, '?')
    print(f'EC[1932] = {reg:3d} (0x{reg:02x})')
    print(f'  Power:    {"ON" if on else "OFF"} (bit1={int(not on)})')
    print(f'  Level:    {lvl} ({label})')
    print(f'  Bits:     {reg:08b}')
    return reg

def set_level(h, lvl):
    if not (0 <= lvl <= 4):
        raise ValueError('level must be 0-4')
    reg = ec_read(h, 1932)
    reg |= 0x10            # bit4 always set (from EcBacklightLevel)
    reg &= 0x1F            # clear bits 5-7
    reg |= (lvl & 7) << 5  # set level
    reg &= ~2              # power on (clear bit1)
    ec_write(h, 1932, reg)
    print(f'Set keyboard backlight level to {lvl} ({LEVEL_LABELS.get(lvl, "?")})')
    print(f'EC[1932] = {reg} (0x{reg:02x})')

def set_power(h, on):
    reg = ec_read(h, 1932)
    if on:
        reg &= ~2
    else:
        reg |= 2
    ec_write(h, 1932, reg)
    print(f'Keyboard backlight {"ON" if on else "OFF"}')
    print(f'EC[1932] = {reg} (0x{reg:02x})')

def main():
    p = argparse.ArgumentParser(description='Single-color keyboard backlight control')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status', help='Show backlight state')
    sp = sub.add_parser('off', help='Turn backlight off')
    sp.set_defaults(level=0, power=False)
    sp = sub.add_parser('dim', help='Dim backlight')
    sp.set_defaults(level=2)
    sp = sub.add_parser('bright', help='Bright backlight')
    sp.set_defaults(level=4)
    sp = sub.add_parser('on', help='Turn backlight on (bright)')
    sp.set_defaults(level=4)
    sp = sub.add_parser('level', help='Set specific level 0-4')
    sp.add_argument('value', type=int, help='0=off, 1-2=dim, 3-4=bright')
    args = p.parse_args()
    h = open_dev()
    try:
        if args.cmd == 'status':
            status(h)
        elif args.cmd == 'off':
            set_level(h, 0)
        elif args.cmd in ('dim', 'bright', 'on'):
            set_level(h, {'dim': 2, 'bright': 4, 'on': 4}[args.cmd])
        elif args.cmd == 'level':
            set_level(h, args.value)
    finally:
        kernel32.CloseHandle(h)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'error: {e}', file=sys.stderr); sys.exit(1)
