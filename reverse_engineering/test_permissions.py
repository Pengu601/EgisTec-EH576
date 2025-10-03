#!/usr/bin/env python3
import usb.core
import sys

VENDOR = 0x1c7a
PRODUCT = 0x0576

print("Looking for EgisTec EH576 device...")
dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)

if dev is None:
    print("Device not found. Make sure it's connected.")
    sys.exit(1)

print(f"Device found: Bus {dev.bus:03d} Device {dev.address:03d}: ID {dev.idVendor:04x}:{dev.idProduct:04x}")

try:
    cfg = dev.get_active_configuration()
    print("✓ Successfully accessed device configuration!")
    print(f"Configuration: {cfg.bConfigurationValue}")
    print(f"Interfaces: {len(cfg.interfaces())}")
except usb.core.USBError as e:
    print(f"✗ Permission error: {e}")
    print("Solutions:")
    print("1. Run with sudo: sudo python3 test_permissions.py")
    print("2. Log out and log back in (to apply group membership)")
    print("3. Unplug and replug the device")
    sys.exit(1)
