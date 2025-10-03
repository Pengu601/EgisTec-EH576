#!/usr/bin/env python3
"""
EgisTec EH576 - Targeted Fingerprint Capture
Based on successful command 6 response
"""
import usb.core
import usb.util
import time
import sys
from datetime import datetime

VENDOR = 0x1c7a
PRODUCT = 0x0576

def connect_device():
    dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
    if dev is None:
        print("❌ Device not found")
        return None
    
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError as e:
        print(f"❌ Permission error: {e}")
        return None
    
    intf = cfg[(0,0)]
    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
        dev.detach_kernel_driver(intf.bInterfaceNumber)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    
    print("✅ Device connected")
    return dev, intf

def send_and_receive(dev, cmd, expected_response_size=64, timeout=2000):
    """Send command and read response"""
    try:
        # Send command
        dev.write(0x01, bytes(cmd), timeout=timeout)
        cmd_str = ' '.join(f'{b:02x}' for b in cmd)
        print(f"📤 Sent: {cmd_str}")
        
        # Read response
        try:
            response = dev.read(0x82, expected_response_size, timeout=timeout)
            resp_str = ' '.join(f'{b:02x}' for b in response[:20])
            if len(response) > 20:
                resp_str += f"... ({len(response)} total bytes)"
            print(f"📥 Response: {resp_str}")
            return response
        except usb.core.USBError as e:
            if 'timeout' not in str(e).lower():
                print(f"❌ Read error: {e}")
            return None
            
    except Exception as e:
        print(f"❌ Send error: {e}")
        return None

def capture_fingerprint_sequence(dev):
    """Execute the successful command sequence with finger detection"""
    
    print("\n🚀 Starting Fingerprint Capture Sequence")
    print("=" * 50)
    
    # Commands that worked (based on your success)
    init_commands = [
        # Command 1-5 (setup)
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc],  # POST_INIT 1
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc],  # POST_INIT 2
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xfc],  # POST_INIT 3
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x09, 0x0b, 0x83, 0x24, 0x00, 0x44, 0x0f, 0x08, 0x20, 0x20, 0x01, 0x05, 0x12],  # Config
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06],  # Setup
    ]
    
    # Execute initialization
    print("\n📋 Phase 1: Device Initialization")
    for i, cmd in enumerate(init_commands):
        print(f"\n--- Init Command {i+1} ---")
        response = send_and_receive(dev, cmd)
        time.sleep(0.2)
    
    # Command 6 - The successful image capture command
    image_command = [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec]  # This was your successful "command 6"
    
    print("\n🖼️  Phase 2: Image Capture")
    print("👆 PLACE YOUR FINGER ON THE SENSOR NOW!")
    print("Press Enter when finger is positioned...")
    input()
    
    # Try multiple captures with finger on sensor
    for attempt in range(3):
        print(f"\n--- Capture Attempt {attempt + 1} ---")
        
        # Send image capture command
        response = send_and_receive(dev, image_command, expected_response_size=6000, timeout=5000)
        
        if response and len(response) > 100:
            # Save the capture
            filename = f"fingerprint_capture_{attempt + 1}_{datetime.now().strftime('%H%M%S')}.bin"
            with open(filename, 'wb') as f:
                f.write(response)
            print(f"💾 Saved {len(response)} bytes to {filename}")
            
            # Quick analysis
            non_zero_bytes = sum(1 for b in response if b != 0)
            if non_zero_bytes > len(response) * 0.1:  # More than 10% non-zero
                print(f"🎉 SUCCESS! Captured {non_zero_bytes} non-zero bytes - likely fingerprint data!")
            else:
                print(f"📊 Captured mostly zeros - sensor may be empty or need calibration")
        
        time.sleep(1)
    
    print("\n🔄 Phase 3: Continuous Monitoring")
    print("Keep finger on sensor, monitoring for changes...")
    
    try:
        for i in range(10):  # 10 more attempts
            print(f"Monitoring... {i+1}/10")
            response = send_and_receive(dev, image_command, expected_response_size=6000, timeout=2000)
            
            if response and len(response) > 100:
                non_zero_bytes = sum(1 for b in response if b != 0)
                if non_zero_bytes > len(response) * 0.2:  # More than 20% non-zero
                    filename = f"fingerprint_monitor_{i+1}_{datetime.now().strftime('%H%M%S')}.bin"
                    with open(filename, 'wb') as f:
                        f.write(response)
                    print(f"🎯 GOOD CAPTURE! {non_zero_bytes} non-zero bytes saved to {filename}")
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n⏹️  Monitoring stopped by user")

def main():
    print("🖐️  EgisTec EH576 - Targeted Fingerprint Capture")
    print("Based on your successful command 6 results!")
    print("=" * 50)
    
    result = connect_device()
    if result is None:
        return
    
    dev, intf = result
    
    try:
        capture_fingerprint_sequence(dev)
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        usb.util.release_interface(dev, intf.bInterfaceNumber)
        try:
            dev.attach_kernel_driver(intf.bInterfaceNumber)
        except:
            pass

if __name__ == "__main__":
    main()
