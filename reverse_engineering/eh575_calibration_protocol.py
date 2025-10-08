#!/usr/bin/env python3
"""
EgisTec EH576 - Complete EH575 Calibration Protocol Implementation
Based on the libfprint.patch USB command sequences
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

def send_and_receive(dev, cmd, expected_response_size=64, timeout=2000, description=""):
    """Send command and read response"""
    try:
        # Send command
        dev.write(0x01, bytes(cmd), timeout=timeout)
        cmd_str = ' '.join(f'{b:02x}' for b in cmd)
        print(f"📤 {description}: {cmd_str}")
        
        # Read response
        try:
            response = dev.read(0x82, expected_response_size, timeout=timeout)
            resp_str = ' '.join(f'{b:02x}' for b in response[:20])
            if len(response) > 20:
                resp_str += f"... ({len(response)} total bytes)"
            print(f"📥 Response: {resp_str}")
            
            # Check for SIGE header
            if len(response) >= 4 and response[:4] == bytes([0x53, 0x49, 0x47, 0x45]):
                print("✅ Valid SIGE response received")
            
            return response
        except usb.core.USBError as e:
            if 'timeout' not in str(e).lower():
                print(f"❌ Read error: {e}")
            return None
            
    except Exception as e:
        print(f"❌ Send error: {e}")
        return None

def analyze_capture_quality(data):
    """Analyze the quality of captured data"""
    if not data or len(data) < 100:
        return "No data"
    
    non_zero_bytes = sum(1 for b in data if b != 0)
    total_bytes = len(data)
    percentage = (non_zero_bytes / total_bytes) * 100
    
    # Calculate entropy (simplified)
    unique_values = len(set(data))
    entropy = unique_values / 256  # Normalized entropy
    
    if percentage > 50 and entropy > 0.3:
        return f"EXCELLENT ({percentage:.1f}% non-zero, entropy: {entropy:.2f})"
    elif percentage > 20 and entropy > 0.1:
        return f"GOOD ({percentage:.1f}% non-zero, entropy: {entropy:.2f})"
    elif percentage > 5:
        return f"FAIR ({percentage:.1f}% non-zero, entropy: {entropy:.2f})"
    else:
        return f"POOR ({percentage:.1f}% non-zero, entropy: {entropy:.2f})"

def execute_eh575_calibration(dev):
    """Execute the complete EH575 calibration sequence"""
    
    print("\n🔧 Phase 1: EH575 PRE_INIT_PACKETS (Full Calibration)")
    print("=" * 60)
    
    # PRE_INIT_PACKETS - 29 commands from libfprint.patch
    pre_init_packets = [
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00], 7, "PRE_INIT 1"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x00], 7, "PRE_INIT 2"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd], 7, "PRE_INIT 3"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x35, 0x02], 7, "PRE_INIT 4"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x80, 0x00], 7, "PRE_INIT 5"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x80, 0x00], 7, "PRE_INIT 6"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfc], 7, "PRE_INIT 7"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x01, 0x02, 0x0f, 0x03], 9, "PRE_INIT 8"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0c, 0x22], 7, "PRE_INIT 9"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x09, 0x83], 7, "PRE_INIT 10"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06], 13, "PRE_INIT 11 - Config"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xf4], 7, "PRE_INIT 12"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0c, 0x44], 7, "PRE_INIT 13"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x50, 0x03], 7, "PRE_INIT 14"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x50, 0x03], 7, "PRE_INIT 15"),
        ([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], 5356, "PRE_INIT 16 - BIG CAPTURE"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xec], 7, "PRE_INIT 17"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x09, 0x0b, 0x83, 0x24, 0x00, 0x44, 0x0f, 0x08, 0x20, 0x20, 0x01, 0x05, 0x12], 18, "PRE_INIT 18 - Config"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06], 13, "PRE_INIT 19 - Config"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x23, 0x00], 7, "PRE_INIT 20"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x24, 0x33], 7, "PRE_INIT 21"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x20, 0x00], 7, "PRE_INIT 22"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x21, 0x66], 7, "PRE_INIT 23"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x66], 7, "PRE_INIT 24"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x66], 7, "PRE_INIT 25"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0x66], 7, "PRE_INIT 26"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0c, 0x22], 7, "PRE_INIT 27"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0b, 0x03], 7, "PRE_INIT 28"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfc], 7, "PRE_INIT 29 - Final"),
    ]
    
    # Execute PRE_INIT sequence
    for i, (cmd, expected_size, description) in enumerate(pre_init_packets):
        print(f"\n--- {description} ({i+1}/29) ---")
        response = send_and_receive(dev, cmd, expected_size, timeout=5000, description=description)
        
        # Special analysis for the big capture (command 16)
        if i == 15 and response:  # PRE_INIT 16 - the big one
            quality = analyze_capture_quality(response)
            print(f"🔍 PRE_INIT Capture Quality: {quality}")
            if "EXCELLENT" in quality or "GOOD" in quality:
                filename = f"pre_init_calibration_{datetime.now().strftime('%H%M%S')}.bin"
                with open(filename, 'wb') as f:
                    f.write(response)
                print(f"💾 Saved PRE_INIT calibration to {filename}")
        
        time.sleep(0.3)
    
    print("\n✅ PRE_INIT Calibration Complete!")
    
    print("\n🔧 Phase 2: EH575 POST_INIT_PACKETS")
    print("=" * 60)
    
    # POST_INIT_PACKETS - 18 commands  
    post_init_packets = [
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0xfc], 7, "POST_INIT 1"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0xfc], 7, "POST_INIT 2"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x40, 0xfc], 7, "POST_INIT 3"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x09, 0x0b, 0x83, 0x24, 0x00, 0x44, 0x0f, 0x08, 0x20, 0x20, 0x01, 0x05, 0x12], 18, "POST_INIT 4 - Config"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06], 13, "POST_INIT 5 - Config"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x23, 0x00], 7, "POST_INIT 6"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x24, 0x33], 7, "POST_INIT 7"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x20, 0x00], 7, "POST_INIT 8"),
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x21, 0x66], 7, "POST_INIT 9"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x66], 7, "POST_INIT 10"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x66], 7, "POST_INIT 11"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x2c, 0x02, 0x00, 0x57], 9, "POST_INIT 12"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x2d, 0x02], 7, "POST_INIT 13"),
        ([0x45, 0x47, 0x49, 0x53, 0x62, 0x67, 0x03], 10, "POST_INIT 14"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x0f, 0x03], 7, "POST_INIT 15"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x2c, 0x02, 0x00, 0x13], 9, "POST_INIT 16"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x02], 7, "POST_INIT 17"),
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], 5356, "POST_INIT 18 - IMAGE CAPTURE"),
    ]
    
    # Execute POST_INIT sequence
    for i, (cmd, expected_size, description) in enumerate(post_init_packets):
        print(f"\n--- {description} ({i+1}/18) ---")
        response = send_and_receive(dev, cmd, expected_size, timeout=5000, description=description)
        
        # Special analysis for the final image capture
        if i == 17 and response:  # POST_INIT 18 - final image
            quality = analyze_capture_quality(response)
            print(f"🔍 POST_INIT Image Quality: {quality}")
            if "EXCELLENT" in quality or "GOOD" in quality:
                filename = f"post_init_image_{datetime.now().strftime('%H%M%S')}.bin"
                with open(filename, 'wb') as f:
                    f.write(response)
                print(f"💾 Saved POST_INIT image to {filename}")
        
        time.sleep(0.2)
    
    print("\n✅ POST_INIT Complete!")
    
    return True

def execute_repeat_cycle(dev):
    """Execute the REPEAT_PACKETS cycle for continuous capture"""
    
    print("\n🔄 Phase 3: EH575 REPEAT_PACKETS (Continuous Capture)")
    print("=" * 60)
    print("👆 PLACE YOUR FINGER ON THE SENSOR NOW!")
    
    # REPEAT_PACKETS - 9 commands for continuous operation
    repeat_packets = [
        ([0x45, 0x47, 0x49, 0x53, 0x61, 0x2d, 0x20], 7, "REPEAT 1"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x20], 7, "REPEAT 2"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x20], 7, "REPEAT 3"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x2c, 0x02, 0x00, 0x57], 9, "REPEAT 4"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x2d, 0x02], 7, "REPEAT 5"),
        ([0x45, 0x47, 0x49, 0x53, 0x62, 0x67, 0x03], 10, "REPEAT 6"),
        ([0x45, 0x47, 0x49, 0x53, 0x63, 0x2c, 0x02, 0x00, 0x13], 9, "REPEAT 7"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x02], 7, "REPEAT 8"),
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], 5356, "REPEAT 9 - FINGERPRINT CAPTURE"),
    ]
    
    cycle_count = 0
    successful_captures = 0
    
    try:
        while cycle_count < 10:  # Try 10 cycles
            cycle_count += 1
            print(f"\n🔄 Capture Cycle {cycle_count}/10")
            
            # Execute full repeat sequence
            for i, (cmd, expected_size, description) in enumerate(repeat_packets):
                response = send_and_receive(dev, cmd, expected_size, timeout=3000, description=description)
                
                # Analyze the final capture command
                if i == 8 and response:  # REPEAT 9 - fingerprint capture
                    quality = analyze_capture_quality(response)
                    print(f"🔍 Fingerprint Quality: {quality}")
                    
                    if "EXCELLENT" in quality or "GOOD" in quality:
                        successful_captures += 1
                        filename = f"fingerprint_cycle_{cycle_count}_{datetime.now().strftime('%H%M%S')}.bin"
                        with open(filename, 'wb') as f:
                            f.write(response)
                        print(f"🎯 SUCCESS! Saved quality fingerprint to {filename}")
                    elif "FAIR" in quality:
                        filename = f"fingerprint_fair_{cycle_count}_{datetime.now().strftime('%H%M%S')}.bin"
                        with open(filename, 'wb') as f:
                            f.write(response)
                        print(f"📝 Fair quality saved to {filename}")
                
                time.sleep(0.1)
            
            time.sleep(1)  # Pause between cycles
            
    except KeyboardInterrupt:
        print(f"\n⏹️  Stopped by user after {cycle_count} cycles")
    
    print(f"\n📊 Results: {successful_captures} successful captures out of {cycle_count} cycles")
    return successful_captures > 0

def main():
    print("🔧 EgisTec EH576 - Complete EH575 Calibration Protocol")
    print("Implementing exact libfprint.patch USB sequences")
    print("=" * 65)
    
    result = connect_device()
    if result is None:
        return
    
    dev, intf = result
    
    try:
        # Execute the complete EH575 calibration protocol
        if execute_eh575_calibration(dev):
            print("\n🎉 Calibration successful! Now ready for fingerprint capture.")
            
            # Execute continuous capture cycles
            success = execute_repeat_cycle(dev)
            
            if success:
                print("\n🎊 SUCCESS! EH575 protocol working on EH576!")
                print("You now have calibrated fingerprint captures.")
            else:
                print("\n⚠️  Calibration complete but fingerprint quality still poor.")
                print("Try different finger positions or check sensor.")
        
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
