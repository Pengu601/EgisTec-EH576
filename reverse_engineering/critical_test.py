#!/usr/bin/env python3

"""
CRITICAL COMMAND FINDER - EgisTec EH576
=======================================

This script tests the hypothesis that command [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd] 
is the critical sensor activation command missing from our calibration.

USAGE:
1. Run this script: python3 critical_test.py
2. Follow the prompts
3. Compare background capture percentages before/after the critical command

EXPECTED RESULT:
- Background BEFORE: ~0%
- Background AFTER: 2-5% (like EH575)
- This would prove we found the missing sensor activation command
"""

import usb.core
import usb.util
import sys

def main():
    print("🔍 EgisTec EH576 Critical Command Test")
    print("=" * 40)
    
    try:
        # Connect
        print("Connecting to device...")
        dev = usb.core.find(idVendor=0x1c7a, idProduct=0x0576)
        if dev is None:
            print("❌ Device not found!")
            return
            
        cfg = dev.get_active_configuration()
        intf = cfg[(0,0)]
        
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
        usb.util.claim_interface(dev, 0)
        print("✅ Connected successfully")
        
        def test_command(cmd, name):
            print(f"\nTesting {name}...")
            dev.write(0x01, bytes(cmd))
            resp = dev.read(0x82, 6000, timeout=3000)
            non_zero = sum(1 for b in resp if b != 0)
            percentage = (non_zero / len(resp)) * 100
            print(f"Result: {percentage:.2f}% non-zero ({non_zero}/{len(resp)} bytes)")
            return percentage
        
        # Phase 1: Basic initialization (your working commands)
        print("\n📋 PHASE 1: Basic Initialization")
        test_command([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], "Init Command 1")
        test_command([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc], "Init Command 2")
        
        # Phase 2: Background capture BEFORE critical command
        print("\n📋 PHASE 2: Background Capture (BEFORE critical)")
        bg_before = test_command([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background BEFORE")
        
        # Phase 3: The critical EH575 command
        print("\n📋 PHASE 3: Critical EH575 Command")
        print("🎯 Testing suspected sensor activation command...")
        test_command([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd], "CRITICAL: 0x61, 0x0a, 0xfd")
        
        # Phase 4: Background capture AFTER critical command
        print("\n📋 PHASE 4: Background Capture (AFTER critical)")
        bg_after = test_command([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Background AFTER")
        
        # Analysis
        print("\n" + "=" * 40)
        print("📊 ANALYSIS:")
        print(f"Background BEFORE critical: {bg_before:.2f}%")
        print(f"Background AFTER critical:  {bg_after:.2f}%")
        print(f"Improvement: {bg_after - bg_before:.2f}%")
        
        if bg_after > bg_before + 1:  # Significant improvement
            print("\n🎉 SUCCESS! Critical command identified!")
            print("The command [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd] activates the sensor!")
            
            # Test finger capture
            print("\n📋 PHASE 5: Finger Capture Test")
            print("Place your finger on the sensor and press Enter...")
            input()
            finger_result = test_command([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], "Finger Capture")
            
            if finger_result > 10:
                print(f"\n🎊 BREAKTHROUGH! Finger capture: {finger_result:.2f}%")
                print("\n✅ OPTIMAL CALIBRATION SEQUENCE FOUND:")
                print("1. [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc]  # Init 1")
                print("2. [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc]  # Init 2") 
                print("3. [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd]  # SENSOR ACTIVATION")
                print("4. [0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec]  # Background")
                print("5. [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec]  # Finger")
            else:
                print(f"Finger capture still low: {finger_result:.2f}%")
                print("Need to test additional commands...")
        else:
            print("\n❌ That wasn't the critical command")
            print("Try testing these other EH575 commands manually:")
            print("- [0x45, 0x47, 0x49, 0x53, 0x61, 0x35, 0x02]")
            print("- [0x45, 0x47, 0x49, 0x53, 0x61, 0x80, 0x00]")
            print("- [0x45, 0x47, 0x49, 0x53, 0x60, 0x80, 0x00]")
            print("- [0x45, 0x47, 0x49, 0x53, 0x61, 0x50, 0x4d]")
        
        # Cleanup
        usb.util.release_interface(dev, 0)
        print("\n✅ Test completed successfully")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Make sure:")
        print("1. Device is connected")
        print("2. You have permission (udev rules)")
        print("3. No other process is using the device")

if __name__ == "__main__":
    main()
