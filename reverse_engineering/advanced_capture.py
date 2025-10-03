#!/usr/bin/env python3
"""
EgisTec EH576 - Advanced Fingerprint Capture
Multiple strategies to handle "mostly zeros" issue
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

def try_full_eh575_sequence(dev):
    """Try the complete EH575 initialization sequence"""
    
    print("\n🔧 Strategy 1: Full EH575 PRE_INIT Sequence")
    print("=" * 50)
    
    # Complete PRE_INIT sequence from EH575 libfprint driver
    pre_init_commands = [
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00],  # Basic init
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x00],  # Basic init 2
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfd],  # Setup
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x35, 0x02],  # Config
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x80, 0x00],  # Enable
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x80, 0x00],  # Enable variant
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xfc],  # Switch to POST_INIT
    ]
    
    # Execute PRE_INIT sequence
    print("Executing PRE_INIT sequence...")
    for i, cmd in enumerate(pre_init_commands):
        print(f"\nPRE_INIT Command {i+1}:")
        response = send_and_receive(dev, cmd)
        
        # Check for special responses that indicate state changes
        if response and len(response) >= 3:
            if response[:3] == bytes([0x01, 0x01, 0x01]):
                print("⚠️  Device requests different initialization")
            elif response[:4] == b'SIGE':
                print("✅ SIGE response - device responding correctly")
        
        time.sleep(0.3)
    
    return True

def try_sensor_calibration(dev):
    """Try sensor calibration commands"""
    
    print("\n🎯 Strategy 2: Sensor Calibration")
    print("=" * 50)
    
    calibration_commands = [
        # Calibration and sensor setup commands from EH575
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x01, 0x02, 0x0f, 0x03],  # Calibration setup
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0c, 0x22],  # Calibration mode
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x09, 0x83],  # Sensor config
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x26, 0x06, 0x06, 0x60, 0x06, 0x05, 0x2f, 0x06],  # Complex config
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0a, 0xf4],  # Calibration trigger
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x0c, 0x44],  # Another calibration
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x50, 0x03],  # Sensor enable
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x50, 0x03],  # Sensor enable variant
    ]
    
    print("🔧 NO FINGER - Calibrating empty sensor...")
    for i, cmd in enumerate(calibration_commands):
        print(f"\nCalibration {i+1}:")
        response = send_and_receive(dev, cmd)
        time.sleep(0.2)
    
    return True

def try_image_commands_variations(dev):
    """Try different image capture command variations"""
    
    print("\n📸 Strategy 3: Multiple Image Capture Approaches")
    print("=" * 50)
    
    # Different image capture commands found in EH575
    image_commands = [
        ([0x45, 0x47, 0x49, 0x53, 0x73, 0x14, 0xec], "Original EH575 image command"),
        ([0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec], "Your successful command 6"),
        ([0x45, 0x47, 0x49, 0x53, 0x62, 0x67, 0x03], "Alternative capture"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x2d, 0x02], "Capture trigger"),
        ([0x45, 0x47, 0x49, 0x53, 0x60, 0x0f, 0x03], "Capture ready"),
    ]
    
    print("👆 PLACE FINGER NOW and press Enter...")
    input()
    
    best_capture = None
    best_score = 0
    
    for cmd, description in image_commands:
        print(f"\n📷 Trying: {description}")
        
        # Try multiple captures with this command
        for attempt in range(2):
            response = send_and_receive(dev, cmd, expected_response_size=6000, timeout=5000)
            
            if response and len(response) > 100:
                non_zero_bytes = sum(1 for b in response if b != 0)
                zero_ratio = (len(response) - non_zero_bytes) / len(response)
                score = non_zero_bytes / len(response)  # Percentage of non-zero data
                
                print(f"   Attempt {attempt+1}: {len(response)} bytes, {non_zero_bytes} non-zero ({score:.1%})")
                
                # Save if this is the best capture so far
                if score > best_score:
                    best_score = score
                    best_capture = (response, cmd, description)
                    filename = f"best_capture_{datetime.now().strftime('%H%M%S')}.bin"
                    with open(filename, 'wb') as f:
                        f.write(response)
                    print(f"   🏆 NEW BEST! Saved to {filename}")
            
            time.sleep(0.5)
    
    return best_capture, best_score

def try_continuous_scan_mode(dev):
    """Try continuous scanning like a real fingerprint sensor"""
    
    print("\n🔄 Strategy 4: Continuous Scan Mode")
    print("=" * 50)
    
    # Commands for continuous scanning from EH575 REPEAT sequence
    scan_commands = [
        [0x45, 0x47, 0x49, 0x53, 0x61, 0x2d, 0x20],  # Scan mode setup
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x20],  # Scan ready
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x01, 0x20],  # Scan start
        [0x45, 0x47, 0x49, 0x53, 0x63, 0x2c, 0x02, 0x00, 0x57],  # Scan config
        [0x45, 0x47, 0x49, 0x53, 0x60, 0x2d, 0x02],  # Scan trigger
        [0x45, 0x47, 0x49, 0x53, 0x64, 0x14, 0xec],  # Image capture
    ]
    
    print("Setting up continuous scan mode...")
    for i, cmd in enumerate(scan_commands[:-1]):  # All except the last image command
        print(f"Scan setup {i+1}:")
        response = send_and_receive(dev, cmd)
        time.sleep(0.1)
    
    print("\n👆 PLACE FINGER and keep it steady...")
    print("Will try rapid captures to catch finger placement...")
    
    image_cmd = scan_commands[-1]  # The image capture command
    captures = []
    
    try:
        for i in range(20):  # 20 rapid captures
            print(f"Rapid capture {i+1}/20", end=" - ")
            
            response = send_and_receive(dev, image_cmd, expected_response_size=6000, timeout=1000)
            
            if response and len(response) > 100:
                non_zero_bytes = sum(1 for b in response if b != 0)
                score = non_zero_bytes / len(response)
                
                if score > 0.05:  # More than 5% non-zero
                    filename = f"rapid_capture_{i+1}_{score:.3f}.bin"
                    with open(filename, 'wb') as f:
                        f.write(response)
                    print(f"SAVED! {score:.1%} data")
                    captures.append((filename, score))
                else:
                    print(f"{score:.1%} data")
            else:
                print("no response")
            
            time.sleep(0.1)  # Very fast captures
            
    except KeyboardInterrupt:
        print("\nStopped by user")
    
    return captures

def analyze_best_results(results):
    """Analyze and report the best results"""
    
    print(f"\n{'='*50}")
    print("📊 ANALYSIS SUMMARY")
    print(f"{'='*50}")
    
    if not any(results):
        print("❌ No successful captures found")
        print("\n💡 TROUBLESHOOTING SUGGESTIONS:")
        print("1. Try cleaning the sensor surface")
        print("2. Make sure finger is dry (not too wet/oily)")
        print("3. Press firmly but don't slide finger")
        print("4. Try different fingers")
        print("5. Sensor might need hardware reset (unplug/replug)")
        return
    
    # Find best overall result
    best_files = []
    
    for result_group in results:
        if isinstance(result_group, list):  # Multiple captures
            for filename, score in result_group:
                best_files.append((filename, score, "Rapid capture"))
        elif result_group and len(result_group) > 1:  # Single best capture
            response, cmd, desc = result_group[0], result_group[1], result_group[2]
            best_files.append((f"best_capture.bin", result_group[1], desc))
    
    if best_files:
        # Sort by score
        best_files.sort(key=lambda x: x[1], reverse=True)
        
        print("🏆 BEST CAPTURES:")
        for i, (filename, score, method) in enumerate(best_files[:5]):
            print(f"   {i+1}. {filename}: {score:.1%} data ({method})")
        
        best_file, best_score, best_method = best_files[0]
        
        if best_score > 0.2:  # More than 20% non-zero
            print(f"\n🎉 EXCELLENT! {best_file} has {best_score:.1%} fingerprint data")
            print("💡 This file likely contains a usable fingerprint image")
        elif best_score > 0.05:  # More than 5% non-zero
            print(f"\n📊 PROMISING! {best_file} has {best_score:.1%} data")
            print("💡 This might be a partial fingerprint or sensor calibration data")
        else:
            print(f"\n🤔 MINIMAL DATA: Best capture only has {best_score:.1%} non-zero data")

def main():
    print("🔬 EgisTec EH576 - Advanced Capture Strategies")
    print("Multiple approaches to solve the 'zeros' problem")
    print("=" * 50)
    
    result = connect_device()
    if result is None:
        return
    
    dev, intf = result
    
    try:
        # Try different strategies
        print("🚀 Starting comprehensive capture sequence...")
        
        # Strategy 1: Full EH575 initialization
        try_full_eh575_sequence(dev)
        time.sleep(1)
        
        # Strategy 2: Sensor calibration
        try_sensor_calibration(dev)
        time.sleep(1)
        
        # Strategy 3: Multiple image commands
        best_capture, best_score = try_image_commands_variations(dev)
        time.sleep(1)
        
        # Strategy 4: Continuous scan mode
        rapid_captures = try_continuous_scan_mode(dev)
        
        # Analyze results
        analyze_best_results([best_capture, rapid_captures])
        
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
