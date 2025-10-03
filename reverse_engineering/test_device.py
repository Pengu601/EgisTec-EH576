#!/usr/bin/env python3
"""
EgisTec EH576 Test Script
Based on EH575 libfprint driver research
"""
import usb.core
import usb.util
import time
import sys
from datetime import datetime

VENDOR = 0x1c7a
PRODUCT = 0x0576

def test_egis_device():
    print("🔍 EgisTec EH576 Protocol Test (Based on EH575 Research)")
    print("=" * 60)
    
    # Find device
    dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
    if dev is None:
        print("❌ Device not found! Make sure EH576 is connected.")
        return False
    
    print(f"✅ Device found: {VENDOR:04x}:{PRODUCT:04x}")
    
    # Check permissions
    try:
        cfg = dev.get_active_configuration()
        intf = cfg[(0,0)]
    except usb.core.USBError as e:
        print(f"❌ Permission error: {e}")
        print("💡 Fix: Run 'sudo python3 test_device.py' or check udev rules")
        return False
    
    # Detach kernel driver and claim interface
    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
        print("🔌 Detaching kernel driver...")
        dev.detach_kernel_driver(intf.bInterfaceNumber)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    
    print("✅ Device claimed successfully")
    
    # Test key EgisTec commands
    test_commands = [
        ("POST_INIT_1", [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc]),
        ("POST_INIT_2", [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc]),
        ("PRE_INIT_1", [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00]),  
        ("PRE_INIT_2", [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x00]),
        ("IMAGE_CMD", [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec]),
    ]
    
    success_count = 0
    
    try:
        for name, cmd in test_commands:
            print(f"\n--- Testing {name} ---")
            cmd_str = ' '.join(f'{b:02x}' for b in cmd)
            print(f"📤 Sending: {cmd_str}")
            
            try:
                # Send command
                dev.write(0x01, bytes(cmd), timeout=2000)
                print("✅ Command sent successfully")
                
                # Read response
                try:
                    # Use larger buffer for image commands
                    buffer_size = 6000 if name == "IMAGE_CMD" else 64
                    timeout = 5000 if name == "IMAGE_CMD" else 2000
                    
                    response = dev.read(0x82, buffer_size, timeout=timeout)
                    resp_str = ' '.join(f'{b:02x}' for b in response[:20])  # Show first 20 bytes
                    if len(response) > 20:
                        resp_str += f"... ({len(response)} total bytes)"
                    
                    print(f"📥 Response: {resp_str}")
                    success_count += 1
                    
                    # Save response
                    filename = f"response_{name.lower()}.bin"
                    with open(filename, "wb") as f:
                        f.write(response)
                    print(f"💾 Saved to {filename}")
                    
                    # Check for special responses
                    if len(response) >= 3:
                        if response[:3] == bytes([0x01, 0x01, 0x01]):
                            print("⚠️  Device requests PRE_INIT sequence")
                        elif len(response) > 100:
                            print("🖼️  Large response - possible image data!")
                    
                except usb.core.USBError as e:
                    if 'timeout' in str(e).lower():
                        print("⏱️  No response (timeout - normal for some commands)")
                    else:
                        print(f"❌ Read error: {e}")
                        
            except usb.core.USBError as e:
                print(f"❌ Send error: {e}")
            
            time.sleep(0.5)  # Pause between commands
        
        print(f"\n📊 Results: {success_count}/{len(test_commands)} commands got responses")
        
        if success_count > 0:
            print("\n🎉 SUCCESS! Device responds to EgisTec protocol!")
            print("📁 Check response_*.bin files for captured data")
            print("🔄 You can now try the full initialization sequence")
        else:
            print("\n🤔 No responses received. Possible issues:")
            print("   • EH576 uses different protocol than EH575")
            print("   • Device needs different initialization")
            print("   • Try with sudo if permission-related")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        try:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
            dev.attach_kernel_driver(intf.bInterfaceNumber)
        except:
            pass
    
    return success_count > 0

if __name__ == "__main__":
    try:
        success = test_egis_device()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)
