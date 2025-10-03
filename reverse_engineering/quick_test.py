#!/usr/bin/env python3
import usb.core
import usb.util
import time
import sys

VENDOR = 0x1c7a
PRODUCT = 0x0576

print("Testing EgisTec EH576 with EH575 commands...")

# Connect to device
dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
if dev is None:
    print("❌ Device not found!")
    sys.exit(1)

try:
    cfg = dev.get_active_configuration()
    intf = cfg[(0,0)]
    
    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
        dev.detach_kernel_driver(intf.bInterfaceNumber)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    
    print("✅ Device connected")
    
    # Test a few key commands from EH575
    test_commands = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00],  # First PRE_INIT command
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x00],  # Second PRE_INIT command
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc],  # First POST_INIT command
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc],  # Second POST_INIT command (checks device state)
    ]
    
    for i, cmd in enumerate(test_commands):
        print(f"\n--- Testing command {i+1} ---")
        cmd_str = ' '.join(f'{b:02x}' for b in cmd)
        print(f"Sending: {cmd_str}")
        
        try:
            # Send command
            dev.write(0x01, bytes(cmd), timeout=2000)
            
            # Try to read response
            try:
                response = dev.read(0x82, 64, timeout=2000)
                resp_str = ' '.join(f'{b:02x}' for b in response)
                print(f"✅ Response: {resp_str}")
                
                # Save response
                with open(f"test_cmd_{i+1}_response.bin", "wb") as f:
                    f.write(response)
                
            except usb.core.USBError as e:
                if 'timeout' in str(e).lower():
                    print("⏱️  No response (timeout)")
                else:
                    print(f"❌ Read error: {e}")
                    
        except Exception as e:
            print(f"❌ Send error: {e}")
        
        time.sleep(0.5)
    
    print("\n🔍 If any responses were received, check the test_cmd_*_response.bin files")
    
    # Cleanup
    usb.util.release_interface(dev, intf.bInterfaceNumber)
    try:
        dev.attach_kernel_driver(intf.bInterfaceNumber)
    except:
        pass

except Exception as e:
    print(f"❌ Error: {e}")

print("Done!")
