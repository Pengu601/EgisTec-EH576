#!/usr/bin/env python3
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
        print("Device not found")
        return None
    
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError as e:
        print(f"Permission error: {e}")
        return None
    
    intf = cfg[(0,0)]
    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
        dev.detach_kernel_driver(intf.bInterfaceNumber)
    usb.util.claim_interface(dev, intf.bInterfaceNumber)
    
    return dev, intf

def send_command(dev, data, endpoint=0x01):
    """Send command to device"""
    try:
        result = dev.write(endpoint, data, timeout=1000)
        print(f"Sent {len(data)} bytes to EP {hex(endpoint)}: {' '.join(f'{b:02x}' for b in data)}")
        return result
    except Exception as e:
        print(f"Failed to send command: {e}")
        return None

def read_response(dev, endpoint, length=64, timeout=2000):
    """Read response from device"""
    try:
        data = dev.read(endpoint, length, timeout=timeout)
        print(f"Received {len(data)} bytes from EP {hex(endpoint)}: {' '.join(f'{b:02x}' for b in data)}")
        return data
    except usb.core.USBError as e:
        if 'timeout' not in str(e).lower():
            print(f"Read error from EP {hex(endpoint)}: {e}")
        return None

def try_fingerprint_commands(dev):
    """Try various commands that might activate the fingerprint sensor"""
    
    commands = [
        # Basic commands
        [0x01],                    # Simple start
        [0x00],                    # Reset/init
        [0x02],                    # Another init
        [0xAA],                    # From analysis logs
        [0x55],                    # Common pattern
        [0x01, 0x00],              # Init with parameter
        [0x02, 0x00],              # Start scan
        [0x03, 0x00],              # Get status
        [0x04, 0x00],              # Get image
        [0x05, 0x00],              # Stop scan
        [0x60],                    # From decompiled code
        [0x60, 0x00],              # Prefixed command
        [0x60, 0x01],              # Another variant
        
        # Multi-byte sequences
        [0x01, 0x02, 0x03],        # Sequential
        [0xAA, 0x55],              # Pattern
        [0x55, 0xAA],              # Reverse pattern
        [0x00, 0x01, 0x00],        # Common init pattern
        [0x01, 0x01, 0x01],        # Repeated pattern
        
        # Longer sequences (from Windows driver analysis)
        [0x60, 0x00, 0x00, 0x00],  # Extended command
        [0x01, 0x00, 0x00, 0x01],  # Parameter command
    ]
    
    bulk_in = 0x82
    intr_in = [0x83, 0x84]
    
    for i, cmd in enumerate(commands):
        print(f"\n--- Testing command {i+1}/{len(commands)} ---")
        
        # Send command
        result = send_command(dev, bytes(cmd))
        if result is None:
            continue
            
        # Wait a bit
        time.sleep(0.1)
        
        # Try to read responses from all IN endpoints
        response_found = False
        for ep in [bulk_in] + intr_in:
            data = read_response(dev, ep, timeout=500)
            if data:
                response_found = True
                # Save successful command/response
                with open(f"cmd_{i+1}_response.bin", "wb") as f:
                    f.write(data)
        
        if response_found:
            print(f"*** Command {i+1} got response! ***")
            
        time.sleep(0.2)  # Pause between commands

def continuous_monitor(dev):
    """Monitor for any activity after commands"""
    print("\n" + "="*60)
    print("CONTINUOUS MONITORING")
    print("Touch sensor now or perform any action...")
    print("Press Ctrl+C to stop")
    print("="*60)
    
    bulk_in = 0x82
    intr_in = [0x83, 0x84]
    
    try:
        count = 0
        while True:
            count += 1
            if count % 100 == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Still monitoring... (cycle {count})")
            
            # Check all endpoints
            for ep in [bulk_in] + intr_in:
                data = read_response(dev, ep, timeout=50)
                if data:
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    print(f"\n[{timestamp}] *** ACTIVITY DETECTED on EP {hex(ep)} ***")
                    with open(f"activity_{timestamp.replace(':', '')}.bin", "wb") as f:
                        f.write(data)
            
            time.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\nStopping monitoring...")

def main():
    print("EgisTec EH576 Fingerprint Scanner Test")
    print("=====================================")
    
    result = connect_device()
    if result is None:
        return
    
    dev, intf = result
    
    try:
        # First try various initialization commands
        try_fingerprint_commands(dev)
        
        # Then monitor continuously
        continuous_monitor(dev)
        
    finally:
        # Cleanup
        print("\nCleaning up...")
        usb.util.release_interface(dev, intf.bInterfaceNumber)
        try:
            dev.attach_kernel_driver(intf.bInterfaceNumber)
        except:
            pass

if __name__ == "__main__":
    main()
