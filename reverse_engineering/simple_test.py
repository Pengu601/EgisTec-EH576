#!/usr/bin/env python3
"""
Simple test to find the critical missing command
"""
import usb.core, usb.util

# Connect
dev = usb.core.find(idVendor=0x1c7a, idProduct=0x0576)
cfg = dev.get_active_configuration()
intf = cfg[(0,0)]
if dev.is_kernel_driver_active(0): dev.detach_kernel_driver(0)
usb.util.claim_interface(dev, 0)

def test(cmd, name):
    dev.write(0x01, bytes(cmd))
    resp = dev.read(0x82, 6000, timeout=3000)
    pct = sum(1 for b in resp if b != 0) / len(resp) * 100
    print(f"{name}: {pct:.1f}%")
    return pct

print("Testing critical command hypothesis...")

# Your working init (gets 0% background)
test([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], "Init 1")
test([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc], "Init 2")
bg1 = test([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background baseline")

# Add suspected critical command
test([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd], "CRITICAL COMMAND")
bg2 = test([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background after critical")

print(f"Before: {bg1:.1f}%, After: {bg2:.1f}%")

if bg2 > bg1:
    print("SUCCESS! Critical command found!")
    print("Place finger and press Enter...")
    input()
    finger = test([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], "Finger")
    print(f"Finger: {finger:.1f}%")
else:
    print("Not it. Try other commands manually.")

usb.util.release_interface(dev, 0)
