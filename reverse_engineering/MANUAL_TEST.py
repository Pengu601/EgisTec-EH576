# Manual Test - Copy and paste into Python terminal
# Finding the critical command that enables sensor response

import usb.core, usb.util

# Connect to device
dev = usb.core.find(idVendor=0x1c7a, idProduct=0x0576)
cfg = dev.get_active_configuration()
intf = cfg[(0,0)]
if dev.is_kernel_driver_active(0): 
    dev.detach_kernel_driver(0)
usb.util.claim_interface(dev, 0)

# Helper function
def test_cmd(cmd, name):
    dev.write(0x01, bytes(cmd))
    resp = dev.read(0x82, 6000, timeout=3000)
    pct = sum(1 for b in resp if b != 0) / len(resp) * 100
    print(f"{name}: {pct:.1f}%")
    return pct

print("=== CRITICAL COMMAND TEST ===")

# Step 1: Your working init (should get 0% background)
print("\nStep 1: Baseline test (should get 0%)")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], "Init 1")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc], "Init 2")
bg_before = test_cmd([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background BEFORE")

# Step 2: Add the critical EH575 command
print("\nStep 2: Adding critical EH575 command")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd], "CRITICAL: 0x61, 0x0a, 0xfd")
bg_after = test_cmd([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background AFTER")

print(f"\nRESULT: Before={bg_before:.1f}%, After={bg_after:.1f}%")

if bg_after > bg_before:
    print("🎉 SUCCESS! Critical command found!")
    print("Now test finger capture:")
    print("PLACE YOUR FINGER ON SENSOR")
    input("Press Enter when finger is on sensor...")
    finger = test_cmd([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], "FINGER")
    print(f"Finger capture: {finger:.1f}%")
    
    if finger > 10:
        print("🎊 BREAKTHROUGH! Working calibration found!")
        print("\nOptimal sequence:")
        print("1. [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc]")
        print("2. [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc]") 
        print("3. [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd]  # CRITICAL")
        print("4. [0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec]  # Background")
        print("5. [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec]  # Finger")
else:
    print("❌ That wasn't the critical command")
    print("Try these other EH575 commands:")
    print("test_cmd([0x45, 0x47, 0x49, 0x53, 0x61, 0x35, 0x02], 'Test 1')")
    print("test_cmd([0x45, 0x47, 0x49, 0x53, 0x61, 0x80, 0x00], 'Test 2')")
    print("test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x80, 0x00], 'Test 3')")

# Cleanup
usb.util.release_interface(dev, 0)
print("✅ Test complete")
