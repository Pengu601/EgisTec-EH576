#!/usr/bin/env python3
"""
EgisTec EH576 - Critical Command Finder
Finding the exact command that enables sensor response
"""
import usb.core
import usb.util
import time

print("🔍 EgisTec EH576 - Critical Command Finder")
print("EH575 gets 2-5%, background_baseline gets 0%")
print("Let's find the missing piece...")

# Connect
dev = usb.core.find(idVendor=0x1c7a, idProduct=0x0576)
if not dev:
    print("❌ Device not found")
    exit()

cfg = dev.get_active_configuration()
intf = cfg[(0,0)]
if dev.is_kernel_driver_active(0):
    dev.detach_kernel_driver(0)
usb.util.claim_interface(dev, 0)
print("✅ Connected")

def test_cmd(data, desc):
    try:
        dev.write(0x01, bytes(data))
        resp = dev.read(0x82, 6000, timeout=3000)
        non_zero = sum(1 for b in resp if b != 0)
        pct = (non_zero / len(resp)) * 100
        print(f"📊 {desc}: {pct:.1f}%")
        return pct
    except:
        print(f"❌ {desc}: Failed")
        return 0

print("\n🧪 Test 1: Background baseline approach (should get 0%)")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], "Init 1")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc], "Init 2")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xfc], "Init 3")
bg1 = test_cmd([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background Test")

print(f"\n✅ Baseline result: {bg1:.1f}% (expected: 0%)")

print("\n🧪 Test 2: Add critical EH575 command")
print("Hypothesis: [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd] activates sensor")

# Reset with your working init
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], "Reset 1")
test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc], "Reset 2")

# Add the suspected critical command
test_cmd([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd], "🎯 CRITICAL COMMAND")

# Test background again
bg2 = test_cmd([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background After Critical")

print(f"\n📊 Result after critical command: {bg2:.1f}%")

if bg2 > bg1:
    print(f"🎉 SUCCESS! Critical command found!")
    print(f"Improvement: {bg2/max(bg1,0.1):.1f}x better")
    
    print("\n🖐️ Testing finger capture...")
    print("👆 PLACE FINGER NOW")
    time.sleep(3)
    
    finger = test_cmd([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], "Finger Capture")
    print(f"🔍 Finger result: {finger:.1f}%")
    
    if finger > 10:
        print("🎊 BREAKTHROUGH! Working calibration found!")
        print("\nOptimal sequence:")
        print("[0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc]  # Init 1")
        print("[0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc]  # Init 2") 
        print("[0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd]  # Critical activation")
        print("[0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec]  # Background")
        print("[0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec]  # Finger")
    
else:
    print("🔍 That wasn't it. Testing other EH575 commands...")
    
    critical_candidates = [
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00], "EH575 Init 1"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x00], "EH575 Init 2"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x35, 0x02], "EH575 Sensor Setup"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x80, 0x00], "EH575 Config 1"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x80, 0x00], "EH575 Config 2"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfc], "EH575 Final Cal"),
    ]
    
    for cmd, desc in critical_candidates:
        print(f"\n🧪 Testing: {desc}")
        
        # Reset
        test_cmd([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], "Reset")
        
        # Test this command
        test_cmd(cmd, desc)
        
        # Check background
        bg_test = test_cmd([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "BG Test")
        
        if bg_test > 1.0:
            print(f"🎯 FOUND IT! {desc} enables sensor")
            print(f"Command: {' '.join(f'{b:02x}' for b in cmd)}")
            break

print("\n🧹 Cleanup...")
usb.util.release_interface(dev, 0)
print("✅ Test complete")
